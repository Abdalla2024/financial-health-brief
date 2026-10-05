"""Write the normalized CSVs and the draft brief."""

import csv
import io
from decimal import Decimal

from compute import BUDGET_COLUMNS, LEDGER_COLUMNS, MATERIAL_FLOOR, MATERIAL_RATE, REVENUE_COLUMNS, REVENUE_METRICS

CENTS = Decimal("0.01")


def plain(value):
    """Exact decimal text, at least two decimal places, no thousands separators."""
    if value == value.quantize(CENTS):
        return f"{value.quantize(CENTS):f}"
    return f"{value:f}"


def signed(value):
    text = plain(value)
    return text if value == 0 else (text if value < 0 else "+" + text)


def _csv_text(columns, rows):
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(row)
    return out.getvalue()


def ledger_csv(analysis):
    rows = []
    for r in analysis.ledger:
        values = dict(r)
        values["amount"] = plain(r["_amount"]) if r["_amount"] is not None else ""
        rows.append([values[c] for c in LEDGER_COLUMNS])
    return _csv_text(LEDGER_COLUMNS, rows)


def budget_csv(analysis):
    rows = []
    for r in analysis.budget:
        values = dict(r)
        values["budget_amount"] = plain(r["_amount"])
        rows.append([values[c] for c in BUDGET_COLUMNS])
    return _csv_text(BUDGET_COLUMNS, rows)


def revenue_csv(analysis):
    rows = []
    for r in analysis.revenue:
        values = dict(r)
        is_money = bool(r["currency"])
        values["value"] = plain(r["_value"]) if is_money else f"{r['_value']:f}"
        rows.append([values[c] for c in REVENUE_COLUMNS])
    return _csv_text(REVENUE_COLUMNS, rows)


def _cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ")


def _table(headers, rows):
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def _amount(row):
    return plain(row["_amount"]) if row["_amount"] is not None else "unknown"


