"""Validate the three sources and derive the brief's figures. Business rules: references/business-rules.md."""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

LEDGER_COLUMNS = ["transaction_id", "date", "account", "category", "description", "amount",
                  "currency", "status", "source", "source_version", "amount_status"]
BUDGET_COLUMNS = ["period", "category", "budget_amount", "currency", "owner", "review_rule",
                  "source", "source_version"]
REVENUE_COLUMNS = ["date", "source", "metric", "value", "currency", "source_version"]

STATUSES = ("posted", "pending", "disputed")
OPEN_STATUSES = ("pending", "disputed")
AMOUNT_STATUSES = ("confirmed", "unknown")
REVENUE_METRICS = ("collected_revenue", "outstanding_balance")

MATERIAL_RATE = Decimal("0.10")
MATERIAL_FLOOR = Decimal("500")

MONEY_RE = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


class ValidationError(Exception):
    """The sources cannot support a reliable brief; each problem names who must clarify it."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__("; ".join(self.problems))


def parse_money(text):
    if not MONEY_RE.match(text or ""):
        return None
    return Decimal(text.replace(",", ""))


def parse_date(text):
    if not DATE_RE.match(text or ""):
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _missing_columns(tab, columns):
    return [c for c in columns if c not in tab.headers]


def _single_value(rows, column, label, owner, problems):
    values = sorted({r[column] for r in rows})
    if len(values) > 1:
        problems.append(f"{label} carries more than one {column} ({', '.join(values)}); {owner} must resolve this")
    return values[0] if values else ""


def parse_ledger(tab, problems):
    missing = _missing_columns(tab, LEDGER_COLUMNS)
    if missing:
        problems.append(f"ledger is missing columns {missing}; Operations must supply them")
        return []
    rows, seen = [], {}
    for raw in tab.rows:
        where = f"ledger row {raw['_row']} ({raw['transaction_id'] or 'no id'})"
        row = dict(raw)
        if not raw["transaction_id"]:
            problems.append(f"{where}: blank transaction_id; Operations must supply it")
        elif raw["transaction_id"] in seen:
            problems.append(f"{where}: duplicate transaction_id also on row {seen[raw['transaction_id']]}; Operations must resolve before the brief can proceed")
        else:
            seen[raw["transaction_id"]] = raw["_row"]
        row["_date"] = parse_date(raw["date"])
        if row["_date"] is None:
            problems.append(f"{where}: date '{raw['date']}' is not YYYY-MM-DD; Operations must correct it")
        row["status"] = raw["status"].lower()
        if row["status"] not in STATUSES:
            problems.append(f"{where}: unrecognized status '{raw['status']}'; Operations must clarify")
        row["amount_status"] = raw["amount_status"].lower()
        if row["amount_status"] not in AMOUNT_STATUSES:
            problems.append(f"{where}: unrecognized amount_status '{raw['amount_status']}'; Operations must clarify")
        row["category"] = raw["category"].lower()
        row["_amount"] = None
        if row["amount_status"] == "confirmed":
            row["_amount"] = parse_money(raw["amount"])
            if row["_amount"] is None:
                problems.append(f"{where}: confirmed amount '{raw['amount']}' is blank or not a number; Operations must clarify")
        elif row["amount_status"] == "unknown":
            if raw["amount"]:
                problems.append(f"{where}: amount_status is unknown but an amount '{raw['amount']}' is present; Operations must clarify")
            if row["status"] == "posted":
                problems.append(f"{where}: a posted row cannot have an unknown amount; Operations must clarify")
        if row["_amount"] is not None and row["_amount"] < 0 and row["status"] in OPEN_STATUSES:
            problems.append(f"{where}: negative {row['status']} amount; only posted credits are defined, Operations must clarify")
        if not raw["currency"]:
            problems.append(f"{where}: blank currency; Operations must supply it")
        rows.append(row)
    return rows


def parse_budget(tab, problems):
    missing = _missing_columns(tab, BUDGET_COLUMNS)
    if missing:
        problems.append(f"budget is missing columns {missing}; Finance must supply them")
        return []
    rows, seen = [], set()
    for raw in tab.rows:
        where = f"budget row {raw['_row']} ({raw['period']} {raw['category']})"
        row = dict(raw)
        row["category"] = raw["category"].lower()
        if not PERIOD_RE.match(raw["period"]):
            problems.append(f"{where}: period '{raw['period']}' is not YYYY-MM; Finance must correct it")
        key = (raw["period"], row["category"])
        if key in seen:
            problems.append(f"{where}: duplicate period and category; Finance must resolve")
        seen.add(key)
        row["_amount"] = parse_money(raw["budget_amount"])
        if row["_amount"] is None or row["_amount"] < 0:
            problems.append(f"{where}: budget_amount '{raw['budget_amount']}' is not a numeric allocation; Finance must clarify")
        if not raw["currency"]:
            problems.append(f"{where}: blank currency; Finance must supply it")
        rows.append(row)
    return rows


def parse_revenue(tab, problems):
    missing = _missing_columns(tab, REVENUE_COLUMNS)
    if missing:
        problems.append(f"revenue snapshot is missing columns {missing}; Finance must supply them")
        return []
    rows, seen, versions = [], set(), {}
    for raw in tab.rows:
        where = f"revenue row {raw['_row']} ({raw['date']} {raw['metric']})"
        row = dict(raw)
        row["_date"] = parse_date(raw["date"])
        if row["_date"] is None:
            problems.append(f"{where}: date '{raw['date']}' is not YYYY-MM-DD; Finance must correct it")
        row["_value"] = parse_money(raw["value"])
        if row["_value"] is None:
            problems.append(f"{where}: value '{raw['value']}' is blank or not a number; Finance must clarify")
        if not raw["metric"]:
            problems.append(f"{where}: blank metric; Finance must supply it")
        key = (raw["date"], raw["metric"])
        if key in seen:
            problems.append(f"{where}: duplicate date and metric; Finance must resolve")
        seen.add(key)
        versions.setdefault(raw["date"], set()).add(raw["source_version"])
        if raw["metric"] in REVENUE_METRICS and not raw["currency"]:
            problems.append(f"{where}: blank currency on a money metric; Finance must supply it")
        rows.append(row)
    for day, found in sorted(versions.items()):
        if len(found) > 1:
            problems.append(f"revenue snapshot for {day} carries more than one source_version ({', '.join(sorted(found))}); Finance must resolve")
    return rows


@dataclass
class DayTotals:
    day: date
    posted: Decimal
    pending: Decimal
    disputed: Decimal
    row_ids: dict
    unknown_ids: list
    row_count: int


@dataclass
class Variance:
    category: str
    owner: str
    review_rule: str
    budget: Decimal
    mtd_posted: Decimal
    variance: Decimal
    threshold: Decimal
    material: bool
    direction: str
    row_ids: list


@dataclass
class RevenueFigure:
    metric: str
    reporting: Decimal
    prior: Decimal
    change: Decimal
    reporting_row: dict
    prior_row: dict


@dataclass
class Analysis:
    reporting_date: date
    prior_date: date
    month_start: date
    currency: str
    ledger: list
    budget: list
    revenue: list
    reporting_totals: DayTotals
    prior_totals: DayTotals
    posted_change: Decimal
    queue: list
    variances: list
    revenue_figures: dict
    revenue_unresolved: list
    later_rows: int
    versions: dict
    sources: dict = field(default_factory=dict)


def day_totals(ledger, day):
    rows = [r for r in ledger if r["_date"] == day]
    totals = {s: Decimal(0) for s in STATUSES}
    ids = {s: [] for s in STATUSES}
    unknown = []
    for r in rows:
        if r["amount_status"] == "confirmed":
            totals[r["status"]] += r["_amount"]
            ids[r["status"]].append(r["transaction_id"])
        else:
            unknown.append(r["transaction_id"])
    return DayTotals(day, totals["posted"], totals["pending"], totals["disputed"], ids, unknown, len(rows))


def analyse(tabs, reporting_date, prior_date):
    """Validate every source, then derive the figures. Raises ValidationError listing all problems."""
    problems = []
    if prior_date >= reporting_date:
        problems.append(f"prior date {prior_date} must be before reporting date {reporting_date}")
    ledger = parse_ledger(tabs["ledger"], problems)
    budget = parse_budget(tabs["budget"], problems)
    revenue = parse_revenue(tabs["revenue"], problems)
    for label, rows, tab, owner in (("ledger", ledger, tabs["ledger"], "Operations"),
                                    ("budget", budget, tabs["budget"], "Finance"),
                                    ("revenue snapshot", revenue, tabs["revenue"], "Finance")):
        if not tab.rows:
            problems.append(f"{label} has no data rows; {owner} must confirm")
    sources = {role: _single_value(tab.rows, "source", role, "the source owner", problems)
               for role, tab in tabs.items() if not _missing_columns(tab, ["source"])}
    versions = {}
    for role, rows in (("ledger", ledger), ("budget", budget), ("revenue", revenue)):
        found = sorted({r["source_version"] for r in rows})
        versions[role] = found
        if role != "revenue" and len(found) > 1:
            owner = "Operations" if role == "ledger" else "Finance"
            problems.append(f"{role} carries more than one source_version ({', '.join(found)}); {owner} must resolve")

    month_start = reporting_date.replace(day=1)
    period = reporting_date.strftime("%Y-%m")
    currencies = {r["currency"] for r in ledger + budget if r["currency"]}
    currencies |= {r["currency"] for r in revenue if r["currency"] and r["metric"] in REVENUE_METRICS}
    if len(currencies) > 1:
        problems.append(f"more than one currency appears ({', '.join(sorted(currencies))}); totals cannot be combined, Finance must clarify")
    if not any(r["_date"] == reporting_date for r in ledger):
        problems.append(f"the ledger has no rows dated {reporting_date}; the manager must confirm the reporting date")
    if not any(r["_date"] == prior_date for r in ledger):
        problems.append(f"the ledger has no rows dated {prior_date}; the manager must confirm the prior business day")
    period_rows = [b for b in budget if b["period"] == period]
    if not period_rows:
        problems.append(f"the budget has no allocations for {period}; Finance must supply them")
    categories = {b["category"] for b in period_rows}
    for r in ledger:
        in_window = r["_date"] is not None and month_start <= r["_date"] <= reporting_date
        if in_window and r["category"] not in categories:
            problems.append(f"ledger row {r['_row']} ({r['transaction_id']}): category '{r['category']}' has no {period} budget allocation; Finance must map it")
    if problems:
        raise ValidationError(problems)

    reporting_totals = day_totals(ledger, reporting_date)
    prior_totals = day_totals(ledger, prior_date)
    window = [r for r in ledger if month_start <= r["_date"] <= reporting_date]
    queue = sorted((r for r in window if r["status"] in OPEN_STATUSES),
                   key=lambda r: (r["_date"], r["transaction_id"]))

    variances = []
    for b in sorted(period_rows, key=lambda b: b["category"]):
        posted = [r for r in window if r["status"] == "posted" and r["category"] == b["category"]]
        mtd = sum((r["_amount"] for r in posted), Decimal(0))
        variance = mtd - b["_amount"]
        threshold = b["_amount"] * MATERIAL_RATE
        material = abs(variance) > threshold and abs(variance) > MATERIAL_FLOOR
        direction = "over" if variance > 0 else "under" if variance < 0 else "on budget"
        variances.append(Variance(b["category"], b["owner"], b["review_rule"], b["_amount"], mtd, variance,
                                  threshold, material, direction, [r["transaction_id"] for r in posted]))

    by_key = {(r["_date"], r["metric"]): r for r in revenue}
    figures, unresolved = {}, []
    for metric in REVENUE_METRICS:
        now_row = by_key.get((reporting_date, metric))
        before_row = by_key.get((prior_date, metric))
        if now_row is None:
            unresolved.append(f"no {metric} snapshot dated {reporting_date}; a snapshot must match the reporting date exactly, so Finance must clarify")
        if before_row is None:
            unresolved.append(f"no {metric} snapshot dated {prior_date} for the comparison; Finance must clarify")
        if now_row is not None and before_row is not None:
            figures[metric] = RevenueFigure(metric, now_row["_value"], before_row["_value"],
                                            now_row["_value"] - before_row["_value"], now_row, before_row)
    return Analysis(
        reporting_date=reporting_date, prior_date=prior_date, month_start=month_start,
        currency=next(iter(currencies)) if currencies else "", ledger=ledger, budget=budget, revenue=revenue,
        reporting_totals=reporting_totals, prior_totals=prior_totals,
        posted_change=reporting_totals.posted - prior_totals.posted, queue=queue, variances=variances,
        revenue_figures=figures, revenue_unresolved=unresolved,
        later_rows=sum(1 for r in ledger if r["_date"] > reporting_date), versions=versions, sources=sources,
    )
