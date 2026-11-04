# Baleegh Academy Portal

**Status: Phases 1-4 of 7 complete, Phase 5 started, plus the admin controls below and persistent storage (hosted PostgreSQL + bucket files).** Foundation (login, roles, courses, batches, enrollment, admin shell, English/Dhivehi), admissions (public form, private ID uploads, admin approval queue) learning tools (timetable with Join class, attendance, assignments and tests, grades, class materials) and fees (monthly invoices, discounts, bank-transfer slips with admin verification, PDF receipts, overdue reminders, monthly report).
Next: tutorials and announcements (Phase 5), reports and certificates, delivery.

## Persistent storage (hosted PostgreSQL + file bucket)
Out of the box the portal keeps data in a SQLite file and uploads in a folder, which is fine on your own computer or a server with a disk. On Vercel (no permanent disk) use the hosted setup below so nothing is lost on redeploy.
1. **Database:** create a free PostgreSQL database (Supabase, Neon, Render, Railway). Copy its connection address into `DATABASE_URL`. On Vercel use the host's *pooled / transaction pooler* address. Tables are created automatically on first start.
2. **Files:** create a private bucket on any S3-compatible service (Supabase Storage, Cloudflare R2, Backblaze B2, AWS S3) and set `S3_BUCKET`, `S3_ENDPOINT_URL`, `S3_REGION`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`. Keep the bucket **private**: files are only ever served through the portal, after it checks who is asking.
3. **Check it:** `python check_storage.py` (with the same variables set). It reports OK or FAILED for the database and for files. Run it before you rely on it.
4. **Existing data?** `python migrate_to_hosted.py --dry-run`, then without `--dry-run`, copies your old SQLite file and uploads folder into the new database and bucket. It refuses to run into a database that already has people.
5. First start creates the admin from `ADMIN_EMAIL` / `ADMIN_PASSWORD`. On hosted PostgreSQL the demo teacher/student accounts are **not** created (their passwords are public in this README); set `SEED_DEMO=1` only for a test database.
- **Vercel upload size:** Vercel rejects any request over 4.5 MB, so on Vercel the portal limits uploads (slips, ID copies, assignments, materials) to **4 MB** and says so. For larger files (audio, video) run the portal on Render, Railway, Fly.io or a VPS, where the limit does not apply.
- Backups: your database host keeps backups (check the plan; free tiers are often limited), and bucket files are kept by the bucket. Test a restore once.
- Connections: each request opens its own connection, which is why the pooled address matters on Vercel.
- Tests: `python -m unittest tests.test_hosted_storage -v` covers the PostgreSQL translation and the bucket code using stand-ins. Only `check_storage.py` against your real services proves the live connection.

## Run locally
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then edit SECRET_KEY
export $(grep -v '^#' .env | xargs)
ADMIN_EMAIL=you@example.com ADMIN_PASSWORD='a-long-password' python seed.py
python app.py               # open http://localhost:5000
```
Seed also creates demo teacher and student accounts (`teacher@baleegh.test`, `student@baleegh.test`).
**Disable or change all demo passwords before going live** (People tab).

## Run tests
`python -m unittest tests.test_phase1 tests.test_phase2 tests.test_phase3 tests.test_phase4 tests.test_phase5 tests.test_admin_controls tests.test_hosted_storage -v`
Optional browser test (phone-sized screen, real app): `pip install playwright && playwright install chromium && python tests/e2e_browser.py`

## Production
`gunicorn -w 2 -b 0.0.0.0:8000 "app:create_app()"` behind HTTPS (Render, Railway, Fly.io or a VPS).
If the frontend stays on Netlify, set `CORS_ORIGINS` to your Netlify URL and add
`<script>window.PORTAL_API="https://your-backend-url"</script>` before the main script in `static/index.html`.
Back up `instance/portal.db` daily, or set `DATABASE_URL` to use PostgreSQL (see Persistent storage above).

