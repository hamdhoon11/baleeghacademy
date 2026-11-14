# v0.8.49: template download fix, server-error reasons, salary calculation explained, contact number required

Builds on v0.8.48. **Database change: additive only** (new table `server_errors`, created automatically on start).

Reported: "Something went wrong on the server" when downloading the import template (Finance → Import expenses from Excel); teacher salary calculation not working; adding a person in People must require a contact number.

## What was checked
Both features were run against a real PostgreSQL 16 database (like the live site), on a fresh database and on databases upgraded from the oldest versions in the history. Both worked there, so the live failure depends on something in the live data. The live error log is only in Vercel, which this session cannot read.

## Fixed: templates and Excel downloads with hidden characters
- Found: a name holding a hidden control character (often from copy-paste, e.g. an expense category) crashed the template download. The first category is used as the example in the template, so one bad name broke the whole file.
- Now every text written into a template or Excel download is cleaned of characters Excel files cannot hold (expense, course, batch, people and grade templates, and every Excel report).
- This is the most likely cause of the template error. If it still fails, the new error reference (below) will say exactly why.

## New: the reason for "Something went wrong on the server"
- Every unexpected server error is now recorded with a short reference (e.g. `CB7E99`).
- The message on screen gives the reference; **admins also see the technical reason** in the same message.
- **Settings → Server errors** (full admins): the last errors with time, page, person, reason and code lines. Kept: the last 500; never passwords or form contents. Clearing the portal's data keeps them.

## Teacher salary (earnings) calculation explained
Calculate now says what it found, in a box under the buttons:
- When nothing was paid in the month: "No fee payments were recorded with a payment date in 2026-10. Teacher earnings count fees in the month they were PAID…", plus the months that do have payments.
- How much was paid, how much is on batches and counted for teachers, registration fees (not shared), and money on invoices with no batch.
- **Batches with no teacher:** named, with "Choose a teacher in Batches, then press Calculate again" (their share goes to the academy).

The calculation itself is unchanged: it counts fees by the date they were paid, for monthly-fee invoices on a batch, at the share % in Settings.

## Contact number required when adding a person
- **People → Add person** has a **Contact number** field and it is required (at least 7 digits; `7771234`, `+960 777 1234` and the like). The server refuses an add without one ("Enter a contact number").
- Editing existing people is unchanged. The People Excel import and online applications follow their own rules as before.

## Checks run
- Unit tests: whole suite **538, all pass**. New `tests/test_session49.py` (5): number required and checked; error recorded with reference and reason; server errors for full admins only; template with a hidden character downloads; Calculate explains an empty month. `test_session41` (reset keeps server_errors) and the `test_session32` security map were updated.
- PostgreSQL 16 (local, through a small test driver): template downloads, calculation, error recording, number rule.
- Browser: new `tests/e2e_v0849.py` at 390 px (5 checks, all pass).
- Not tested: the live Vercel site itself.
