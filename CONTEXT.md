# CONTEXT.md: project map (generated in Session 8)

Read this instead of the source. Regenerate the route and table sections with the grep commands at the end when they change.

## Stack and layout

- Flask app factory `create_app()` in `app.py`; feature modules register routes with `register(app, ns)`: `learning.py` (timetable, attendance, assignments, grades, materials, tutorials, recordings, student/teacher information) and `fees.py` (invoices, slips, payments, reminders, reports). `payments.py` and `receipts.py` are helpers.
- `ns` shared by modules: `db, rows, one, raw_setting, audit, err, auth, need, UPLOADS, store`.
- DB: `dbx.py` wraps SQLite (local) and PostgreSQL (`DATABASE_URL`). SQL is written SQLite-style with `?` placeholders; `schema.sql` is re-applied on start (`CREATE TABLE IF NOT EXISTS`). New tables with `id INTEGER PRIMARY KEY AUTOINCREMENT` get their id back on both engines. Column additions to existing tables need a migration (none exists yet; Session 10 adds the pattern).
- Files: `storage.py` (local folder or S3 bucket; areas `ids`, `learning`, `slips`), `common.py` (upload validation, `file_headers`, Vercel 4 MB limit). Files are never public; every download goes through a route that checks the user.
- Front end (no build step): `static/index.html` (main script: `api()`, `fetchFile()`, `readError()`, `signout()`, `render()`), `static/learning.js` (student/teacher/classroom screens, `download()`/`viewFile()`/`apiForm()`), `static/fees.js` (fees screens), `static/admin.js` (admin screens), `static/apply.html` (public admission form), `static/i18n/en.json` (all UI text; add a key for every new string).
- Auth: JWT bearer token; `@auth("admin", "teacher", perm="area")` checks role, then the person's permission list (NULL = everything their role has). Errors: `err(msg, code)` gives `{error: msg}`. All `/api/*` errors are JSON (Session 8 handlers for HTTPException, FileNotFoundError and unexpected errors).
- Hosting: Vercel (`vercel.json`) + hosted PostgreSQL + S3-compatible bucket. Vercel rejects bodies over 4.5 MB (portal limit 4 MB on Vercel via `common.cap_mb`).
- Demo accounts (SQLite only): `teacher@baleegh.test` / `ChangeMe-Teach1`, `student@baleegh.test` / `ChangeMe-Stud1`; admin from `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

## Permission areas (settings_schema.py)

`admissions, courses, batches, classroom, people, enrollments, fees, settings, audit, tutorials, assignments, progress, materials, create_tutorials, submit_tutorial_work, class_links, recordings, add_recordings, student_information, teacher_information, edit_grades, cancel_class, finance`. Role defaults are in `ROLE_AREAS` and tab order in `ROLE_TABS`. `edit_grades` and `cancel_class` are teacher opt-ins; `finance` (admin, Session 23) is part of a full admin's "everything", a limited admin needs it ticked.

## Tables (schema.sql)

| Table | Columns |
|---|---|
| users | id, login_id, email, password_hash, full_name, role, phone, lang, is_active, must_change_password, permissions, created_at |
| students | user_id, date_of_birth, grade, island, guardian_name, guardian_relationship, guardian_phone, student_code |
| teachers | user_id, bio, teacher_code |
| courses | id, name, level, description, textbook, monthly_fee_mvr, days_per_week, minutes_per_class, status, created_at, kind, code, is_active |
| batches | id, course_id, code, days, start_time, start_date, capacity, teacher_id, meet_link, status |
| enrollments | id, student_id, batch_id, status, enrolled_at, enrol_code |
| settings | key, value |
| substitutions | id, batch_id, class_date (first day), ends_on (last day, NULL = one day), session_id, original_teacher_id, substitute_teacher_id, reason, created_by, created_at, removed_at, removed_by |
| audit_unlock | flag (empty; a row only exists inside the one-off backfill transaction; the audit_log UPDATE trigger checks it) |
| audit_log | id, user_id, action, entity, entity_id, detail, at, user_role, login_id, course_id, batch_id, old_value, new_value, ip |
| applications | id, ref, full_name, date_of_birth, is_minor, grade, phone, email, island, course_id, batch_id, id_file, guardian_name, guardian_relationship, guardian_phone, guardian_id_file, status, reject_reason, student_user_id, decided_by, decided_at, created_at |
| sessions | id, batch_id, session_date, start_time, status, topic, note, meet_link, created_by, created_at |
| attendance | id, session_id, student_id, status, note, marked_by, marked_at |
| assignments | id, batch_id, title, description, kind, due_date, max_points, attachment, attachment_name, created_by, created_at |
| submissions | id, assignment_id, student_id, text_answer, file, file_name, submitted_at, is_late, grade, feedback, graded_by, graded_at |
| materials | id, batch_id, title, description, kind, file, file_name, url, uploaded_by, created_at |
| recordings | id, batch_id, title, url, recorded_on, created_by, created_at |
| tutorials | id, title, body, course_id, file, file_name, url, uploaded_by, created_at |
| tutorial_submissions | id, tutorial_id, student_id, text_answer, file, file_name, submitted_at |
| families | id, name, concession_kind, concession_value, concession_reason, created_at |
| family_members | student_id, family_id, concession_applies |
| invoices | id, enrollment_id, student_id, course_id, batch_id, period, description, amount_mvr, discount_mvr, amount_due_mvr, paid_mvr, waived_mvr, due_date, status, status_reason, discount_note, notes, created_by, created_at |
| discounts | id, scope, enrollment_id, invoice_id, kind, value, amount_mvr, reason, active, created_by, created_at, ended_by, ended_at |
| payment_slips | id, invoice_id, student_id, file, file_name, file_hash, amount_mvr, transfer_date, reference, status, reject_reason, reviewed_by, reviewed_at, created_at |
| payments | id, invoice_id, student_id, amount_mvr, method, paid_on, reference, note, slip_id, receipt_seq, receipt_no, recorded_by, created_at, reversed_at, reversed_by, reverse_reason |
| reminders | id, invoice_id, channel, recipient, sent_by, sent_at |
| counters | name, value |
| expense_categories | id, name (unique, case-insensitive checked in code), is_active, created_at |
| expenses | id, expense_date, amount_mvr (whole MVR, >0), category_id, description, receipt_file (private area `receipts`), receipt_name, entered_by, created_at, updated_by, updated_at |
| enrollment_events | id, student_id, from_batch_id, to_batch_id, kind (transfer/withdrawal), effective_date, reason, by_user, at |
| wa_log | id, user_id, to_kind (student/teacher/guardian), phone, preview, sent_by, sent_at (Maldives time) |
| notifications | id, user_id, kind, title, body, link (a tab name), dedupe_key (unique with user_id; NULL = event, never deduplicated), created_at (UTC text), read_at |

Key facts: `batches.teacher_id` is the single permanent teacher; `batches.meet_link` is the class link; `courses.monthly_fee_mvr` defaults to 0 (fee-0 courses get no invoices); `invoices` is unique on `(enrollment_id, period)`; `audit_log` has v2 columns (`user_role, login_id, course_id, batch_id, old_value, new_value, ip`, Session 20); `audit(action, entity, entity_id, detail, *, course_id, batch_id, old, new, role, login_id)` fills who and IP itself; `teacher_earnings` (Session 30: teacher_id, batch_id, period YYYY-MM, collected_mvr, share_percent, teacher_share_mvr, academy_share_mvr, status draft|approved; UNIQUE batch_id+period; `earnings.py`, setting `revenue_share_percent`; routes `POST /api/earnings/calculate`, `GET /api/earnings`, admin perm=finance). Session 23: `finance.py` (expenses; `register(app, ns, today)`), storage area `receipts`, tab `finance` (static/admin.js `views.finance`).

## Routes

| Method | Path | Auth | Function | File |
|---|---|---|---|---|
| GET | `/` | public / none | index | app.py |
| GET | `/api/health` | public / none | health | app.py |
| POST | `/api/auth/login` | public / none | login | app.py |
| GET | `/api/auth/me` |  | me | app.py |
| POST | `/api/auth/change-password` |  | change_password | app.py |
| POST | `/api/users/<int:uid>/reset-password` | admin, perm=people | users_reset_password | app.py |
| GET | `/api/users` | admin | users_list | app.py |
| GET | `/api/users/<int:uid>` | admin, perm=people | users_get | app.py |
| POST | `/api/users` | admin, perm=people | users_create | app.py |
| PATCH | `/api/users/<int:uid>` | admin, perm=people | users_update | app.py |
| DELETE | `/api/users/<int:uid>` | admin, perm=people | users_delete | app.py |
| GET | `/api/public/courses` | public / none | public_courses | app.py |
| GET | `/api/courses` |  | courses_list | app.py |
| POST | `/api/courses` | admin, perm=courses | courses_create | app.py |
| PATCH | `/api/courses/<int:cid>` | admin, perm=courses | courses_update | app.py |
| DELETE | `/api/courses/<int:cid>` | admin, perm=courses | courses_delete | app.py |
| GET | `/api/batches` |  | batches_list | app.py |
| POST | `/api/batches` | admin, perm=batches | batches_create | app.py |
| PATCH | `/api/batches/<int:bid>` | admin, perm=batches | batches_update | app.py |
| DELETE | `/api/batches/<int:bid>` | admin, perm=batches | batches_delete | app.py |
| GET | `/api/batches/<int:bid>/students` | admin, teacher | batch_students | app.py |
| GET | `/api/enrollments` |  | enroll_list | app.py |
| GET | `/api/enrollment-events` | admin, perm=enrollments | ev_list | transfers.py |
| GET | `/api/enrollment-events.csv` | admin, perm=enrollments | ev_csv | transfers.py |
| POST | `/api/enrollments` | admin, perm=enrollments | enroll_create | app.py |
| PATCH | `/api/enrollments/<int:eid>` | admin, perm=enrollments | enroll_update | app.py |
| GET | `/api/public/info` | public / none | public_info | app.py |
| GET | `/api/public/batches` | public / none | public_batches | app.py |
| POST | `/api/public/apply` | public / none | apply | app.py |
| POST | `/api/public/apply/status` | public / none | apply_status | app.py |
| GET | `/api/applications` | admin, perm=admissions | apps_list | app.py |
| GET | `/api/applications/<int:aid>` | admin, perm=admissions | apps_get | app.py |
| GET | `/api/applications/<int:aid>/file/<which>` | admin, perm=admissions | apps_file | app.py |
| POST | `/api/applications/<int:aid>/approve` | admin, perm=admissions | apps_approve | app.py |
| POST | `/api/applications/<int:aid>/reject` | admin, perm=admissions | apps_reject | app.py |
| POST | `/api/applications/<int:aid>/waitlist` | admin, perm=admissions | apps_waitlist | app.py |
| DELETE | `/api/applications/<int:aid>/files` | admin, perm=admissions | apps_delete_files | app.py |
| DELETE | `/api/enrollments/<int:eid>` | admin, perm=enrollments | enroll_delete | app.py |
| PATCH | `/api/applications/<int:aid>` | admin, perm=admissions | apps_edit | app.py |
| GET | `/api/dashboard` | admin | dashboard | app.py |
| GET | `/api/settings` | admin, perm=settings | settings_get | app.py |
| GET | `/api/settings/schema` | admin, perm=settings | settings_schema | app.py |
| PUT | `/api/settings` | admin, perm=settings | settings_put | app.py |
| POST | `/api/substitutions` | admin, perm=batches | sub_create | substitutions.py |
| GET | `/api/substitutions` | admin, perm=batches | sub_list (?batch_id, ?when) | substitutions.py |
| DELETE | `/api/substitutions/<id>` | admin, perm=batches | sub_remove (soft) | substitutions.py |
| GET | `/api/my/substitutions` | teacher | sub_mine | substitutions.py |
| GET | `/api/expense-categories` | admin, perm=finance | exp_cat_list | finance.py |
| POST | `/api/expense-categories` | admin, perm=finance | exp_cat_create | finance.py |
| PATCH | `/api/expense-categories/<int:kid>` | admin, perm=finance | exp_cat_update | finance.py |
| DELETE | `/api/expense-categories/<int:kid>` | admin, perm=finance | exp_cat_delete (409 if used) | finance.py |
| GET | `/api/expenses` | admin, perm=finance | exp_list (?category_id, date_from, date_to, q, page, per_page) | finance.py |
| POST | `/api/expenses` | admin, perm=finance | exp_create (multipart, optional file) | finance.py |
| PATCH | `/api/expenses/<int:eid>` | admin, perm=finance | exp_update (file replaces, remove_receipt=1 removes) | finance.py |
| DELETE | `/api/expenses/<int:eid>` | admin, perm=finance | exp_delete | finance.py |
| GET | `/api/expenses/<int:eid>/receipt` | admin, perm=finance | exp_receipt (logged) | finance.py |
| GET | `/api/finance/revenue` | admin, perm=finance | fin_revenue (?date_from, date_to, course_id, batch_id, kind) | finance.py |
| GET | `/api/admin/dashboard` | admin (financial part needs finance, fee notices need fees) | admin_dashboard (?course_id, batch_id, kind, teacher_id, date_from, date_to) | admindash.py |
| GET | `/api/finance/dashboard` | admin, perm=finance | fin_dashboard (?date_from, date_to; default this month) | finance.py |
| GET | `/api/audit` | admin, perm=audit | audit_list (filters, paging, list) | auditview.py |
| GET | `/api/audit.csv` | admin, perm=audit | audit_csv (export logged) | auditview.py |
| GET | `/api/audit/summary` | admin, perm=audit | audit_summary (drill-down) | auditview.py |
| GET | `/api/audit/actions` | admin, perm=audit | audit_actions | auditview.py |
| POST | `/api/auth/logout` | any signed-in user | logout (writes the log row only) | app.py |
| PUT | `/api/batches/<int:bid>/meet-link` | admin, teacher, perm=class_links | l_batch_link | learning.py |
| GET | `/api/timetable` |  | l_timetable | learning.py |
| POST | `/api/batches/<int:bid>/sessions` | admin, teacher, perm=classroom | l_session_set | learning.py |
| GET | `/api/batches/<int:bid>/attendance` | admin, teacher, perm=classroom | l_att_get | learning.py |
| POST | `/api/batches/<int:bid>/attendance` | admin, teacher, perm=classroom | l_att_save | learning.py |
| GET | `/api/batches/<int:bid>/attendance/summary` | admin, teacher, perm=classroom | l_att_summary | learning.py |
| GET | `/api/my/batches` | student, teacher | l_my_batches | learning.py |
| GET | `/api/my/information` | student, teacher | l_my_info | learning.py |
| GET | `/api/my/given-grades` | teacher (classroom) | l_given_grades | learning.py |
| GET | `/api/teacher/dashboard` | teacher (classroom) | l_teacher_dash | learning.py |
| GET | `/api/my/attendance` | student, perm=progress | l_my_att | learning.py |
| POST | `/api/batches/<int:bid>/assignments` | admin, teacher, perm=classroom | l_assign_create | learning.py |
| GET | `/api/assignments/<int:aid>/attachment` | perm=A_PERM | l_assign_attachment | learning.py |
| PATCH | `/api/assignments/<int:aid>` | admin, teacher, perm=classroom | l_assign_update | learning.py |
| DELETE | `/api/assignments/<int:aid>` | admin, teacher, perm=classroom | l_assign_delete | learning.py |
| GET | `/api/assignments` | perm=A_PERM | l_assign_list | learning.py |
| POST | `/api/assignments/<int:aid>/submit` | student, perm=assignments | l_submit | learning.py |
| GET | `/api/assignments/<int:aid>/submissions` | admin, teacher, perm=classroom | l_subs | learning.py |
| GET | `/api/submissions/<int:sid>/file` | perm=A_PERM | l_sub_file | learning.py |
| POST | `/api/assignments/<int:aid>/grades` | admin, teacher, perm=classroom | l_grade | learning.py |
| GET | `/api/batches/<int:bid>/gradebook` | admin, teacher, perm=classroom | l_gradebook | learning.py |
| GET | `/api/my/grades` | student, perm=progress | l_my_grades | learning.py |
| GET | `/api/student-information` | admin, perm=student_information | l_si_list | learning.py |
| GET | `/api/student-information/<int:uid>` | admin, perm=student_information | l_si_get | learning.py |
| GET | `/api/teacher-information` | admin, perm=teacher_information | l_ti_list | learning.py |
| GET | `/api/teacher-information/<int:uid>` | admin, perm=teacher_information | l_ti_get | learning.py |
| POST | `/api/batches/<int:bid>/materials` | admin, teacher, perm=classroom | l_mat_add | learning.py |
| GET | `/api/materials` | perm=M_PERM | l_mat_list | learning.py |
| GET | `/api/materials/<int:mid>/file` | perm=M_PERM | l_mat_file | learning.py |
| DELETE | `/api/materials/<int:mid>` | admin, teacher, perm=classroom | l_mat_del | learning.py |
| POST | `/api/batches/<int:bid>/recordings` | admin, teacher, perm=add_recordings | l_rec_add | learning.py |
| GET | `/api/recordings` | perm={student: recordings, teacher: classroom, admin: classroom} | l_rec_list | learning.py |
| DELETE | `/api/recordings/<int:rid>` | admin, teacher, perm=add_recordings | l_rec_del | learning.py |
| POST | `/api/tutorials` | admin, teacher, perm=create_tutorials | l_tut_add | learning.py |
| GET | `/api/tutorials` | perm=tutorials | l_tut_list | learning.py |
| GET | `/api/tutorials/<int:tid>` | perm=tutorials | l_tut_one | learning.py |
| GET | `/api/tutorials/<int:tid>/file` | perm=tutorials | l_tut_file | learning.py |
| DELETE | `/api/tutorials/<int:tid>` | admin, teacher, perm=tutorials | l_tut_del | learning.py |
| POST | `/api/tutorials/<int:tid>/submission` | student, perm=submit_tutorial_work | l_tut_submit | learning.py |
| GET | `/api/tutorials/<int:tid>/submission` | student, perm=submit_tutorial_work | l_tut_my_answer | learning.py |
| GET | `/api/tutorials/<int:tid>/submissions` | admin, teacher, perm=create_tutorials | l_tut_answers | learning.py |
| GET | `/api/tutorial-submissions/<int:sid>/file` | perm={student: submit_tutorial_work, teacher: create_tutorials, admin: create_tutorials} | l_tut_answer_file | learning.py |
| GET | `/api/my/home` | student, teacher | l_home | learning.py |
| POST | `/api/invoices/generate` | admin, perm=fees | inv_generate | fees.py |
| POST | `/api/invoices/catch-up` | admin, perm=fees | inv_catch_up | fees.py |
| GET | `/api/invoices/<id>/invoice.pdf` | admin, perm=fees | invoice_pdf | fees.py |
| GET, POST | `/api/cron/generate-invoices` | CRON_SECRET bearer (no user) | cron_generate_invoices | app.py |
| GET | `/api/invoices` | admin, perm=fees | inv_list | fees.py |
| GET | `/api/invoices/<int:iid>` | admin, student, perm=fees | inv_get | fees.py |
| POST | `/api/invoices/<int:iid>/discount` | admin, perm=fees | inv_discount | fees.py |
| POST | `/api/invoices/<int:iid>/void` | admin, perm=fees | inv_void | fees.py |
| POST | `/api/invoices/<int:iid>/waive` | admin, perm=fees | inv_waive | fees.py |
| POST | `/api/invoices/<int:iid>/reopen` | admin, perm=fees | inv_reopen | fees.py |
| POST | `/api/enrollments/<int:eid>/void-open-invoices` | admin, perm=fees | void_open | fees.py |
| GET | `/api/discounts` | admin, perm=fees | disc_list | fees.py |
| POST | `/api/discounts` | admin, perm=fees | disc_create | fees.py |
| DELETE | `/api/discounts/<int:did>` | admin, perm=fees | disc_end | fees.py |
| GET | `/api/families` | admin, perm=fees | fam_list | fees.py |
| POST | `/api/families` | admin, perm=fees | fam_create | fees.py |
| PATCH | `/api/families/<int:fid>` | admin, perm=fees | fam_update | fees.py |
| POST | `/api/families/<int:fid>/members` | admin, perm=fees | fam_add | fees.py |
| PATCH | `/api/families/<int:fid>/members/<int:sid>` | admin, perm=fees | fam_member | fees.py |
| DELETE | `/api/families/<int:fid>/members/<int:sid>` | admin, perm=fees | fam_remove | fees.py |
| GET | `/api/my/fees/summary` | student, perm=fees | my_fees_summary | fees.py |
| GET | `/api/my/fees` | student, perm=fees | my_fees | fees.py |
| POST | `/api/invoices/<int:iid>/slips` | student, perm=fees | slip_upload | fees.py |
| GET | `/api/slips/<int:sid>/file` | admin, student, perm=fees | slip_file | fees.py |
| GET | `/api/slips` | admin, perm=fees | slips_list | fees.py |
| POST | `/api/slips/<int:sid>/verify` | admin, perm=fees | slip_verify | fees.py |
| POST | `/api/slips/<int:sid>/reject` | admin, perm=fees | slip_reject | fees.py |
| POST | `/api/payments` | admin, perm=fees | pay_manual | fees.py |
| GET | `/api/payments` | admin, perm=fees | pay_list | fees.py |
| POST | `/api/payments/<int:pid>/reverse` | admin, perm=fees | pay_reverse | fees.py |
| GET | `/api/payments/<int:pid>/receipt.pdf` | admin, student, perm=fees | receipt_pdf | fees.py |
| GET | `/api/fees/overdue` | admin, perm=fees | overdue_list | fees.py |
| POST | `/api/invoices/<int:iid>/reminders` | admin, perm=fees | remind_log | fees.py |
| POST | `/api/invoices/<int:iid>/reminders/email` | admin, perm=fees | remind_email | fees.py |
| GET | `/api/fees/report` | admin, perm=fees | fees_report | fees.py |
| GET | `/api/fees/report.csv` | admin, perm=fees | fees_report_csv | fees.py |
| GET | `/api/fees/payment-report` | admin, perm=fees | payrep | payreports.py |
| GET | `/api/fees/payment-report.csv` | admin, perm=fees | payrep_csv | payreports.py |
| GET | `/api/fees/payment-report.xlsx` | admin, perm=fees | payrep_xlsx | payreports.py |
| GET | `/api/fees/student-history/<int:sid>` | admin, perm=fees | student_history | payreports.py |

113 routes.

## Tests

- Everything: `python -m unittest tests.test_phase1 tests.test_phase2 tests.test_phase3 tests.test_phase4 tests.test_phase5 tests.test_admin_controls tests.test_hosted_storage tests.test_permissions tests.test_session2 tests.test_session4 tests.test_session5 tests.test_session6 tests.test_session7 tests.test_session8 tests.test_session9 tests.test_session10 tests.test_session11 tests.test_session12 -v` (older suites run with PORTAL_SKIP_FORCED_CHANGE=1, set in `tests/__init__.py`; `test_warm_connection` only passes when run alone)
- `tests.test_warm_connection` passes alone but fails when run after the other modules (an earlier module leaves `ADMIN_EMAIL` in the environment). This was already so in v0.8.7. Run it separately.
- Each test module builds its own temporary database. Use the pattern in `tests/test_session8.py` for new tests.
- Browser tests (`tests/e2e_*.py`) need Playwright and are optional.

## Regenerate the map

```
grep -n '@app\.\(get\|post\|put\|patch\|delete\)' app.py learning.py fees.py
grep -n 'CREATE TABLE' schema.sql
```

## Session 9 notes
- Hooks in `app.extensions["fees"]`: `first_invoice`, `first_invoice_result` (returns invoice_id, reason, message), `catch_up(user_id, how)`, `generate`. Skip reasons live in `SKIP_MSG` in fees.py.
- `POST /api/enrollments` answers `invoice_id`, `invoice_skipped`, `invoice_message`; `POST /api/courses` answers `warning: fee_zero`; `PATCH /api/courses/<id>` answers `invoices_created` when the fee goes from 0 to above 0.
- The cron route is in app.py (not fees.py) so the role sweep in test_phase4 test_39 does not treat it as a role endpoint. Permission-matrix tests (Session 32) must special-case it.
- Env: `CRON_SECRET`. vercel.json has the daily cron.

## Session 10 notes: ID codes (MIGRATION)
- `idcodes.py`: `fill_missing(conn, unenrolled_students=True)` (the backfill and the "new row gets a code" step), `next_number` (counters table), `derive_course_code`, `assign_student_code`, `duplicates`. `app.py` calls `fill_codes()` before the commit in users create/update, enrolment create, transfer, application approval; courses create sets the code itself.
- Formats: course `AL1`/`G8M` (unique, 2 to 8 of A-Z0-9); student `BAL/<course code>/NNN` (permanent, first course decides; `BAL/STU/NNN` for old students with no enrolment); teacher `BAL/T/NNN`; enrolment `BAL/<course code>/ENNN` (the E keeps it apart from the student ID). Counters: `student:<CODE>`, `enrol:<CODE>`, `teacher`.
- A student created without a course has NO code until the first enrolment (or `course_id` in the create request). Session 11 must decide how login ID works for these.
- Columns are added in `dbx.init_schema` (nullable or defaulted) with unique indexes `ux_courses_code`, `ux_students_code`, `ux_teachers_code`, `ux_enrol_code`; indexes are NOT in schema.sql because older tables lack the columns when it runs. `migrate_session10.py` = dry run by default; `--apply --i-have-a-backup`.
- `courses.is_active` is set from status only when an older course first gets its code; afterwards it is independent of status (Session 12 decides the rules). Nothing reads `kind` or `is_active` yet.
- Test trick: `tests/fixtures/schema_v0_8_8.sql` is the pre-Session-10 schema; patching `dbx.read_schema` to return it makes any test module run on an old-then-upgraded database.

## Session 13 notes: transfers and withdrawals
- `transfers.py`: `record_event()` (called from `enroll_update` in app.py), `backfill()` (used by `migrate_session13.py`, dry run by default), report routes. Table `enrollment_events` is in schema.sql (CREATE TABLE IF NOT EXISTS, no column additions).
- Student access to a batch = enrolment status `active` only, in ONE place each: `viewable()` and `my_batches()` in learning.py (every student list, file route, timetable, grades, attendance and home go through them), plus `l_submit` and `l_sub_file`. Course tutorials use `STU_TUT` / `tut_blocked()` (active enrolment in that course, or tutorial has no course).
- Teachers and admins are unchanged (teachers see their own batch's active roster). Admin Student Information `progress` now includes dropped batches with `enrollment_status`.
- Tests: `tests/test_session13.py` (6). Old `test_phase5` tutorial test updated to the new tutorial rule.

## Session 14 notes: student selector
- Server: `my_batches(batch_id)` in learning.py aborts 403 for a student asking for a batch without an ACTIVE enrolment (also for ids that do not exist). It is the single check behind `?batch_id=` on the student routes. Teachers/admins are unchanged (Session 15 adds the teacher rule).
- Page (`static/index.html`): `S.mine` (from `/my/batches`), `S.sb` (selected batch, kept in sessionStorage `sb`), `withBatch()` adds `batch_id` to the GET paths in `SB_PATH` for students, the picker screen and the header `<select id="sbsel">` are in `render()`. New student screens that read batch data must either use a path matching `SB_PATH` or pass `batch_id` themselves. Fees is not batch-scoped.
- Tests: `tests/test_session14.py` (5). `test_session5` and `test_session13` updated: foreign or dropped `batch_id` is now 403, not `[]`.

## Session 15 notes: teacher selector
- `teacher_batches(uid)` in learning.py is THE rule for which batches a teacher may use (a set of ids; also published as `app.extensions["teacher_batches"]`, used by `GET /api/batches` in app.py). `manage()`, `viewable()`, `my_batches()` and `l_sub_file` all call it. Session 22 (substitutes) changes only this function, plus date logic.
- `my_batches(batch_id)` aborts 403 "This is not your batch" for a teacher asking for a foreign or missing batch. The page shares the Session 14 picker (`S.sb`); the Classroom screen uses it for teachers (admins keep their own dropdown).
- Tests: `tests/test_session15.py` (5). `test_session14` updated (teacher foreign batch is 403).


Session 22 rule: `teacher_batches(uid)` = own batches only (grades, assignments, materials, tutorials, information, cancelling). `class_batches(uid)` = own + batches where the teacher substitutes today; used only by the picker (`/api/my/batches`), `/api/timetable` and the attendance routes via `manage(bid, cls=True)` and `sub_day_error()`.


## Session 23 notes: expenses
- `finance.py` only; amounts are whole MVR (`payments.as_int`), dates not in the future. Hard delete of an expense also deletes its receipt file; the activity log row (`expense_delete`, old amount, detail with date/category/description) is the record. Log actions: `expense_create`, `expense_update`, `expense_delete`, `view_expense_receipt`, `expense_category_create/update/delete`.
- Areas: `finance` added to `AREAS`, admin `ROLE_AREAS`, admin `ROLE_TABS` (after fees) and the People editor labels (`AREA_LABELS`, `ROLE_AREAS` copy in static/admin.js).
- Tests: `tests/test_session23.py` (8). `test_permissions` updated for the new admin tab.

## Session 24 notes: revenue and financial dashboard
- In `finance.py`: `paid_where()/collected()` (revenue = payments with reversed_at NULL, by `paid_on`, course/batch/kind via the payment's invoice), `outstanding()` (non-void invoices, due-waived-paid floored at 0), `expenses_total()`. Sessions 25 and 31 must reuse these, not redefine them. Dashboard returns `teacher_earnings` and `academy_revenue` as the string "coming" until Session 31 fills them.
- UI: `views.finance` in static/admin.js is wrapped to put the dashboard and revenue panel under the heading. Tests: `tests/test_session24.py` (8).

## Session 25 notes: admin dashboard
- `admindash.py` (new): filters pick a set of batches, every card is counted for that set; definitions are listed at the top of the file. `learning.scope_counts(bids, d1, d2)` (exposed as `app.extensions["scope_counts"]`) is the one place for held/upcoming classes and assignment, hand-in, graded and pending numbers (uses `occurrences()` and `assign_counts()`). Finance helpers are exposed as `app.extensions["finance"]` (`collected`, `outstanding`, `expenses_total`); `scope()` in finance.py now also takes `teacher_id`. `ns.has_perm` added.
- UI: `views.dashboard` in static/admin.js replaces the admin dashboard (the older fees.js wrapper no longer applies to it; fee notices come from the same endpoint). Tests: `tests/test_session25.py` (8).

Session 26: `payreports.py` (`register(app, ns, today)`) holds the payment report and `to_xlsx(rows, headers, sheet)` (import it from there for any Excel export). `student_code` is in the `students` table, not `users`. UI: tab `payrep` in static/fees.js (`FX_TABS`, key `fx_tab_payrep`). Tests: `python -m unittest tests.test_session26`.
Session 27: `portio.py` (`register(app, ns)`) has the people and enrolment exports and the three CSV imports (validate first, apply row by row with a commit per row; dry run is the default). Routes: `/api/student-information/export.*`, `/api/student-information/enrolments.*`, `/api/teacher-information/export.*`, `/api/import/students|teachers|enrolments`. UI: export buttons in `siList`/`tiList` and `impPanel` (appended to `views.people`) in static/admin.js. Tests: `python -m unittest tests.test_session27`. Test helper `make_app(tag)` there builds a second empty app and restores `SEED_DEMO` afterwards (do not leak env vars between test modules).

Session 28: `notify.py` (`register(app, ns, now)`, called in app.py BEFORE learning/fees/substitutions because they call `ns.notify`). `ns.notify(user_ids, kind, title, body, link, dedupe)` inserts without committing (a rolled-back request leaves nothing), skips when the `notify_enabled` setting is 0, returns how many were created; `ns.notify_students_of(batch_id)`, `ns.notify_admins_with(area)`. Events: fees.py (slip upload/verify/reject), learning.py (assignment create, grade, class cancel/reinstate), substitutions.py (assign/remove). Scheduled: `run_reminders()` (fee due soon, overdue every N days, assignments due, admin digest, retention) behind `/api/cron/reminders` (Bearer CRON_SECRET, vercel.json 02:30 UTC) and `POST /api/notifications/run` (dry run by default). Dedupe keys: `due:<invoice>`, `overdue:<invoice>:<bucket>`, `assign:<assignment>`, `digest-overdue:<date>`, `digest-slips:<date>`. Last run time is in settings key `_last_reminder_run` (not in SETTING_KEYS). UI: bell button in the nav (index.html) and `static/notify.js` (panel, announcements, reminders). Tests: `python -m unittest tests.test_session28`.

Session 29: `whatsapp.py` (`register(app, ns, now)`): `POST /api/whatsapp/prepare` builds wa.me links per person (phones via `common.digits_intl`; students need `student_information`, teachers `teacher_information`; guardians optional) and `POST /api/whatsapp/sent` logs an opened chat (`wa_log` + audit `whatsapp_sent`). UI: `waForm` in static/notify.js (button in the Notifications panel, admins only). Tests: `python -m unittest tests.test_session29` (reuses `make_app` from test_session28).

## Session 31 additions
`courses.registration_fee_mvr` (one-time, default 0); `invoices.kind` ('monthly' | 'registration'; registration invoices have period `REG-FEE`, which satisfies the 7-character CHECK and sorts after every month, so any code comparing periods as strings must filter `kind='monthly'`, as fees.py does for transfer and drop); `teacher_payments(id, teacher_id, amount_mvr, paid_on, method, reference, note, recorded_by, created_at, voided_at, voided_by, void_reason)`; setting `teachers_see_earnings` (default on); teacher tab `my_earnings`; routes listed in API.md; `app.extensions['earnings']` = approved_in, paid_in (used by finance.py and admindash.py).

## Session 32 notes: security sweep
- `auth()` now stores `wrap.auth_roles` and `wrap.auth_perm` on every protected view, so tests can read each route's rule. `tests/test_session32.py` holds the hand-written policy (`OPEN` = routes that are not admin-only, `AREA` = admin permission area by path prefix, `NO_AREA` = admin routes that check inside, `PUBLIC` = routes without sign-in). Adding a route without updating it fails test_01 or test_02: that is the point.
- Helper in app.py: `can_any(u, *areas)` and `PICKER_AREAS` (people, batches, enrollments, fees, classroom, settings). Used by `GET /api/users` (full list needs `people`, pickers get `id, full_name, role, is_active`), `GET /api/enrollments` (admin), `GET /api/batches/<id>/students` (admin). `GET /api/dashboard` adds the money extras only with `fees`.
- The matrix runs refused writes and all allowed GETs; allowed writes are covered by each session's own tests.
- `RESTORE.md`: backup and restore procedure. `API.md` last section: generated route table.

## UI refresh (navigation and layout)
- `static/index.html` holds the app shell and design system. Desktop: grouped icon sidebar with the user and Sign out pinned at the bottom. Phone (880px and under): top bar, bottom bar with the first 4 tabs plus **More** (a menu with the other tabs, the user and Sign out).
- Tab order and the bar's four tabs come from the server's `ROLE_TABS`; groups for the admin sidebar are `NAV_GROUP` in `index.html`.
- The address bar follows the tab (`#fees`), so Back, refresh and links work. Only a plain `#name` is used.
- On phones, any table with a `<thead>` becomes labelled cards (`labelTables`). Add class `nostack` to a table to keep it as a normal scrolling table.
- New i18n keys: `skip_to_content`, `menu_more`, `main_menu`, `all_sections`, `show_password`, `nav_*`.
- Tests: `tests/e2e_navigation.py` sweeps every tab for every role on phone and desktop (192 checks). `tests/e2e_shim.py` opens the phone menu for the older browser scripts. Older `e2e_*.py` scripts were already stale before this work (login IDs, course chooser); `e2e_submit`, `e2e_student_info`, `e2e_teacher_info` run, the rest need updating.
- Known: `tests.test_warm_connection` errors inside the full suite only (environment leaks from another test); it passes alone.
