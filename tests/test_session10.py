"""Session 10: course type, ID codes, generator, backfill (dry run, apply, twice), upgrade from the v0.8.8 schema."""
import os, sqlite3, subprocess, sys, tempfile, threading, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import dbx, idcodes
PW = "Passw0rd!x1"
OLD_SCHEMA = os.path.join(ROOT, "tests", "fixtures", "schema_v0_8_8.sql")


def old_database(path):
    """A database as v0.8.8 left it: old schema, no codes. 3 courses (open, upcoming, closed), 2 teachers, 4 students, one with no enrolment."""
    c = sqlite3.connect(path)
    c.executescript(open(OLD_SCHEMA, encoding="utf-8").read())
    for i, (email, role) in enumerate([("a@o.test", "admin"), ("t1@o.test", "teacher"), ("t2@o.test", "teacher"), ("s1@o.test", "student"),
                                       ("s2@o.test", "student"), ("s3@o.test", "student"), ("s4@o.test", "student")], 1):
        c.execute("INSERT INTO users(id,email,password_hash,full_name,role) VALUES(?,?,'x',?,?)", (i, email, email.split("@")[0], role))
    c.executemany("INSERT INTO teachers(user_id) VALUES(?)", [(2,), (3,)])
    c.executemany("INSERT INTO students(user_id) VALUES(?)", [(4,), (5,), (6,)])    # student 7 has no students row at all (older account)
    c.execute("INSERT INTO courses(id,name,level,monthly_fee_mvr,status) VALUES(1,'Arabic','Level 1',350,'open')")
    c.execute("INSERT INTO courses(id,name,level,status) VALUES(2,'Islam Basic for GCE O Level','O Level','upcoming')")
    c.execute("INSERT INTO courses(id,name,level,status) VALUES(3,'Arabic','Level 2','closed')")
    c.execute("INSERT INTO batches(id,course_id,code,teacher_id) VALUES(1,1,'004',2),(2,1,'005',2),(3,2,'A',3)")
    # student 4: first Arabic then Islam; 5: Islam, dropped; 6: Arabic; 7: Arabic (no students row)
    c.executemany("INSERT INTO enrollments(student_id,batch_id,status,enrolled_at) VALUES(?,?,?,?)",
                  [(4, 1, "active", "2026-01-01 10:00:00"), (4, 3, "active", "2026-02-01 10:00:00"), (5, 3, "dropped", "2026-01-05 10:00:00"),
                   (6, 2, "active", "2026-01-06 10:00:00"), (7, 1, "waitlist", "2026-01-07 10:00:00")])
    c.execute("UPDATE counters SET value=41 WHERE name='receipt'")
    c.commit(); c.close()


def conn_for(path):
    return dbx.Conn(None, path)


class Generator(unittest.TestCase):
    def test_01_course_code_derivation(self):
        d = idcodes.derive_course_code
        self.assertEqual(d("Arabic", "Level 1"), "AL1")
        self.assertEqual(d("Grade 8 Mathematics"), "G8M")
        self.assertEqual(d("Grade 8 Mathematics", None, {"G8M"}), "G8M2")
        self.assertEqual(d("Grade 8 Mathematics", None, {"G8M", "G8M2"}), "G8M3")
        self.assertEqual(d("ދިވެހި", None, (), "C7"), "C7")                      # no Latin letters: fallback
        self.assertEqual(d("X"), "XX")                                           # at least 2 characters
        self.assertLessEqual(len(d("A Very Long Course Name Indeed Really", "Level 10")), 8)
        self.assertEqual(idcodes.norm_course_code(" al1 "), "AL1")
        for bad in ("A", "TOOLONGCODE", "A/B", "a b", ""): self.assertIsNone(idcodes.norm_course_code(bad), bad)

    def test_02_counter_is_unique_under_concurrent_requests(self):
        path = os.path.join(tempfile.mkdtemp(), "c.db")
        c = conn_for(path); dbx.init_schema(c, ROOT); c.close()
        got, errs = [], []

        def worker():
            try:
                cc = conn_for(path)
                for _ in range(15):
                    n = idcodes.next_number(cc, "student:AL1"); cc.commit(); got.append(n)
                cc.close()
            except Exception as e: errs.append(e)
        ts = [threading.Thread(target=worker) for _ in range(4)]
        [t.start() for t in ts]; [t.join() for t in ts]
        self.assertEqual(errs, [])
        self.assertEqual(sorted(got), list(range(1, 61)))                         # no duplicates, no gaps

    def test_03_rolled_back_request_gives_its_number_back(self):
        path = os.path.join(tempfile.mkdtemp(), "c.db")
        c = conn_for(path); dbx.init_schema(c, ROOT)
        self.assertEqual(idcodes.next_number(c, "teacher"), 1); c.commit()
        self.assertEqual(idcodes.next_number(c, "teacher"), 2); c.rollback()
        self.assertEqual(idcodes.next_number(c, "teacher"), 2)


