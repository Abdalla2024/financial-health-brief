---
name: daily-financial-health-brief
description: Prepares the Quillhaven Academy daily financial health and budget brief as a source-traceable draft for the Operations owner. Reads the Transaction ledger, Budget targets and Revenue snapshot Google Sheets fresh through their view-only links, then writes normalized CSVs and a report with posted, pending and disputed totals, month-to-date budget variances, revenue changes, an unresolved-items queue and source metadata. Use when asked to produce, rerun or check the daily financial brief. Read-only; never approves spending or resolves disputes.
---

# Daily financial health brief

Produces a **draft for human review**. The Operations owner decides spending changes and disputed items; this skill never does.

## Run

From the skill root (the directory holding this file), with Python 3.9 or later and no packages to install:

```
python3 scripts/run.py \
  --source <sheet url> --source <sheet url> --source <sheet url> \
  --reporting-date YYYY-MM-DD --prior-date YYYY-MM-DD
```

- Give the three view-only Sheets links in any order. Each tab's role (ledger, budget, revenue) is decided from its fields, not its name or column order.
- `--reporting-date` and `--prior-date` come from the manager's request for each report. Never infer them from the ledger or by skipping weekends. If the request does not give both, ask.
- Output goes to `../deliverables/` (override with `--out-dir`): `report.md` and `normalized/{transactions,budget,revenue}.csv`.
- The run prints each source's URL, spreadsheet ID, tab, fetch time, row count and checksum before it publishes. The same details are in `report.md`.
- Check the code with `python3 -m unittest discover -s tests`.

The sources for the Quillhaven brief:

- Transaction ledger: https://docs.google.com/spreadsheets/d/16HhjfR9uG1oUwSFNjQvAvU9Q9gVjzxL0ufBzTJe82v8
- Budget targets: https://docs.google.com/spreadsheets/d/1pnHBrxWvZBDIQItyxhmaSUZBxF8VMYqo_fyN7JtgyA4
- Revenue snapshot: https://docs.google.com/spreadsheets/d/1DToTpZtuwtVIdCPethZRe4T-y6mxGpWuivWSmR2XZt4

## What happens on failure

Exit code 1 means the run failed, usually because the sources could not support a reliable brief; exit code 2 means the arguments were wrong. Either way the run deletes every earlier deliverable, so nothing stale can be read as current, and leaves `../deliverables/RUN_FAILED.md` with the reasons. This includes unexpected errors and a failure while writing outputs. Each reason names the owner who must clarify it (Operations for the ledger, Finance for budget and revenue). Relay those requests to the manager. Do not retry with cached or downloaded copies, edit a Sheet, or guess a missing value.

Stops the run: a source that cannot be fetched or identified, duplicate transaction IDs, more than one source version in a sheet, unrecognized statuses, unreadable amounts or dates, an unmapped category, a second currency, no ledger rows on either date.

Does not stop the run, and appears in the report instead: a pending or disputed row whose amount is unknown, and a missing revenue snapshot for either date.

## After a run

1. Read `report.md` section 1 (decisions needed) and section 5 (clarification requests) first, and tell the user what needs their decision or a source owner's clarification.
2. Quote the key figures exactly as written, with sign and currency. Never round them or describe only their direction.
3. Say plainly that the brief is a draft and which items are unresolved.

## References

- `references/business-rules.md`: the confirmed rules and where each came from in the interviews.
- `references/sources-and-validation.md`: what each source holds, the checks that block a run, and role detection.
- `references/report-structure.md`: the report's sections and the traceability each figure carries.
