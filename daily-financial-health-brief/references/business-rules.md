# Business rules

Confirmed with the Finance and Operations Manager across three interviews (`interviews/`). Rules marked *assumption* were not stated outright.

## Purpose and boundaries
- The brief is a repeatable draft for the Operations owner's operations meeting.
- Read-only. The system may organize data, derive totals, flag risks and draft. It never approves spending, resolves disputes or edits a source.
- The Operations owner decides spending changes and disputed items.

## Dates
- The reporting date and the prior business day are set by the manager's request for each report. Do not take the latest ledger date or skip weekends and holidays. For the first meeting: 2026-08-11 against 2026-08-10.
- Month to date runs from the first calendar day of the reporting month through the reporting date, inclusive. If the ledger has nothing for the first days, use what exists.

## Transaction statuses
- Posted, pending and disputed are kept separate. Each daily total is reported on its own.
- Only the posted total is actual posted activity. Pending and disputed amounts are never added to it.
- Positive posted amounts are expenses. Confirmed negative posted amounts are source-authorized credits or corrections: keep the sign and include them, which lowers daily and month-to-date posted totals.
- "Confirmed" means `amount_status` is `confirmed`. A pending or disputed row with an unknown amount stays in the unresolved queue, its amount is excluded from every total, and it is labelled unknown.

## Budget variance
- Variance = month-to-date posted spend minus the category's full monthly budget allocation.
- Material only when the absolute variance is strictly above both 10% of that allocation and 500 USD. Equal is not material.
- Both overages and underspends are flagged.
- Only posted activity enters the comparison. The test does not apply to the unresolved queue.
- Partial-month spend is compared with the full allocation, as Finance specified, so underspend flags are common early in a month.

## Unresolved queue
- All pending and disputed rows from the first day of the reporting month through the reporting date, inclusive, go to the Operations owner for decision, whatever their size. This covers the `review_all_pending_or_disputed` rule on refunds.
- The manager's request flags a 700 USD disputed refund (TX-1012 in the first data). The brief lists every disputed refund in the queue rather than singling one out.

## Revenue
- Report `collected_revenue` and `outstanding_balance` for the reporting date against the prior date, with the change.
- Enrolled students and past-due accounts are not part of the brief unless Finance says otherwise.
- Payment plan balance and outstanding balance are not combined until Finance defines their relationship.
- A snapshot is stale if its date is not the reporting date. No age limit, no substitution, no zero-fill. A missing snapshot is left unresolved and escalated to Finance.

## Evidence and ownership
- Missing, conflicting, stale, unmapped or unknown evidence must be clarified with its source owner before it supports a conclusion. Operations owns the Transaction ledger. Finance owns the Budget targets and Revenue snapshot, including the budget `owner` column's reviewers: that column names the category reviewer, and clarification requests on budget targets go to Finance.
- Two source versions in one sheet, or duplicate transaction IDs, mean the work cannot proceed. Suspected duplicates (same ID) go to Operations before the brief proceeds. Different IDs with similar descriptions, such as TX-1012 and TX-1070, are ordinary queue items. *Assumption:* the interview named same-ID duplicates only.
- Every monetary claim keeps its currency, source identity, date or period and source version. All current data is USD. *Assumption:* a second currency stops the run, since nothing defines how to combine currencies.
