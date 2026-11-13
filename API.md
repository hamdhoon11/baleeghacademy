# API (Phases 1-4). Base path /api. Auth header: `Authorization: Bearer <token>`.
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | /health | public | Health check |
| GET | /public/courses | public | Open and upcoming courses for the website |
| POST | /auth/login | public | `{login,password}` (`login` = login ID like `BAL/AL1/001`, case and spaces ignored; an email also works while `ALLOW_EMAIL_LOGIN` is on) returns `{token,user}`. Limited per address and per account (8 failures in 5 minutes gives 429). While `user.must_change_password` is 1 every route except `/auth/me` and `/auth/change-password` answers 403 `{code:"password_change_required"}` |
| GET | /auth/me | any | Current user: `{id,email,full_name,role,must_change_password,permissions,tabs}`. `permissions` is `null` (everything the role has) or a list of areas; `tabs` is what the page may draw |
| POST | /users/<id>/reset-password | admin (people) | New random temporary password, returned once as `{login_id,temporary_password}` (no-store); old password stops working; person must change it at next sign-in. Not for your own account |
| POST | /auth/change-password | any | `{current_password,new_password}` returns `{ok,token}`. v0.8.39: every older sign-in of the account stops working; use the returned `token` |
| GET, POST | /users | admin | List (`?role=`), create admin/teacher/student. Create needs `full_name,email,role`; leave `password` out and the server makes a random one and returns `{id,login_id,temporary_password}` once. Create accepts optional `permissions` (full admin only) and, for a student, optional `course_id`: the permanent student ID (BAL/<course code>/NNN) is issued at once from that course |
| PATCH | /users/:id | admin | Name, phone, active flag, password reset, `permissions` (`"all"` or a list of areas for that role; full admin only) |
| GET | /courses | any | List |
| POST, PATCH | /courses, /courses/:id | admin | Create, update. Optional `kind` (`course` or `tuition`), `code` (2 to 8 letters or digits, unique, stored upper case; derived from the name when omitted), `is_active`. Duplicate code: 409. Answers include `kind`, `code`, `is_active` |
| GET | /batches | any | Admin all, teacher own, student enrolled |
| POST, PATCH | /batches, /batches/:id | admin | Create, update (Meet link, teacher, capacity) |
| GET | /batches/:id/students | admin, own teacher | Roster |
| GET | /enrollments | admin, student (own) | List |
| GET | /my/batches | student, teacher | Batches the student is ACTIVELY in (picker choices). `?batch_id=` on /my/home, /my/grades, /my/attendance, /assignments, /materials, /recordings, /tutorials and /timetable limits a student's answer to that batch; a batch they are not actively in is 403. For a teacher the same routes accept `?batch_id=` for their own batches only (403 otherwise) |
| POST | /enrollments | admin | `{student_id,batch_id}`; waitlists when full |
| PATCH | /enrollments/:id | admin | `{status}` or `{transfer_to_batch_id}`, plus optional `reason` and `effective_date` (YYYY-MM-DD, default today). A transfer or a change to `dropped` writes one `enrollment_events` row |
| GET | /enrollment-events | admin (perm enrollments) | Transfers and withdrawals; filters `kind`, `from`, `to`, `student_id`, `batch_id` |
| GET | /enrollment-events.csv | admin (perm enrollments) | Same rows as CSV (logged in the audit log) |
| GET | /dashboard | admin | Counts |
| GET, PUT | /settings | admin | Academy info and bank details |
| GET | /audit.csv | admin (perm audit) | Same filters as CSV, max 20000 rows; the export is logged |
| GET | /audit/summary | admin (perm audit) | Total, first/last time, counts per action and busiest users for the filter (drill-down) |
| GET | /audit/actions | admin (perm audit) | Action names present in the log |
| GET | /audit | admin | Last 100 actions, now with user_role, login_id, course_id, batch_id, old_value, new_value, ip Filters `user_id, login_id, role, course_id, batch_id, action (comma list), entity, entity_id, q, date_from, date_to` (Maldives dates); `page`, `per_page` (max 500); totals in headers `X-Total-Count`, `X-Page`, `X-Per-Page`. No route can change or delete a row |
| POST | /auth/logout | any signed-in user | Writes a `logout` log row. v0.8.39: also ends every sign-in of the account (all devices) at once |
| GET | /public/info | public | Academy name, phone, WhatsApp number |
| GET | /public/batches | public | Open batches with seats left |
| POST | /public/apply | public | Multipart application (`id_card`, and `guardian_id` if under 18); 5 per hour per IP |
| POST | /public/apply/status | public | `{ref,phone}` returns status |
| GET | /applications | admin | List (`?status=`) |
| GET | /applications/:id | admin | Detail |
| GET | /applications/:id/file/id or guardian_id | admin | Open an ID copy (logged) |
| POST | /applications/:id/approve | admin | `{batch_id,delete_files}` creates account and enrollment, returns temp password and WhatsApp link |
| POST | /applications/:id/reject | admin | `{reason}` |
| POST | /applications/:id/waitlist | admin | Move pending application to waitlist |
| DELETE | /applications/:id/files | admin | Delete stored ID copies |

## Phase 3: learning tools
All need `Authorization: Bearer <token>`. "Own batch" = teacher assigned to it (admins reach every batch; students only batches they are enrolled in). Dates are `YYYY-MM-DD`, times `HH:MM`, Maldives time.

| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | /my/home | student, teacher | Next class (with `can_join`, `meet_link`), today, next 7 days, plus student: courses summary and assignments to do; teacher: submissions waiting for grading and low-attendance students |
| GET | /timetable | any | Classes from `?from=&to=` (default 14 days, max 62), optional `?batch_id=`; scoped to the caller's batches |
| POST | /batches/:id/sessions | admin, own teacher | `{date, start_time?, status: scheduled or cancelled, topic?, note?}` cancels, reinstates or adds an extra class |
| GET | /batches/:id/attendance?date= | admin, own teacher | Roster with marks for that date |
| POST | /batches/:id/attendance | admin, own teacher | `{date, topic?, records:[{student_id, status: present/late/absent/excused, note?}]}`; not for future dates; re-posting updates |
| GET | /batches/:id/attendance/summary | admin, own teacher | Per-student counts, percentage and low flag, plus the threshold |
| GET | /my/attendance | student | Own percentage and recent marks per course |
| POST | /batches/:id/assignments | admin, own teacher | `{title, description?, kind: assignment or test, due_date?, max_points?}` |
| PATCH, DELETE | /assignments/:id | admin, own teacher | Edit (title, description, due_date, max_points) or delete with its submissions |
| GET | /assignments | any | Student: own batches with own submission and grade only. Teacher/admin: counts. Optional `?batch_id=` |
| POST | /assignments/:id/submit | student (active in batch) | Multipart `text` and/or `file`; replaces earlier work until graded; 409 once graded |
| GET | /assignments/:id/submissions | admin, own teacher | Every student's work and grade for the assignment |
| GET | /submissions/:id/file | owner student, own teacher, admin | Download (attachment) |
| POST | /assignments/:id/grades | admin, own teacher | `{student_id, grade (0..max_points), feedback?}`; also used to enter test marks |
| GET | /batches/:id/gradebook | admin, own teacher | Average grade, attendance and low flag per student |
| GET | /my/grades | student | Per course: average, attendance, every item with grade and feedback |
| POST | /batches/:id/materials | admin, own teacher | Multipart `title`, `description?` and either `file` or `url` (https/http) |
| GET | /materials | any | Materials for the caller's batches (`?batch_id=`) |
| GET | /materials/:id/file | batch members, own teacher, admin | Download |
| DELETE | /materials/:id | admin, own teacher | Remove |

Changes to earlier endpoints: `POST/PATCH /batches` now validate `days` (like `Sun,Tue,Thu`, normalised and ordered), `start_time` (`HH:MM`) and `meet_link` (must start with `https://`). `PUT /settings` accepts `low_attendance_pct`.

## Phase 4: fees and payments
All amounts are whole MVR integers. Periods are `YYYY-MM`. Invoice numbers look like `INV-202603-0007` (derived, not stored). **Teachers get 403 on every endpoint below. Students get 403 on every "admin" row. No token gives 401.** A student asking for someone else's invoice, slip, payment or receipt gets 404 (never data). Money actions are written to the audit log.

