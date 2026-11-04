# API (Phases 1-4). Base path /api. Auth header: `Authorization: Bearer <token>`.
| Method | Path | Who | Purpose |
|---|---|---|---|
| GET | /health | public | Health check |
| GET | /public/courses | public | Open and upcoming courses for the website |
| POST | /auth/login | public | `{email,password}` returns `{token,user}` (rate-limited) |
| GET | /auth/me | any | Current user |
| POST | /auth/change-password | any | `{current_password,new_password}` |
| PATCH | /auth/language | any | `{lang:"en"or"dv"}` |
| GET, POST | /users | admin | List (`?role=`), create admin/teacher/student |
| PATCH | /users/:id | admin | Name, phone, active flag, password reset |
| GET | /courses | any | List |
| POST, PATCH | /courses, /courses/:id | admin | Create, update |
| GET | /batches | any | Admin all, teacher own, student enrolled |
| POST, PATCH | /batches, /batches/:id | admin | Create, update (Meet link, teacher, capacity) |
| GET | /batches/:id/students | admin, own teacher | Roster |
| GET | /enrollments | admin, student (own) | List |
| POST | /enrollments | admin | `{student_id,batch_id}`; waitlists when full |
| PATCH | /enrollments/:id | admin | `{status}` or `{transfer_to_batch_id}` |
| GET | /dashboard | admin | Counts |
| GET, PUT | /settings | admin | Academy info and bank details |
| GET | /audit | admin | Last 200 actions |
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
| POST | /invoices/generate | admin | `{month}` creates the missing invoices for active enrollments; returns `{created, skipped, skipped_total}`. Safe to repeat |
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
| GET | /dashboard | admin | Now also `unpaid_invoices`, `overdue_invoices`, `slips_pending`, `month_collection_mvr` |
| GET, PUT | /settings | admin | New keys: `invoice_due_day`, `first_invoice_mode`, `first_invoice_grace_days`, `receipt_prefix`, `reminder_template_en`, `reminder_template_dv` |
