#!/usr/bin/env python3
"""Produce the daily financial health brief from three Google Sheets read through their view-only links.

    python3 scripts/run.py --source URL --source URL --source URL \
        --reporting-date 2026-08-11 --prior-date 2026-08-10

Run from the skill root. Python 3.9+, standard library only. Read-only: the sheets are never written.
Exit codes: 0 success, 1 the run failed (no usable outputs are left), 2 bad arguments (earlier outputs are cleared too).
"""

import argparse
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import compute  # noqa: E402
import render  # noqa: E402
import sources  # noqa: E402

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = SKILL_ROOT / ".." / "deliverables"
OUTPUTS = ("normalized/transactions.csv", "normalized/budget.csv", "normalized/revenue.csv", "report.md")
FAILURE_MARKER = "RUN_FAILED.md"


def invalidate(out_dir):
    """Remove every earlier deliverable so a failed run cannot leave stale output that reads as current."""
    for name in (*OUTPUTS, FAILURE_MARKER):
        path = out_dir / name
        if path.exists():
            path.unlink()


def mark_failed(out_dir, reason, when):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / FAILURE_MARKER).write_text(
        f"# RUN FAILED\n\nNo current brief exists. The run at {when} stopped before publishing outputs, "
        f"and earlier deliverables were removed.\n\n{reason}\n", encoding="utf-8")


def early_out_dir(argv):
    """Find --out-dir without full parsing, so even a usage error can clear stale deliverables."""
    finder = argparse.ArgumentParser(add_help=False)
    finder.add_argument("--out-dir", default=str(DEFAULT_OUT))
    try:
        found, _ = finder.parse_known_args(argv)
        return Path(found.out_dir).resolve()
    except SystemExit:
        return Path(DEFAULT_OUT).resolve()


def fail(out_dir, problems, when):
    """Leave no readable deliverables: clear them all, then record why."""
    reason = "\n".join(f"- {p}" for p in problems)
    invalidate(out_dir)
    try:
        mark_failed(out_dir, reason, when)
    except OSError as err:
        print(f"could not write {FAILURE_MARKER}: {err}", file=sys.stderr)
    print("RUN FAILED: no deliverables were published.", file=sys.stderr)
    print(reason, file=sys.stderr)


def print_source_metadata(tabs):
    print("Source metadata")
    for role in ("ledger", "budget", "revenue"):
        t = tabs[role]
        print(f"  {role}: url={t.url} spreadsheet_id={t.sheet_id} tab='{t.tab_name}' gid={t.gid} "
              f"fetched_at={t.fetched_at} rows_fetched={t.row_count} sha256={t.sha256}")


def publish(out_dir, files):
    """Write each file next to its destination, then rename into place."""
    for name, text in files.items():
        target = out_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                handle.write(text)
            os.replace(tmp, target)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise


def parse_args(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", action="append", required=True, metavar="URL",
                        help="view-only Google Sheets link; give the ledger, budget and revenue links in any order")
    parser.add_argument("--reporting-date", required=True, help="YYYY-MM-DD, set by the manager's request")
    parser.add_argument("--prior-date", required=True, help="YYYY-MM-DD prior business day, set by the manager's request")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT), help="deliverables directory (default ../deliverables from the skill root)")
    args = parser.parse_args(argv)
    args.reporting = compute.parse_date(args.reporting_date)
    args.prior = compute.parse_date(args.prior_date)
    if args.reporting is None or args.prior is None:
        parser.error("--reporting-date and --prior-date must be YYYY-MM-DD")
    return args


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    now = os.environ.get("FHB_FIXED_NOW") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        args = parse_args(argv)
    except SystemExit as exit_:
        if exit_.code not in (0, None):  # a usage error is a failed run; --help is not
            fail(early_out_dir(argv), ["the command was invoked with invalid arguments; see the error on standard error"], now)
        raise
    out_dir = Path(args.out_dir).resolve()
    invalidate(out_dir)
    try:
        fetched = []
        for url in args.source:
            fetched.extend(sources.fetch_spreadsheet(url, now))
        tabs = sources.assign_roles(fetched)
        print_source_metadata(tabs)
        analysis = compute.analyse(tabs, args.reporting, args.prior)
        files = {
            "normalized/transactions.csv": render.ledger_csv(analysis),
            "normalized/budget.csv": render.budget_csv(analysis),
            "normalized/revenue.csv": render.revenue_csv(analysis),
            "report.md": render.report_md(analysis, tabs, now),
        }
        publish(out_dir, files)
    except (sources.SourceError, compute.ValidationError) as err:
        fail(out_dir, err.problems if isinstance(err, compute.ValidationError) else [str(err)], now)
        return 1
    except Exception as err:  # any other failure must still leave no readable deliverables
        fail(out_dir, [f"unexpected {type(err).__name__}: {err}"], now)
        return 1
    except KeyboardInterrupt:
        fail(out_dir, ["the run was interrupted"], now)
        return 130
    print(f"Brief written to {out_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