Invoice `status` is `unpaid`, `slip_submitted`, `paid`, `void` or `waived`. `overdue` is never stored: responses carry `overdue` (bool) and `days_overdue`, worked out from the due date and today's Maldives date.

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | /invoices/generate | admin | `{month}` creates the missing invoices for active enrollments; returns `{created, skipped, skipped_total, details[], details_truncated}`. `details` names each enrolment with no new invoice and the `reason` (fee_zero, inactive_student, not_enrolled_yet, first_month_skipped, already_invoiced). Safe to repeat |
| POST | /invoices/catch-up | admin | creates what is missing for the current month; `{period, created}`. Called when Fees opens |
| GET | /invoices/{id}/invoice.pdf | admin | invoice PDF (attachment) |
| GET/POST | /cron/generate-invoices | `Authorization: Bearer CRON_SECRET` | scheduler entry point; 401 for a wrong or missing secret or when CRON_SECRET is unset |
| GET | /invoices | admin | `?month=&status=&student_id=&q=`; status may be `open`, `overdue` or any status. Max 500 rows |
| GET | /invoices/:id | admin, owning student | Invoice, payments, slips (admin also: discounts, reminders, file hashes) |
| POST | /invoices/:id/discount | admin | One-off `{kind: fixed or percent, value, reason}`; never below 0 or below what is already paid |
| POST | /invoices/:id/void | admin | `{reason}`; not when payments exist or a slip is waiting |
| POST | /invoices/:id/waive | admin | `{reason}` writes off the remaining balance |
| POST | /invoices/:id/reopen | admin | `{reason}` reopens a void or waived invoice |
| POST | /enrollments/:id/void-open-invoices | admin | After a drop: `{reason, from_month?}` voids unpaid invoices with no payments |
| GET, POST | /discounts | admin | Recurring enrollment discounts: `{enrollment_id, kind, value, reason}` |
| DELETE | /discounts/:id | admin | End a recurring discount (old invoices are not changed) |
| GET, POST | /families | admin | Family with an optional concession `{name, concession_kind, concession_value, concession_reason}`. No rate is assumed |
| PATCH | /families/:id | admin | Change name or concession |
| POST | /families/:id/members | admin | `{student_id, concession_applies?}`; a student is in at most one family |
| PATCH, DELETE | /families/:id/members/:student_id | admin | Turn the concession on or off for a child, or remove them |
| GET | /my/fees | student | Bank details, own invoices (with pending slip, last rejection reason, `can_upload`), payments, summary |
| GET | /my/fees/summary | student | `{balance_due, open_count, overdue_count, next_due}` for the Home notice |
| POST | /invoices/:id/slips | owning student | Multipart `amount_mvr`, `transfer_date`, `reference?`, `file` (PDF, JPG or PNG, 5 MB, content checked). One waiting slip per invoice; 10 per hour per student (`SLIP_LIMIT`) |
| GET | /slips/:id/file | owning student, admin | Download (attachment, `Cache-Control: private, no-store`); each open is logged |
| GET | /slips | admin | `?status=pending` (default), `verified`, `rejected`, `reversed` or `all`; each row lists `duplicates` (same file used elsewhere) |
| POST | /slips/:id/verify | admin | `{amount_mvr?, paid_on?, confirm_duplicate?}`; amount defaults to the claimed amount; 400 if above the balance; 409 if already checked, or 409 with `needs_confirm` when the same file was already accepted |
| POST | /slips/:id/reject | admin | `{reason}`; the student sees it and can upload again |
| POST | /payments | admin | Cash or manual payment `{invoice_id, amount_mvr, method: cash, bank_transfer or other, paid_on?, reference?, note?}`; returns a receipt number |
| GET | /payments | admin | `?month=&invoice_id=` |
| POST | /payments/:id/reverse | admin | `{reason}`; reopens the balance; the receipt number stays used |
| GET | /payments/:id/receipt.pdf | owning student, admin | PDF receipt built on demand (identical every time); no bank account or ID data on it |
| GET | /fees/overdue | admin | Overdue invoices with message text, WhatsApp and Viber links (student and guardian), reminders already sent, `email_enabled` |
| POST | /invoices/:id/reminders | admin | `{channel: whatsapp or viber, to: student or guardian}` records that a reminder was sent |
| POST | /invoices/:id/reminders/email | admin | 409 with a clear message when email is off (nothing recorded); 502 when the mail server fails |
| GET | /fees/report | admin | `?month=` totals, per-course breakdown, who owes |
| GET | /fees/report.csv | admin | Same month as a CSV file, one row per invoice (formula-injection safe) |
| GET | /fees/payment-report | admin, perm=fees | `?month=&course_id=&batch_id=&kind=course\|tuition&status=paid\|partial\|unpaid\|waived\|none` one row per student per batch: fee, due, paid, balance, status, payment dates; plus totals |
| GET | /fees/payment-report.csv | admin, perm=fees | Same filters as a CSV file (formula-injection safe); the export is logged |
| GET | /fees/payment-report.xlsx | admin, perm=fees | Same filters as an Excel file; the export is logged |
| GET | /fees/student-history/<id> | admin, perm=fees | All of one student's invoices with every payment (reversed ones flagged) and totals |
| GET | /student-information/export.csv, .xlsx | admin, perm=student_information | `?q=&batch_id=&status=` one row per student (ID, login ID, contact, guardian, enrolments); logged; no fees, no passwords |
| GET | /student-information/enrolments.csv, .xlsx | admin, perm=student_information | One row per enrolment (student code, course code, batch code, status, enrolment ID, date); the file the enrolment import reads |
| GET | /teacher-information/export.csv, .xlsx | admin, perm=teacher_information | `?q=&status=` one row per teacher (ID, login ID, contact, bio, batches); logged |
| POST | /import/students | admin, perm=people | CSV file (field `file` or a text/csv body). `?dry_run=1` is the default and saves nothing; `dry_run=0` imports. Returns every row with status created / would_create / rejected and the reason; temporary passwords once |
| POST | /import/teachers | admin, perm=people | Same, for teachers |
| POST | /import/enrolments | admin, perm=enrollments | Same, for enrolments (course_code + batch_code + student_code or login_id or student_email) |
| GET | /dashboard | admin | Now also `unpaid_invoices`, `overdue_invoices`, `slips_pending`, `month_collection_mvr` |
| GET, PUT | /settings | admin | New keys: `invoice_due_day`, `first_invoice_mode`, `first_invoice_grace_days`, `receipt_prefix`, `reminder_template_en`, `reminder_template_dv` |

## Tutorials (Session 2)
Areas: `tutorials` (open the tab and read), `create_tutorials` (teacher/admin: post, see answers), `submit_tutorial_work` (student: send answers). Post and answer calls need `tutorials` as well.
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | /tutorials | `tutorials` | List (`?q=&course_id=&limit=`). Each item adds `can_delete`, `accepts_answers` (false for older student posts), and for students `can_submit` and `my_submission` (`null` or `{submitted_at,has_file,has_text}`); for the poster teacher and admins `can_view_answers` and `answer_count` |
| POST | /tutorials | teacher, admin with `create_tutorials` | Create (form or JSON: `title`, `text`, `url`, `file`, `course_id`). Students get 403 |
| DELETE | /tutorials/:id | admin (any), teacher with `create_tutorials` (own) | Also removes answers and their files. Students get 403 |
| POST | /tutorials/:id/submission | student with `submit_tutorial_work` | Multipart `text` and/or `file`. 201 first time, 200 when replacing. 409 on older student posts |
| GET | /tutorials/:id/submission | student with `submit_tutorial_work` | My answer: `{submission: null or {id,text_answer,file_name,has_file,submitted_at}}` |
| GET | /tutorials/:id/submissions | admin, or the teacher who posted it (`create_tutorials`) | `{tutorial, submissions:[{id,student_id,full_name,text_answer,file_name,has_file,submitted_at}]}` |
| GET | /tutorial-submissions/:id/file | the student who sent it, the poster teacher, admin | Download the answer's file |

