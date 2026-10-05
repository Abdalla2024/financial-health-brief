"""Run from the skill root: python3 -m unittest discover -s tests"""

import os
import sys
import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import compute  # noqa: E402
import render  # noqa: E402
import run  # noqa: E402
import sources  # noqa: E402

LEDGER = """transaction_id,date,account,category,description,amount,currency,status,source,source_version,amount_status
T1,2026-08-10,ops,staffing,payroll,"1,000.00",USD,posted,ledger,v1,confirmed
T2,2026-08-10,ops,supplies,credit,-25.50,USD,posted,ledger,v1,confirmed
T3,2026-08-11,ops,staffing,payroll,300,USD,posted,ledger,v1,confirmed
T4,2026-08-11,ops,supplies,order,200,USD,pending,ledger,v1,confirmed
T5,2026-08-11,ops,refunds,dispute,700,USD,disputed,ledger,v1,confirmed
T6,2026-08-11,ops,supplies,estimate,,USD,pending,ledger,v1,unknown
T7,2026-08-06,ops,refunds,old dispute,350,USD,disputed,ledger,v1,confirmed
T8,2026-08-12,ops,staffing,later,50,USD,posted,ledger,v1,confirmed
"""
BUDGET = """period,category,budget_amount,currency,owner,review_rule,source,source_version
2026-08,staffing,"1,300.00",USD,ops,review_material_overage,budget,b1
2026-08,supplies,1000,USD,ops,review_material_overage,budget,b1
2026-08,refunds,1300,USD,fin,review_all_pending_or_disputed,budget,b1
2026-08,training,500,USD,ops,review_material_overage,budget,b1
"""
REVENUE = """date,source,metric,value,currency,source_version
2026-08-10,tuition,collected_revenue,100,USD,r10
2026-08-10,tuition,outstanding_balance,40,USD,r10
2026-08-10,tuition,enrolled_students,5,,r10
2026-08-11,tuition,collected_revenue,130,USD,r11
2026-08-11,tuition,outstanding_balance,30,USD,r11
"""
REPORTING, PRIOR = date(2026, 8, 11), date(2026, 8, 10)


def make_tab(role, text, name=None):
    headers, rows = sources.parse_csv_text(text)
    return sources.Tab(url=f"https://docs.google.com/spreadsheets/d/{role}", sheet_id=role, gid="1",
                       tab_name=name or role, title="t", fetched_at="2026-10-05T00:00:00Z",
                       headers=headers, rows=rows, sha256="x", role=role)


def tabs(ledger=LEDGER, budget=BUDGET, revenue=REVENUE):
    return {"ledger": make_tab("ledger", ledger), "budget": make_tab("budget", budget), "revenue": make_tab("revenue", revenue)}


def analyse(**kwargs):
    return compute.analyse(tabs(**kwargs), REPORTING, PRIOR)


class Figures(unittest.TestCase):
    def test_daily_totals_keep_statuses_separate_and_exclude_unknown(self):
        a = analyse()
        self.assertEqual(a.reporting_totals.posted, Decimal("300"))
        self.assertEqual(a.reporting_totals.pending, Decimal("200"))
        self.assertEqual(a.reporting_totals.disputed, Decimal("700"))
        self.assertEqual(a.reporting_totals.unknown_ids, ["T6"])
        self.assertEqual(a.prior_totals.posted, Decimal("974.50"))
        self.assertEqual(a.posted_change, Decimal("-674.50"))

    def test_queue_spans_month_start_to_reporting_date_and_keeps_unknown(self):
        ids = [r["transaction_id"] for r in analyse().queue]
        self.assertEqual(ids, ["T7", "T4", "T5", "T6"])

    def test_materiality_is_strictly_above_both_thresholds(self):
        by = {v.category: v for v in analyse().variances}
        self.assertEqual(by["staffing"].variance, Decimal("0"))
        # supplies: -25.50 posted -> variance -1025.50, above 100 and 500 -> material under
        self.assertTrue(by["supplies"].material)
        self.assertEqual(by["supplies"].direction, "under")
        self.assertTrue(by["training"].variance == Decimal("-500") and not by["training"].material)

    def test_threshold_equal_to_floor_is_not_material(self):
        budget = BUDGET.replace("training,500", "training,5000")
        by = {v.category: v for v in analyse(budget=budget).variances}
        self.assertEqual(by["training"].variance, Decimal("-5000"))
        self.assertTrue(by["training"].material)
        ledger = LEDGER + "T9,2026-08-11,ops,training,spend,4500,USD,posted,ledger,v1,confirmed\n"
        by = {v.category: v for v in analyse(budget=budget, ledger=ledger).variances}
        self.assertEqual(by["training"].variance, Decimal("-500"))
        self.assertFalse(by["training"].material)

    def test_revenue_change_and_missing_snapshot_is_unresolved(self):
        a = analyse()
        self.assertEqual(a.revenue_figures["collected_revenue"].change, Decimal("30"))
        self.assertEqual(a.revenue_figures["outstanding_balance"].change, Decimal("-10"))
        short = "\n".join(l for l in REVENUE.splitlines() if "2026-08-11" not in l) + "\n"
        a = analyse(revenue=short)
        self.assertEqual(a.revenue_figures, {})
        self.assertEqual(len(a.revenue_unresolved), 2)
        self.assertTrue(all("2026-08-11" in m for m in a.revenue_unresolved))

    def test_report_states_exact_signed_figures(self):
        a = analyse()
        text = render.report_md(a, tabs(), "2026-10-05T00:00:00Z")
        for expected in ("+300.00 USD", "+200.00 USD", "+700.00 USD", "+974.50 USD", "-674.50 USD", "DRAFT FOR HUMAN REVIEW"):
            self.assertIn(expected, text)
        self.assertLess(text.index("## 1. Decisions needed"), text.index("## 2. Key figures"))


