-- Baleegh Academy Portal schema. Written in SQLite style; dbx.py translates it for PostgreSQL automatically
-- (AUTOINCREMENT -> identity column, datetime('now') -> UTC text, REAL -> DOUBLE PRECISION). Dates and times are TEXT on both.
-- Keep new tables in this file with `CREATE TABLE IF NOT EXISTS`; a table whose first column is `id INTEGER PRIMARY KEY AUTOINCREMENT`
-- gets its new id back after INSERT on both engines. The tables are created again whenever this file changes.
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  full_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','teacher','student')),
  phone TEXT,
  lang TEXT NOT NULL DEFAULT 'en' CHECK (lang IN ('en','dv')),
  is_active INTEGER NOT NULL DEFAULT 1,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  login_id TEXT,               -- Session 11: ID used to sign in (student/teacher code, admins BAL/A/NNN); unique index made in dbx.init_schema
  permissions TEXT,            -- admins only: NULL = full admin, else comma list of allowed areas
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS students (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  date_of_birth TEXT,
  grade TEXT,
  island TEXT,
  guardian_name TEXT,
  guardian_relationship TEXT,
  guardian_phone TEXT,
  student_code TEXT            -- permanent ID, BAL/<COURSE CODE>/<NNN> (Session 10); unique index made in dbx.init_schema
);
CREATE TABLE IF NOT EXISTS teachers (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  bio TEXT,
  teacher_code TEXT            -- BAL/T/<NNN>
);
CREATE TABLE IF NOT EXISTS courses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  level TEXT,
  description TEXT,
  textbook TEXT,
  monthly_fee_mvr INTEGER NOT NULL DEFAULT 0 CHECK (monthly_fee_mvr >= 0),
  registration_fee_mvr INTEGER NOT NULL DEFAULT 0 CHECK (registration_fee_mvr >= 0),   -- Session 31: one-time, charged at first enrolment in the course
  days_per_week INTEGER,
  minutes_per_class INTEGER,
  status TEXT NOT NULL DEFAULT 'upcoming' CHECK (status IN ('open','upcoming','closed')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  kind TEXT NOT NULL DEFAULT 'course' CHECK (kind IN ('course','tuition')),   -- Session 10
  code TEXT,                                                                   -- e.g. AL1, G8M; unique
  is_active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS batches (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  course_id INTEGER NOT NULL REFERENCES courses(id),
  code TEXT NOT NULL,
  days TEXT,                 -- e.g. 'Sun,Tue,Thu'
  start_time TEXT,           -- 'HH:MM' 24h, Maldives time
  start_date TEXT,
  capacity INTEGER NOT NULL DEFAULT 20,
  teacher_id INTEGER REFERENCES users(id),
  meet_link TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','running','closed')),
  UNIQUE (course_id, code)
);
CREATE TABLE IF NOT EXISTS enrollments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL REFERENCES users(id),
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','waitlist','dropped','completed')),
  enrolled_at TEXT NOT NULL DEFAULT (datetime('now')),
  enrol_code TEXT,             -- BAL/<COURSE CODE>/E<NNN> (Session 10)
  UNIQUE (student_id, batch_id)
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  action TEXT NOT NULL,
  entity TEXT,
  entity_id INTEGER,
  detail TEXT,
  at TEXT NOT NULL DEFAULT (datetime('now')),
  user_role TEXT,
  login_id TEXT,
  course_id INTEGER,
  batch_id INTEGER,
  old_value TEXT,
  new_value TEXT,
  ip TEXT
);
-- Session 21: empty except for the moment the one-off backfill runs; the audit_log triggers read it
CREATE TABLE IF NOT EXISTS audit_unlock (flag INTEGER NOT NULL);
-- Session 22: a substitute teacher for one class or a date range. batches.teacher_id never changes.
-- Access runs from class_date to COALESCE(ends_on, class_date), both inclusive (Maldives dates); removed_at ends it early.
CREATE TABLE IF NOT EXISTS substitutions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  class_date TEXT NOT NULL,
  session_id INTEGER REFERENCES sessions(id),
  original_teacher_id INTEGER REFERENCES users(id),
  substitute_teacher_id INTEGER NOT NULL REFERENCES users(id),
  reason TEXT,
  created_by INTEGER REFERENCES users(id),
  ends_on TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  removed_at TEXT,
  removed_by INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_subs_teacher ON substitutions(substitute_teacher_id);