## Class links (Session 4)
Area `class_links` (teacher, admin) plus the usual `classroom` access to the batch (a teacher only for batches where they are the teacher).
| Method | Path | Who | Purpose |
|---|---|---|---|
| PUT | /batches/:id/meet-link | admin (any batch), teacher with `class_links` (own batches) | `{meet_link}` an `https://` address up to 500 characters, or empty to remove. Returns `{ok,meet_link}` |
| POST | /batches/:id/sessions | admin, teacher (own batches) | As before, plus optional `meet_link`: a one-off link for that date and time (empty removes it). Sending `meet_link` needs `class_links`; without it the request is 403 and nothing is saved |
| GET | /timetable, /my/home | any | Each class now carries `meet_link` (its own link if it has one, else the batch link) and `own_link` (true when it has its own) |

## Class recordings (Session 5)
Areas `add_recordings` (teacher, admin; also needs `classroom`) and `recordings` (student). A teacher only reaches their own batches; a student only batches they are enrolled in.
| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | /batches/:id/recordings | admin (any batch), teacher with `add_recordings` (own batches) | JSON `{title (max 200), recorded_on (YYYY-MM-DD, not in the future), url}`; `url` must be an `https://drive.google.com/` or `https://docs.google.com/` link up to 500 characters. 201 `{id}` |
| GET | /recordings | student with `recordings`; teacher, admin with `classroom` | Recordings of the caller's batches (`?batch_id=`), newest class first: `{id,batch_id,batch_code,course_name,title,url,recorded_on,added_by,download_url}`. `download_url` is null unless `url` is a single Drive file |
| DELETE | /recordings/:id | admin, teacher with `add_recordings` (own batches) | Remove the recording (the Drive file is not touched) |

## Student information (Session 6)
Area `student_information` (admin only, read-only). Fee data is included only when the caller also has `fees`.
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | /student-information | admin with `student_information` | Students only. `?q=` (name, email or phone), `?batch_id=`, `?status=active\|inactive`, `?limit=` (1-100, default 30). Returns `{total, fees_visible, students:[{id,full_name,email,phone,is_active,batches,balance_due}]}`; `balance_due` is null without `fees` |
| GET | /student-information/:id | admin with `student_information` | `{profile, enrollments, progress, fees, fees_visible}`. `progress` has per batch attendance counts and percentage, recent classes, graded items and average. `fees` is null without `fees`. 404 if the id is not a student |

## Teacher information (Session 7)
Area `teacher_information` (admin only, read-only).
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | /teacher-information | admin with `teacher_information` | Teachers only. `?q=` (name, email or phone), `?status=active\|inactive`, `?limit=` (1-100, default 30). Returns `{total, teachers:[{id,full_name,email,phone,is_active,batch_count,student_count,weekly_hours}]}` |
| GET | /teacher-information/:id | admin with `teacher_information` | `{profile (with bio), batches, students, workload:{active_batches,students,weekly_classes,weekly_hours,classes_held_30d,to_grade}}`. 404 if the id is not a teacher |

Session 12: `GET /courses?active=1` leaves out inactive courses (`is_active=0`); `/public/courses` never lists them. `POST /enrollments`, enrolment transfer and `POST /batches` answer 409 for a batch/course that is inactive. Invoice generation skips enrolments of inactive courses (reason `course_inactive`). `GET /batches` rows carry `course_kind` and `course_active`; `GET /batches/<id>/students` rows carry `enrollment_id` (drop with `PATCH /enrollments/<id> {status:"dropped"}`). The Batches screen no longer sends `meet_link` (Classroom: `PUT /batches/<id>/meet-link`); the batch API still accepts it.

## GET /api/my/information (student, teacher)
Read-only profile of the signed-in user: `role`, `profile` (login_id, student_code or teacher_code, name, email, phone, plus date of birth, grade, island and guardian for students, bio for teachers), `batches` (students: active enrolments with `enrol_code`, course kind, teacher; teachers: their batches from `teacher_batches()`), `locked` (fields only an admin can change). No fees. Admin 403, no token 401.

## Grades (Session 17)
`POST /api/assignments/<id>/grades` {student_id, grade, feedback}: first grade needs `classroom`; changing a saved grade needs admin or the teacher permission `edit_grades` (403 otherwise; identical values return `changed:false`). Logged as `grade` (none -> value) or `grade_change` (old -> new, feedback old -> new). `GET /api/assignments/<id>/submissions` now includes `can_edit_grades`. `GET /api/my/given-grades?batch_id=` (teacher): grades given by me in batches I may use. `GET /api/my/grades` items now carry `status` (pending, submitted, graded). `edit_grades` is an opt-in area in `settings_schema.OPT_IN`: NULL permissions never include it.

## Session 18
`POST /api/batches/<id>/sessions` with status `cancelled` needs admin or teacher permission `cancel_class` (opt-in, never part of "everything a teacher has"). `GET /api/tutorials` for a teacher: own posts plus courses of own batches; `?batch_id=` narrows (403 if not theirs); `GET /api/tutorials/<id>` and its file/answers 403 outside that scope; `POST /api/tutorials` with a course the teacher does not teach is 403. `GET /api/assignments` (teacher/admin) items now carry `student_count`, `submitted_count`, `graded_count`, `pending_count` (active students only, each once).