class Validation(unittest.TestCase):
    def assert_blocked(self, **kwargs):
        with self.assertRaises(compute.ValidationError) as ctx:
            analyse(**kwargs)
        return ctx.exception.problems

    def test_duplicate_transaction_id_blocks(self):
        problems = self.assert_blocked(ledger=LEDGER + "T1,2026-08-10,ops,staffing,again,1,USD,posted,ledger,v1,confirmed\n")
        self.assertTrue(any("duplicate transaction_id" in p for p in problems))

    def test_two_source_versions_block(self):
        self.assert_blocked(ledger=LEDGER.replace("T3,2026-08-11,ops,staffing,payroll,300,USD,posted,ledger,v1", "T3,2026-08-11,ops,staffing,payroll,300,USD,posted,ledger,v2"))

    def test_posted_row_with_unknown_amount_blocks(self):
        self.assert_blocked(ledger=LEDGER.replace("T3,2026-08-11,ops,staffing,payroll,300,USD,posted,ledger,v1,confirmed", "T3,2026-08-11,ops,staffing,payroll,,USD,posted,ledger,v1,unknown"))

    def test_unmapped_category_and_second_currency_block(self):
        self.assert_blocked(ledger=LEDGER + "T9,2026-08-11,ops,mystery,x,5,USD,posted,ledger,v1,confirmed\n")
        self.assert_blocked(ledger=LEDGER.replace("T3,2026-08-11,ops,staffing,payroll,300,USD", "T3,2026-08-11,ops,staffing,payroll,300,EUR"))

    def test_unrecognized_status_and_bad_amount_block(self):
        self.assert_blocked(ledger=LEDGER.replace("posted,ledger,v1,confirmed\nT2", "settled,ledger,v1,confirmed\nT2"))
        self.assert_blocked(ledger=LEDGER.replace('"1,000.00"', "about 1000"))

    def test_dates_without_ledger_rows_block(self):
        with self.assertRaises(compute.ValidationError):
            compute.analyse(tabs(), date(2026, 8, 20), PRIOR)
        with self.assertRaises(compute.ValidationError):
            compute.analyse(tabs(), REPORTING, date(2026, 8, 9))

    def test_missing_budget_period_blocks(self):
        self.assert_blocked(budget=BUDGET.replace("2026-08", "2026-07"))


class Roles(unittest.TestCase):
    def test_roles_come_from_fields_not_names_or_column_order(self):
        shuffled = make_tab("x", "metric,value,date,source,currency,source_version\n" + "\n".join(
            ",".join([c[2], c[3], c[0], c[1], c[4], c[5]]) for c in (l.split(",") for l in REVENUE.splitlines()[1:])) + "\n", name="Ledger")
        found = sources.assign_roles([make_tab("a", BUDGET, "Revenue"), shuffled, make_tab("c", LEDGER, "Budget targets")])
        self.assertEqual(set(found), {"ledger", "budget", "revenue"})
        self.assertEqual(found["revenue"].tab_name, "Ledger")

    def test_missing_or_duplicate_role_is_an_error(self):
        with self.assertRaises(sources.SourceError):
            sources.assign_roles([make_tab("a", LEDGER), make_tab("b", BUDGET)])
        with self.assertRaises(sources.SourceError):
            sources.assign_roles([make_tab("a", LEDGER), make_tab("b", LEDGER), make_tab("c", BUDGET), make_tab("d", REVENUE)])


def fake_http(bodies):
    def get(url):
        for sheet_id, text in bodies.items():
            if f"/d/{sheet_id}/htmlview" in url:
                return f'<title>Doc {sheet_id} - Google Drive</title><li id="sheet-button-7">'.encode(), {}
            if f"/d/{sheet_id}/export" in url:
                disposition = f"attachment; filename*=UTF-8''Doc%20{sheet_id}%20-%20Tab%20{sheet_id}.csv"
                return text.encode(), {"Content-Type": "text/csv", "Content-Disposition": disposition}
        raise sources.SourceError(f"unreachable {url}")
    return get


