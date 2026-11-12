# HANDOFF

## Done: Session 8 (v0.8.8): project map, ID card and file errors
- Cause of "Unexpected token ... is not valid JSON": `static/index.html` admissions viewer did `(await r.json()).error` on a failed file request; Flask/Vercel answered 404/413/500 with HTML.
- Added `fetchFile()` / `readError()` in `static/index.html`; `download()` and new `viewFile()` in `static/learning.js` use it. Slip view (`fees.js`), assignment attachment, submission, material, tutorial and tutorial-answer buttons now preview PDF/images.
- Server: JSON error handlers for all `/api/*` (HTTPException, 413 with size message, FileNotFoundError, unexpected 500); storage raises `FileNotFoundError` for missing files; `common.file_headers()` sets Content-Disposition, no-store and nosniff on admission, slip and learning files; `?download=1` on the admission file route.
- New: `CONTEXT.md` (generated map), `tests/test_session8.py`, i18n keys `file_too_large_server`, `file_missing`, `file_forbidden`, `file_open_failed`.

## Left over / not verified
- Not tested in a real browser or on the live Vercel + bucket setup. Run `python check_storage.py` and open an ID copy of each type (PDF, JPG, PNG) on the hosted site once.
- Pop-up blockers: preview opens a new tab at the click. If a browser blocks it, the file falls back to a download.
- Public form (`static/apply.html`) still reads replies with `r.json()`. Its API replies are now always JSON, so the original error cannot occur there, but a Vercel-level 413 (before the app runs) would still show a generic message. Fix when that form is next touched.
- `tests.test_warm_connection` fails only when run after the other test modules (already so in v0.8.7); it passes alone.
- File size limits differ by route (ID copies 5 MB, learning files `LEARNING_MAX_MB`); on Vercel all are capped at 4 MB.

## Decisions recorded
(none recorded in this session; the latest list is the last "Decisions recorded" section below)

