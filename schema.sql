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
  guardian_phone TEXT
);
CREATE TABLE IF NOT EXISTS teachers (
  user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  bio TEXT
);
CREATE TABLE IF NOT EXISTS courses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  level TEXT,
  description TEXT,
  textbook TEXT,
  monthly_fee_mvr INTEGER NOT NULL DEFAULT 0 CHECK (monthly_fee_mvr >= 0),
  days_per_week INTEGER,
  minutes_per_class INTEGER,
  status TEXT NOT NULL DEFAULT 'upcoming' CHECK (status IN ('open','upcoming','closed')),
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
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
  at TEXT NOT NULL DEFAULT (datetime('now'))
);
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
