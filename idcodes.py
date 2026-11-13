"""ID codes (Session 10).

  student_code  BAL/<COURSE CODE>/<NNN>     permanent, from the course of the student's first enrolment (BAL/STU/NNN if none)
  teacher_code  BAL/T/<NNN>
  enrol_code    BAL/<COURSE CODE>/E<NNN>    one per enrolment row; the "E" keeps it apart from the student's own ID
  courses.code  2 to 8 capitals or digits (AL1, G8M), unique across courses and tuition classes

Numbers come from the `counters` table (one counter per course code and kind), so they are never reused and two requests at the same moment
cannot get the same number: the UPDATE locks the counter row until the caller commits, and a rolled-back request gives its number back.

fill_missing() is both the one-off backfill of older databases and the "give new rows a code" step that the create routes call before they commit.
It only ever fills empty codes; it never changes a code that exists.
"""
import re

ORG = "BAL"
NO_COURSE = "STU"
TEACHER = "T"
CODE_RE = re.compile(r"^[A-Z0-9]{2,8}$")
_STOP = {"for", "of", "and", "the", "to", "in", "a", "an"}
KINDS = ("course", "tuition")


def norm_course_code(v):
    """'al1 ' -> 'AL1'; None when it is not 2 to 8 letters or digits."""
    s = str(v or "").strip().upper()
    return s if CODE_RE.match(s) else None


def derive_course_code(name, level=None, taken=(), fallback="C"):
    """'Grade 8 Mathematics' -> G8M, 'Arabic' + 'Level 1' -> AL1. Words with digits are kept whole, other words give their first letter.
    Adds 2, 3, ... when the code is taken. Names without Latin letters or digits use the fallback."""
    def initials(text):
        out = ""
        for w in re.findall(r"[A-Za-z0-9]+", text or ""):
            if w.lower() in _STOP: continue
            out += w.upper() if any(ch.isdigit() for ch in w) else w[0].upper()
        return out
    base = (initials(name) + initials(level))[:8] or fallback
    if len(base) < 2: base += "X"
    taken, cand, n = set(taken), base, 1
    while cand in taken:
        n += 1
        cand = base[:8 - len(str(n))] + str(n)
    return cand


def next_number(conn, counter):
    """Next number of a named counter. Call inside the transaction that stores the code; the caller commits."""
    conn.execute("INSERT INTO counters(name,value) VALUES(?,0) ON CONFLICT (name) DO NOTHING", (counter,))
    conn.execute("UPDATE counters SET value=value+1 WHERE name=?", (counter,))
    return conn.execute("SELECT value FROM counters WHERE name=?", (counter,)).fetchone()[0]


def _alloc(conn, counter, make, table, column):
    while True:   # skips a number whose code was typed in by hand
        code = make(next_number(conn, counter))
        if not conn.execute(f"SELECT 1 FROM {table} WHERE {column}=?", (code,)).fetchone():
            return code


def student_code_for(conn, course_code):
    c = course_code or NO_COURSE
    return _alloc(conn, f"student:{c}", lambda n: f"{ORG}/{c}/{n:03d}", "students", "student_code")


def teacher_code_for(conn):
    return _alloc(conn, "teacher", lambda n: f"{ORG}/{TEACHER}/{n:03d}", "teachers", "teacher_code")


def admin_login_for(conn):
    return _alloc(conn, "admin", lambda n: f"{ORG}/A/{n:03d}", "users", "login_id")


def enrol_code_for(conn, course_code):
    return _alloc(conn, f"enrol:{course_code}", lambda n: f"{ORG}/{course_code}/E{n:03d}", "enrollments", "enrol_code")


def course_code_for(conn, name, level, course_id=None):
    taken = {r[0] for r in conn.execute("SELECT code FROM courses WHERE code IS NOT NULL").fetchall()}
    return derive_course_code(name, level, taken, f"C{course_id}" if course_id else "C")