## Admissions
- Public form: `/apply.html` (link it from your Netlify site's Register button). Under-18 applicants must give guardian details and a guardian ID copy.
- ID copies are saved in private file storage (`instance/uploads/` locally, or your bucket; never served publicly; only admins can open them via the portal, and each view is logged). Back them up with the database.
- Admin: Admissions tab -> Review -> assign batch -> Approve. This creates the student account, enrolls them, and shows a one-time temporary password plus a WhatsApp button with a ready message. Tick "delete ID copies" to remove the files after verification.

## Learning tools (Phase 3)
**Set up each batch once (admin, Batches tab -> Edit):** tick the class days, set the start time and the Google Meet link. Without days there is no timetable, and the portal says so.
- **Timetable and Join class.** The weekly pattern comes from the batch days and start time (Maldives time). Teachers and admins can cancel one class or add an extra class (Classroom -> Schedule). Students see their next class on Home; the **Join class** button appears 15 minutes before the start (`JOIN_EARLY_MIN`) and stays until the class ends.
- **Attendance** (teacher or admin, Classroom -> Attendance). Pick the date, change the exceptions (everyone starts as Present), save. You cannot mark a class that has not happened yet, and cancelled classes cannot be marked. Percentage = (present + late) / (present + late + absent); excused classes are not counted for or against the student. A student is flagged "low attendance" when they have at least 3 counted classes and are below the warning level (Settings, default 75%).
- **Assignments and tests.** Assignments take a written answer and/or a file (PDF, JPG, PNG, DOCX, MP3, M4A or MP4, up to `LEARNING_MAX_MB`, default 20 MB). Resubmitting replaces the earlier work until it is graded; late work is flagged but accepted. Tests/quizzes have no submission: the teacher just enters marks. Grades are numbers from 0 to the maximum points, with written feedback.
- **Progress.** Students see attendance, grades and an overall average per course. Teachers see a gradebook per batch (average grade, attendance, low-attendance flag).
- **Materials.** Teachers upload files or add links per batch (PDF, images, DOCX, PPTX, XLSX, audio, MP4). Only that batch's students, its teacher and admins can open them. (The shared tutorials library for everyone arrives in Phase 5.)
- Access rules are enforced on the server: a teacher only reaches their own batches, a student only their own submissions, grades and attendance. Downloads are checked per request and are never served from a public folder.

## Fees (Phase 4)
Money is whole MVR. Teachers cannot see any fee data; students see only their own.
- **Set the bank details first:** Settings -> bank name, account name, account number. Until they are filled in, students see a friendly "not added yet" message instead of blank fields. The same screen holds the due day, receipt prefix and reminder messages.
- **Invoices:** one per active enrollment per month, using the course fee at that moment (later fee changes never rewrite old invoices). Waitlisted, dropped, completed and fee-0 enrollments are not billed. Fees tab -> Invoices -> **Generate invoices** (pick the month). Pressing it twice is safe. A new student's first invoice is created automatically when they are approved or enrolled.
- **Schedule it:** the portal does not assume a scheduler exists. To create each month's invoices automatically, run `python generate_invoices.py` from cron on the server (load your `.env` first):
  `0 1 1 * *  cd /path/to/baleegh-portal && . .venv/bin/activate && python generate_invoices.py >> instance/invoices.log 2>&1` (01:00 UTC = 06:00 Maldives time on the 1st). Running it daily is also fine; it only adds what is missing. `--month 2026-04` does a specific month.
- **Discounts:** per invoice (Invoices -> Discount: type `50` for MVR 50 or `10%`, then a required reason) or recurring per enrollment and per family (Discounts and families). A discount can never take an invoice below 0.
- **Student pays:** Fees tab shows the bank details, a reminder to put the invoice number in the transfer reference, and an Upload slip form (amount, date, reference, PDF/JPG/PNG up to 5 MB).
- **Verify slips:** Fees -> Slips to verify -> Open slip, check your bank statement, type the amount you actually received, **Verify**. Less than the amount due leaves the invoice open with a balance; more is refused. **Reject** needs a reason, which the student sees. The same slip file used twice triggers a warning. A verified payment cannot be edited, only reversed (Record payment -> Reverse, with a reason).
- **Cash or other payments:** Fees -> Record payment. Every payment gets a sequential receipt number (`BA-R-0001`, prefix editable, numbers are never reused) and a PDF receipt that students and admins can download.
- **Reminders:** Fees -> Overdue and reminders lists overdue invoices with WhatsApp and Viber buttons (student, and guardian when a number is on file). Clicking records who sent it and when, so nobody is messaged twice by accident. Edit the wording in Settings (`{name} {amount} {invoice} {due_date} {course} {academy}`).
- **Email reminders are OFF.** Set `EMAIL_ENABLED=1` and the `SMTP_*` values in `.env` to turn them on (see `.env.example`). While off, the portal says so and sends nothing.
- **Monthly report:** Fees -> Monthly report: invoiced, collected, outstanding, overdue count, per course, who owes, and a CSV download. The Dashboard shows unpaid invoices and this month's collection. Students see a "fees to pay" notice on Home.
- Slips and receipts are private files (`instance/uploads/slips/` locally, or your bucket), only served to the owning student and admins, and every open is logged. Back them up with the database.
- **Online gateway later:** all money goes through `payments.py` (`record(...)`), so a gateway only needs to call it with `method="gateway"`.

## Assignments with a file, and Tutorials (Phase 5, started)
- **Assignments:** when a teacher creates an assignment or test they can write the instructions, attach a file (worksheet, PDF, image, Word, PowerPoint, Excel, audio or video, up to `LEARNING_MAX_MB`), or do both. Students see a "File from your teacher" button on the assignment. Only the batch's teacher, its enrolled students and admins can download it.
- **Tutorials tab (everyone):** anyone signed in can read and post. A post has a title and any mix of written text (up to 8000 characters), one file and one link, with an optional course tag. Search and course filter on top. Poster or admin can delete a post (the file is removed too). Every post and delete is in the Activity log, so admins can monitor everything.
- Not built yet: teacher approval of student posts, comments, reporting a post. Tell me if you want any of these. Student posting is open by design (you asked for free upload); if it gets noisy, switching it to teachers-only is a one-line change in `l_tut_add`.
- Existing databases get the two new assignment columns automatically on restart.

## Day-to-day (admin panel)
- Add a course: Courses tab. Add a batch with its Meet link and teacher: Batches tab.
- Add teachers and students: People tab. Enroll a student: Enrollments tab (full batches waitlist the student).

## TODOs for you
**Fees (Phase 4), all have working defaults you can change in Settings:**
- Invoice due day: defaults to the **10th**. New students get at least 7 days from joining. Please confirm.
- First month: billed as a **full month**. Proration is not built (`first_invoice_mode` can be set to `skip` to start billing next month). Please confirm.
- **Sibling/family rule:** no rate is assumed. Enter the amount or percent you decide in Discounts and families.
- Late fee: **none**.
- **Bank details:** empty until you enter them in Settings.
- **Email service** for reminders: not chosen. Google Workspace SMTP is the likely choice.
- Reminder wording in English and Dhivehi (the Dhivehi template is empty; English is used until you add one).
- Fees for the two coming-soon courses are 0 (no invoices are created); set them in Courses when known.
- Receipt prefix/format: `BA-R-0001` is my default. Receipts are English only (a Thaana name prints as "?" because the built-in PDF fonts have no Thaana).
- Slip upload limit (10 per hour) is counted per server process; with several gunicorn workers it is per worker.

- **Batch days and Meet links are still empty for batches 004 and 005** (they are not on your website, so I did not guess). Until an admin sets them in Batches -> Edit, students see "no class days set" and no Join button.
- Confirm the attendance rules I chose: late counts as attended, excused is not counted, low-attendance flag at 75% after 3 counted classes. All are easy to change.
- Confirm the Join button window (15 minutes before the start) suits your teachers.
- Dhivehi strings in `static/i18n/dv.json` are a small machine-drafted set. A Dhivehi speaker should review and complete them; missing keys show in English.
- Confirmation emails are not sent yet (no email service is configured). Applicants get their reference on screen with a WhatsApp link, and you send login details by WhatsApp. Tell me which email service you want (for example your Google Workspace SMTP) and I'll add it.
- Email-based password reset is not built yet (admins can reset passwords for now).
- Confirm which Facebook page is the real one (your two sources differ).

## Deploying on Vercel
Entry point is `app:app` (set in `pyproject.toml`). In Vercel -> Project -> Settings -> Environment Variables set `SECRET_KEY` (long random), `CORS_ORIGINS`, and optionally `ADMIN_EMAIL` / `ADMIN_PASSWORD` (used to create the first admin on a fresh start).
**Important:** Vercel functions have no permanent disk. Without `DATABASE_URL` and `S3_BUCKET`, the SQLite database and uploads live in `/tmp` and are lost on redeploy or when the instance recycles. That is fine for a demo only. For real student data set `DATABASE_URL` and the `S3_*` variables (see Persistent storage), then run `python check_storage.py` locally with the same values.

## Admin controls (added after Phase 5 start)
- **Edit and correct everything:** people (name, email, phone, role, student/teacher details, password, active), courses (all fields), batches (name/code, course, days, time, seats, teacher, link, status), enrollments (move, change status), applications (fix typos before deciding).
- **Delete mistakes safely:** people, courses, batches and enrollments created by mistake can be deleted. Anything with real records (enrollments, grades, invoices, applications) is refused with a clear message: disable it or set it to Closed/Dropped instead, so history is never lost.
- **Admin permissions:** People -> Edit an admin -> *Limited to the areas ticked*. Areas: admissions, courses, batches, classroom, people, enrollments, fees, settings, audit. Limited admins only see their tabs and the server refuses the rest. Only a full admin can create admins or change permissions, nobody can change their own role/permissions, and the last full admin cannot be disabled, deleted or restricted.
- **Settings** (grouped tabs, each with defaults and hints): academy details and login-page notice, admissions open/closed + closed message + guardian age + default seats + approval message template, Join-class lead time and attendance warning, minimum password length and sign-in duration, bank details and invoice rules.
- **Audit log** now records what changed (old -> new), never passwords.
Tests: `python -m unittest tests.test_admin_controls -v`