## Done: Session 9 (v0.8.9): invoice generation for new courses
- Confirmed cause with a reproduction: a course with fee 0 (the default when the form's fee is left empty) never gets an invoice, at enrolment or in generate; any fee above 0 invoiced correctly. No other cause found.
- Fix: fee 0 stays "not billed" (free courses are possible) but is no longer silent. Course create answers `warning: fee_zero` and the course forms show a live warning; `POST /api/enrollments` returns `invoice_id` / `invoice_skipped` / `invoice_message`; `generate()` returns `details` (student, course, batch, reason, message per skipped enrolment, first 500); setting a fee from 0 to above 0 bills the already enrolled students for the current month.
- Automatic generation: `GET/POST /api/cron/generate-invoices` (Bearer CRON_SECRET, constant-time compare, 401 when wrong or unset), registered in `vercel.json` daily at 01:00 UTC; `POST /api/invoices/catch-up` called once per session when an admin opens Fees. Both only add missing invoices (UNIQUE enrollment_id, period) and write one audit row when something was created.
- Admin invoice PDF: `GET /api/invoices/<id>/invoice.pdf` (`receipts.build_invoice`), audited as view_invoice_pdf, button on each invoice row.
- Tests: `tests/test_session9.py` (10). Full unit run: 212 tests OK (test_warm_connection passes alone).
- Files touched: fees.py, app.py, receipts.py, static/fees.js, static/admin.js, static/i18n/en.json, vercel.json, docs.

## Left over / not verified
- **You must set `CRON_SECRET` in Vercel (Project, Settings, Environment Variables) and redeploy.** Until then the cron answers 401 and only the catch-up on opening Fees and the enrolment hook create invoices. Check Vercel, Cron Jobs tab, that the job is listed and run it once.
- Vercel Hobby allows one cron run per day, which is what is configured.
- "Student ID" on the invoice PDF is the internal user id for now; Session 10 adds the real student_code, then switch `student_id` in `invoice_pdf` to it.
- Browser behaviour (warning box, PDF download, skip list under Generate) is syntax-checked only, not clicked through. Fee-0 course creation still succeeds; only a warning is shown.
- `static/index.html` still has an older inline Courses form; `admin.js` replaces it, so the warning is added there only. Session 12 rebuilds that screen.
- `generate_invoices.py` (own-server cron) unchanged; it does not print the per-enrolment reasons.

## Decisions recorded
(none recorded in this session; the latest list is the last "Decisions recorded" section below)

## Done: Session 10 (v0.8.10): course type and ID codes (MIGRATION)
- New `idcodes.py`: counter-based generator (`counters` table, row lock until commit, rolled-back request gives the number back), `fill_missing()` = backfill + "new row gets a code", `derive_course_code`, `duplicates`.
- Columns: courses.kind/code/is_active, students.student_code, teachers.teacher_code, enrollments.enrol_code, added in `dbx.init_schema` (also in schema.sql for fresh databases) with four unique indexes. Additive; the app works before the backfill is run.
- `migrate_session10.py`: DRY RUN by default (runs the real backfill and rolls it back, prints every code and row counts before/after); `--apply --i-have-a-backup` to write. Refuses to apply without the flag. Second run finds nothing to do. Aborts and rolls back if a duplicate would appear.
- Hooks (app.py): users create/update, enrolment create, transfer, application approval call `fill_codes()` before commit; course create sets its code; `seed.py` fills codes. Courses API accepts `kind`, `code`, `is_active` (validation, 409 on duplicate code).
- Tests: `tests/test_session10.py` (14): derivation, concurrent counter (4 threads, 60 numbers, no gaps), rollback, upgrade from the v0.8.8 schema, dry run changes nothing, apply, apply twice, hand-typed codes skipped, unique index, CLI refusal without backup flag, app runs on upgraded DB, API behaviour. Old suites: 226 tests OK on the fresh schema, and 191 tests OK when every test database is created with the old schema and upgraded (patch `dbx.read_schema`, see CONTEXT.md).
- Files touched: idcodes.py (new), migrate_session10.py (new), dbx.py, schema.sql, app.py, seed.py, docs, tests.

## Decisions recorded
- Session 10 (from the user): IDs follow the BAL format and "any form relating to it" is fine. Chosen: students `BAL/<COURSE CODE>/NNN` (example BAL/AL1/001, BAL/G8M/001), teachers `BAL/T/NNN`, enrolments `BAL/<COURSE CODE>/ENNN` (the extra E is my choice so an enrolment code never looks like a student ID; tell me if you want it changed before Session 11, it is a one-line change in `idcodes.enrol_code_for`).
- Course codes derive from name + level (Arabic Level 1 = AL1, Grade 8 Mathematics = G8M); an admin can set or change a code through the API; issued student IDs never change when a course code is edited.
- A student's permanent ID comes from the first course they join; students with no enrolment get `BAL/STU/NNN` only through the migration; new accounts get no ID until a first enrolment unless the create request names a `course_id`.
- Still needed: Session 11 (do admins log in by ID or keep email), Session 29 (WhatsApp provider), Session 31 (teachers see own earnings?).

## Left over / not verified
- **Not run against a real PostgreSQL**: no PostgreSQL in the test environment. Only portable SQL is used (ON CONFLICT DO NOTHING, UPDATE then SELECT on the counter, ALTER ADD COLUMN, CREATE UNIQUE INDEX IF NOT EXISTS), but run the dry run on a copy of the hosted database first and read the report.
- `migrate_to_hosted.py` copies only columns that exist in the source, so a SQLite file older than v0.8.10 arrives without codes; run `migrate_session10.py` on the hosted database afterwards.
- `courses.is_active` and `courses.kind` are stored and editable through the API but nothing uses them yet (Session 12). `public/courses` does not list `code`/`kind` yet.
- No screen shows the codes (by design); the Session 9 invoice PDF still prints the internal user id as "Student ID": switch it to `student_code` (fall back to the id when empty) in Session 11 or 16.
- Dropped-and-reactivated enrolments keep their old enrol_code; a transfer to a new batch creates a new enrolment row with a new code.

## NEXT SESSION: 11 (login by ID and account management). Ask me first: do admins log in by ID or keep email?

## Done: Session 11 (v0.8.11): login by ID and account management
- `users.login_id` (unique index `ux_users_login_id`, added in `dbx.init_schema` and schema.sql, additive). `idcodes.fill_missing()` step 5 backfills it: students and teachers use their own code, admins get `BAL/A/NNN` (counter `admin`). `migrate_session10.py` (dry run / apply) now also reports and fills login IDs; safe to run twice. `idcodes.give_login_id()` is called by user create and application approval.
- Sign in: `POST /api/auth/login {login, password}`. Case and spaces ignored. Email still accepted while `ALLOW_EMAIL_LOGIN` is on (default on); set `ALLOW_EMAIL_LOGIN=0` once everyone has used their ID. Same message for wrong ID and wrong password, the password hash is always checked (dummy hash when the ID is unknown), and each account is limited to 8 failures per 5 minutes on top of the per-address limit.
- Forced first-login change is enforced in `auth()`: while `must_change_password` is 1 every route except `/api/auth/me` and `/api/auth/change-password` answers 403 `code: password_change_required`. The page (`static/index.html`) now has the change-password screen it never had.
- Admin: create account without a password gives a random temporary password, returned once (`Cache-Control: no-store`) and shown in a panel until "Done"; `POST /api/users/<id>/reset-password`; edit Login ID in the person editor (format and uniqueness checked, 409 on a clash); activate/deactivate unchanged. People list shows the Login ID. Audit rows: `create_user` (role and login ID), `reset_password` (login ID only), `update_user` with `login_id: old -> new`. No password or hash is logged or returned (test 09).
- Tests: `tests/test_session11.py` (10). Full unit run: 237 tests, only `test_warm_connection` fails when run after the others (passes alone, as before).
- Files touched: app.py, idcodes.py, dbx.py, schema.sql, migrate_session10.py, static/index.html, static/admin.js, tests, docs.

## Decisions recorded
- Session 11 (from the user): everyone signs in by ID, admins included. Admin IDs are `BAL/A/NNN` (my choice, changeable per person in People).
- A student created with no course gets a sign-in ID `BAL/STU/NNN` only; the permanent `student_code` still waits for the first enrolment (Session 10 decision). The sign-in ID is NOT changed when the code arrives, so a student can end up with login `BAL/STU/004` and student code `BAL/AL1/003`. An admin can edit the login ID to match, then reset the password so the person is told.
- Test-only switch: `PORTAL_SKIP_FORCED_CHANGE=1` (set in `tests/__init__.py`) turns the forced change off so the ~230 older tests, which sign in with freshly created accounts, keep working. `test_session11.py` runs with it off. It must never be set on a real server.
- Still needed: Session 29 (WhatsApp provider), Session 31 (do teachers see their own earnings, default no).

## Left over / not verified
- **Run the backfill on the hosted database** (dry run first): until then existing accounts have no login ID and can only sign in by email. Do not set `ALLOW_EMAIL_LOGIN=0` before that.
- Browser behaviour (login form, forced change screen, temporary password panel, Reset button) is only syntax-checked, not clicked through. Not run against real PostgreSQL.
- Old sessions stay valid after a password reset or change until the token expires (`session_hours`). A password-version claim in the token would close that; not done.
- Failed-login counters are in memory per server instance (as before), so on Vercel they reset when an instance restarts and are not shared between instances. A database-backed counter belongs with Session 20 (failed-login events).
- IDs are guessable (`BAL/AL1/002`), so the password is the only secret: consider a longer `min_password_length` in Settings.
- The Session 9 invoice PDF still prints the internal user id as "Student ID": switch it to `student_code` in Session 16.
- Admin-typed passwords are still accepted on create/edit (kept for compatibility); the page now leaves the field empty so the server generates one.
- The help text strings added to the page are English only (`static/i18n/en.json` has no entries; the page shows the key as text).

## NEXT SESSION: 12 (courses, tuition classes and batches, admin)

## Done: Session 12 (v0.8.12): courses, tuition classes and batches (admin)
- Courses screen = "Courses and tuition" (`static/admin.js`, label `courses` in en.json): type (course / tuition class), code (empty = made from the name), active checkbox, table with Type, Code and an "Inactive" tag. Creating "Grade 8 Mathematics" as tuition gives code G8M.
- Inactive courses (`courses.is_active=0`): hidden from `/public/courses`, `GET /courses?active=1` and the course, batch and enrolment dropdowns; refused (409) for new enrolments, enrolment transfers into them and new batches; `fees.generate()` and the first invoice skip them with reason `course_inactive` (shown in the skip list). Old invoices, enrolments, the monthly report and the admin course list still include them. Switching back to active restores everything.
- Batches screen: Google Meet link field removed from the create form and the editor (saved batches no longer send `meet_link`, so saving never erases it); a note points to Classroom. The database column and `PUT /batches/<id>/meet-link` are unchanged, and the batch API still accepts `meet_link` (old scripts and tests use it).
- Batch editor: new "Students in this batch" panel (active/capacity, enrol a student by name and login ID, remove with confirmation). It uses `POST /enrollments` and `PATCH /enrollments/<id>` so capacity, waitlist, inactive-course and first-invoice rules stay in one place; the invoice skip message is shown after enrolling. `GET /batches/<id>/students` now also returns `enrollment_id`; `GET /batches` returns `course_kind` and `course_active`.
- A new course or tuition class appears in invoices, the student's Fees tab and the monthly report with no extra step (test 01 checks all three and that generating twice adds nothing).
- Tests: `tests/test_session12.py` (5). Full run: 242 tests, only `test_warm_connection` fails when run after the others (passes alone).
- Files touched: app.py, fees.py, static/admin.js, static/learning.js, static/i18n/en.json, tests, docs.

## Decisions recorded
- "Remove from batch" sets the enrolment to `dropped` (history kept). Session 13 adds the `enrollment_events` table and the transfer/withdrawal report on top of this.
- Inactive means "no new work": existing students in an inactive course keep their enrolment, but no new invoices are generated for them. If you want old students to keep being billed, close the course to new students another way (e.g. status Closed) instead; tell me if you prefer that rule.

## Left over / not verified
- Browser behaviour of the new screens (type selector, inactive tag, student panel, hidden link field) is syntax-checked and covered by API tests only, not clicked through.
- Students waiting on a waitlist show in the batch panel with status `waitlist`; "Remove" drops them too.
- `static/index.html` still contains the old inline Courses form; `admin.js` replaces it at load. It can be deleted when convenient.
- The Application screen's course dropdown hides inactive courses except the application's own; the batch dropdown there still lists all batches.
- New i18n strings are English only (page shows the key text).

## NEXT SESSION: 13 (transfers and withdrawals, MIGRATION: remind me to back up and give a dry run)

## Done: Session 13 (v0.8.13): transfers and withdrawals (MIGRATION)
- **Back up the database before running the migration.** New table `enrollment_events` (schema.sql, created automatically on start, additive). `migrate_session13.py`: DRY RUN by default, `--apply --i-have-a-backup` to write, refuses without the flag, safe to run twice. It writes one event for every enrolment that is already `dropped` and has none: real date, admin and new batch from the activity log when a row exists; otherwise a later enrolment of the same student in another batch of the same course counts as a transfer (date approximate); otherwise a withdrawal with unknown date. Reasons say "Backfilled". It never changes an enrolment, attendance, submission or grade and aborts if the enrolment count moves.
- New `transfers.py`: `record_event()`, `backfill()`, `GET /api/enrollment-events` (filters kind, from, to, student_id, batch_id) and `/api/enrollment-events.csv` (formula-safe, audit entry `export_enrollment_events_csv`), admin with permission `enrollments`.
- `PATCH /api/enrollments/<id>` takes optional `reason` and `effective_date` (default today, Maldives). A transfer writes one `transfer` event; a change to `dropped` writes one `withdrawal` event (dropping an already dropped enrolment adds nothing; a refused request adds nothing).
- Access audit (learning.py): a student sees a batch only with an **active** enrolment. `viewable()` and `my_batches()` no longer include `completed`; `l_sub_file` (own submission file) now also needs an active enrolment. Course tutorials (list, one, file, my answer, submit) need an active enrolment in that course; tutorials with no course stay open to students. Teacher/admin routes unchanged.
- History: Student Information (admin) now keeps the old batch's grades and attendance after a drop or transfer, with `enrollment_status` on each progress entry.
- Admin screen: Enrollments now ends with a "Transfers and withdrawals" table and a Download CSV button; dropping, moving and "Remove from batch" ask for an optional reason.
- Tests: `tests/test_session13.py` (6): transfer hides assignments, materials, recordings, timetable, grades, attendance and files and keeps grade and submission for admin; withdrawal once, bad date, full-batch transfer writes nothing; tutorials follow active enrolment (404 stays 404, admin unaffected); completed students lose access; report filters, CSV, 401/403 (student, teacher, admin without `enrollments`); migration dry run, apply, second run, refusal without flag. Full run: 247 tests OK; `test_warm_connection` passes alone.
- Files touched: transfers.py (new), migrate_session13.py (new), app.py, learning.py, schema.sql, static/admin.js, tests (new + one edited), docs.

## Decisions recorded
- **Completed enrolments lose student access too** (rule is `status='active'` as the plan says). If you want finished students to keep seeing their grades and materials, change `'active'` back to `IN ('active','completed')` in `viewable()` and `my_batches()` (two lines).
- **Course tutorials now need an active enrolment in that course** (they were open to every student). This changed an old test (test_phase5), which had pinned the open rule. Tutorials with no course stay open. Session 18 reworks tutorials for teachers.
- Access ends the moment the enrolment is dropped; `effective_date` is a record for the report, not a delayed cut-off.
- Teachers still see only their batch's active students; the history is for admins (Student Information and the report).
- Event kinds are only `transfer` and `withdrawal`. Setting an enrolment to completed or waitlist is not an event.

## Left over / not verified
- **Run the dry run on a copy of the hosted PostgreSQL first.** Not run against real PostgreSQL (only portable SQL is used). A database upgraded from an older schema was not re-tested for this session; the table is plain CREATE TABLE IF NOT EXISTS.
- Browser behaviour (report table, CSV button, reason prompts) is syntax-checked only, not clicked through. The new labels are English only (the page shows the key text).
- A re-activated dropped enrolment keeps its old events (history is never deleted).
- The Application screen's batch dropdown and the student "My batches" API still list waitlist batches; unchanged.

## NEXT SESSION: 14 (student course/batch selector)

## Done: Session 14 (v0.8.14): student course/batch selector
- No database change, no migration.
- Server (learning.py): `my_batches(batch_id)` answers **403** for a student asking for a batch they are not actively in (including ids that do not exist). `?batch_id=` is now accepted by `/api/my/home`, `/api/my/grades`, `/api/my/attendance` and by `/api/tutorials` (selected batch's course tutorials plus general ones); assignments, materials, recordings and timetable already had it. New `GET /api/my/batches` (student): active batches only, the picker's choices. File routes already checked per-id access.
- Page (static/index.html): after sign-in a student with 2 or more active enrolments sees a "Choose your course" screen; with 1 the picker is skipped; the choice is kept per browser tab (sessionStorage) and a Course dropdown in the header switches without signing out. `withBatch()` in `api()` adds the selected `batch_id` to every batch-scoped GET, so Home, schedule, assignments, tutorials, progress (grades and attendance), materials and recordings follow it with no per-screen edits. Sign-out forgets the choice.
- Tests: `tests/test_session14.py` (5): picker list (3, 1 and 0 enrolments, 401, staff 403); all tabs show only the selected batch (3 batches, 3 courses incl. a tuition class); a foreign or missing batch_id is 403 on all 8 routes plus file and submit; waitlisted and dropped batches are not choices; teacher and admin calls unchanged. Full run: 252 tests OK; `test_warm_connection` passes alone. Updated `test_session5` and `test_session13` (empty list became 403).
- Files touched: learning.py, static/index.html, tests, docs.

## Decisions recorded
- "Comments" in the plan: there is no separate comments tab; the teacher's comment is the feedback on a graded assignment, which follows the selected batch (Session 17 splits grade and comment into columns).
- The Fees tab is not batch-scoped (a student's invoices across all courses stay visible), as fees belong to the person.
- Calls without `batch_id` still return everything the student is in (older scripts keep working); the page always sends one.

## Left over / not verified
- Browser behaviour (picker screen, header dropdown, switching) is syntax-checked only, not clicked through. New strings are English only (the page shows the key text, which is English).
- The choice list is loaded once per sign-in: if an admin enrols the student in a new course mid-session, it appears after the next sign-in (or reload). Being dropped mid-session shows a 403 message until then.
- Minimum slice was exceeded: all tabs were done, not just Home, assignments and grades.

## NEXT SESSION: 15 (teacher course/batch selector)

## Done: Session 15 (v0.8.15): teacher course/batch selector
- No database change, no migration.
- ONE function `teacher_batches(uid)` (learning.py) = the batches a teacher may use (today: `batches.teacher_id = uid`). `manage()`, `viewable()`, `my_batches()`, `l_sub_file` and the teacher branch of `GET /api/batches` (app.py, through `app.extensions["teacher_batches"]`) all use it. **Session 22 plugs substitutes in here and nowhere else** (it must also make the access date-limited).
- A teacher asking for a batch they may not use: `?batch_id=` on assignments, materials, recordings, timetable, my/home now answers 403 "This is not your batch" (it used to be an empty list); direct routes (attendance, gradebook, sessions, assignment create, grades, attachments) already answered 403 and still do.
- `GET /api/my/batches` now serves teachers too (their own batches). The page's picker and header switch (Session 14) cover teachers: Classroom uses the selected batch and no longer shows its own dropdown for teachers (admins keep it). `withBatch()` adds the selected batch_id to the GET reads for teachers as well.
- Tests: `tests/test_session15.py` (5): picker list (own only, none, 401, admin 403); every read limited to the selected batch; foreign, teacherless and missing batches 403 on 5 list routes and 7 direct routes; moving a batch to another teacher changes access at once everywhere (the one-function test); admin and student unchanged. Full run: 257 tests OK; `test_warm_connection` passes alone. `test_session14` updated.
- Files touched: learning.py, app.py, static/index.html, static/learning.js, tests, docs.

## Decisions recorded
- The picker lists all of a teacher's batches, closed ones included (they may still need history). Tell me if closed batches should be hidden.
- The teacher "Tutorials" screen is untouched (it has its own course selector, removed in Session 18). `batch_id` sent to `/api/tutorials` by a teacher is ignored.

## Left over / not verified
- Browser behaviour (teacher picker, header switch, Classroom following it) is syntax-checked only, not clicked through.
- The batch list is loaded once per sign-in; an admin reassigning batches shows up at the next sign-in/reload (the server enforces it at once).
- Teacher Home counts (pending grading, low attendance) follow the selected batch; there is no "all my batches" view yet (Session 19 adds the dashboard with that choice).

## NEXT SESSION: 16 (My Information, student and teacher)

## Done: Session 16 (v0.8.16): My Information, student and teacher
- No database change, no migration.
- New `GET /api/my/information` (learning.py, `@auth("student","teacher")`, no id in the URL: the person is always the token's user). Students get login ID, student ID, personal and guardian details and active batches with enrolment ID, course kind and teacher. Teachers get login ID, teacher ID, contact, bio and their batches (through `teacher_batches()`, so Session 22 substitutes will show up as soon as that function covers them; revisit then). Fees, notes, password data and permissions are not in the response (a test searches the text).
- New tab `my_information` for students and teachers (settings_schema.ROLE_TABS), no permission area, so limited accounts keep it. View is in static/learning.js; strings in en.json; small `.kv` table style in index.html.
- Locked fields: there is no self-edit route at all. `PATCH /api/users/<id>` stays admin-only (area `people`); tests check student and teacher get 403, and PATCH/PUT/POST on `/api/my/information` are refused.
- Tests: `tests/test_session16.py` (7): student page, teacher page, no fees or secrets, cannot reach another person, locked fields, 401/403 and tab list, a dropped batch leaves the page. Updated the pinned tab lists in `tests/test_permissions.py` (5 tests) for the new tab. Full run: 265 tests; only `test_warm_connection` fails when run after the others (known, passes alone).
- Files touched: learning.py, settings_schema.py, static/learning.js, static/index.html, static/i18n/en.json, tests, docs.

## Decisions recorded
- The page lists **active** enrolments only (dropped, completed and waitlist are hidden), consistent with Session 13.
- Date of birth and guardian details are shown to the student themselves (they are their own data). Say if you want them hidden.
- No permission area for the tab: every student and teacher account sees it.

## Left over / not verified
- Browser behaviour of the new tab is syntax-checked only, not clicked through. New labels are English only.
- The list of "locked" fields is informational; the page does not draw edit buttons because none exist.
- A teacher's batch list includes closed batches (same as the picker).

## NEXT SESSION: 17 (grading, feedback, grade-edit permission)

## Done: Session 17 (v0.8.17): grading, feedback, grade-edit permission
- No database change, no migration.
- New opt-in permission area `edit_grades` (settings_schema: AREAS, ROLE_AREAS teacher, `OPT_IN`). `has_perm` (app.py) and `can` (learning.py) treat opt-in areas as NOT part of "everything their role has", so existing and new teachers start without it; an admin ticks it in People (teacher permissions list; admin.js labels updated). Students and admins cannot hold it (validated by ROLE_AREAS); admins can always change grades.
- `POST /api/assignments/<id>/grades`: first grade as before; changing a saved grade or feedback needs admin or `edit_grades`, else 403 with a clear message and nothing written or logged; identical values are a no-op (`changed:false`). `graded_by` stays the first grader.
- Log: `grade` (detail "student N: grade none -> X (max M)") and `grade_change` ("grade old -> new ...; feedback old -> new"). Stored in the existing `detail` text because audit_log gets real old_value/new_value columns in Session 20; convert then if wanted.
- Teachers: `GET /api/my/given-grades` plus a "Grades I gave" panel in the gradebook; the grading form locks saved grades for a teacher without the permission.
- Students: `grades_for()` items carry `status` (one definition); Progress table now has Status, Grade, Teacher's comment as separate columns.
- Tests: `tests/test_session17.py` (7). Full run: 272 tests, only `test_warm_connection` errors when run after the others (known, passes alone).
- Files touched: learning.py, app.py, settings_schema.py, static/learning.js, static/admin.js, static/i18n/en.json, tests, docs.

## Decisions recorded
- **Tutorials have no grades yet** (no grade or comment columns on `tutorial_submissions`). Grading tutorial answers, which needs a migration, belongs to Session 18 ("view, comment and grade submissions"); I did not add it here to avoid an unplanned schema change. Student tutorial status is therefore only submitted / not submitted until then, and the Progress columns cover assignments and tests.
- A teacher's first grade needs no extra permission; only changing a saved grade does.
- Grade edits by an admin are not limited to the admin's own batches (admins manage all).

## Left over / not verified
- Browser behaviour (locked grade inputs, Progress columns, Grades I gave) is syntax-checked only. New strings English only.
- Existing teachers who already edit grades will now get 403 on changes until an admin grants `edit_grades`; tell them.
- Session 18 should reuse `status` logic and add tutorial grading; Session 20 should move the old/new text in `detail` into real columns.

## NEXT SESSION: 18 (cancel permission, tutorials cleanup, assignment statistics). No decision needed.

## Done: Session 18 (v0.8.18): cancel permission, tutorials cleanup, assignment statistics
- No database change, no migration.
- `cancel_class`: opt-in teacher area (settings_schema AREAS, ROLE_AREAS teacher, `OPT_IN`; admin.js labels). Enforced in `POST /api/batches/<id>/sessions` when status is `cancelled`. Teachers with "everything" do NOT get it; grant it per teacher in People (permissions list). Existing teachers lose cancelling until granted: tell them.
- Tutorials (teacher): `teacher_tut_sql()` = posted by me, or course of one of my batches (via `teacher_batches()`, so Session 22 substitutes inherit it). List, one, file and answers are limited to that; `?batch_id=` narrows to that batch's course plus my general posts; posting for a course I do not teach is 403. Teacher page: course selector and course field removed; posting uses the header batch's course. **General tutorials with no course posted by an admin (or old student posts) are no longer visible to teachers** (only their own general posts are). Students unchanged.
- Statistics: could not reproduce row multiplication on resubmission (submissions are UNIQUE per assignment and student, and tutorials live in another table). The real errors found and fixed: counts included students who had left the batch (dropped or transferred), a graded test could make graded exceed submitted, and "pending grading" counted tests and left students. One function `assign_counts()` (+ `pending_grading()`) now feeds the assignment list, the teacher Home "pending grading" and Teacher information. Session 19 must reuse these; never write a second definition.
- Tests: `tests/test_session18.py` (4): cancel denied/granted/revoked/scoped; tutorial scope; counts with 3 resubmissions, ungraded, graded, test, dropped student and a tutorial answer, matched with a raw-row count. Edited old tests: test_phase3 (teacher is granted cancel_class in `world()`), test_session4 (admin cancels), test_session2 (teachers no longer see unrelated tutorials). Full run: 276 tests, only `test_warm_connection` errors after the others (known; passes alone).
- Files touched: learning.py, settings_schema.py, static/learning.js, static/admin.js, tests, docs.

## Decisions recorded
- **Tutorial grading and comments are NOT done.** Tutorial answers have no grade or comment columns, so it needs a MIGRATION (add grade, feedback, graded_by, graded_at to `tutorial_submissions`, and a max points on `tutorials`) and a decision on the scale. I stopped at the size cap and did not add an unplanned schema change. Proposal: grade out of `tutorials.max_points` (default 100, nullable = comment only), same rules as assignments (`edit_grades` to change). Tell me to do it as "Session 18b" before Session 19, or later; Session 19's "tutorials given" count works without it.
- A teacher's tutorial view follows ownership of courses through batches, not through the admin's "tutorials" flag.

## Left over / not verified
- Browser behaviour (Tutorials without selector, posting from the header batch) is syntax-checked only. English strings only.
- The Application and admin screens still show the course filter on Tutorials (admins unchanged).

## NEXT SESSION: 19 (teacher dashboard), unless you ask for 18b (tutorial grading) first. No decision needed for 19.

## Done: Session 19 (v0.8.19): teacher dashboard
- No database change, no migration.
- New `GET /api/teacher/dashboard` (learning.py `l_teacher_dash`, `@auth("teacher", perm="classroom")`). Batches come from `my_batches()` (so `teacher_batches()` and Session 22 substitutes apply; a foreign batch_id is 403). Numbers: assignments, tests, submissions, graded, pending come ONLY from `assign_counts()` / `pending_grading()` (Session 18); attendance from `att_multi()` + `roster_multi()` (active students only) through `stat()`; classes from `sessions` and `occurrences()`.
- Definitions: held = sessions with status held (attendance taken); upcoming = occurrences from today to +27 days that are not cancelled or held (today's class counts until attendance is taken); cancelled = sessions marked cancelled; tutorials given = tutorials this teacher posted that are general or for a course of the selected batches; tutorial answers = answers to those from students currently active in the selected batches (and, for course tutorials, in that course).
- Recent activity = the teacher's own last 10 audit rows (sign-ins excluded). The audit log has no batch column yet, so it is not narrowed by batch; Session 20 adds batch_id and this can then follow the selection.
- Page: the teacher Home shows 12 number cards, the batch list and recent activity; it falls back to the old two cards if the call fails. Strings added to en.json (English only).
- Tests: `tests/test_session19.py` (6): seeded world (2 batches, a dropped student, 3 held classes, a cancelled class, resubmissions, a test, tutorials with answers) compared with hand counts for batch 1, batch 2 and all; pending equals teacher Home and the assignment list; grading updates the dashboard; recent activity is own only; other teacher empty; 401/403 rules. Full run: 282 tests, only `test_warm_connection` errors after the others (known; passes alone).
- Files touched: learning.py, static/learning.js, static/i18n/en.json, tests, docs.

## Decisions recorded
- The dashboard needs the Classroom area (same as the numbers it shows); a teacher without it gets 403 and the page falls back to the old cards.
- No "all my batches" toggle was added to the page: the header batch picker decides, as in Sessions 14 and 15. The API supports both. Tell me if you want a toggle button.
- Attendance percentage excludes excused classes, as everywhere else.

## Left over / not verified
- Browser behaviour (cards, fallback) is syntax-checked only, not clicked through.
- Tutorial grading (Session 18b) is still not done; see the Session 18 decision. The dashboard's "graded" counts assignments and tests only.
- Upcoming counts and "held" ignore substitute teachers until Session 22 changes `teacher_batches()`.

## NEXT SESSION: 20 (activity log v2, MIGRATION: remind me to back up and give a dry run), unless you ask for 18b first. No decision needed.

## Done: Session 20 (v0.8.20): activity log v2 (MIGRATION)
- **Migration (back up first):** `audit_log` gets seven nullable columns: `user_role, login_id, course_id, batch_id, old_value, new_value, ip` (schema.sql for new databases; `dbx.init_schema` adds them to old ones, so they appear on app start; indexes on batch_id and user_id). Old rows are never changed in their old columns. `python migrate_session20.py` is a DRY RUN by default (does the work in a transaction and rolls back, prints rows filled per step); `--apply --i-have-a-backup` commits. Backfill (`auditlog.backfill`) fills role and login ID from the user, batch/course from the entity (batch, enrolment, assignment, session, course, tutorial) and old/new from the grade and transfer text. Only empty cells are filled, so it is safe to run twice. **Run it before Session 21 adds the read-only triggers.**
- `audit()` (app.py) keeps its old signature; new optional keyword arguments `course_id, batch_id, old, new, role, login_id`. User, role, login ID and IP are automatic. A batch_id without a course_id looks the course up. Floats such as 6.0 are stored as 6. Scheduled runs have role `system` (cron endpoint, `generate_invoices.py`); failed logins have role `anonymous`.
- New events: `login` (already existed, now with role/ID/IP), `logout` (new `POST /api/auth/logout`; the sign-out button calls it and still signs out if the call fails), `failed_login` (detail: unknown ID / wrong password / account disabled; the ID that was typed is kept in login_id, the password never; for a real account the attempt is stored as entity_id and user_id stays empty because the account owner did not do it), `assign_teacher` (batch create or change, old and new teacher id), `permission_change` (old and new permission list, "all" = everything).
- Instrumentation checklist (all ticked and tested in `tests/test_session20.py`, 8 tests):
  [x] course creation (course_id) [x] batch creation (batch_id, course_id) [x] enrolment (batch, old status, new status) [x] teacher assignment [x] attendance (old = changed marks before, new = after) [x] assignment upload [x] tutorial upload (course_id) [x] submissions (assignment and tutorial; "resubmitted") [x] grading (old and new in columns) [x] permission changes [x] password reset (no password in the row) [x] transfers (old batch, new batch) [x] invoice generation (admin and cron). Also now carrying batch_id: class links, one-off class status, assignment update/delete, materials, recordings, enrolment status and delete, batch update/delete, course update/delete.
- Files touched: schema.sql, dbx.py, app.py, learning.py, fees.py, generate_invoices.py, static/index.html, new auditlog.py and migrate_session20.py, tests, docs. (More than the usual three source files, because `audit()` callers are spread through the code.)
- Tests: `tests/test_session20.py` (8). Full run: 290 tests; only `test_warm_connection` errors when run after the others (known; passes alone). My first run broke tutorial answers (a query lacked `course_id`); fixed and covered by the old Session 2 and 18 tests.

## Decisions recorded
- The Session 17 grade text in `detail` is kept (readable by old screens) and the same values now also sit in `old_value` / `new_value`.
- Payments, slips, reminders and other fee events do not carry batch_id yet (they were not in the list); the viewer in Session 21 can still filter them by user, action and date.
- Sign-in blocked by the rate limit (HTTP 429) is not logged, so an attacker cannot fill the log without limit. Say if you want it logged.
- Logout is advisory: tokens stay valid until they expire (unchanged).

## Left over / not verified
- Browser behaviour of the sign-out call is not clicked through (one line in static/index.html).
- The teacher dashboard's "recent activity" still reads the teacher's own rows only; it can now follow the selected batch (batch_id exists) if you want it.
- Old rows whose entity cannot be matched stay with empty role/batch; nothing is guessed.
- Not tested on a hosted PostgreSQL copy; the migration uses plain ALTER TABLE ADD COLUMN and UPDATE ... subqueries, which both engines accept.

## NEXT SESSION: 21 (activity log viewer and protection; no decision needed). Remind me to run `migrate_session20.py` (dry run, then apply with a backup) on real data first.

## Done: Session 21 (v0.8.21): activity log viewer and protection
- Schema: one new table `audit_unlock(flag)` (empty normally), plus two triggers on `audit_log`, installed by `dbx.init_schema` on every start (schema version bumped, so old databases get them on first start). No data changes, no migration script needed beyond the Session 20 one.
- Protection: SQLite triggers `audit_log_no_update` / `audit_log_no_delete` (RAISE ABORT "audit_log is append-only"); PostgreSQL function `audit_log_guard` + trigger `audit_log_guard_t` (BEFORE UPDATE OR DELETE, per row). DELETE is never allowed. UPDATE is allowed only while a row exists in `audit_unlock`, which only `auditlog.backfill()` sets, inside its own transaction (so the Session 20 migration still works and the switch is off after commit or rollback). No app route updates or deletes the log (test tries POST/PUT/PATCH/DELETE on every audit URL).
- Viewer: new `auditview.py` replaces the old `/api/audit` route (same URL, still returns a JSON list so the 15 older tests and screens work; totals in headers). Filters, paging, CSV (formula-safe, max 20000 rows, export logged as `export_audit_csv` with the filters), `/api/audit/summary` (drill-down for a user, batch or course), `/api/audit/actions`. All values are bound parameters. Dates are Maldives days converted to UTC (test at the midnight boundary).
- Screen: `views.audit` in static/admin.js (filter form, "This user" / "This batch" buttons, summary panel, previous/next, Download CSV). English labels only; syntax-checked, not clicked through.
- Tests: `tests/test_session21.py` (10): filters against direct SQL counts, Maldives date range, paging, CSV, summary, 401/403/400 rules, no changing route, direct UPDATE and DELETE fail (data unchanged, INSERT still works), backfill dry run and apply still work and the switch is off after, upgrade of an old database installs triggers. Full run: 300 tests; only `test_warm_connection` errors after the others (known; passes alone).
- Files touched: auditview.py (new), auditlog.py, dbx.py, schema.sql, app.py, static/admin.js, tests, docs.

## Decisions recorded
- `/api/audit` keeps returning a list; paging totals are in response headers (changing it to an object would have broken many existing tests and screens).
- The Next button on the screen is enabled when a full page came back (it does not read the total header).
- Someone with direct database access can still switch the guard off (drop the triggers or insert into audit_unlock). The triggers protect against the app, mistakes and scripts, not against a database owner; for that, use provider-side backups and restricted database credentials. TRUNCATE is not blocked.

## Left over / not verified
- **PostgreSQL triggers were not run** (no PostgreSQL in the build environment); the SQL is standard plpgsql but please test once on a copy of the hosted database: `UPDATE audit_log SET detail='x' WHERE id=1;` must fail with "audit_log is append-only", and `python migrate_session20.py` (dry run) must still work. Same for `DELETE FROM audit_log`.
- If a hosted-data copy script (`migrate_to_hosted.py`) ever needs to clear `audit_log` on the target, it will now be refused; it only inserts today.
- Browser behaviour of the new screen is not clicked through.

## NEXT SESSION: 22 (substitute teachers). No decision needed. Run `migrate_session20.py` first if you have not.

## Done: Session 22 (v0.8.22): substitute teachers
- Schema: new table `substitutions` (the planned columns plus `created_at`, `removed_at`, `removed_by`). New table, so no migration and no backup step needed.
- Window rule: access runs from `class_date` to `COALESCE(ends_on, class_date)`, inclusive, Maldives dates, compared with today on every request. Nothing runs to end it. Removing sets `removed_at` (history stays). A `session_id` makes it that one class (date taken from the class). One substitute per batch at a time (overlap is 409); different batches may share dates. Max 92 days per row. The batch's own teacher cannot be their own substitute; `batches.teacher_id` is never written.
- Code: `substitutions.py` (new: `windows()` helper and the four routes). learning.py: `sub_windows`, `class_batches`, `sub_day_error`; `manage(bid, cls=False)`, `my_batches(batch_id, scope="own")`. `teacher_batches()` is unchanged (own batches), so every grade, assignment, material, tutorial, information and cancel check refuses a substitute without further changes.
- Log: `substitute_assign` / `substitute_remove` with batch_id, old/new teacher; attendance saved by a substitute says "as substitute" in the detail.
- UI: panel "Substitute teachers" under the batch being edited (static/admin.js); teachers see "(substitute until DATE)" in the picker (static/index.html). English only; syntax-checked, not clicked through.
- Tests: `tests/test_session22.py` (8): no access before; access, timetable, attendance only on the dates; refused list (assignments, gradebook, materials, recordings, cancel, link, summary, dashboard); automatic end with a moved clock (day before, first day, last day, day after); removal and history; validation and overlaps; single class by session; permissions (401/403 for teacher, student, limited admin). Full run: 308 tests; only `test_warm_connection` errors after the others (known; passes alone).
- Files touched: substitutions.py (new), learning.py, app.py, schema.sql, static/admin.js, static/index.html, tests, docs.

## Decisions recorded (change any of these by telling me)
- **A substitute gets class information only**: picker, timetable for their dates, class students (names, phone), join link and attendance for those dates. Not assignments, grades, feedback, materials, tutorials, recordings, cancelling, editing the link, or the batch's earlier attendance history. I chose this because the plan says "class information and students only"; giving them everything would have meant grade access.
- A substitute does not appear as "assigned" teacher: My Information, `GET /api/batches` and the teacher dashboard still list only their own batches (this settles the Session 16 and 19 notes).
- The substitution cannot start in the past (end date must be today or later); a start date before today is allowed if the end is not, so an admin can cover "from yesterday to Friday".
- Admin permission area for the routes is `batches` (same as assigning a teacher).

## Left over / not verified
- On the substitute's other tabs (assignments, grades, ...) for the batch chosen in the picker the server answers 403 with a message; the tabs were not redesigned to hide themselves.
- Admins are not told when a teacher's substitution ends; the original teacher is not notified (Session 28 notifications could add that).
- Teacher earnings (Session 30) should treat substitute-taught classes per the plan: the helper is `substitutions.windows()` / the table; decide then whether the substitute gets a share.
- Browser behaviour is not clicked through.

## NEXT SESSION: 23 (finance part 1, expenses). No decision needed.

## Done: Session 23 (v0.8.23): finance part 1, expenses
- Schema: new tables `expense_categories` and `expenses` (CREATE TABLE IF NOT EXISTS, created on start). No existing table changed, so no migration and no backup step.
- Code: new `finance.py` (9 routes, see API.md), registered in app.py. Storage gets a fourth private area `receipts` (same store, same validation as slips: PDF/JPG/PNG, size cap, magic bytes). New permission area `finance` (settings_schema.py, admin role and tab "finance" after Fees). UI: `views.finance` in static/admin.js (add/edit form with receipt, filters, total, table, categories), People editor label added.
- Log: `expense_create`, `expense_update` (old/new amount; detail lists changed fields; no row when nothing changed), `expense_delete`, `view_expense_receipt`, `expense_category_create/update/delete`.
- Tests: `tests/test_session23.py` (8): add with receipt and download, PNG and bad files, filters and totals against SQL, validation, edit/replace/remove receipt with old/new log, delete removes the file, categories, permissions (401, and 403 for limited admin without finance, teacher, student, on every route). `test_permissions` updated for the new admin tab. Full run: 316 tests; only `test_warm_connection` errors after the others (known; passes alone).
- Files touched: finance.py (new), schema.sql, settings_schema.py, storage.py, app.py, static/admin.js, static/i18n/en.json, tests, docs.

## Decisions recorded (change any by telling me)
- `finance` is NOT opt-in (unlike edit_grades): a full admin has it, a limited admin needs it ticked. Making it opt-in would have locked everyone out, because nobody can grant themselves a permission.
- Amounts are whole MVR, like payments (no laari). Say if expenses need decimals; it would touch Session 24 totals too.
- An expense cannot be dated in the future or more than 5 years back. A receipt is optional.
- Deleting an expense is a real delete (row and file); the activity log keeps what it was. Categories in use cannot be deleted, only made inactive; inactive categories stay on old expenses.
- No default categories are seeded; the admin adds their own on the Finance screen.

## Left over / not verified
- Browser behaviour of the Finance screen is not clicked through (syntax-checked only). English labels only (the tab name has an i18n key; the rest use the English text as key like the other admin screens).
- Not run against PostgreSQL (plain SQL, `datetime('now')` is translated by dbx like elsewhere). S3 storage not run either (same `store` calls as slips).
- No expense CSV/Excel export yet (Session 26 adds the Excel helper; add it there if wanted).
- Session 24 will read `expenses` for net profit; the amounts are `expenses.amount_mvr`, date in `expense_date`.


## Done: Session 24 (v0.8.24): finance part 2, revenue and financial dashboard
- No schema change, no migration. Two read-only routes added to `finance.py`: `GET /api/finance/revenue` and `GET /api/finance/dashboard` (area `finance`). Finance tab (static/admin.js) now shows dashboard cards, a 'revenue' section with filters (dates, course, batch, course/tuition) and tables by month, course and batch, above the Session 23 expenses screen.
- Rules: revenue = `payments` with `reversed_at IS NULL`, counted on `paid_on`; partial payments count what was paid; course, batch and kind (course or tuition class) come from the payment's invoice. Outstanding = sum of max(amount_due - waived - paid, 0) over non-void invoices (same rule as `payments.balance`), independent of the date filter. Net = revenue minus expenses in the same dates. Teacher earnings and academy revenue are the text "coming" in the API and "coming soon" on screen.
- Tests: `tests/test_session24.py` (8): seeded partial payments, a reversed payment, a tuition class, expenses in two months; totals checked by hand and against SQL; filters; void invoices; default month and a loss month; a later reversal updates the totals; permissions (401, 403 for a fees-only admin, teacher, student).
- Files touched: finance.py, static/admin.js, tests, docs (three source files or fewer).

## Decisions recorded (change any by telling me)
- A payment on a later-voided invoice still counts as revenue (the money was received); say if void should remove it.
- Revenue is counted by the day paid, not by the invoice's billing month, so a March invoice paid in February shows in February.
- The dashboard default range is this month so far (Maldives date); the 12-month series always ends this month and ignores the filters.
- "Outstanding" includes invoices not yet due as well as overdue ones.
- The page filters (course, batch, type) apply to the revenue section only; the dashboard cards use the dates only.

## Left over / not verified
- Browser behaviour is not clicked through (syntax-checked). English labels only. No CSV/Excel export of revenue (Session 26 adds the Excel helper).
- Not run against PostgreSQL (plain GROUP BY, SUBSTR and CASE, which both engines accept).
- Session 25 (admin dashboard) should call `collected()`, `outstanding()` and `expenses_total()` in finance.py (they are local to `register()`; expose them on `app.extensions["finance"]` when you need them there, I did not add that yet).


## Done: Session 25 (v0.8.25): admin dashboard
- No schema change. New `admindash.py` with `GET /api/admin/dashboard` (any admin; money only with `finance`, fee notices only with `fees`). The filters (course, batch, course/tuition class, teacher, dates) first pick a set of batches and every card is counted for that set, in one place.
- Reuse, no second definitions: new `scope_counts()` in learning.py (classes held / cancelled / upcoming from sessions and `occurrences()`; assignments, tests, submissions, graded, pending from Session 18's `assign_counts()`), exposed as `app.extensions["scope_counts"]`; money from finance.py's `collected / outstanding / expenses_total`, now exposed as `app.extensions["finance"]` (and `scope()` there takes `teacher_id`). The teacher dashboard code was NOT changed; a test checks that the admin numbers for one teacher equal that teacher's own dashboard (held, upcoming, students, assignments, tests, submissions, graded, pending).
- UI: `views.dashboard` in static/admin.js replaces the admin dashboard (filters, academic cards, finance cards, fee notices, application link). `GET /api/dashboard` is unchanged (old tests and any script keep working).
- Tests: `tests/test_session25.py` (8): hand-counted seed (sessions, assignments, a test, hand-ins including a dropped student's, tutorials, applications, payments, an expense); unfiltered, tuition, course, batch, teacher and date filters; money; same numbers as the teacher dashboard; permissions and validation; the old route. Full run: 332 tests; only `test_warm_connection` errors after the others (known; passes alone).
- Files touched: admindash.py (new), learning.py, finance.py, app.py, static/admin.js, tests, docs.

## Decisions recorded (change any by telling me)
- No date range means all time (not this month). Classes "coming up" look ahead 28 days (or to the end date, max 92 days) and are 0 when the range ends before today.
- "Students" = active student accounts with an active enrolment in the chosen scope; "Teachers" = active teachers assigned to an open or running batch in scope. Separate unfiltered cards `student_accounts` and `teacher_accounts` count all active accounts (the screen shows them under the filters).
- Assignments, tests, hand-ins, graded and waiting-for-grading are for assignments GIVEN in the date range; tutorials by their created date; applications: "waiting" ignores dates, "received" uses them.
- Expenses are academy wide: only the dates apply, not course/batch/teacher.
- A dropped student's unpaid invoice still counts as outstanding (existing behaviour: dropping does not void invoices). Say if dropping should void unpaid invoices; that is a fees change.
- A tutorial with no course counts only when no filter is set.

## Left over / not verified
- Browser behaviour is not clicked through (syntax-checked). English labels only.
- The old fee cards on the admin dashboard are rebuilt from the new endpoint; fees.js still contains the old wrapper (harmless, replaced by admin.js loading last).
- Not run against PostgreSQL (plain COUNT, IN and GROUP BY).


## Done: Session 26 (v0.8.26): payment reports
- No schema change, no migration, no backup step. New `payreports.py` (4 routes, area `fees`), registered in app.py; new "Payment report" tab in static/fees.js (filters, totals, table, History view, CSV and Excel buttons); `openpyxl>=3.1` added to requirements.txt; label `fx_tab_payrep` in en.json.
- Report: one row per student per batch for a month. Listed: active enrolments enrolled by the end of the month, plus anyone with a non-void invoice that month (dropped or transferred students stay in the month they were billed). Money: invoice amounts, and payments with `reversed_at IS NULL` (same rules as `payments.balance` and the Session 24 revenue). Status: Paid, Partially Paid, Unpaid, Waived, No invoice. Filters: month, course, batch, kind (course or tuition), status. Totals equal the invoice and payment totals (tested against SQL).
- `to_xlsx(rows, headers, sheet)` in payreports.py is the ONE Excel helper (formula-safe text). Session 27 should import it from there.
- Tests: `tests/test_session26.py` (12): statuses and amounts, payment dates, a reversed payment, totals against SQL, a dropped-but-billed student, every filter, bad filters (400), history, CSV and Excel contents, the helper's formula safety, permissions (401, 403 for finance-only admin, teacher, student). `test_phase4` tab list updated for the new tab. Full run: 344 tests; only `test_warm_connection` errors after the others (known; passes alone).
- Files touched: payreports.py (new), app.py, static/fees.js (plus requirements.txt, en.json, tests, docs).

## Decisions recorded (change any by telling me)
- Waived is shown as its own status (a fully waived or fully discounted invoice), and "No invoice" for an enrolled student with nothing billed that month; the fee is shown but they owe 0 in that report. Say if you want only the three statuses.
- The month's "enrolled" cut-off is the enrolment date; a student enrolled after the month ends is not listed for it.
- Amount paid counts every non-reversed payment on the month's invoice, whatever day it was paid (this is the invoice view; the Finance revenue tab counts by payment day).
- Void invoices are left out of the report, like the existing monthly report.

## Left over / not verified
- Browser behaviour of the new tab is not clicked through (syntax-checked only). English labels only.
- Not run against PostgreSQL (plain joins and SUBSTR, which both engines accept). `openpyxl` must be installed on the host (it is in requirements.txt).
- The old "Monthly report" tab is unchanged.
- Fee and payment history import/export is not part of this session.


## Done: Session 27 (v0.8.27): exports and imports
- No schema change, no migration, no backup step. New `portio.py` (9 routes: 3 exports x CSV/Excel plus 3 imports), registered in app.py; export buttons and an "Import from CSV" panel in static/admin.js. Reuses `to_xlsx` and `csv_safe` from payreports.py and the Session 10 generator (`idcodes`).
- Exports: students (`student_information`), enrolments (`student_information`), teachers (`teacher_information`); CSV (UTF-8 with BOM, opens in Excel) and .xlsx; same filters as the lists (q, batch_id, status); every download logged (`export_student_information`, `export_teacher_information`, `export_enrolments`). No fees, internal notes, passwords or hashes. Text starting with = + - @ gets an apostrophe; the importer removes exactly that apostrophe so a round trip keeps the text.
- Imports: students and teachers need `people`, enrolments need `enrollments`. Dry run is the default (`dry_run=0` to import). Each row is checked first (email, duplicates inside the file and in the database, ID format and uniqueness, dates, status, batch capacity), then written and committed on its own, so a failing row never blocks the others. Every rejected row comes back with its row number and reason. Each created account is logged (`create_user`, "imported") and the run gets one `import_students|teachers|enrolments` row with counts.
- Tests: `tests/test_session27.py` (12): exports (columns, filters, formula safety, no secrets, Excel, log rows, permissions), dry run writes nothing and is the default, apply with rejected rows (duplicates, bad email, bad date, existing email, repeated ID), temporary password works once and forces a change and is not in the log, teacher import, file problems, enrolment rules (capacity, unknown student or batch, bad status, kept enrolment ID and date, repeat run), import permissions, and a round trip into an empty database (same people, IDs, enrolments). Full run: 356 tests; only `test_warm_connection` errors after the others (known; passes alone).
- Files touched: portio.py (new), app.py, static/admin.js (plus tests and docs).

## Decisions recorded (change any by telling me)
- Temporary passwords for imported accounts are returned once in the import response (no-store), with a button on screen to save them as a CSV; they are never logged. Same idea as Session 11's create account, but for many people at once.
- Courses and batches are NOT created by the import; enrolment rows that name a missing course or batch are rejected with that reason. Transfers and withdrawals history (`enrollment_events`) is not exported or imported: a dropped or completed enrolment is imported as such, without an event.
- An imported ID is kept only if it matches the ID format and is unused; otherwise the row is rejected (it is not silently replaced). A student with no code and no course gets a sign-in ID BAL/STU/NNN, as in Session 11.
- Imported active enrolments do not create invoices themselves; the Fees screen's catch-up (and the monthly cron) bills them the normal way. Capacity is enforced for `active` rows (a full batch rejects the row; it does not waitlist it).
- Import is CSV only (Excel is for downloads). Limits: 2 MB and 2000 rows per file.

## Left over / not verified
- Fee and payment history import is skipped (it was optional). Say if you want it as a later session.
- Browser behaviour of the new buttons and panel is not clicked through (syntax-checked only). English labels only (English text used as the label key, like the other admin screens).
- Not run against PostgreSQL (plain SQL; `datetime('now')` is translated by dbx like elsewhere).
- The People screen shows the import panel to any admin who can open People; an admin without `enrollments` gets a 403 message when importing enrolments.

## Done: Session 28 (v0.8.28): notifications and reminder scheduling
- No migration, no backup step: one new table `notifications` (CREATE IF NOT EXISTS in schema.sql, applied on start). New `notify.py` (registered in app.py before learning/fees/substitutions), `static/notify.js`, a Notifications button in the nav (index.html), a "Notifications and reminders" settings group, cron entry `/api/cron/reminders` (02:30 UTC = 07:30 Maldives) in vercel.json.
- In-app only. Each person sees their own inbox (list, unread count, mark read, mark all read). Events (created inside the same transaction, so a failed request leaves nothing): slip uploaded (admins with Fees), verified, rejected; class cancelled / reinstated (students, and the teacher when someone else did it); substitution assigned / removed (substitute, original teacher, students; this closes the Session 22 gap); new assignment or test; grade and grade change.
- Scheduled run (`run_reminders`): fee due soon (unpaid invoices only, once per invoice), overdue (day 1, then every N days, one dedupe bucket per N days), assignment due soon (only students who have not handed in), a daily line for fee admins (overdue count, slips waiting), and housekeeping (read rows after 90 days, all after 180). Running it twice sends nothing twice. Invoices with a slip waiting (`slip_submitted`) are not reminded.
- Admin: announcements to a batch (students plus its teacher), all students, all teachers or everyone; Reminders panel (status, Preview = dry run, Run now). `POST /api/notifications/run` is a dry run unless `dry_run=0`.
- Tests: `tests/test_session28.py` (20): every event and who is (not) told, no duplicate on repeat or no-op, failed requests leave nothing, privacy (404 for someone else's), paging, announcements (audiences, limits, permissions, audit), dry run default, dedupe, overdue buckets across days, slip-submitted and paid left alone, each reminder off, master switch off, retention, cron secret rules, permissions. Full run: 376 tests; only `test_warm_connection` errors after the others (known; passes alone).
- Files touched: notify.py (new), static/notify.js (new), app.py, fees.py, learning.py, substitutions.py, settings_schema.py, schema.sql, static/index.html, static/i18n/en.json, vercel.json (plus tests and docs).

## Decisions recorded (change any by telling me)
- Notifications are in the portal only. No email, WhatsApp or SMS is sent automatically: there is no provider yet (Session 29 is the WhatsApp decision) and Fees -> Overdue still does those by hand.
- Fee reminders go to the student only (not the guardian, who has no account). Defaults: 3 days before the due date, every 7 days once overdue, assignments 1 day before.
- An invoice with a slip waiting for the admin is not reminded. Fee due soon fires once per invoice even if its due date is later changed.
- Teachers do not get notified about their own cancellations, and a teacher cannot send announcements (admin only). Students are not told about attendance marks or new materials/recordings (kept quiet on purpose; easy to add through `ns.notify`).
- An admin with the Settings area runs reminders by hand; announcements need the Classroom area.

## Left over / not verified
- **Set `CRON_SECRET` in Vercel and redeploy** (needed since Session 9 for the invoice cron). Then check the Cron Jobs tab lists `/api/cron/reminders`, and use Notifications -> Reminders -> Preview once. Vercel Hobby allows one run a day per cron job, which is what is configured (two cron jobs total).
- Browser behaviour of the bell, panel, announcement form and Reminders panel is syntax-checked only (not clicked through). English labels only. The bell refreshes its count every 60 seconds while the tab is visible and on every screen change; there is no push.
- Not run against PostgreSQL (uses `INSERT OR IGNORE` and `DELETE`, which `dbx` translates like elsewhere; `SUBSTR` and plain joins elsewhere).
- An invoice stays in the overdue reminders (every 7 days) until it is paid, waived or voided; there is no cap. Void or waive old ones to stop them.
- Existing students get no back-dated notifications: only events after this version.

## Done: Session 29 (v0.8.29): WhatsApp by phone number
- Decision from you: send through the academy's own WhatsApp, by the student's number. Built as click-to-chat (no provider, no cost): no migration, one new table `wa_log` (created on start). New `whatsapp.py` (2 routes, registered in app.py), WhatsApp panel in `static/notify.js` (Notifications, then WhatsApp; admins only).
- Flow: audience (one student, batch with its teacher, all students, all teachers, everyone) + message with `{name} {student} {academy}` + optional guardians -> one row per person with an Open WhatsApp button (wa.me link, text prefilled). Opening a chat logs it (`wa_log`, audit `whatsapp_sent`) and marks it "Sent today". People with no valid number are listed, not skipped silently.
- Tests: `tests/test_session29.py` (8): link and 960 prefix, batch + teacher, guardians only when asked, audiences, bad input, URL-safe text, sent log and next-day reset and audit, permissions (teacher/student 403, admin with only Student information gets students but not teachers or the batch teacher).
- Files touched: whatsapp.py (new), static/notify.js, app.py, schema.sql, static/i18n/en.json (plus tests and docs).

## Decisions recorded (change any by telling me)
- Fully automatic sending is NOT built. WhatsApp does not allow a normal number to be automated; the official route (WhatsApp Business API via Meta or Twilio) needs a business number registered with it, costs per conversation and needs approved message templates for first contact; unofficial tools risk the number being banned and cannot run on Vercel. Say if you want that as a later session (then fee reminders and the daily run could send by themselves).
- Phone numbers are personal data: the screen needs Student information (students, guardians) and/or Teacher information (teachers). Max 500 chats per preparation.
- The Fees -> Overdue WhatsApp buttons (Session 4) are unchanged and write to the old `reminders` table; this new screen writes `wa_log`.

## Left over / not verified
- Browser behaviour (panel, Open WhatsApp button, pop-up handling) is syntax-checked only, not clicked through; test on a phone and on a computer with WhatsApp Web. English labels only.
- "Sent today" means the chat was opened, not that you pressed Send in WhatsApp; the portal cannot see that.
- Guardian numbers are used whenever one is on file and "Also message the guardian" is ticked, whatever the student's age.

## NEXT SESSION: 30 (teacher earnings). Ask me first: how is a teacher paid (per class, per student, monthly fixed, or a share of fees)? Session 31 then needs: do teachers see their own earnings (default no).

## Done: Session 30 (v0.8.30): teacher earnings calculation (MIGRATION)
- New `earnings.py` (2 routes, area `finance`), table `teacher_earnings` (CREATE IF NOT EXISTS, UNIQUE batch_id+period), setting `revenue_share_percent` (default 50, group "Teacher earnings"), `migrate_session30.py` (dry run by default; `--apply --i-have-a-backup`; writes DRAFT rows for every past month with payments; safe twice). **Back up the database before running it.** No UI yet.
- Rule: collected(batch, month) = payments paid in the month minus payments reversed in the month, void-invoice payments excluded. Teacher share = collected x percent, whole MVR rounded towards zero; academy = the rest. Re-run updates drafts; any approved row locks the whole month (409). Percent used is stored on each row.
- Tests: `tests/test_session30.py` (10): MVR 10,000 gives 5,000/5,000, partial, reversed in same month, multi-batch roll-up, re-run no duplicates, dry run and percent setting, later-month reversal lands as a correction, void excluded, approved month untouched, permissions and input, audit row, migration dry run/apply/twice. Full run 394 tests; only `test_warm_connection` errors (known).
- Files touched: earnings.py, migrate_session30.py (new), app.py, schema.sql, settings_schema.py (plus tests and docs).

## Decisions recorded (change any by telling me)
- The handoff asked how teachers are paid; the plan itself specified a share of collected fees (default 50%), so I built that. Per class, per student or fixed monthly pay are NOT built; say so if you want them.
- The earner is the batch's permanent teacher (`batches.teacher_id`) at calculation time. Substitutes earn nothing extra. A batch with no teacher: all collected goes to the academy share.
- Month is by `paid_on` (payment date) and by the date part of `reversed_at` (UTC timestamp, so a reversal near midnight Maldives time can fall in the neighbouring month).
- Negative months are kept (a correction), not carried forward or floored at zero.

## Left over / not verified
- No Finance screen yet, no approval or teacher payments (Session 31). The finance dashboard still shows teacher earnings and academy revenue as "coming" until Session 31 feeds them.
- Not run against PostgreSQL (uses `ON CONFLICT ... DO UPDATE ... WHERE`, supported by both).
- Session 31 needs your answer: do teachers see their own approved earnings (default no)?

## NEXT SESSION: 31 (earnings approval, teacher payments, reports). Ask me first: do teachers see their own earnings (default no)?

## Done: Session 31 (v0.8.31): approval, teacher payments, reports, registration fee
- Your decisions applied: teachers see their own approved earnings (setting `teachers_see_earnings`, default on); teachers are paid only from monthly course fees; registration fee is set per course when adding or editing it and is a one-time charge.
- **Registration fee** (new): `courses.registration_fee_mvr` and `invoices.kind` (columns added on start with defaults, no data changed: back up first anyway). Course create/edit forms have the field. One registration invoice per student and course, made when an enrolment becomes active (`registration_invoice` in fees.py), due after the first-invoice grace days, no discounts or family concession. Excluded from teacher earnings (earnings.py), included in revenue and outstanding. Period is `REG-FEE`; transfer and drop code now filter `kind='monthly'` (a bug found by test: the string compare made REG-FEE look like a future month).
- **Approval**: `POST /api/earnings/approve` recalculates, optionally checks the total the admin reviewed, locks the month. Only finished months. No unlock route (a mistake is corrected in the next month's figures, or by a developer with the database).
- **Teacher payments**: `teacher_payments`; cannot exceed approved-and-unpaid; void with reason; outstanding = approved earned - non-void payments, across all months.
- **Report**: JSON, CSV and Excel (reuses `to_xlsx`/`csv_safe`); exports logged. **Dashboards**: Finance dashboard and admin dashboard show teacher earnings, academy revenue (approved months in the dates) and, in Finance, paid to teachers.
- **Teacher view**: `GET /api/my/earnings` and a My earnings tab; approved months only, no academy share shown.
- UI: Finance screen panel (month, Calculate, Approve, owed table, record/void payment prompts, CSV/Excel); My earnings tab; registration field on both course forms. Syntax-checked only, not clicked through.
- Tests: `tests/test_session31.py` (8): registration once and not in earnings (2000 collected, 2400 revenue), no-fee course unchanged and validation, transfer not charged again, approve rules and lock, payments (limit, void, reason, method), teacher view (own, approved only, setting off, student 403), report/CSV/Excel/dashboards, permissions and log rows. Updated three old tests (teacher tab list, "coming" placeholders, dashboard dict) to the new behaviour. Full run: 402 tests, all pass except `test_warm_connection` when run last in the full run (known; passes alone).
- Files touched: earnings.py, fees.py, finance.py, admindash.py, app.py, dbx.py, schema.sql, settings_schema.py, static/admin.js, static/learning.js, static/i18n/en.json (plus tests and docs).

## Decisions recorded (change any by telling me)
- A transfer inside the same course moves that month's invoice to the new batch (existing behaviour), so that month's fee, and the teacher's share of it, goes to the new batch's teacher. No pro-rating between two teachers.
- Registration fee applies to new enrolments only: existing students are not charged when you set a fee on an existing course, and students added by CSV import (Session 27) or enrolled while the fee was 0 get no registration invoice. Say if you want a catch-up.
- Registration invoices have no discounts; waiving one is done like any other invoice.
- The dashboards count approved months only, so an un-approved month shows 0 for teacher earnings and academy revenue (stated on the Finance screen).

## Left over / not verified
- Browser behaviour of the new Finance panel, prompts and My earnings tab is not clicked through. English labels only. Payments use simple prompt boxes (amount, method, reference), not a form.
- The teacher tab shows even if the admin switched the setting off; the page then says earnings are not shown.
- Not run against PostgreSQL (plain SQL; ALTER ... ADD COLUMN with default works on both).
- Registration invoices show "REG-FEE" in the Period column of invoice lists; a nicer label is a UI polish.

## NEXT SESSION: 32 (security and regression sweep). No decision needed.

## Done: Session 32 (v0.8.32): security and regression sweep
- New `tests/test_session32.py` (13 tests): (1) hand-written policy vs every `@auth` rule (roles, then permission area), and the exact list of public routes; (2) no token = 401 on every protected route; (3) matrix of 9 callers x every route (refused writes executed, allowed GETs executed, never a 5xx); (4) limited-admin and picker rules; (5) other student, withdrawn student, other teacher, substitute (inside and after the dates); (6) no hash, password or stored file key in any GET response; (7) cron secrets; (8) disabled account loses its token at once; (9) forged tokens and JSON errors. Mutation-checked: putting two of the fixes back makes tests 05 and 06 fail.
- **Fixed** (app.py only): `GET /api/users` leaked emails, phones, login IDs and permission lists to any admin; now People area for full details, names-only for admins in a picker area, 403 for the rest. `GET /api/enrollments` (admin) and `GET /api/batches/<id>/students` (admin) now need one of those areas. `GET /api/dashboard` money figures only with the Fees area. `auth()` records `auth_roles` and `auth_perm` on each view (the matrix test reads them).
- Whole suite run together: 415 tests, one error: `test_warm_connection` when run last (known, passes alone).
- Migrations: re-run on a populated copy whose student, teacher, enrolment and login codes and the audit v2 columns were blanked, and whose events were deleted: all four scripts safe twice, dry run changed nothing, people, payments, invoices and enrolments identical, no duplicate or missing codes, one withdrawal event rebuilt, login by new ID and by email works.
- Docs: README entry, `API.md` (generated who-can-call-what table), `RESTORE.md` (new), CONTEXT.md notes.

## Decisions recorded (change any by telling me)
- An admin who has any one of People, Batches, Enrolments, Fees, Classroom or Settings still sees names (not emails, phones or login IDs) in the dropdowns of those screens. An admin with only Admissions, Audit, Finance or the information areas no longer gets the people list, the enrolment list or batch rosters. Say if Finance or the information areas should count as picker areas.
- The old dashboard cards for students, teachers, batches and enrolments are still shown to every admin (counts only).
- Substitutes can open the class's attendance sheet (which lists the students) on their dates but get 403 on `GET /api/batches/<id>/students` and the gradebook. Unchanged since Session 22; I did not change it. Say if a substitute should also get the plain student list.
- Every signed-in student sees the full course list with fees (`GET /api/courses`); it is the same information the public application page shows.

## Left over / not verified
- **The `instance/portal.db` inside the zip is empty (0 users).** The migration comparison above used a populated test copy on SQLite, not your live data and not PostgreSQL, and not a real v0.8.7 file. Before the live upgrade: back up (see `RESTORE.md`), run each `migrate_sessionNN.py` dry run, apply, and compare the counts it prints against the dashboard.
- Allowed writes (create, edit, delete as the right person) are not part of the matrix; each feature session tests its own. A mistake of the "right role, wrong object" kind on a write route would be found only by that session's tests. Spot checks here covered reads and refusals.
- Nothing has been run against PostgreSQL or a real bucket in any session; `check_storage.py` and one real PostgreSQL run of the full suite are still yours to do.
- Browser screens added in Sessions 24 to 31 (Finance panels, bell, WhatsApp panel, My earnings, Reminders) are syntax-checked only, never clicked through, English labels only.
- Still to set live: `CRON_SECRET` in Vercel (invoice and reminder crons), `PORTAL_SKIP_FORCED_CHANGE` must NOT be set, demo accounts must have their passwords changed or be deleted.
- Login attempt limits and token lifetime were not reviewed in this sweep; tokens are not revoked by a restore (see `RESTORE.md`).
- Known: `test_warm_connection` errors when it runs last in the full run.

## NEXT SESSION: none. The plan (Sessions 8 to 32) is complete. Suggested follow-ups if you want them: a real PostgreSQL run of all tests, a click-through of the browser screens, and automatic WhatsApp sending through the Business API.

## Done: v0.8.33: UI correction sessions 1 to 22 (front end; small server additions)
- Full detail, names to keep and a 5-line manual test per session: `CORRECTIONS-v0.8.33.md`.
- New: `static/ui.js` (dialogs), `tools/codemod_styles.py`, `tests/e2e_ui.py`, `tests/test_session33.py`. Rewritten: the script in `static/index.html`, `static/admin.js` (one definition per view), `static/notify.js` panel, `static/apply.html` script.
- Server: `GET /api/audit?offset=`, `/api/public/info` returns `upload_max_mb` and `learning_max_mb`, notification links `tab:id` (fees.py, learning.py, notify.py, substitutions.py). No schema change, no migration.
- Tests: 418 unit tests pass in ONE run (test_warm_connection isolated); all 10 browser scripts pass (349 checks).
- Names later sessions must keep: `go`, `navBack`, `closeDetail`, `mount`, `showErr`, `busy`, `tabs`, `crumb`/`crumbFor`, `addPanel`, `pickField`, `checkFile`, `fmtTime`/`fmtDate`/`fmtNum`, `setLang`, `ui.*`, `NAV_KEYS`/`DETAIL_KEY`/`TAB_RESET`/`BAR_PREFS`, storage keys `tok sb flt` (session) and `lastTab:<id> navClosed:<id>` (local).
- Decisions still open: fonts (self-host or keep Google Fonts) and login token storage (Session 20d, left unchanged); a language setting for `setLang` (none exists yet).
- Not verified: real PostgreSQL, iOS Safari (needs 15.4+ for `<dialog>`), a screen reader pass, Dhivehi RTL with real text.