URLS = [f"https://docs.google.com/spreadsheets/d/{s}" for s in ("LEDGER1", "BUDGET1", "REVENUE1")]
BODIES = {"LEDGER1": LEDGER, "BUDGET1": BUDGET, "REVENUE1": REVENUE}


def run_cli(out_dir, bodies=BODIES, extra=()):
    argv = [a for u in URLS for a in ("--source", u)] + ["--reporting-date", "2026-08-11", "--prior-date", "2026-08-10",
                                                          "--out-dir", str(out_dir), *extra]
    with mock.patch.object(sources, "HTTP_GET", fake_http(bodies)), mock.patch.dict(os.environ, {"FHB_FIXED_NOW": "2026-10-05T00:00:00Z"}):
        with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            return run.main(argv)


class EndToEnd(unittest.TestCase):
    def test_success_writes_all_deliverables_and_reruns_identically(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(run_cli(out), 0)
            names = ["report.md", "normalized/transactions.csv", "normalized/budget.csv", "normalized/revenue.csv"]
            first = {n: (out / n).read_bytes() for n in names}
            self.assertEqual(run_cli(out), 0)
            self.assertEqual(first, {n: (out / n).read_bytes() for n in names})
            self.assertEqual(len((out / "normalized/transactions.csv").read_text().splitlines()), 9)
            self.assertFalse((out / "RUN_FAILED.md").exists())

    def test_failed_run_removes_earlier_outputs_and_marks_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(run_cli(out), 0)
            self.assertEqual(run_cli(out, bodies={"LEDGER1": LEDGER, "BUDGET1": BUDGET}), 1)
            self.assertFalse((out / "report.md").exists())
            self.assertFalse(list((out / "normalized").glob("*.csv")))
            self.assertIn("RUN FAILED", (out / "RUN_FAILED.md").read_text())

    def test_usage_error_also_clears_earlier_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(run_cli(out), 0)
            for argv in (["--out-dir", str(out)],
                         ["--source", URLS[0], "--reporting-date", "nonsense", "--prior-date", "2026-08-10", "--out-dir", str(out)]):
                self.assertEqual(run_cli(out), 0)
                with mock.patch("sys.stderr"), self.assertRaises(SystemExit) as ctx:
                    run.main(argv)
                self.assertEqual(ctx.exception.code, 2)
                self.assertFalse((out / "report.md").exists())
                self.assertFalse(list((out / "normalized").glob("*.csv")))
                self.assertIn("RUN FAILED", (out / "RUN_FAILED.md").read_text())

    def test_help_does_not_clear_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(run_cli(out), 0)
            with mock.patch("sys.stdout"), self.assertRaises(SystemExit) as ctx:
                run.main(["--help", "--out-dir", str(out)])
            self.assertEqual(ctx.exception.code, 0)
            self.assertTrue((out / "report.md").exists())

    def test_unexpected_error_leaves_no_deliverables_and_a_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(run_cli(out), 0)
            with mock.patch.object(render, "report_md", side_effect=RuntimeError("boom")):
                self.assertEqual(run_cli(out), 1)
            self.assertFalse((out / "report.md").exists())
            self.assertFalse(list((out / "normalized").glob("*.csv")))
            self.assertIn("boom", (out / "RUN_FAILED.md").read_text())

    def test_failure_while_publishing_clears_partial_outputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            real_replace = os.replace
            calls = []

            def flaky(src, dst):
                calls.append(dst)
                if len(calls) == 3:
                    raise OSError("disk full")
                return real_replace(src, dst)
            with mock.patch.object(run.os, "replace", flaky):
                self.assertEqual(run_cli(out), 1)
            self.assertFalse((out / "report.md").exists())
            self.assertFalse(list((out / "normalized").glob("*.csv")))
            self.assertFalse(list(out.rglob("*.tmp")))
            self.assertIn("disk full", (out / "RUN_FAILED.md").read_text())

    def test_entry_point_is_executable(self):
        self.assertTrue(os.access(Path(run.__file__), os.X_OK))

    def test_invalid_data_fails_without_publishing(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            bad = LEDGER + "T1,2026-08-11,ops,staffing,dup,1,USD,posted,ledger,v1,confirmed\n"
            self.assertEqual(run_cli(out, bodies={**BODIES, "LEDGER1": bad}), 1)
            self.assertFalse((out / "report.md").exists())

    def test_non_csv_response_is_rejected(self):
        def get(url):
            if "htmlview" in url:
                return b"<title>Doc - Google Drive</title><li id=\"sheet-button-7\">", {}
            return b"<title>Sign in</title>", {"Content-Type": "text/html"}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sources, "HTTP_GET", get):
            with self.assertRaises(sources.SourceError):
                sources.fetch_spreadsheet(URLS[0], "now")


if __name__ == "__main__":
    unittest.main()
