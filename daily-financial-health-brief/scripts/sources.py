"""Read Google Sheets tabs through their view-only links and identify each tab's role from its fields."""

import csv
import hashlib
import html
import io
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

USER_AGENT = "daily-financial-health-brief/1.0 (read-only)"
SHEET_URL_RE = re.compile(r"^https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)")
TIMEOUT_SECONDS = 30
ATTEMPTS = 3

# A tab's role is decided by the fields it carries, never by file name or column position.
ROLE_SIGNATURES = {
    "ledger": {"transaction_id", "amount", "status"},
    "budget": {"budget_amount", "category", "period"},
    "revenue": {"metric", "value", "date"},
}


class SourceError(Exception):
    """A source could not be fetched, read or identified."""


@dataclass
class Tab:
    url: str
    sheet_id: str
    gid: str
    tab_name: str
    title: str
    fetched_at: str
    headers: list
    rows: list = field(default_factory=list)
    sha256: str = ""
    role: str = ""

    @property
    def row_count(self):
        return len(self.rows)


def norm_header(name):
    return re.sub(r"\s+", "_", name.strip().lower())


def http_get(url):
    """Return (body, headers) for a GET, retrying transient failures."""
    last = None
    for attempt in range(ATTEMPTS):
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return response.read(), response.headers
        except urllib.error.HTTPError as err:
            last = err
            if err.code < 500:
                break
        except (urllib.error.URLError, TimeoutError) as err:
            last = err
        time.sleep(attempt + 1)
    raise SourceError(f"could not fetch {url}: {last}")


# Tests replace this to supply fixtures without the network.
HTTP_GET = http_get


def parse_sheet_url(url):
    match = SHEET_URL_RE.match(url.strip())
    if not match:
        raise SourceError(f"not a Google Sheets view link: {url}")
    parsed = urllib.parse.urlparse(url.strip())
    gid = None
    for part in (parsed.query, parsed.fragment):
        values = urllib.parse.parse_qs(part).get("gid")
        if values:
            gid = values[0]
    return match.group(1), gid


def parse_csv_text(text):
    """Return (headers, rows) where each row maps normalized header -> stripped text, plus its sheet row number."""
    table = list(csv.reader(io.StringIO(text, newline="")))
    if not table or not any(cell.strip() for cell in table[0]):
        raise SourceError("the tab has no header row")
    headers = [norm_header(cell) for cell in table[0]]
    if "" in headers:
        raise SourceError("the header row has a blank column name")
    if len(set(headers)) != len(headers):
        raise SourceError("the header row repeats a column name")
    rows = []
    for number, cells in enumerate(table[1:], start=2):
        if not any(cell.strip() for cell in cells):
            continue
        if len(cells) > len(headers) and any(cell.strip() for cell in cells[len(headers):]):
            raise SourceError(f"row {number} has more cells than the header has columns")
        padded = cells + [""] * (len(headers) - len(cells))
        row = {name: padded[i].strip() for i, name in enumerate(headers)}
        row["_row"] = number
        rows.append(row)
    return headers, rows


def _discover_tabs(sheet_id, url_gid):
    page, _ = HTTP_GET(f"https://docs.google.com/spreadsheets/d/{sheet_id}/htmlview")
    page = page.decode("utf-8", errors="replace")
    match = re.search(r"<title>(.*?)</title>", page, re.S)
    title = html.unescape(match.group(1)).strip() if match else ""
    title = re.sub(r"\s*-\s*Google Drive$", "", title)
    if url_gid:
        return title, [url_gid]
    gids = list(dict.fromkeys(re.findall(r"sheet-button-(\d+)", page)))
    if not gids:
        match = re.search(r'gid: "(\d+)"', page)
        gids = [match.group(1)] if match else []
    if not gids:
        raise SourceError(f"no tabs found for spreadsheet {sheet_id}; is the view-only link open?")
    return title, gids


def _tab_name(headers, gid, title):
    disposition = headers.get("Content-Disposition", "") or ""
    match = re.search(r"filename\*=UTF-8''([^;]+)", disposition)
    if not match:
        return f"gid {gid}"
    name = urllib.parse.unquote(match.group(1))
    name = name[:-4] if name.lower().endswith(".csv") else name
    if title and name.startswith(title + " - "):
        return name[len(title) + 3:]
    return name.rpartition(" - ")[2] or f"gid {gid}"


def fetch_spreadsheet(url, fetched_at):
    """Fetch every tab of one spreadsheet, fresh, and return a list of Tab."""
    sheet_id, url_gid = parse_sheet_url(url)
    title, gids = _discover_tabs(sheet_id, url_gid)
    tabs = []
    for gid in gids:
        export = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
        body, headers = HTTP_GET(export)
        if "csv" not in (headers.get("Content-Type", "") or "").lower():
            raise SourceError(f"{url} (gid {gid}) did not return CSV; the link may need sign-in")
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError as err:
            raise SourceError(f"{url} (gid {gid}) is not valid UTF-8 text: {err}") from err
        try:
            parsed_headers, rows = parse_csv_text(text)
        except SourceError as err:
            raise SourceError(f"{url} (gid {gid}): {err}") from err
        tabs.append(Tab(
            url=url.strip(), sheet_id=sheet_id, gid=gid, tab_name=_tab_name(headers, gid, title),
            title=title, fetched_at=fetched_at, headers=parsed_headers, rows=rows,
            sha256=hashlib.sha256(body).hexdigest(),
        ))
    return tabs


def classify(tab):
    fields = set(tab.headers)
    return [role for role, signature in ROLE_SIGNATURES.items() if signature <= fields]


def assign_roles(tabs):
    """Return {role: Tab}; every role must be found exactly once across all fetched tabs."""
    by_role = {}
    problems = []
    for tab in tabs:
        roles = classify(tab)
        if len(roles) > 1:
            problems.append(f"tab '{tab.tab_name}' of {tab.url} matches more than one role: {', '.join(roles)}")
        elif roles:
            tab.role = roles[0]
            by_role.setdefault(roles[0], []).append(tab)
    for role in ROLE_SIGNATURES:
        found = by_role.get(role, [])
        if not found:
            problems.append(f"no tab carries the {role} fields {sorted(ROLE_SIGNATURES[role])}")
        elif len(found) > 1:
            names = ", ".join(f"'{t.tab_name}' ({t.url})" for t in found)
            problems.append(f"more than one tab looks like the {role}: {names}")
    if problems:
        raise SourceError("; ".join(problems))
    return {role: tabs_[0] for role, tabs_ in by_role.items()}
