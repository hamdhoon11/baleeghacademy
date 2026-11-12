"""v0.8.37 (Round 3): tutorial grading (and its migration with dry run and backup), My files, the week timetable for everyone,
recurring monthly expenses, the new tabs."""
import datetime as dt, io, os, shutil, sqlite3, subprocess, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"
CLOCK = {"now": dt.datetime(2027, 3, 10, 17, 0, tzinfo=MVT)}


class Round3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s37.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: CLOCK["now"]
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.H = cls.tok("admin@s37.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": e.split("@")[0], "role": role, **kw}).get_json()["id"]
        cls.t1, cls.t2 = mk("t1@s37.test", "teacher"), mk("t2@s37.test", "teacher")
        cls.s1, cls.s2 = mk("s1@s37.test", "student"), mk("s2@s37.test", "student")
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.course = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 500, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": cls.course, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Mon,Wed", "start_time": "16:00"}).get_json()["id"]
        for s in (cls.s1, cls.s2): assert P("/api/enrollments", {"student_id": s, "batch_id": cls.b1}).status_code == 201
        cls.T1, cls.T2, cls.S1, cls.S2 = (cls.tok(e, PW) for e in ("t1@s37.test", "t2@s37.test", "s1@s37.test", "s2@s37.test"))

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def post_tut(self, h, **kw):
        d = {"title": "Lesson", "text": "Read and answer", "course_id": str(self.course)}; d.update(kw)
        r = self.c.post("/api/tutorials", data=d, headers=h, content_type="multipart/form-data"); self.assertEqual(r.status_code, 201, r.get_json()); return r.get_json()["id"]

    def answer(self, tid, h, text="my answer", file=None):
        d = {"text": text}
        if file: d["file"] = file
        r = self.c.post(f"/api/tutorials/{tid}/submission", data=d, headers=h, content_type="multipart/form-data"); self.assertIn(r.status_code, (200, 201), r.get_json())
        return r.get_json()["id"]

    # ---- tutorial grading ----
    def test_01_grade_tutorial_answer(self):
        tid = self.post_tut(self.T1)
        sid = self.answer(tid, self.S1)
        lst = {t["id"]: t for t in self.c.get("/api/tutorials", headers=self.T1).get_json()}
        self.assertEqual((lst[tid]["max_points"], lst[tid]["ungraded_count"]), (100, 1))
        self.assertEqual(self.c.get("/api/my/home", headers=self.T1).get_json()["tut_to_grade"], 1)
        G = lambda h, **j: self.c.post(f"/api/tutorial-submissions/{sid}/grade", json=j, headers=h)
        self.assertEqual(G(self.T1, grade=120).status_code, 400)                   # over the maximum
        self.assertEqual(G(self.T2, grade=50).status_code, 403)                    # not their tutorial
        self.assertEqual(G(self.S1, grade=100).status_code, 403)
        self.assertEqual(G(self.T1, grade=85, feedback="Good work").status_code, 200)
        mine = self.c.get(f"/api/tutorials/{tid}/submission", headers=self.S1).get_json()["submission"]
        self.assertEqual((mine["grade"], mine["feedback"]), (85, "Good work"))
        st = {t["id"]: t for t in self.c.get("/api/tutorials", headers=self.S1).get_json()}[tid]["my_submission"]
        self.assertTrue(st["graded"]); self.assertEqual(st["grade"], 85)
        self.assertEqual(self.c.get("/api/my/home", headers=self.T1).get_json()["tut_to_grade"], 0)
        n = self.c.get("/api/notifications", headers=self.S1).get_json()
        items = n["items"] if isinstance(n, dict) else n
        self.assertTrue(any("Lesson" in (x.get("body") or x.get("text") or "") for x in items))
        # a saved grade: the teacher cannot change it without "edit_grades"; the same value is a no-op; an admin can
        self.assertEqual(G(self.T1, grade=85, feedback="Good work").get_json()["changed"], False)
        self.assertEqual(G(self.T1, grade=90).status_code, 403)
        self.assertEqual(G(self.H, grade=90, feedback="Raised").status_code, 200)
        self.assertEqual(self.sql_("SELECT grade, graded_by FROM tutorial_submissions WHERE id=?", (sid,))[0], (90.0, self.t1))   # first grader kept
        # the student sends again after grading: the teacher sees it changed
        self.sql_("UPDATE tutorial_submissions SET graded_at='2020-01-01 00:00:00' WHERE id=?", (sid,))
        self.answer(tid, self.S1, "better answer")
        a = self.c.get(f"/api/tutorials/{tid}/submissions", headers=self.T1).get_json()
        self.assertTrue(a["submissions"][0]["changed_after_grading"]); self.assertFalse(a["can_edit_grades"])
        acts = [r[0] for r in self.sql_("SELECT action FROM audit_log WHERE action LIKE 'tutorial_grade%'")]
        self.assertIn("tutorial_grade", acts); self.assertIn("tutorial_grade_change", acts)

    def test_02_comments_only_tutorial(self):
        tid = self.post_tut(self.T1, title="Discussion", max_points="")
        sid = self.answer(tid, self.S2)
        G = lambda **j: self.c.post(f"/api/tutorial-submissions/{sid}/grade", json=j, headers=self.T1)
        self.assertEqual(G(grade=5, feedback="x").status_code, 400)
        self.assertEqual(G(feedback="").status_code, 400)
        self.assertEqual(G(feedback="Nice thinking").status_code, 200)
        s = self.c.get(f"/api/tutorials/{tid}/submission", headers=self.S2).get_json()["submission"]
        self.assertEqual((s["grade"], s["feedback"]), (None, "Nice thinking"))
        self.assertEqual(self.c.post("/api/tutorials", data={"title": "x", "text": "y", "max_points": "0"}, headers=self.T1, content_type="multipart/form-data").status_code, 400)

    # ---- my files ----
    def test_03_my_files(self):
        r = self.c.post(f"/api/batches/{self.b1}/materials", data={"title": "Notes", "file": (io.BytesIO(b"%PDF-1.4 notes"), "notes.pdf")}, headers=self.T1, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201, r.get_json())
        tid = self.post_tut(self.T1, title="With file", file=(io.BytesIO(b"%PDF-1.4 tut"), "tut.pdf"))
        self.answer(tid, self.S1, file=(io.BytesIO(b"%PDF-1.4 ans"), "ans.pdf"))
        f1 = self.c.get("/api/my/files", headers=self.S1).get_json()["files"]
        kinds = {x["kind"] for x in f1}
        self.assertTrue({"material", "tutorial", "my_tutorial_answer"} <= kinds, kinds)
        for x in f1:   # every path opens for the owner
            self.assertEqual(self.c.get("/api" + x["path"], headers=self.S1).status_code, 200, x)
        f2 = self.c.get("/api/my/files", headers=self.S2).get_json()["files"]
        self.assertNotIn("my_tutorial_answer", {x["kind"] for x in f2})       # not someone else's answer
        ft = self.c.get("/api/my/files", headers=self.T1).get_json()["files"]
        self.assertTrue({"material", "tutorial"} <= {x["kind"] for x in ft})
        self.assertEqual(self.c.get("/api/my/files", headers=self.T2).get_json()["files"], [])
        self.assertEqual(self.c.get("/api/my/files", headers=self.H).status_code, 403)

    def test_04_timetable_whole_week(self):
        r = self.c.get("/api/timetable?from=2027-03-08&to=2027-03-14&batch_id=0", headers=self.S1).get_json()
        self.assertEqual([o["date"] for o in r], ["2027-03-08", "2027-03-10"])
        a = self.c.get("/api/timetable?from=2027-03-08&to=2027-03-14&batch_id=0", headers=self.H).get_json()
        self.assertEqual(len(a), 2); self.assertEqual(a[0]["teacher_name"], "t1")
        self.assertEqual(self.c.get("/api/timetable?from=2027-03-08&to=2027-03-14&batch_id=0", headers=self.T2).get_json(), [])

    # ---- recurring expenses ----
    def test_05_recurring_expenses(self):
        cat = self.c.post("/api/expense-categories", json={"name": "Rent"}, headers=self.H).get_json()["id"]
        P = lambda j: self.c.post("/api/recurring-expenses", json=j, headers=self.H)
        self.assertEqual(P({"category_id": cat, "amount_mvr": 1000, "day_of_month": 31}).status_code, 400)
        self.assertEqual(P({"category_id": cat, "amount_mvr": 1000, "day_of_month": 5, "start_month": "2025-01"}).status_code, 400)   # too far back
        r = P({"category_id": cat, "amount_mvr": 8000, "day_of_month": 5, "description": "Office rent", "start_month": "2027-01"})
        self.assertEqual(r.status_code, 201, r.get_json()); rid = r.get_json()["id"]
        self.assertEqual(r.get_json()["written"], 3)                              # Jan, Feb, Mar (the 5th has passed on the 10th)
        rid2 = P({"category_id": cat, "amount_mvr": 500, "day_of_month": 20, "start_month": "2027-03"}).get_json()["id"]
        rows = self.sql_("SELECT expense_date, amount_mvr, recurring_id FROM expenses WHERE recurring_id IS NOT NULL ORDER BY expense_date")
        self.assertEqual(rows, [("2027-01-05", 8000, rid), ("2027-02-05", 8000, rid), ("2027-03-05", 8000, rid)])   # the 20th is not here yet
        self.c.get("/api/expenses", headers=self.H); self.c.get("/api/finance/dashboard", headers=self.H)
        self.assertEqual(len(self.sql_("SELECT id FROM expenses WHERE recurring_id IS NOT NULL")), 3)            # written once
        lst = {x["id"]: x for x in self.c.get("/api/recurring-expenses", headers=self.H).get_json()}
        self.assertEqual((lst[rid]["months_written"], lst[rid]["next_date"]), (3, "2027-04-05"))
        self.assertEqual(lst[rid2]["next_date"], "2027-03-20")
        # a month deleted by hand is not written again
        feb = self.sql_("SELECT id FROM expenses WHERE expense_date='2027-02-05'")[0][0]
        self.assertEqual(self.c.delete(f"/api/expenses/{feb}", headers=self.H).status_code, 200)
        self.c.get("/api/expenses", headers=self.H)
        self.assertEqual(len(self.sql_("SELECT id FROM expenses WHERE recurring_id=?", (rid,))), 2)
        # time moves on: April 20 writes April for both; editing the amount only changes months to come
        self.assertEqual(self.c.patch(f"/api/recurring-expenses/{rid}", json={"amount_mvr": 9000}, headers=self.H).status_code, 200)
        CLOCK["now"] = dt.datetime(2027, 4, 20, 9, 0, tzinfo=MVT)
        try:
            self.c.get("/api/expenses", headers=self.H)
            got = self.sql_("SELECT expense_date, amount_mvr FROM expenses WHERE recurring_id IS NOT NULL ORDER BY expense_date, amount_mvr")
            self.assertEqual(got, [("2027-01-05", 8000), ("2027-03-05", 8000), ("2027-03-20", 500), ("2027-04-05", 9000), ("2027-04-20", 500)])
            # paused: nothing new; resumed later catches up
            self.c.patch(f"/api/recurring-expenses/{rid2}", json={"is_active": False}, headers=self.H)
            CLOCK["now"] = dt.datetime(2027, 5, 21, 9, 0, tzinfo=MVT)
            self.c.get("/api/expenses", headers=self.H)
            self.assertEqual(len(self.sql_("SELECT id FROM expenses WHERE recurring_id=?", (rid2,))), 2)
            self.assertEqual(len(self.sql_("SELECT id FROM expenses WHERE recurring_id=?", (rid,))), 4)        # May 5 written
            # deleting the rule keeps its expenses
            self.assertEqual(self.c.delete(f"/api/recurring-expenses/{rid}", headers=self.H).status_code, 200)
            self.assertEqual(len(self.sql_("SELECT id FROM expenses WHERE amount_mvr IN (8000, 9000)")), 4)
            self.assertEqual(self.sql_("SELECT COUNT(*) FROM recurring_expenses WHERE id=?", (rid,))[0][0], 0)
        finally:
            CLOCK["now"] = dt.datetime(2027, 3, 10, 17, 0, tzinfo=MVT)
        for h in (self.T1, self.S1):
            self.assertEqual(self.c.get("/api/recurring-expenses", headers=h).status_code, 403)

    def test_06_tabs(self):
        u = self.c.post("/api/auth/login", json={"login": "s1@s37.test", "password": PW}).get_json()["user"]
        self.assertIn("timetable", u["tabs"]); self.assertIn("my_files", u["tabs"])
        a = self.c.post("/api/auth/login", json={"login": "admin@s37.test", "password": "AdminPass123"}).get_json()["user"]
        self.assertIn("timetable", a["tabs"]); self.assertNotIn("my_files", a["tabs"])


