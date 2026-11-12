# v0.8.41: Clear portal data (keeps the admins)

Builds on v0.8.40. Independent of v0.8.39 (the security fixes). No database change.

Asked for: remove all the data that was entered in the portal and keep only the login IDs; then: keep the admins only.

## New: Settings → Clear portal data
At the bottom of Settings, for **full admins only** (an admin limited to some areas does not see it and is refused by the server).

1. **Clear portal data…** first shows a preview: how many records of each kind would be deleted, and what is kept. Nothing is changed yet.
2. **Continue** asks for three things: whether ID and receipt numbers carry on or start again from 1, **your password**, and the words **DELETE ALL DATA** typed exactly.
3. Then everything is deleted in one step. If anything fails half way, nothing is deleted.

**Kept:** every admin account (login ID, password, permissions), the settings, and the activity log. The log cannot be deleted by design; it gets one new line saying who cleared the data, when, and how much. Old log lines still hold the names they were written with.

**Deleted:** teacher and student accounts and profiles, courses, batches, enrolments, transfers, applications and their ID copies, classes, attendance, assignments, submitted work and grades, materials, recordings, tutorials and answers, substitutes, families, invoices, discounts, payment slips, payments, reminders, expenses and their categories, monthly expenses, teacher earnings and payments to teachers, notifications, the WhatsApp log, password requests, and every uploaded file.

**Numbers:** by default student, teacher, enrolment and receipt numbers carry on from the last one, so a number is never given out twice. "Start again from 1" restarts them; admin IDs never restart.

**It cannot be undone.** Take your database provider's backup first (Supabase / Neon: Backups, or `pg_dump`).

Decisions made where no preference was given: courses and batches are deleted too ("login IDs only"); settings and the activity log are kept.

## Also from the command line
`python resetdata.py` shows what would be deleted (a dry run). `python resetdata.py --apply --i-have-a-backup` deletes; add `--reset-numbers` to restart the numbers. The command line does not remove files from a bucket or folder (files kept in the database go with it).

## Route
`POST /api/admin/reset-data` (Settings area, full admin). `{}` returns the preview. `{"apply": true, "password", "confirm": "DELETE ALL DATA", "reset_numbers"}` deletes. A wrong password is written to the activity log.

## Checks run
- Unit tests: whole suite in one run, 471 tests. 470 pass; the one failure is the `test_session13` date test, which fails between 00:00 and 05:00 Maldives time and is fixed in v0.8.39.
- New `tests/test_session41.py` (10): the deletion order matches the references the database reports; teacher, student and limited admin refused; the preview changes nothing; wrong words or password delete nothing; after clearing every data table is empty, both admins sign in as before, settings and counters unchanged, the log has one more line, uploaded files are gone, and the portal works (new teacher, new course); numbers restart when asked and admin IDs do not; a failure half way deletes nothing; rows in the PostgreSQL shape; files kept in the database; the command line (dry run, refusal without the backup flag, apply). `test_session32` security map updated for the new route.
- Browser: new `tests/e2e_reset.py` (12 checks on a phone screen); `e2e_navigation.py`, `e2e_permissions.py`, `e2e_ui.py` pass. The other twelve scripts were not run.
- **Not tested: a real PostgreSQL database**, a real Vercel deployment, a bucket (S3) for files. On PostgreSQL a failure rolls everything back, so the worst case is that nothing is deleted.
