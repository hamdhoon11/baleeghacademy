# v0.8.34: download problems fixed

Reported: after uploading, downloads said "The file could not be found. It may have been removed."

## What was wrong
1. **Uploads were lost on Vercel.** With no bucket (`S3_BUCKET`) set, uploaded files went to Vercel's temporary disk (`/tmp`). Each Vercel copy of the app has its own, and it is wiped, so the next request often found nothing. This gave exactly the message above.
2. **Arabic and Dhivehi file names crashed downloads.** The original name went straight into the `Content-Disposition` header, which a real server (gunicorn, Vercel) can only send in Latin letters. The server failed with `UnicodeEncodeError` (confirmed on a running server with `درس.pdf`). Dhivehi names also lost their vowel signs when saved.
3. **"View" opened a blank tab first.** On Android (no built-in PDF viewer), in iPhone home-screen apps and with popup blockers that tab stayed empty, and it was left open when a download failed.
4. **CSV exports showed garbled text in Excel** for Arabic and Dhivehi names (no BOM) in the activity log, payment report, monthly fee report and transfers exports.

## What changed
- **Files in the database on Vercel** (`storage.DbStorage`, table `stored_files`, BYTEA on PostgreSQL). Chosen automatically on Vercel when no bucket is set. `FILE_STORAGE=db|s3|local` forces a choice. A file and the record pointing to it are saved in the same commit, so a failed upload leaves nothing behind. Needs `DATABASE_URL` (PostgreSQL) on Vercel, as data already did.
- **Download names:** `filename="english-fallback.pdf"; filename*=UTF-8''<full name>` (RFC 6266). Browsers save the real Arabic or Dhivehi name. `common.shown_name()` keeps vowel marks.
- **Viewer inside the page** (`ui.viewer`): images always show; PDFs show where the browser can display them, and on Android the viewer says so and offers Download. Download and "Open in a new tab" are always there. No tab is opened before the file arrives.
- **Files and storage** (Settings): where files are kept, the database type, number and size of stored files, and whether files survive restarts. "Check for missing files" lists every ID copy, slip, assignment file, submission, material, tutorial file, answer and receipt whose file is gone. A red banner on the Dashboard and in Settings appears when files would be lost. New routes `GET /api/admin/storage` and `GET /api/admin/storage/missing` (Settings area, read only).
- Clearer message for a missing file ("...ask the person to upload it again").
- CSV exports start with a BOM and say `charset=utf-8`.
- `migrate_to_hosted.py` now also copies expense receipts, and works with database storage. `check_storage.py` works with database storage.
- Removed `static/i18n/dv.json`, a leftover from before Phase 3 that was still in the repository (the app no longer has Dhivehi text; a test checks the file is gone).

## What you need to do on Vercel
1. Make sure `DATABASE_URL` (PostgreSQL) is set. Files now live in the database, so the database must be the permanent one.
2. Leave `FILE_STORAGE` empty (or set it to `db`). If you later add a bucket, set the `S3_*` variables instead.
3. After deploying: Settings -> Files and storage. "Files survive restarts" should say Yes. Press "Check for missing files" to see which old uploads were lost, and ask those people to upload again. Lost files cannot be recovered.

## Checks run
- Unit tests: whole suite in one run (`python -m unittest discover -s tests`), including the new `tests/test_session34.py`.
- Browser: all 10 `tests/e2e_*.py` scripts; `e2e_ui.py` now also opens an Arabic-named PDF in the viewer, downloads it with its real name, and checks the Android path and the storage panel.
- Not tested: a real Vercel deployment, a real PostgreSQL database, real Android and iPhone devices.

## Known, not fixed
- PDF receipts and invoices print Arabic or Dhivehi names as "????" (the built-in PDF fonts have no such letters). Fixing it needs a bundled Arabic and Thaana font plus right-to-left shaping.