class Migration(unittest.TestCase):
    """migrate_v0837.py on a database made before v0.8.37: the dry run changes nothing, --apply makes a backup and adds the columns,
    existing tutorials and answers are unchanged, a second run finds nothing."""
    def test_dry_run_then_apply(self):
        tmp = tempfile.mkdtemp(); db = os.path.join(tmp, "old.db")
        con = sqlite3.connect(db)
        con.executescript("""CREATE TABLE users(id INTEGER PRIMARY KEY, full_name TEXT);
          CREATE TABLE tutorials(id INTEGER PRIMARY KEY, title TEXT, body TEXT, course_id INTEGER, file TEXT, file_name TEXT, url TEXT, uploaded_by INTEGER, created_at TEXT);
          CREATE TABLE tutorial_submissions(id INTEGER PRIMARY KEY, tutorial_id INTEGER, student_id INTEGER, text_answer TEXT, file TEXT, file_name TEXT, submitted_at TEXT);
          CREATE TABLE expenses(id INTEGER PRIMARY KEY, expense_date TEXT, amount_mvr INTEGER, category_id INTEGER, description TEXT);
          INSERT INTO users VALUES(1,'T'); INSERT INTO tutorials VALUES(1,'Old','text',NULL,NULL,NULL,NULL,1,'2026-01-01');
          INSERT INTO tutorial_submissions VALUES(1,1,2,'answer',NULL,NULL,'2026-01-02'); INSERT INTO expenses VALUES(1,'2026-01-03',100,1,'x');""")
        con.commit(); con.close()
        env = dict(os.environ, DATABASE_PATH=db, DATABASE_URL="")
        run = lambda *a: subprocess.run([sys.executable, "migrate_v0837.py", *a], cwd=ROOT, env=env, capture_output=True, text=True)
        cols = lambda t: [r[1] for r in sqlite3.connect(db).execute(f"PRAGMA table_info({t})")]
        r = run(); self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("DRY RUN", r.stdout)
        self.assertNotIn("grade", cols("tutorial_submissions")); self.assertNotIn("max_points", cols("tutorials"))
        r = run("--apply"); self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("APPLIED", r.stdout)
        self.assertTrue(any(f.startswith("old.db.before-v0.8.37-") for f in os.listdir(tmp)))
        self.assertIn("grade", cols("tutorial_submissions")); self.assertIn("recurring_id", cols("expenses"))
        c = sqlite3.connect(db)
        self.assertEqual(c.execute("SELECT max_points FROM tutorials").fetchone()[0], 100)
        self.assertEqual(c.execute("SELECT text_answer, grade FROM tutorial_submissions").fetchone(), ("answer", None))
        c.close()
        self.assertIn("Nothing to add", run().stdout)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