## GET /api/teacher/dashboard (teacher, area classroom)
`?batch_id=` optional (403 if not the teacher's batch). Returns `scope`, `batches[]`, `courses`, `students` (active, distinct), `classes {held, held_30d, upcoming, cancelled, next[]}`, `assignments {given, tests, submissions, graded, pending_grading}`, `tutorials {given, answers}`, `attendance {present, late, absent, excused, counted, pct, low, low_students}`, `recent_activity[]` (the teacher's own last 10 actions, sign-ins excluded). Admin, student and no token: 403 / 403 / 401.

## Substitute teachers (Session 22)
| Method | Path | Who | Notes |
|---|---|---|---|
| POST | /substitutions | admin (perm batches) | `batch_id, substitute_teacher_id, class_date` (or `session_id`, which fixes the date to that one class), optional `ends_on` (inclusive, max 92 days), `reason`. 400 for the batch's own teacher, a non-teacher, past dates; 409 if another substitute already covers some of those dates |
| GET | /substitutions | admin (perm batches) | `?batch_id=`, `?when=active\|upcoming\|past\|removed\|all`; each row has `state` |
| DELETE | /substitutions/<id> | admin (perm batches) | Ends it now; the row stays as history |
| GET | /my/substitutions | teacher | Own current and upcoming ones (no student data). Students 403, no token 401 |
A substitute gets 403 outside the dates on: attendance (read and save), `/my/batches` (the batch is then absent), `/timetable` (their dates only). Always 403 for a substitute: assignments, gradebook, materials, recordings, sessions (cancel), meet-link, attendance summary, dashboard.

## Finance: expenses (Session 23)
All admin only with area `finance` (a limited admin without it gets 403; teachers and students 403; no token 401).
| Method | Path | Notes |
|---|---|---|
| GET | /expense-categories | `[{id, name, is_active, expense_count}]` |
| POST | /expense-categories | `{name}`; same name in any case is 409 |
| PATCH | /expense-categories/<id> | `{name?, is_active?}` |
| DELETE | /expense-categories/<id> | 409 while an expense uses it (make it inactive instead) |
| GET | /expenses | `?category_id=&date_from=&date_to=&q=&page=&per_page=` returns `{items, count, total_mvr, page, per_page}`; totals cover all matches, not just the page |
| POST | /expenses | multipart or JSON: `expense_date, amount_mvr (whole, >0), category_id (active), description?`, `file?` (PDF/JPG/PNG, real content checked) |
| PATCH | /expenses/<id> | any of the fields; `file` replaces the receipt, `remove_receipt=1` removes it; returns `changed[]` |
| DELETE | /expenses/<id> | removes the row and the receipt file |
| GET | /expenses/<id>/receipt | the file as an attachment; 404 JSON when there is none; each view is logged |

## Finance: revenue and dashboard (Session 24)
Admin only, area `finance` (others 403, no token 401). Revenue = payments received, not reversed, counted on `paid_on`. Invoices are never revenue.
| Method | Path | Notes |
|---|---|---|
| GET | /finance/revenue | `?date_from=&date_to=&course_id=&batch_id=&kind=course\|tuition` returns `total_collected, payment_count, outstanding, reversed_not_counted, by_kind, by_course[], by_batch[], by_month[]`. `outstanding` ignores the dates (unpaid balance of non-void invoices in the course/batch/kind filter). 400 on a bad date, bad kind or start after end |
| GET | /finance/dashboard | `?date_from=&date_to=` (default: first of this month to today, Maldives) returns `revenue, expenses, net, outstanding_fees, months[12] {month, revenue, expenses, net}, teacher_earnings, academy_revenue` (the last two are "coming" until Session 31) |
| POST | /earnings/calculate | admin, `finance`. Body/query `month` (YYYY-MM, not in the future), `dry_run=1` previews and saves nothing. Returns `month, dry_run, share_percent, count, items[], by_teacher[], totals`. 409 if the month has an approved row. Teacher share is rounded down towards zero; academy gets the rest |
| GET | /earnings | admin, `finance`. `?month=&teacher_id=&batch_id=` returns saved rows (`collected_mvr, share_percent, teacher_share_mvr, academy_share_mvr, status`), `by_teacher`, `totals` |
| POST | /earnings/approve | admin, `finance`. `month` (must have ended), optional `expected_teacher_total` (409 if the recalculated total differs). Recalculates, then locks every row of the month |
| GET | /earnings/teachers | admin, `finance`. Per teacher `earned_mvr` (approved months), `paid_mvr`, `outstanding_mvr` |
| POST / GET | /earnings/payments | admin, `finance`. POST `teacher_id, amount_mvr, method (cash, bank_transfer, cheque, other), paid_on?, reference?, note?`; 409 above outstanding. GET `?teacher_id=` |
| POST | /earnings/payments/<id>/void | admin, `finance`. `reason` required; the row stays |
| GET | /earnings/report, /earnings/report.csv, /earnings/report.xlsx | admin, `finance`. `?from=YYYY-MM&to=YYYY-MM&teacher_id=`; exports are logged |
| GET | /my/earnings | teacher, own approved months and payments only; 403 when setting `teachers_see_earnings` is off |

## Admin dashboard (Session 25)
| Method | Path | Notes |
|---|---|---|
| GET | /admin/dashboard | Any admin (teacher/student 403, no token 401). Filters `?course_id=&batch_id=&kind=course\|tuition&teacher_id=&date_from=&date_to=` (400 on a bad value). Returns `students, teachers, batches, courses, tuition_classes, student_accounts, teacher_accounts, admissions_pending, admissions_received, classes_held, classes_cancelled, classes_upcoming, assignments, tests, submissions, graded, pending_grading, tutorials`, `filters`, `options` (course, batch and teacher lists for the dropdowns). `financial {revenue, expenses, net, outstanding}` only with area `finance`; `fees {unpaid_invoices, overdue_invoices, slips_pending}` only with area `fees`. Definitions are at the top of admindash.py. No dates = all time |