# v0.8.42: {students} is "students without a code" for the migration, and "students without a code WHO HAVE AN ENROLMENT" for the create
# routes (unenrolled_students=False). Before, every student waiting for a first course made fill_missing() do its full work on every call,
# with one more query per such student: importing N students cost about N*N/2 queries, and the import timed out on the hosted database.
_ENROLLED = " AND EXISTS (SELECT 1 FROM enrollments e WHERE e.student_id=s.user_id)"
_PENDING = ("SELECT (SELECT COUNT(*) FROM courses WHERE code IS NULL), (SELECT COUNT(*) FROM teachers WHERE teacher_code IS NULL), "
            "(SELECT COUNT(*) FROM students s WHERE s.student_code IS NULL{students}), (SELECT COUNT(*) FROM enrollments WHERE enrol_code IS NULL), "
            "(SELECT COUNT(*) FROM users u WHERE u.role='student' AND NOT EXISTS (SELECT 1 FROM students s WHERE s.user_id=u.id)), "
            "(SELECT COUNT(*) FROM users u WHERE u.role='teacher' AND NOT EXISTS (SELECT 1 FROM teachers t WHERE t.user_id=u.id)), "
            "(SELECT COUNT(*) FROM users u WHERE u.login_id IS NULL AND (u.role='admin' OR EXISTS (SELECT 1 FROM students s WHERE s.user_id=u.id AND s.student_code IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM teachers t WHERE t.user_id=u.id AND t.teacher_code IS NOT NULL)))")


def assign_student_code(conn, user_id, course_id):
    """Issue the permanent ID now, from a chosen course (used when an account is created with a course). No-op if the student already has one."""
    c = conn.execute("SELECT code FROM courses WHERE id=?", (course_id,)).fetchone()
    if not c or not c["code"]: return None
    code = student_code_for(conn, c["code"])
    return code if conn.execute("UPDATE students SET student_code=? WHERE user_id=? AND student_code IS NULL", (code, user_id)).rowcount else None