CREATE INDEX IF NOT EXISTS idx_subs_batch ON substitutions(batch_id);
CREATE INDEX IF NOT EXISTS idx_batches_teacher ON batches(teacher_id);
CREATE INDEX IF NOT EXISTS idx_enroll_student ON enrollments(student_id);
CREATE INDEX IF NOT EXISTS idx_enroll_batch ON enrollments(batch_id);

-- Phase 2: admissions
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ref TEXT NOT NULL UNIQUE,
  full_name TEXT NOT NULL,
  date_of_birth TEXT NOT NULL,
  is_minor INTEGER NOT NULL DEFAULT 0,
  grade TEXT,
  phone TEXT NOT NULL,
  email TEXT NOT NULL,
  island TEXT,
  course_id INTEGER NOT NULL REFERENCES courses(id),
  batch_id INTEGER REFERENCES batches(id),
  id_file TEXT,
  guardian_name TEXT,
  guardian_relationship TEXT,
  guardian_phone TEXT,
  guardian_id_file TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','approved','rejected','waitlist')),
  reject_reason TEXT,
  student_user_id INTEGER REFERENCES users(id),
  decided_by INTEGER REFERENCES users(id),
  decided_at TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_app_status ON applications(status);

-- Phase 3: learning tools
-- sessions: one row per dated class that is held, cancelled or added as an extra. The normal weekly pattern comes from batches.days + start_time.
CREATE TABLE IF NOT EXISTS sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  session_date TEXT NOT NULL,          -- YYYY-MM-DD, Maldives date
  start_time TEXT NOT NULL,            -- HH:MM, Maldives time
  status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','held','cancelled')),
  topic TEXT,
  note TEXT,
  meet_link TEXT,                      -- one-off link for this class only (Session 4); NULL = use the batch's link
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (batch_id, session_date, start_time)
);
CREATE TABLE IF NOT EXISTS attendance (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES users(id),
  status TEXT NOT NULL CHECK (status IN ('present','late','absent','excused')),
  note TEXT,
  marked_by INTEGER REFERENCES users(id),
  marked_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (session_id, student_id)
);
CREATE TABLE IF NOT EXISTS assignments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  title TEXT NOT NULL,
  description TEXT,
  kind TEXT NOT NULL DEFAULT 'assignment' CHECK (kind IN ('assignment','test')),  -- tests have no student submission; teacher enters marks
  due_date TEXT,
  max_points INTEGER NOT NULL DEFAULT 100 CHECK (max_points > 0),
  attachment TEXT,        -- optional file from the teacher (worksheet, instructions); stored name
  attachment_name TEXT,   -- the name the teacher gave it, shown on download
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
-- submissions doubles as the grade record: a row with grade but no submitted_at is a mark entered by the teacher.
CREATE TABLE IF NOT EXISTS submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  assignment_id INTEGER NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
  student_id INTEGER NOT NULL REFERENCES users(id),
  text_answer TEXT,
  file TEXT,
  file_name TEXT,
  submitted_at TEXT,
  is_late INTEGER NOT NULL DEFAULT 0,
  grade REAL,
  feedback TEXT,
  graded_by INTEGER REFERENCES users(id),
  graded_at TEXT,
  UNIQUE (assignment_id, student_id)
);
CREATE TABLE IF NOT EXISTS materials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  title TEXT NOT NULL,
  description TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('file','link')),
  file TEXT,
  file_name TEXT,
  url TEXT,
  uploaded_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sessions_batch ON sessions(batch_id, session_date);
CREATE INDEX IF NOT EXISTS idx_att_student ON attendance(student_id);
CREATE INDEX IF NOT EXISTS idx_assign_batch ON assignments(batch_id);
CREATE INDEX IF NOT EXISTS idx_sub_student ON submissions(student_id);
CREATE INDEX IF NOT EXISTS idx_mat_batch ON materials(batch_id);

-- Session 5: class recordings. A teacher adds a Google Drive link with a title and the class date, per batch. The video stays in Drive.
CREATE TABLE IF NOT EXISTS recordings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  recorded_on TEXT NOT NULL,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rec_batch ON recordings(batch_id, recorded_on);

