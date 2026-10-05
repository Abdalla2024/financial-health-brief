# Sources and validation

## Sources
| Role | Owner | Fields that identify it | Meaning |
|---|---|---|---|
| Ledger | Operations | `transaction_id`, `amount`, `status` | Daily activity. One row per transaction. |
| Budget | Finance | `period`, `category`, `budget_amount` | Monthly allocation per category for a `YYYY-MM` period. |
| Revenue | Finance | `date`, `metric`, `value` | Dated snapshot metrics, one row per date and metric. |

Role detection reads each fetched tab's header names. A tab that matches no role is ignored; zero or two tabs matching one role, or one tab matching two roles, stops the run. Required columns per role are the columns of the matching normalized CSV in the assignment.

## Fetching
- Each run reads every spreadsheet fresh: the `htmlview` page gives the title and tab IDs (`gid`), and `export?format=csv&gid=…` gives each tab's data. The tab name comes from the export's `Content-Disposition`.
- A response that is not CSV (for example a sign-in page) is a failure. Failures retry up to three times, then stop the run. No cache, no local copy.
- Source version is the `source_version` carried by the rows. The revenue snapshot carries one per date. The report also records a SHA-256 of each tab's exported bytes.

## Blocking checks (exit code 1, owner named in each message)
Ledger: blank or duplicate `transaction_id`; date not `YYYY-MM-DD`; status not posted, pending or disputed; `amount_status` not confirmed or unknown; confirmed amount blank or not a number; a row marked amount unknown that still carries an amount; a posted row with an unknown amount; a negative pending or disputed amount; blank currency; more than one source or source version.

Budget: period not `YYYY-MM`; duplicate period and category; `budget_amount` not numeric; blank currency; more than one source version; no allocations for the reporting month.

Revenue: date not `YYYY-MM-DD`; value not numeric; duplicate date and metric; blank currency on a money metric; more than one source version for a date.

Across sources: more than one currency; a ledger category in the month-to-date window with no budget allocation; no ledger rows on the reporting date or the prior date; prior date not before reporting date.

## Not blocking
- A pending or disputed row with `amount_status` unknown: queued, excluded from totals, labelled unknown, and listed as a clarification request to Operations.
- A missing `collected_revenue` or `outstanding_balance` snapshot for either date: the revenue section shows it as unresolved and lists a Finance clarification request.
- Ledger rows dated after the reporting date: kept in `transactions.csv`, left out of the brief, and counted in the exceptions section.

## Normalized CSVs
Every recognized source row is kept, in source order, with the required columns only. Amounts are plain decimals (no thousands separators, at least two decimal places); an unknown amount is left blank with `amount_status` unknown. Revenue count metrics keep their integer value and blank currency.

## Determinism
Outputs depend only on the fetched data, the two dates and the fetch time. The fetch time appears in `report.md`; set `FHB_FIXED_NOW=2026-01-01T00:00:00Z` to compare reruns byte for byte.