def fill_missing(conn, unenrolled_students=True):
    """Give every row without a code its code. Returns a report; one query when there is nothing to do. Does not commit.
    unenrolled_students=False (what the create routes use) leaves a student who has no enrolment yet without a code, so that the first course
    they join decides it; the migration of an older database uses True and gives them BAL/STU/NNN."""
    rep = {"courses": [], "teachers": [], "students": [], "enrollments": [], "login_ids": [], "profiles_created": 0, "courses_deactivated": 0}
    pending = conn.execute(_PENDING.replace("{students}", "" if unenrolled_students else _ENROLLED)).fetchone()
    if not any(pending[i] for i in range(7)): return rep
    # people whose role row is missing (older accounts) get an empty one, so they can carry a code
    for tbl, role in (("students", "student"), ("teachers", "teacher")):
        cur = conn.execute(f"INSERT INTO {tbl}(user_id) SELECT id FROM users WHERE role='{role}' AND id NOT IN (SELECT user_id FROM {tbl})")
        rep["profiles_created"] += max(cur.rowcount, 0)
    # 1. courses first: every other code is built from them
    taken = {r[0] for r in conn.execute("SELECT code FROM courses WHERE code IS NOT NULL").fetchall()}
    for c in conn.execute("SELECT id,name,level,status FROM courses WHERE code IS NULL ORDER BY id").fetchall():
        code = derive_course_code(c["name"], c["level"], taken, f"C{c['id']}")
        taken.add(code)
        closed = c["status"] == "closed"   # first time this course gets a code = an older row: is_active follows its status
        conn.execute("UPDATE courses SET code=?, is_active=? WHERE id=? AND code IS NULL", (code, 0 if closed else 1, c["id"]))
        rep["courses"].append((c["id"], code)); rep["courses_deactivated"] += closed
    # 2. teachers
    for t in conn.execute("SELECT user_id FROM teachers WHERE teacher_code IS NULL ORDER BY user_id").fetchall():
        code = teacher_code_for(conn)
        if conn.execute("UPDATE teachers SET teacher_code=? WHERE user_id=? AND teacher_code IS NULL", (code, t["user_id"])).rowcount:
            rep["teachers"].append((t["user_id"], code))
    # 3. students: the course of their first enrolment, else BAL/STU/...
    # v0.8.42: one query for all of them (the course of the first enrolment comes with each row), and only the enrolled ones unless asked
    for s in conn.execute("SELECT s.user_id, (SELECT c.code FROM enrollments e JOIN batches b ON b.id=e.batch_id JOIN courses c ON c.id=b.course_id "
                          "WHERE e.student_id=s.user_id ORDER BY e.id LIMIT 1) AS first_course FROM students s WHERE s.student_code IS NULL"
                          + ("" if unenrolled_students else _ENROLLED) + " ORDER BY s.user_id").fetchall():
        code = student_code_for(conn, s["first_course"])
        if conn.execute("UPDATE students SET student_code=? WHERE user_id=? AND student_code IS NULL", (code, s["user_id"])).rowcount:
            rep["students"].append((s["user_id"], code))
    # 4. enrolments
    for e in conn.execute("SELECT e.id, c.code FROM enrollments e JOIN batches b ON b.id=e.batch_id JOIN courses c ON c.id=b.course_id "
                          "WHERE e.enrol_code IS NULL ORDER BY e.id").fetchall():
        code = enrol_code_for(conn, e["code"])
        if conn.execute("UPDATE enrollments SET enrol_code=? WHERE id=? AND enrol_code IS NULL", (code, e["id"])).rowcount:
            rep["enrollments"].append((e["id"], code))
    # 5. login IDs (Session 11): a student or teacher signs in with their own code, an admin gets BAL/A/NNN. Someone with no code yet gets one later.
    for u in conn.execute("SELECT u.id, u.role, s.student_code, t.teacher_code FROM users u LEFT JOIN students s ON s.user_id=u.id LEFT JOIN teachers t ON t.user_id=u.id "
                          "WHERE u.login_id IS NULL ORDER BY u.id").fetchall():
        code = u["student_code"] if u["role"] == "student" else u["teacher_code"] if u["role"] == "teacher" else admin_login_for(conn)
        if code and conn.execute("UPDATE users SET login_id=? WHERE id=? AND login_id IS NULL", (code, u["id"])).rowcount:
            rep["login_ids"].append((u["id"], code))
    return rep


def give_login_id(conn, user_id):
    """Make sure this one person can sign in by ID right now. Teachers, admins and students who have a code get theirs. A student with no course yet
    gets a temporary-looking BAL/STU/NNN as sign-in ID only: the permanent student code still waits for the first enrolment (Session 10 decision),
    and the sign-in ID is not changed behind their back when it arrives (an admin can edit it). Returns the login ID."""
    fill_missing(conn, unenrolled_students=False)
    r = conn.execute("SELECT role, login_id FROM users WHERE id=?", (user_id,)).fetchone()
    if r and r["login_id"] is None and r["role"] == "student":
        # same counter as student_code_for(None), so a number is never issued twice across the two columns
        code = _alloc(conn, f"student:{NO_COURSE}", lambda n: f"{ORG}/{NO_COURSE}/{n:03d}", "users", "login_id")
        conn.execute("UPDATE users SET login_id=? WHERE id=? AND login_id IS NULL", (code, user_id))
    return conn.execute("SELECT login_id FROM users WHERE id=?", (user_id,)).fetchone()[0]


def duplicates(conn):
    """Codes used twice (the unique indexes should make this always empty). [(table, column, code, count)]"""
    out = []
    for tbl, col in (("courses", "code"), ("students", "student_code"), ("teachers", "teacher_code"), ("enrollments", "enrol_code"), ("users", "login_id")):
        for r in conn.execute(f"SELECT {col} AS v, COUNT(*) AS n FROM {tbl} WHERE {col} IS NOT NULL GROUP BY {col} HAVING COUNT(*)>1").fetchall():
            out.append((tbl, col, r["v"], r["n"]))
    return out