def report_md(analysis, tabs, fetched_at):
    a = analysis
    cur = a.currency
    ledger_src, budget_src, revenue_src = (a.sources.get(k, "") for k in ("ledger", "budget", "revenue"))
    ledger_ver = ", ".join(a.versions["ledger"])
    budget_ver = ", ".join(a.versions["budget"])
    rt, pt = a.reporting_totals, a.prior_totals
    out = []
    w = out.append

    w(f"# Daily Financial Health Brief: {a.reporting_date}")
    w("")
    w("> **DRAFT FOR HUMAN REVIEW.** Prepared read-only from the three sources listed in section 7. "
      "Nothing here approves spending, resolves a dispute or changes a source. "
      "Decisions on spending changes and disputed items belong to the Operations owner.")
    w("")
    w(f"Reporting date: **{a.reporting_date}**. Prior business day (set by the manager's request): **{a.prior_date}**. "
      f"Month to date: {a.month_start} through {a.reporting_date}, inclusive. All amounts are {cur}.")
    w("")

    open_confirmed = {s: sum((r["_amount"] for r in a.queue if r["status"] == s and r["_amount"] is not None), Decimal(0))
                      for s in ("pending", "disputed")}
    unknown_rows = [r for r in a.queue if r["_amount"] is None]
    w("## 1. Decisions needed: unresolved queue")
    w("")
    w(f"{len(a.queue)} pending or disputed rows dated {a.month_start} to {a.reporting_date} need the Operations owner's decision, "
      f"whatever their size. Confirmed pending: {signed(open_confirmed['pending'])} {cur}. "
      f"Confirmed disputed: {signed(open_confirmed['disputed'])} {cur}. "
      f"{len(unknown_rows)} row(s) have an unknown amount, which is left out of every total.")
    w("")
    rows = []
    for r in a.queue:
        action = "Owner decision"
        if r["_amount"] is None:
            action += "; amount unknown, Operations to confirm"
        rows.append([r["transaction_id"], r["date"], r["status"], r["category"], r["description"], _amount(r), action])
    w(_table(["Transaction", "Date", "Status", "Category", f"Description", f"Amount ({cur})", "Action"], rows))
    w("")
    w(f"Source: {ledger_src}, version {ledger_ver}, dated {a.month_start} to {a.reporting_date}, {cur}.")
    disputed_refunds = [r for r in a.queue if r["status"] == "disputed" and r["category"] == "refunds"]
    if disputed_refunds:
        listed = "; ".join(f"{r['transaction_id']} ({r['date']}, {_amount(r)} {cur})" for r in disputed_refunds)
        w("")
        w(f"Disputed refunds in the queue: {listed}.")
    w("")

    w("## 2. Key figures")
    w("")
    w(f"- **Posted total, {a.reporting_date} (reporting date):** {signed(rt.posted)} {cur}")
    w(f"- **Pending-confirmed total, {a.reporting_date}:** {signed(rt.pending)} {cur}")
    w(f"- **Disputed-confirmed total, {a.reporting_date}:** {signed(rt.disputed)} {cur}")
    w(f"- **Posted total, {a.prior_date} (prior business day):** {signed(pt.posted)} {cur}")
    w(f"- **Change in posted total, {a.reporting_date} minus {a.prior_date}:** {signed(a.posted_change)} {cur}")
    w("")
    for totals in (rt, pt):
        if totals.unknown_ids:
            w(f"- {totals.day}: amount unknown for {', '.join(totals.unknown_ids)}; excluded from every total above and labelled unknown.")
    w("- Only the posted total is actual posted activity. Pending and disputed totals are shown separately and never added to it. "
      "Confirmed negative posted amounts are source-authorized credits or corrections and keep their sign.")
    w("")
    w(_table(["Day", f"Posted ({cur})", f"Pending-confirmed ({cur})", f"Disputed-confirmed ({cur})", "Rows"],
             [[t.day, signed(t.posted), signed(t.pending), signed(t.disputed), t.row_count] for t in (rt, pt)]))
    w("")
    w(f"Source: {ledger_src}, version {ledger_ver}, {cur}; rows dated {a.reporting_date} and {a.prior_date}.")
    w("")

    w("## 3. Budget variance, month to date")
    w("")
    w(f"Variance is month-to-date posted spend minus the full monthly allocation for {a.reporting_date.strftime('%Y-%m')}. "
      f"A variance is material only when its absolute value is strictly above both {int(MATERIAL_RATE * 100)}% of the allocation "
      f"and {plain(MATERIAL_FLOOR)} {cur}. Overages and underspends are both flagged. "
      "Pending and disputed activity is excluded. Partial-month spend is compared with the full allocation, as Finance specified.")
    w("")
    rows = []
    for v in a.variances:
        flag = f"MATERIAL {v.direction.upper()}" if v.material else "within tolerance"
        rows.append([v.category, v.owner, plain(v.budget), plain(v.mtd_posted), signed(v.variance), plain(v.threshold), flag])
    w(_table(["Category", "Reviewer", f"Budget ({cur})", f"MTD posted ({cur})", f"Variance ({cur})", f"10% of budget ({cur})", "Result"], rows))
    w("")
    material = [v for v in a.variances if v.material]
    if material:
        w("Material variances: " + "; ".join(f"{v.category} {signed(v.variance)} {cur} ({v.direction})" for v in material) + ".")
    else:
        w("No category has a material variance.")
    refund_rules = [v.category for v in a.variances if v.review_rule == "review_all_pending_or_disputed"]
    if refund_rules:
        w("")
        w(f"Categories under review_all_pending_or_disputed ({', '.join(refund_rules)}): every pending or disputed row is in section 1.")
    w("")
    w(f"Source: {ledger_src} version {ledger_ver} (posted rows, {a.month_start} to {a.reporting_date}) against "
      f"{budget_src} version {budget_ver} (period {a.reporting_date.strftime('%Y-%m')}), {cur}.")
    w("")

    w("## 4. Revenue and outstanding balances")
    w("")
    if a.revenue_figures:
        rows = []
        for metric in REVENUE_METRICS:
            f = a.revenue_figures.get(metric)
            if f:
                rows.append([metric, plain(f.prior), plain(f.reporting), signed(f.change)])
        w(_table(["Metric", f"{a.prior_date} ({cur})", f"{a.reporting_date} ({cur})", f"Change ({cur})"], rows))
        w("")
    for message in a.revenue_unresolved:
        w(f"- **UNRESOLVED:** {message}. Nothing was substituted or filled with zero.")
    if a.revenue_unresolved:
        w("")
    used = sorted({f.reporting_row["source_version"] for f in a.revenue_figures.values()} |
                  {f.prior_row["source_version"] for f in a.revenue_figures.values()})
    w(f"Source: {revenue_src}, version {', '.join(used) if used else 'none usable'}, dated {a.prior_date} and {a.reporting_date}, {cur}.")
    w("Enrolled students and past-due accounts are not part of this brief. Payment plan balance is not combined with outstanding balance until Finance defines how they relate.")
    w("")

    w("## 5. Exceptions and clarification requests")
    w("")
    items = []
    for r in unknown_rows:
        items.append(f"**Operations:** confirm the amount of {r['transaction_id']} ({r['status']}, {r['date']}, {r['category']}, {r['description']}). Unknown, excluded from totals.")
    for t in (rt, pt):
        for tid in t.unknown_ids:
            if tid not in {r["transaction_id"] for r in unknown_rows}:
                items.append(f"**Operations:** confirm the amount of {tid} dated {t.day}. Unknown, excluded from totals.")
    for message in a.revenue_unresolved:
        items.append(f"**Finance:** {message}.")
    if a.later_rows:
        items.append(f"Informational: {a.later_rows} ledger row(s) are dated after {a.reporting_date}; they are in the normalized ledger but not in this brief.")
    if not items:
        items.append("None.")
    out.extend(f"- {i}" for i in items)
    w("")

    w("## 6. Traceability")
    w("")
    w("Every figure keeps its currency, source, date or period and source version. Rows behind each key figure:")
    w("")
    trace = [
        (f"Posted total {a.reporting_date}", rt.row_ids["posted"], ledger_src, ledger_ver, str(a.reporting_date)),
        (f"Pending-confirmed total {a.reporting_date}", rt.row_ids["pending"], ledger_src, ledger_ver, str(a.reporting_date)),
        (f"Disputed-confirmed total {a.reporting_date}", rt.row_ids["disputed"], ledger_src, ledger_ver, str(a.reporting_date)),
        (f"Posted total {a.prior_date}", pt.row_ids["posted"], ledger_src, ledger_ver, str(a.prior_date)),
    ]
    w(_table(["Figure", "Ledger rows", "Source", "Version", "Date", "Currency"],
             [[f, ", ".join(ids) or "none", s, v, d, cur] for f, ids, s, v, d in trace]))
    w("")
    w(f"The change in posted total ({signed(a.posted_change)} {cur}) is the first posted total minus the second.")
    w("")
    w(f"Month-to-date posted ledger rows behind each budget variance ({ledger_src}, {ledger_ver}, {a.month_start} to {a.reporting_date}, {cur}):")
    w("")
    w(_table(["Category", "Posted rows", "Budget row"],
             [[v.category, ", ".join(v.row_ids) or "none", f"{budget_src} {budget_ver}, {a.reporting_date.strftime('%Y-%m')}"]
              for v in a.variances]))
    w("")
    if a.revenue_figures:
        w("Revenue snapshot rows behind each revenue figure:")
        w("")
        rows = []
        for f in a.revenue_figures.values():
            for row in (f.prior_row, f.reporting_row):
                rows.append([f.metric, row["date"], row["source"], row["source_version"], row["currency"], f"sheet row {row['_row']}"])
        w(_table(["Metric", "Date", "Source", "Version", "Currency", "Location"], rows))
        w("")

    w("## 7. Source metadata")
    w("")
    rows = []
    for role in ("ledger", "budget", "revenue"):
        t = tabs[role]
        rows.append([role, t.url, t.sheet_id, f"{t.tab_name} (gid {t.gid})", t.fetched_at,
                     ", ".join(a.versions[role]), t.row_count, t.sha256])
    w(_table(["Role", "URL", "Spreadsheet ID", "Tab", "Fetched (UTC)", "Source version", "Rows fetched", "Content SHA-256"], rows))
    w("")
    w("Each source was read fresh from its view-only link for this run. Roles were identified from field names, not file names.")
    w("")
    return "\n".join(out)
