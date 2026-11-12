# v0.8.40: teacher earnings fixed on the hosted database

Builds on v0.8.38 (independent of v0.8.39, the security fixes; the two can be merged in either order). No database change.

## What was wrong
Reported: in Finance → Teacher earnings, calculating, showing or approving did not work.

- **Calculate and Approve month failed on the hosted (PostgreSQL) database** with "Something went wrong on the server". `earnings.py` turned every database row into a tuple with `tuple(row)`. On SQLite (a local copy, and all the tests) that gives the values. On PostgreSQL the portal's rows are dictionaries, so it gave the column **names**, and the calculation then tried to read the word `sum` as an amount. Approve recalculates first, so it failed the same way.
- **Show looked broken** because nothing could be calculated: the table was simply empty, with Approve switched off and no explanation.
- **A month the server refuses** (one that has not started, or typed in another form on a browser without a month picker) turned the whole Finance tab into an error, and it stayed so until the page was reloaded.

## What changed
- `dbx.values(row)`: a row as a tuple of its values on both databases. `earnings.py` uses it for Calculate and Approve.
- The same mistake in two upgrade scripts: `migrate_session30.py` (earnings backfill) could not run against PostgreSQL, and the "nothing changed" check in `migrate_v0837.py` compared column names instead of data there.
- Teacher earnings panel: an empty month says "Nothing is calculated for this month yet. Press Calculate…"; a refused month shows its message inside the panel and the rest of Finance stays; the month box shows `YYYY-MM` as a hint where the browser has no month picker.

## What you need to do
Nothing before deploying. Afterwards: Finance → Teacher earnings → choose the month → **Calculate** → check the figures → **Approve month** (finished months only). Earlier months that could not be calculated can be done the same way, one month at a time.

## Checks run
- Unit tests: whole suite in one run, 461 tests. 460 pass; the one failure is the `test_session13` date test, which fails between 00:00 and 05:00 Maldives time and is fixed in v0.8.39.
- New `tests/test_session40.py` (5): the whole earnings flow with rows in the PostgreSQL shape (preview, calculate, re-run, empty month, approve rules, owed, pay, void, teacher's own view, report, CSV, Excel); `dbx.values`; no `tuple(row)` left in the server code; a refused month. Three of them fail on the old code.
- The whole unit suite was also run once with every row in the PostgreSQL shape: all earnings tests pass (14 failed before); what still differs is in the tests themselves, not the portal.
- Browser: new `tests/e2e_earnings.py` (13 checks on a phone screen, server giving PostgreSQL-shaped rows: empty hint, Calculate, Approve, locked month, Record payment, refused month, Show again); `e2e_navigation.py` and `e2e_browser.py` pass. The other eleven scripts were not run.
- **Not tested: a real PostgreSQL database** (none is available here; the row shape was imitated), a real Vercel deployment, real phones.