class Upgrade(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "old.db")
        old_database(self.path)
        self.c = conn_for(self.path)
        dbx.init_schema(self.c, ROOT)                                             # what starting v0.8.9 does

    def tearDown(self): self.c.close()

    def snapshot(self):
        return {t: [tuple(r) for r in self.c.execute(f"SELECT * FROM {t} ORDER BY 1,2").fetchall()] for t in ("users", "batches", "invoices")}

    def test_04_columns_added_and_existing_data_kept(self):
        for t, col in (("courses", "kind"), ("courses", "code"), ("courses", "is_active"), ("students", "student_code"),
                       ("teachers", "teacher_code"), ("enrollments", "enrol_code")):
            self.assertIn(col, self.c.columns(t))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM users").fetchone()[0], 7)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0], 5)
        r = self.c.execute("SELECT kind,code,is_active FROM courses WHERE id=1").fetchone()
        self.assertEqual((r["kind"], r["code"], r["is_active"]), ("course", None, 1))
        dbx.init_schema(self.c, ROOT)                                             # a second start is harmless

    def test_05_dry_run_reports_and_changes_nothing(self):
        import migrate_session10 as m
        before = self.snapshot()
        lines = []
        rep, b, a = m.run(self.c, False, lines.append)
        self.assertEqual((len(rep["courses"]), len(rep["teachers"]), len(rep["students"]), len(rep["enrollments"])), (3, 2, 4, 5))
        self.assertTrue(any("DRY RUN" in x for x in lines))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM courses WHERE code IS NOT NULL").fetchone()[0], 0)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM students").fetchone()[0], 3)       # the profile row it would create was rolled back
        self.assertIsNone(self.c.execute("SELECT value FROM counters WHERE name='teacher'").fetchone())
        self.assertEqual(self.snapshot(), before)

    def test_06_apply_fills_everything_correctly_and_twice_is_a_no_op(self):
        import migrate_session10 as m
        rep, b, a = m.run(self.c, True, lambda *_: None)
        q = lambda s: [tuple(r) for r in self.c.execute(s).fetchall()]
        self.assertEqual(q("SELECT id,code,is_active FROM courses ORDER BY id"), [(1, "AL1", 1), (2, "IBGOLOL", 1), (3, "AL2", 0)])   # closed course -> inactive
        self.assertEqual(q("SELECT user_id,teacher_code FROM teachers ORDER BY 1"), [(2, "BAL/T/001"), (3, "BAL/T/002")])
        # student's code comes from the course of their FIRST enrolment; the one without any enrolment cannot exist here (7 was waitlisted in AL1)
        self.assertEqual(q("SELECT user_id,student_code FROM students ORDER BY 1"),
                         [(4, "BAL/AL1/001"), (5, "BAL/IBGOLOL/001"), (6, "BAL/AL1/002"), (7, "BAL/AL1/003")])
        self.assertEqual(q("SELECT id,enrol_code FROM enrollments ORDER BY 1"),
                         [(1, "BAL/AL1/E001"), (2, "BAL/IBGOLOL/E001"), (3, "BAL/IBGOLOL/E002"), (4, "BAL/AL1/E002"), (5, "BAL/AL1/E003")])
        self.assertEqual(idcodes.duplicates(self.c), [])
        self.assertEqual((b["users"], b["enrollments"], b["courses"]), (a["users"], a["enrollments"], a["courses"]))
        self.assertEqual(self.c.execute("SELECT value FROM counters WHERE name='receipt'").fetchone()[0], 41)   # receipt counter untouched
        # second run: nothing to do, nothing changes
        codes = q("SELECT student_code FROM students ORDER BY 1")
        rep2, *_ = m.run(self.c, True, lambda *_: None)
        self.assertEqual([len(rep2[k]) for k in ("courses", "teachers", "students", "enrollments")], [0, 0, 0, 0])
        self.assertEqual(q("SELECT student_code FROM students ORDER BY 1"), codes)

    def test_07_existing_codes_are_never_changed_and_hand_typed_ones_are_skipped(self):
        self.c.execute("UPDATE courses SET code='ARB' WHERE id=1"); self.c.execute("UPDATE teachers SET teacher_code='BAL/T/001' WHERE user_id=3"); self.c.commit()
        idcodes.fill_missing(self.c); self.c.commit()
        self.assertEqual(self.c.execute("SELECT code FROM courses WHERE id=1").fetchone()[0], "ARB")
        self.assertEqual(self.c.execute("SELECT teacher_code FROM teachers WHERE user_id=3").fetchone()[0], "BAL/T/001")
        self.assertEqual(self.c.execute("SELECT teacher_code FROM teachers WHERE user_id=2").fetchone()[0], "BAL/T/002")   # 001 was taken by hand: skipped
        self.assertEqual(idcodes.duplicates(self.c), [])

    def test_08_unique_indexes_reject_a_duplicate(self):
        idcodes.fill_missing(self.c); self.c.commit()
        with self.assertRaises(dbx.IntegrityError):
            self.c.execute("UPDATE courses SET code='AL1' WHERE id=2")

    def test_09_cli_dry_run_then_refuses_apply_without_backup_flag(self):
        env = {**os.environ, "DATABASE_PATH": self.path, "ADMIN_EMAIL": "a@o.test", "ADMIN_PASSWORD": "AdminPass123"}
        run = lambda *a: subprocess.run([sys.executable, "migrate_session10.py", *a], cwd=ROOT, env=env, capture_output=True, text=True)
        r = run(); self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("DRY RUN", r.stdout)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM courses WHERE code IS NOT NULL").fetchone()[0], 0)
        r = run("--apply"); self.assertNotEqual(r.returncode, 0); self.assertIn("backup", r.stderr.lower())
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM courses WHERE code IS NOT NULL").fetchone()[0], 0)
        r = run("--apply", "--i-have-a-backup"); self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("APPLIED", r.stdout)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM courses WHERE code IS NULL").fetchone()[0], 0)

    def test_10_upgraded_database_runs_the_app(self):
        import migrate_session10 as m
        m.run(self.c, True, lambda *_: None)
        from app import create_app
        os.environ.update(ADMIN_EMAIL="a@o.test", ADMIN_PASSWORD="AdminPass123")
        app = create_app({"DATABASE_PATH": self.path})
        cl = app.test_client()
        self.assertEqual(cl.get("/api/public/courses").status_code, 200)
        self.assertEqual(cl.post("/api/auth/login", json={"email": "nobody@x.test", "password": "x"}).status_code, 401)


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ.update(DATABASE_PATH=os.path.join(cls.tmp, "t.db"), ADMIN_EMAIL="admin@t.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})

    def setUp(self):
        self.c = self.app.test_client()
        self.H = {"Authorization": "Bearer " + self.c.post("/api/auth/login", json={"email": "admin@t.test", "password": "AdminPass123"}).get_json()["token"]}
        self.db = dbx.connect(self.app.config, ROOT)

    def tearDown(self): self.db.close()

    def J(self, m, u, **k): return getattr(self.c, m)(u, headers=self.H, **k)
    def val(self, sql, a=()): return self.db.execute(sql, a).fetchone()[0]

    def test_11_seed_gives_codes(self):
        self.assertEqual(self.val("SELECT code FROM courses WHERE id=1"), "AL1")
        self.assertEqual(self.val("SELECT student_code FROM students s JOIN users u ON u.id=s.user_id WHERE u.email='student@baleegh.test'"), "BAL/AL1/001")
        self.assertEqual(self.val("SELECT teacher_code FROM teachers t JOIN users u ON u.id=t.user_id WHERE u.email='teacher@baleegh.test'"), "BAL/T/001")
        self.assertEqual(self.val("SELECT enrol_code FROM enrollments WHERE id=1"), "BAL/AL1/E001")

    def test_12_course_type_and_code_through_the_api(self):
        r = self.J("post", "/api/courses", json={"name": "Grade 8 Mathematics", "kind": "tuition", "monthly_fee_mvr": 600, "status": "open"})
        self.assertEqual(r.status_code, 201); cid = r.get_json()["id"]
        row = [x for x in self.J("get", "/api/courses").get_json() if x["id"] == cid][0]
        self.assertEqual((row["kind"], row["code"], row["is_active"]), ("tuition", "G8M", 1))
        again = self.J("post", "/api/courses", json={"name": "Grade 8 Mathematics", "kind": "tuition", "monthly_fee_mvr": 600}).get_json()["id"]
        self.assertEqual(self.val("SELECT code FROM courses WHERE id=?", (again,)), "G8M2")                  # same name, still unique
        self.assertEqual(self.J("post", "/api/courses", json={"name": "Chess", "code": "g8m", "monthly_fee_mvr": 1}).status_code, 409)
        self.assertEqual(self.J("post", "/api/courses", json={"name": "Chess", "code": "a/b", "monthly_fee_mvr": 1}).status_code, 400)
        self.assertEqual(self.J("post", "/api/courses", json={"name": "Chess", "kind": "camp", "monthly_fee_mvr": 1}).status_code, 400)
        self.assertEqual(self.J("patch", f"/api/courses/{cid}", json={"code": "al1"}).status_code, 409)
        self.assertEqual(self.J("patch", f"/api/courses/{cid}", json={"code": "", "is_active": False}).status_code, 200)   # empty code ignored
        self.assertEqual(self.val("SELECT is_active FROM courses WHERE id=?", (cid,)), 0)
        self.assertEqual(self.val("SELECT code FROM courses WHERE id=?", (cid,)), "G8M")

    def test_13_new_people_and_enrolments_get_codes_and_keep_them(self):
        cid = self.J("post", "/api/courses", json={"name": "Quran Recitation", "monthly_fee_mvr": 300, "status": "open"}).get_json()["id"]
        code = self.val("SELECT code FROM courses WHERE id=?", (cid,)); self.assertEqual(code, "QR")
        t = self.J("post", "/api/users", json={"email": "nt@t.test", "password": PW, "full_name": "T", "role": "teacher"}).get_json()["id"]
        tc = self.val("SELECT teacher_code FROM teachers WHERE user_id=?", (t,)); self.assertRegex(tc, r"^BAL/T/\d{3}$")
        bid = self.J("post", "/api/batches", json={"course_id": cid, "code": "Q1", "teacher_id": t, "capacity": 5}).get_json()["id"]
        bid2 = self.J("post", "/api/batches", json={"course_id": 1, "code": "Q2", "teacher_id": t, "capacity": 5}).get_json()["id"]
        s = self.J("post", "/api/users", json={"email": "ns@t.test", "password": PW, "full_name": "S", "role": "student"}).get_json()["id"]
        self.assertIsNone(self.val("SELECT student_code FROM students WHERE user_id=?", (s,)))                    # no course yet: no ID yet
        e1 = self.J("post", "/api/enrollments", json={"student_id": s, "batch_id": bid}).get_json()["id"]
        sc = self.val("SELECT student_code FROM students WHERE user_id=?", (s,)); self.assertRegex(sc, r"^BAL/QR/\d{3}$")   # first course decides
        e2 = self.J("post", "/api/enrollments", json={"student_id": s, "batch_id": bid2}).get_json()["id"]
        self.assertEqual(self.val("SELECT student_code FROM students WHERE user_id=?", (s,)), sc)                  # permanent
        ec1, ec2 = (self.val("SELECT enrol_code FROM enrollments WHERE id=?", (x,)) for x in (e1, e2))
        self.assertRegex(ec1, r"^BAL/QR/E\d{3}$"); self.assertRegex(ec2, r"^BAL/AL1/E\d{3}$"); self.assertNotEqual(ec1, sc)
        n = self.J("patch", f"/api/enrollments/{e1}", json={"transfer_to_batch_id": bid2})
        self.assertEqual(n.status_code, 409)                                                                        # already in that batch: unchanged
        self.assertEqual(idcodes.duplicates(self.db), [])

    def test_14_account_created_with_a_course_gets_its_id_at_once(self):
        s = self.J("post", "/api/users", json={"email": "wc@t.test", "password": PW, "full_name": "S", "role": "student", "course_id": 1}).get_json()["id"]
        self.assertRegex(self.val("SELECT student_code FROM students WHERE user_id=?", (s,)), r"^BAL/AL1/\d{3}$")
        s2 = self.J("post", "/api/users", json={"email": "wc2@t.test", "password": PW, "full_name": "S", "role": "student", "course_id": 99999}).get_json()["id"]
        self.assertIsNone(self.val("SELECT student_code FROM students WHERE user_id=?", (s2,)))                   # unknown course: ignored, no ID


if __name__ == "__main__":
    unittest.main()