## Notifications and reminders (Session 28)
Own inbox (any signed-in role; no token 401). Times are UTC text `YYYY-MM-DD HH:MM:SS`. `link` is a tab name the page may open.
| Method | Path | Notes |
|---|---|---|
| GET | /notifications | `?unread=1&limit=30 (max 100)&before=<id>` returns `{items[{id,kind,title,body,link,created_at,read_at}], unread}`, newest first, `Cache-Control: private, no-store` |
| GET | /notifications/unread-count | `{unread}` |
| POST | /notifications/:id/read | Own only (someone else's or missing: 404). Repeating is fine. Returns `{ok, unread}` |
| POST | /notifications/read-all | `{ok, marked, unread: 0}` |
| POST | /announcements | Admin, area `classroom`. `{title (max 100), message (max 500, optional), audience: batch\|students\|teachers\|everyone, batch_id}`. `batch` = that batch's active students plus its teacher. 201 `{sent}`; 400 bad input, 404 unknown batch, 409 nobody there or notifications off |
| POST | /notifications/run | Admin, area `settings`. `?dry_run=1` is the DEFAULT (counts only, nothing kept); `dry_run=0` runs the reminders now. Returns `{dry_run, date, fee_due_soon, fee_overdue, assignment_due, admin_digest, removed_old, skipped}` |
| GET | /notifications/status | Admin, area `settings`: `{enabled, last_run, cron_secret_set, fee_days_before, overdue_every_days, assignment_days_before, unread_total}` |
| GET, POST | /cron/reminders | `Authorization: Bearer <CRON_SECRET>` only (never in the URL; 401 otherwise, also when no secret is set). Runs for real. Registered in vercel.json at 02:30 UTC |

Notification kinds: `slip_uploaded` (admins with fees), `slip_verified`, `slip_rejected`, `class_cancelled`, `class_reinstated`, `substitute_assigned`, `substitute_for_you`, `substitute_class`, `substitute_removed`, `assignment_new`, `grade`, `announcement`, `fee_due_soon`, `fee_overdue`, `assignment_due`, `admin_overdue`, `admin_slips`. New settings: `notify_enabled`, `remind_fee_days_before` (3), `remind_overdue_every_days` (7), `remind_assignment_days_before` (1); 0 turns a reminder off.

## WhatsApp click-to-chat (Session 29)
Admin only (teacher/student 403, no token 401). Nothing is sent by the server; it prepares links and remembers what was opened. Responses are `private, no-store` (phone numbers).
| Method | Path | Notes |
|---|---|---|
| POST | /whatsapp/prepare | `{audience: student\|batch\|students\|teachers\|everyone, student_id, batch_id, message (max 1000), guardians}`. Placeholders `{name} {student} {academy}`. Returns `{items[{user_id, name, to: student\|teacher\|guardian, phone, url, sent_today}], missing[{user_id, name, to}], count}`. `url` is `https://wa.me/<number>?text=...` (7-digit Maldives numbers get 960). 403 without `student_information` (students, guardians) or `teacher_information` (teachers); a batch includes its teacher only with the latter. At most 500 chats (400) |
| POST | /whatsapp/sent | `{user_id, to, preview}` logs that the chat was opened (`wa_log`, audit `whatsapp_sent`); 201. 400 bad `to`/missing id, 404 person not found or wrong role |

## Who can call what (Session 32)

Generated from the `@auth` rules and checked by `tests/test_session32.py`, which fails if a route is added without a decision. `Area` is the permission an admin needs (a limited admin without it gets 403); `-` means the route checks inside. Teachers, students and substitutes are further limited to their own batches and records inside each route (also tested). No token gives 401 on every route below.

| Method | Path | Roles | Area |
|---|---|---|---|
| GET | `/api/admin/dashboard` | admin | - |
| POST | `/api/announcements` | admin | classroom |
| GET | `/api/applications` | admin | admissions |
| GET | `/api/applications/<int:aid>` | admin | admissions |
| PATCH | `/api/applications/<int:aid>` | admin | admissions |
| POST | `/api/applications/<int:aid>/approve` | admin | admissions |
| GET | `/api/applications/<int:aid>/file/<which>` | admin | admissions |
| DELETE | `/api/applications/<int:aid>/files` | admin | admissions |
| POST | `/api/applications/<int:aid>/reject` | admin | admissions |
| POST | `/api/applications/<int:aid>/waitlist` | admin | admissions |
| GET | `/api/assignments` | any signed-in role | student: assignments, teacher: classroom, admin: classroom |
| DELETE | `/api/assignments/<int:aid>` | admin, teacher | classroom |
| PATCH | `/api/assignments/<int:aid>` | admin, teacher | classroom |
| GET | `/api/assignments/<int:aid>/attachment` | any signed-in role | student: assignments, teacher: classroom, admin: classroom |
| POST | `/api/assignments/<int:aid>/grades` | admin, teacher | classroom |
| GET | `/api/assignments/<int:aid>/submissions` | admin, teacher | classroom |
| POST | `/api/assignments/<int:aid>/submit` | student | assignments |
| GET | `/api/audit` | admin | audit |
| GET | `/api/audit.csv` | admin | audit |
| GET | `/api/audit/actions` | admin | audit |
| GET | `/api/audit/summary` | admin | audit |
| POST | `/api/auth/change-password` | any signed-in role | - |
| POST | `/api/auth/logout` | any signed-in role | - |
| GET | `/api/auth/me` | any signed-in role | - |
| GET | `/api/batches` | any signed-in role | - |
| POST | `/api/batches` | admin | batches |
| DELETE | `/api/batches/<int:bid>` | admin | batches |
| PATCH | `/api/batches/<int:bid>` | admin | batches |
| POST | `/api/batches/<int:bid>/assignments` | admin, teacher | classroom |
| GET | `/api/batches/<int:bid>/attendance` | admin, teacher | classroom |
| POST | `/api/batches/<int:bid>/attendance` | admin, teacher | classroom |
| GET | `/api/batches/<int:bid>/attendance/summary` | admin, teacher | classroom |
| GET | `/api/batches/<int:bid>/gradebook` | admin, teacher | classroom |
| POST | `/api/batches/<int:bid>/materials` | admin, teacher | classroom |
| PUT | `/api/batches/<int:bid>/meet-link` | admin, teacher | class_links |
| POST | `/api/batches/<int:bid>/recordings` | admin, teacher | add_recordings |
| POST | `/api/batches/<int:bid>/sessions` | admin, teacher | classroom |
| GET | `/api/batches/<int:bid>/students` | admin, teacher | - |
| GET | `/api/courses` | any signed-in role | - |
| POST | `/api/courses` | admin | courses |
| DELETE | `/api/courses/<int:cid>` | admin | courses |
| PATCH | `/api/courses/<int:cid>` | admin | courses |
| GET | `/api/dashboard` | admin | - |
| GET | `/api/discounts` | admin | fees |
| POST | `/api/discounts` | admin | fees |
| DELETE | `/api/discounts/<int:did>` | admin | fees |
| GET | `/api/earnings` | admin | finance |
| POST | `/api/earnings/approve` | admin | finance |
| POST | `/api/earnings/calculate` | admin | finance |
| GET | `/api/earnings/payments` | admin | finance |
| POST | `/api/earnings/payments` | admin | finance |
| POST | `/api/earnings/payments/<int:pid>/void` | admin | finance |
| GET | `/api/earnings/report` | admin | finance |
| GET | `/api/earnings/report.csv` | admin | finance |
| GET | `/api/earnings/report.xlsx` | admin | finance |
| GET | `/api/earnings/teachers` | admin | finance |
| GET | `/api/enrollment-events` | admin | enrollments |
| GET | `/api/enrollment-events.csv` | admin | enrollments |
| GET | `/api/enrollments` | any signed-in role | - |
| POST | `/api/enrollments` | admin | enrollments |
| DELETE | `/api/enrollments/<int:eid>` | admin | enrollments |
| PATCH | `/api/enrollments/<int:eid>` | admin | enrollments |
| POST | `/api/enrollments/<int:eid>/void-open-invoices` | admin | fees |
| GET | `/api/expense-categories` | admin | finance |
| POST | `/api/expense-categories` | admin | finance |
| DELETE | `/api/expense-categories/<int:kid>` | admin | finance |
| PATCH | `/api/expense-categories/<int:kid>` | admin | finance |
| GET | `/api/expenses` | admin | finance |
| POST | `/api/expenses` | admin | finance |
| DELETE | `/api/expenses/<int:eid>` | admin | finance |
| PATCH | `/api/expenses/<int:eid>` | admin | finance |
| GET | `/api/expenses/<int:eid>/receipt` | admin | finance |
| GET | `/api/families` | admin | fees |
| POST | `/api/families` | admin | fees |
| PATCH | `/api/families/<int:fid>` | admin | fees |
| POST | `/api/families/<int:fid>/members` | admin | fees |
| DELETE | `/api/families/<int:fid>/members/<int:sid>` | admin | fees |
| PATCH | `/api/families/<int:fid>/members/<int:sid>` | admin | fees |
| GET | `/api/fees/overdue` | admin | fees |
| GET | `/api/fees/payment-report` | admin | fees |
| GET | `/api/fees/payment-report.csv` | admin | fees |
| GET | `/api/fees/payment-report.xlsx` | admin | fees |
| GET | `/api/fees/report` | admin | fees |
| GET | `/api/fees/report.csv` | admin | fees |
| GET | `/api/fees/student-history/<int:sid>` | admin | fees |
| GET | `/api/finance/dashboard` | admin | finance |
| GET | `/api/finance/revenue` | admin | finance |
| POST | `/api/import/enrolments` | admin | enrollments |
| POST | `/api/import/students` | admin | people |
| POST | `/api/import/teachers` | admin | people |
| GET | `/api/invoices` | admin | fees |
| GET | `/api/invoices/<int:iid>` | admin, student | fees |
| POST | `/api/invoices/<int:iid>/discount` | admin | fees |
| GET | `/api/invoices/<int:iid>/invoice.pdf` | admin | fees |
| POST | `/api/invoices/<int:iid>/reminders` | admin | fees |
| POST | `/api/invoices/<int:iid>/reminders/email` | admin | fees |
| POST | `/api/invoices/<int:iid>/reopen` | admin | fees |
| POST | `/api/invoices/<int:iid>/slips` | student | fees |
| POST | `/api/invoices/<int:iid>/void` | admin | fees |
| POST | `/api/invoices/<int:iid>/waive` | admin | fees |
| POST | `/api/invoices/catch-up` | admin | fees |
| POST | `/api/invoices/generate` | admin | fees |
| GET | `/api/materials` | any signed-in role | student: materials, teacher: classroom, admin: classroom |
| DELETE | `/api/materials/<int:mid>` | admin, teacher | classroom |
| GET | `/api/materials/<int:mid>/file` | any signed-in role | student: materials, teacher: classroom, admin: classroom |
| GET | `/api/my/attendance` | student | progress |
| GET | `/api/my/batches` | student, teacher | - |
| GET | `/api/my/earnings` | teacher | - |
| GET | `/api/my/fees` | student | fees |
| GET | `/api/my/fees/summary` | student | fees |
| GET | `/api/my/given-grades` | teacher | classroom |
| GET | `/api/my/grades` | student | progress |
| GET | `/api/my/home` | student, teacher | - |
| GET | `/api/my/information` | student, teacher | - |
| GET | `/api/my/substitutions` | teacher | - |
| GET | `/api/notifications` | any signed-in role | - |
| POST | `/api/notifications/<int:nid>/read` | any signed-in role | - |
| POST | `/api/notifications/read-all` | any signed-in role | - |
| POST | `/api/notifications/run` | admin | settings |
| GET | `/api/notifications/status` | admin | settings |
| GET | `/api/notifications/unread-count` | any signed-in role | - |
| GET | `/api/payments` | admin | fees |
| POST | `/api/payments` | admin | fees |
| GET | `/api/payments/<int:pid>/receipt.pdf` | admin, student | fees |
| POST | `/api/payments/<int:pid>/reverse` | admin | fees |
| GET | `/api/recordings` | any signed-in role | student: recordings, teacher: classroom, admin: classroom |
| DELETE | `/api/recordings/<int:rid>` | admin, teacher | add_recordings |
| GET | `/api/settings` | admin | settings |
| PUT | `/api/settings` | admin | settings |
| GET | `/api/settings/schema` | admin | settings |
| GET | `/api/slips` | admin | fees |
| GET | `/api/slips/<int:sid>/file` | admin, student | fees |
| POST | `/api/slips/<int:sid>/reject` | admin | fees |
| POST | `/api/slips/<int:sid>/verify` | admin | fees |
| GET | `/api/student-information` | admin | student_information |
| GET | `/api/student-information/<int:uid>` | admin | student_information |
| GET | `/api/student-information/enrolments.csv` | admin | student_information |
| GET | `/api/student-information/enrolments.xlsx` | admin | student_information |
| GET | `/api/student-information/export.csv` | admin | student_information |
| GET | `/api/student-information/export.xlsx` | admin | student_information |
| GET | `/api/submissions/<int:sid>/file` | any signed-in role | student: assignments, teacher: classroom, admin: classroom |
| GET | `/api/substitutions` | admin | batches |
| POST | `/api/substitutions` | admin | batches |
| DELETE | `/api/substitutions/<int:sid>` | admin | batches |
| GET | `/api/teacher-information` | admin | teacher_information |
| GET | `/api/teacher-information/<int:uid>` | admin | teacher_information |
| GET | `/api/teacher-information/export.csv` | admin | teacher_information |
| GET | `/api/teacher-information/export.xlsx` | admin | teacher_information |
| GET | `/api/teacher/dashboard` | teacher | classroom |
| GET | `/api/timetable` | any signed-in role | - |
| GET | `/api/tutorial-submissions/<int:sid>/file` | any signed-in role | student: submit_tutorial_work, teacher: create_tutorials, admin: create_tutorials |
| GET | `/api/tutorials` | any signed-in role | tutorials |
| POST | `/api/tutorials` | admin, teacher | create_tutorials |
| DELETE | `/api/tutorials/<int:tid>` | admin, teacher | tutorials |
| GET | `/api/tutorials/<int:tid>` | any signed-in role | tutorials |
| GET | `/api/tutorials/<int:tid>/file` | any signed-in role | tutorials |
| GET | `/api/tutorials/<int:tid>/submission` | student | submit_tutorial_work |
| POST | `/api/tutorials/<int:tid>/submission` | student | submit_tutorial_work |
| GET | `/api/tutorials/<int:tid>/submissions` | admin, teacher | create_tutorials |
| GET | `/api/users` | admin | - |
| POST | `/api/users` | admin | people |
| DELETE | `/api/users/<int:uid>` | admin | people |
| GET | `/api/users/<int:uid>` | admin | people |
| PATCH | `/api/users/<int:uid>` | admin | people |
| POST | `/api/users/<int:uid>/reset-password` | admin | people |
| POST | `/api/whatsapp/prepare` | admin | - |
| POST | `/api/whatsapp/sent` | admin | - |

Public (no sign-in, by decision): `/api/auth/login`, `/api/health`, `/api/public/apply`, `/api/public/apply/status`, `/api/public/batches`, `/api/public/courses`, `/api/public/info`, the static pages, and `/api/cron/generate-invoices` and `/api/cron/reminders` (these need `Authorization: Bearer <CRON_SECRET>`; the secret is never accepted in the URL, and without `CRON_SECRET` they are closed).

Changed in Session 32: `GET /api/users` needs the People area for full details; an admin with batches, enrolments, fees, classroom or settings gets names only (`id, full_name, role, is_active`); any other admin gets 403. `GET /api/enrollments` and `GET /api/batches/<id>/students` (admin) need one of the same areas. `GET /api/dashboard` leaves out the money figures unless the admin has the Fees area.