-- Phase 5 (started): tutorials library. Anyone signed in can read and post; each post can have written text, a file, a link, or any mix.
-- Admins can delete any post; everyone else only their own. Every post and delete is written to audit_log.
CREATE TABLE IF NOT EXISTS tutorials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL,
  body TEXT,
  course_id INTEGER REFERENCES courses(id),
  file TEXT,
  file_name TEXT,
  url TEXT,
  uploaded_by INTEGER NOT NULL REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  CHECK (body IS NOT NULL OR file IS NOT NULL OR url IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_tut_course ON tutorials(course_id);

-- Session 2: only teachers and admins post tutorials (older student posts stay, read-only). Students send one answer per tutorial:
-- written text, a file, or both. Sending again replaces the earlier answer.
CREATE TABLE IF NOT EXISTS tutorial_submissions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tutorial_id INTEGER NOT NULL REFERENCES tutorials(id),
  student_id INTEGER NOT NULL REFERENCES users(id),
  text_answer TEXT,
  file TEXT,
  file_name TEXT,
  submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (tutorial_id, student_id),
  CHECK (text_answer IS NOT NULL OR file IS NOT NULL)
);
CREATE INDEX IF NOT EXISTS idx_tutsub_student ON tutorial_submissions(student_id);

-- Phase 4: fees and payments. All money is whole MVR in INTEGER columns (never floats).
-- Postgres: the only SQLite-specific part is AUTOINCREMENT (see the note at the top of this file); these tables get created_at from the app, so they have no datetime('now') defaults.
-- The invoice number is derived, not stored: INV-<YYYYMM>-<id padded to 4>.
CREATE TABLE IF NOT EXISTS families (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  concession_kind TEXT CHECK (concession_kind IN ('fixed','percent')),
  concession_value INTEGER NOT NULL DEFAULT 0 CHECK (concession_value >= 0),   -- entered by the admin; no default rate is assumed
  concession_reason TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS family_members (
  student_id INTEGER PRIMARY KEY REFERENCES users(id),        -- a student belongs to at most one family
  family_id INTEGER NOT NULL REFERENCES families(id) ON DELETE CASCADE,
  concession_applies INTEGER NOT NULL DEFAULT 1                -- admin chooses which children get the concession
);
CREATE TABLE IF NOT EXISTS invoices (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  enrollment_id INTEGER NOT NULL REFERENCES enrollments(id),
  student_id INTEGER NOT NULL REFERENCES users(id),
  course_id INTEGER NOT NULL REFERENCES courses(id),           -- snapshot, for reports
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  period TEXT NOT NULL CHECK (length(period) = 7),             -- 'YYYY-MM'
  description TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'monthly',                         -- Session 31: monthly or registration (period is then 'REG-FEE'; never part of teacher earnings)
  amount_mvr INTEGER NOT NULL CHECK (amount_mvr >= 0),         -- course fee at generation time
  discount_mvr INTEGER NOT NULL DEFAULT 0 CHECK (discount_mvr >= 0),
  amount_due_mvr INTEGER NOT NULL CHECK (amount_due_mvr >= 0),
  paid_mvr INTEGER NOT NULL DEFAULT 0 CHECK (paid_mvr >= 0),   -- sum of payments not reversed (kept in step by payments.recompute)
  waived_mvr INTEGER NOT NULL DEFAULT 0 CHECK (waived_mvr >= 0),
  due_date TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'unpaid' CHECK (status IN ('unpaid','slip_submitted','paid','void','waived')),  -- 'overdue' is derived, never stored
  status_reason TEXT,                                          -- why it was voided or waived
  discount_note TEXT,
  notes TEXT,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  UNIQUE (enrollment_id, period),
  CHECK (discount_mvr <= amount_mvr),
  CHECK (amount_due_mvr = amount_mvr - discount_mvr)
);
CREATE TABLE IF NOT EXISTS discounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  scope TEXT NOT NULL CHECK (scope IN ('enrollment','invoice')),   -- enrollment = recurring, invoice = one-off
  enrollment_id INTEGER REFERENCES enrollments(id),
  invoice_id INTEGER REFERENCES invoices(id),
  kind TEXT NOT NULL CHECK (kind IN ('fixed','percent')),
  value INTEGER NOT NULL CHECK (value > 0),
  amount_mvr INTEGER,                                          -- invoice scope: MVR actually taken off
  reason TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  created_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  ended_by INTEGER REFERENCES users(id),
  ended_at TEXT,
  CHECK ((scope = 'enrollment' AND enrollment_id IS NOT NULL) OR (scope = 'invoice' AND invoice_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS payment_slips (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL REFERENCES invoices(id),
  student_id INTEGER NOT NULL REFERENCES users(id),
  file TEXT NOT NULL,                                          -- private storage name, never a public URL
  file_name TEXT,
  file_hash TEXT NOT NULL,                                     -- sha256, to warn when the same slip is used twice
  amount_mvr INTEGER NOT NULL CHECK (amount_mvr > 0),          -- what the student says they transferred
  transfer_date TEXT NOT NULL,
  reference TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','verified','rejected','reversed')),
  reject_reason TEXT,
  reviewed_by INTEGER REFERENCES users(id),
  reviewed_at TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL REFERENCES invoices(id),
  student_id INTEGER NOT NULL REFERENCES users(id),
  amount_mvr INTEGER NOT NULL CHECK (amount_mvr > 0),
  method TEXT NOT NULL CHECK (method IN ('bank_transfer','cash','other','gateway')),   -- 'gateway' is reserved for a future online gateway
  paid_on TEXT NOT NULL,
  reference TEXT,
  note TEXT,
  slip_id INTEGER REFERENCES payment_slips(id),
  receipt_seq INTEGER NOT NULL UNIQUE,                         -- never reused, even if the payment is reversed
  receipt_no TEXT NOT NULL UNIQUE,
  recorded_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  reversed_at TEXT,
  reversed_by INTEGER REFERENCES users(id),
  reverse_reason TEXT
);
CREATE TABLE IF NOT EXISTS reminders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invoice_id INTEGER NOT NULL REFERENCES invoices(id),
  channel TEXT NOT NULL CHECK (channel IN ('whatsapp','viber','email')),
  recipient TEXT NOT NULL CHECK (recipient IN ('student','guardian')),
  sent_by INTEGER REFERENCES users(id),
  sent_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS counters (
  name TEXT PRIMARY KEY,
  value INTEGER NOT NULL
);
INSERT INTO counters(name, value) VALUES ('receipt', 0) ON CONFLICT (name) DO NOTHING;
CREATE INDEX IF NOT EXISTS idx_inv_student ON invoices(student_id);
CREATE INDEX IF NOT EXISTS idx_inv_period ON invoices(period, status);
CREATE INDEX IF NOT EXISTS idx_inv_due ON invoices(due_date);
CREATE INDEX IF NOT EXISTS idx_pay_invoice ON payments(invoice_id);
CREATE INDEX IF NOT EXISTS idx_pay_paid_on ON payments(paid_on);
CREATE INDEX IF NOT EXISTS idx_slip_status ON payment_slips(status);
CREATE INDEX IF NOT EXISTS idx_slip_invoice ON payment_slips(invoice_id);
CREATE INDEX IF NOT EXISTS idx_slip_hash ON payment_slips(file_hash);
CREATE INDEX IF NOT EXISTS idx_rem_invoice ON reminders(invoice_id);
CREATE INDEX IF NOT EXISTS idx_disc_enroll ON discounts(enrollment_id);

-- Session 13: one row for every transfer between batches and every withdrawal (enrolment set to 'dropped').
-- History only: attendance, submissions and grades are never touched. Nothing in the app updates or deletes these rows.
CREATE TABLE IF NOT EXISTS enrollment_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  student_id INTEGER NOT NULL REFERENCES users(id),
  from_batch_id INTEGER REFERENCES batches(id),
  to_batch_id INTEGER REFERENCES batches(id),
  kind TEXT NOT NULL CHECK (kind IN ('transfer','withdrawal')),
  effective_date TEXT,          -- YYYY-MM-DD; NULL only for old rows whose date is unknown
  reason TEXT,
  by_user INTEGER REFERENCES users(id),
  at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_enrol_events_student ON enrollment_events(student_id);
CREATE INDEX IF NOT EXISTS idx_enrol_events_date ON enrollment_events(effective_date);

-- Session 23: expenses. Whole MVR amounts (same as payments). Receipt files live in the private "receipts" storage area.
CREATE TABLE IF NOT EXISTS expense_categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS expenses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  expense_date TEXT NOT NULL,
  amount_mvr INTEGER NOT NULL CHECK (amount_mvr > 0),
  category_id INTEGER NOT NULL REFERENCES expense_categories(id),
  description TEXT,
  receipt_file TEXT,
  receipt_name TEXT,
  entered_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_by INTEGER REFERENCES users(id),
  updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(expense_date);
CREATE INDEX IF NOT EXISTS idx_expenses_cat ON expenses(category_id);

-- Session 28: in-app notifications. One row per person per message. dedupe_key (optional) makes a scheduled reminder fire once:
-- the unique index ignores the second insert for the same person and key. Rows with no key (events) are never deduplicated.
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT,
  link TEXT,
  dedupe_key TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  read_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_notif_user ON notifications(user_id, id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_notif_dedupe ON notifications(user_id, dedupe_key);

-- Session 29: WhatsApp click-to-chat log. One row each time an admin opened a prepared message for a person (so nobody is messaged twice by accident).
CREATE TABLE IF NOT EXISTS wa_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL REFERENCES users(id),
  to_kind TEXT NOT NULL,          -- student, teacher or guardian
  phone TEXT,
  preview TEXT,                   -- first 80 characters of the message
  sent_by INTEGER REFERENCES users(id),
  sent_at TEXT NOT NULL           -- Maldives time, ISO
);
CREATE INDEX IF NOT EXISTS idx_wa_log_user ON wa_log(user_id, sent_at);

-- Session 30: teacher earnings, one row per batch and month, worked out from real payments (never from invoices).
-- status 'draft' can be recalculated; 'approved' (Session 31) is locked and never touched by a re-run.
CREATE TABLE IF NOT EXISTS teacher_earnings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER REFERENCES users(id),     -- the batch's teacher when it was calculated (NULL = batch had no teacher)
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  period TEXT NOT NULL,                         -- YYYY-MM
  collected_mvr INTEGER NOT NULL DEFAULT 0,     -- paid in the month minus payments reversed in the month (can be negative)
  share_percent INTEGER NOT NULL DEFAULT 50,    -- teacher's percent used for this row
  teacher_share_mvr INTEGER NOT NULL DEFAULT 0,
  academy_share_mvr INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft',         -- draft | approved
  calculated_at TEXT,
  calculated_by INTEGER REFERENCES users(id),
  approved_at TEXT,
  approved_by INTEGER REFERENCES users(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_earn_batch_period ON teacher_earnings(batch_id, period);
CREATE INDEX IF NOT EXISTS idx_earn_teacher ON teacher_earnings(teacher_id, period);

-- Session 31: payments made to teachers out of approved earnings.
CREATE TABLE IF NOT EXISTS teacher_payments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER NOT NULL REFERENCES users(id),
  amount_mvr INTEGER NOT NULL CHECK (amount_mvr > 0),
  paid_on TEXT NOT NULL,
  method TEXT NOT NULL,
  reference TEXT,
  note TEXT,
  recorded_by INTEGER REFERENCES users(id),
  created_at TEXT NOT NULL,
  voided_at TEXT,
  voided_by INTEGER REFERENCES users(id),
  void_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_tpay_teacher ON teacher_payments(teacher_id, paid_on);

-- v0.8.34: uploaded files kept inside the database. Used on Vercel when no bucket is set (its disk loses files) or with FILE_STORAGE=db.
-- area: ids | learning | slips | receipts; name: the generated stored name the other tables point to. BLOB becomes BYTEA on PostgreSQL.
CREATE TABLE IF NOT EXISTS stored_files (
  area TEXT NOT NULL,
  name TEXT NOT NULL,
  content_type TEXT,
  size INTEGER NOT NULL DEFAULT 0,
  data BLOB NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (area, name)
);

-- v0.8.35: "Forgot password" requests. The portal sends no email, so the request goes to admins with the People area, who reset the
-- password and send it by WhatsApp. user_id is NULL when nothing matched what was typed (shown to admins, never to the requester).
CREATE TABLE IF NOT EXISTS password_help (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER REFERENCES users(id),
  login_text TEXT NOT NULL,
  contact TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','done','dismissed')),
  ip TEXT,
  created_at TEXT NOT NULL,
  handled_by INTEGER REFERENCES users(id),
  handled_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_password_help_status ON password_help(status, user_id);
