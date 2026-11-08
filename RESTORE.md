# Restoring from a backup

Written in Session 32. The steps are standard for each service, but **they have not been run against your live host**: do one practice restore into a spare database before you ever need it.

## What a complete backup is
1. **The database** (people, courses, invoices, payments, grades, activity log).
2. **The files** (ID cards, payment slips, assignment and tutorial uploads, expense receipts): the S3 bucket on the host, or `instance/uploads/` locally. The database only stores file names, so a database backup without the files leaves broken downloads, and the other way round.
3. **Your `.env` / Vercel environment variables**, especially `SECRET_KEY`, `DATABASE_URL`, the bucket keys and `CRON_SECRET`. Keep a copy somewhere safe, not in the repository.

Take 1 and 2 together, before every migration and on a schedule (daily is sensible). Never store a backup in the code repository: it contains ID cards and personal data.

## Local (SQLite)
1. Stop the app.
2. Keep the damaged copy (`mv instance/portal.db instance/portal.db.broken`), then copy the backup `.db` file to `instance/portal.db` and the backed-up `uploads/` folder to `instance/uploads/`.
3. Start the app. The schema and added columns are re-applied on start (`CREATE TABLE IF NOT EXISTS`), so a backup from an older version is upgraded automatically; then run any `migrate_sessionNN.py` scripts newer than the backup (dry run first, `--apply --i-have-a-backup` second; each is safe to run twice).
4. Check, below.

## Hosted (PostgreSQL + bucket)
1. Put the site in a quiet state: tell staff not to enter payments; turn off Vercel cron by removing `CRON_SECRET` for the time of the restore (the cron endpoints then refuse to run).
2. Restore into a **new, empty** database first (provider console "restore to new database", or `psql "$NEW_URL" < backup.sql` for a `pg_dump` file). Do not restore over the live one until the check below passes on the new one.
3. Point `DATABASE_URL` at the restored database, redeploy, run the newer migration scripts as in step 3 above.
4. Files: restore the bucket from its own versioning or backup (the provider's "restore previous versions"); if you only have the database backup, files uploaded after that backup are gone and their download buttons will show the "file not found" message, nothing else breaks.
5. Put `CRON_SECRET` back and redeploy.

## Check after any restore
- Sign in as admin; open Fees, Finance and the Activity log.
- Open one ID card copy, one payment slip and one receipt (proves the files match the database).
- Compare the counts the Admin dashboard shows (students, teachers, batches, enrolments) and the Finance dashboard totals with your last known figures.
- Fees, Notifications: run **Catch-up** on Fees only if invoices for the current month are missing. It never creates duplicates.
- Payments, approved earnings months and the Activity log come back as they were at backup time. Anything done after the backup (payments entered, grades, approvals) must be re-entered by hand; the Activity log of the broken copy, if you kept it, tells you what.

## Things a restore does NOT do
- It does not log people out: tokens stay valid until they expire (signed with `SECRET_KEY`). If you suspect a leak, change `SECRET_KEY` (everyone signs in again) and reset the passwords concerned.
- It cannot bring back a single deleted row on its own; for that, restore into a new database and copy the rows across.
