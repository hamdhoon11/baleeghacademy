"""v0.8.41: "Clear portal data" (POST /api/admin/reset-data and python resetdata.py): everything entered is deleted, the admins stay."""
import datetime as dt, io, os, sqlite3, subprocess, sys, tempfile, unittest
from unittest import mock
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"
PDF = b"%PDF-1.4 test file"
PHRASE = "DELETE ALL DATA"


class Reset41(unittest.TestCase):
    def setUp(self):
        """A fresh portal with a bit of everything for every test (each test deletes it)."""
        tmp = tempfile.mkdtemp(); self.tmp = tmp; self.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=self.path, ADMIN_EMAIL="admin@s41.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        self.app = create_app({"DATABASE_PATH": self.path}); self.c = self.app.test_client()
        self.app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 17, 0, tzinfo=MVT)
        self.sql("UPDATE users SET must_change_password=0")
        self.sql("DELETE FROM batches"); self.sql("DELETE FROM courses")   # the seed's example courses: this test makes its own
        self.H = self.tok("admin@s41.test", "AdminPass123")
        P = lambda p, j: self.c.post(p, json=j, headers=self.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": e.split("@")[0], "role": role, **kw}).get_json()["id"]
        self.t1, self.s1, self.s2 = mk("t1@s41.test", "teacher"), mk("s1@s41.test", "student"), mk("s2@s41.test", "student")
        self.lim = mk("lim@s41.test", "admin", permissions=["settings", "people"])
        self.sql("UPDATE users SET must_change_password=0")
        self.assertEqual(self.c.put("/api/settings", json={"academy_name": "Test Academy 41"}, headers=self.H).status_code, 200)
        course = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 500, "status": "open"}).get_json()["id"]
        b1 = P("/api/batches", {"course_id": course, "code": "A1", "teacher_id": self.t1, "capacity": 9, "days": "Mon,Wed", "start_time": "16:00"}).get_json()["id"]
        for s in (self.s1, self.s2): self.assertEqual(P("/api/enrollments", {"student_id": s, "batch_id": b1}).status_code, 201)
        inv = self.c.get(f"/api/invoices?student_id={self.s1}", headers=self.H).get_json()[0]["id"]
        self.assertEqual(P("/api/payments", {"invoice_id": inv, "amount_mvr": 500, "method": "cash", "paid_on": "2027-03-05"}).status_code, 201)
        self.T1, self.S1 = self.tok("t1@s41.test", PW), self.tok("s1@s41.test", PW)
        form = lambda url, h, **d: self.c.post(url, data=d, headers=h, content_type="multipart/form-data")
        self.assertEqual(form(f"/api/batches/{b1}/materials", self.T1, title="Notes", file=(io.BytesIO(PDF), "notes.pdf")).status_code, 201)
        a = form(f"/api/batches/{b1}/assignments", self.T1, title="Homework", max_points="10", due_date="2027-03-20", file=(io.BytesIO(PDF), "task.pdf"))
        self.assertEqual(a.status_code, 201, a.get_json())
        self.assertIn(form(f"/api/assignments/{a.get_json()['id']}/submit", self.S1, text="done", file=(io.BytesIO(PDF), "answer.pdf")).status_code, (200, 201))
        self.c.post(f"/api/batches/{b1}/attendance", json={"date": "2027-03-10", "records": [{"student_id": self.s1, "status": "present"}]}, headers=self.T1)
        cat = P("/api/expense-categories", {"name": "Rent"}).get_json()["id"]
        self.assertEqual(P("/api/expenses", {"category_id": cat, "amount_mvr": 900, "expense_date": "2027-03-01", "description": "March rent"}).status_code, 201)
        self.assertEqual(P("/api/earnings/calculate", {"month": "2027-03"}).status_code, 200)
        self.c.post("/api/auth/forgot", json={"login": "s2@s41.test"})
        self.LIM = self.tok("lim@s41.test", PW)
        import dbx, resetdata
        self.script = dbx.read_schema(ROOT); self.rd = resetdata
        self.data_tables = [t for t in resetdata.delete_order(self.script) if t not in resetdata.KEEP]

    def tok(self, login, pw):
        r = self.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()
        return {"Authorization": "Bearer " + r["token"]}

    def sql(self, q, a=()):
        con = sqlite3.connect(self.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def n(self, table, where=""):
        return self.sql(f"SELECT COUNT(*) FROM {table} {where}")[0][0]

    def rows_left(self):
        return {t: self.n(t) for t in self.data_tables if self.n(t)}

    def files(self):
        return sorted(f for _d, _s, fs in os.walk(os.path.join(self.tmp, "uploads")) for f in fs)

    def reset(self, h=None, **body):
        r = self.c.post("/api/admin/reset-data", json=body, headers=h or self.H)
        return r.status_code, r.get_json()

    APPLY = {"apply": True, "password": "AdminPass123", "confirm": PHRASE}

    # ---- the order of deletion ----
    def test_01_references_read_from_the_schema_match_the_database(self):
        want = self.rd.table_refs(self.script)
        con = sqlite3.connect(self.path)
        try:
            for t in want:
                real = {r[2].lower() for r in con.execute(f"PRAGMA foreign_key_list({t})")} - {t}
                self.assertEqual(want[t], real, t)          # a wrong order would make the delete fail on a reference
        finally: con.close()
        order = self.rd.delete_order(self.script)
        for t, refs in want.items():
            for parent in refs: self.assertLess(order.index(t), order.index(parent), f"{t} must be deleted before {parent}")

    # ---- who may, and the preview ----
    def test_02_only_a_full_admin_and_the_preview_changes_nothing(self):
        self.assertEqual(self.c.post("/api/admin/reset-data", json={}).status_code, 401)
        for h in (self.T1, self.S1): self.assertEqual(self.reset(h)[0], 403)
        code, j = self.reset(self.LIM); self.assertEqual(code, 403); self.assertIn("full admin", j["error"])   # has Settings, but is limited
        self.assertEqual(self.reset(self.LIM, **{**self.APPLY, "password": PW})[0], 403)
        before, files = self.rows_left(), self.files()
        self.assertEqual(len(files), 3)
        code, j = self.reset()
        self.assertEqual(code, 200); self.assertFalse(j["apply"]); self.assertEqual(j["phrase"], PHRASE)
        got = {i["table"]: i["rows"] for i in j["items"]}
        self.assertEqual(got.pop("users"), 3)                                      # the teacher and two students; not the two admins
        self.assertEqual(got, before)
        for t in ("courses", "batches", "enrollments", "invoices", "payments", "materials", "assignments", "submissions", "attendance", "expenses",
                  "expense_categories", "teacher_earnings", "students", "teachers", "password_help", "notifications"): self.assertIn(t, got, t)
        self.assertEqual(j["kept"]["admins"], 2); self.assertEqual(j["total"], sum(before.values()) + 3)
        self.assertEqual((self.rows_left(), self.files(), self.n("users")), (before, files, 5))   # nothing changed

    # ---- refusals ----
    def test_03_needs_the_words_and_the_password(self):
        before = self.rows_left()
        for body, code in (({"apply": True, "password": "AdminPass123"}, 400), ({**self.APPLY, "confirm": "delete all data"}, 400), ({**self.APPLY, "confirm": "yes"}, 400),
                           ({**self.APPLY, "password": "wrong"}, 403), ({**self.APPLY, "password": ""}, 403)):
            self.assertEqual(self.reset(**body)[0], code, body)
        self.assertEqual((self.rows_left(), self.n("users")), (before, 5))
        self.assertEqual(self.n("audit_log", "WHERE action='reset_data_refused'"), 2)   # a wrong password is written down
        self.assertEqual(self.n("audit_log", "WHERE action='reset_data'"), 0)

    # ---- the real thing ----
    def test_04_everything_goes_and_the_admins_stay(self):
        admins = self.sql("SELECT id, email, login_id, password_hash, permissions FROM users WHERE role='admin' ORDER BY id")
        settings, log, counters = self.sql("SELECT key, value FROM settings ORDER BY key"), self.n("audit_log"), self.sql("SELECT name, value FROM counters ORDER BY name")
        self.assertTrue(any(v for _n, v in counters))
        code, j = self.reset(**self.APPLY)
        self.assertEqual(code, 200, j); self.assertTrue(j["apply"])
        self.assertEqual(self.rows_left(), {})                                      # every data table is empty
        self.assertEqual(self.sql("SELECT id, email, login_id, password_hash, permissions FROM users ORDER BY id"), admins)   # admins untouched, nobody else
        self.assertEqual(self.sql("SELECT key, value FROM settings ORDER BY key"), settings)
        self.assertEqual(self.sql("SELECT name, value FROM counters ORDER BY name"), counters)   # numbers carry on
        self.assertEqual(self.n("audit_log"), log + 1)                              # the log is kept and says what happened
        row = self.sql("SELECT user_id, detail, old_value, new_value FROM audit_log WHERE action='reset_data'")[0]
        self.assertEqual(row[0], admins[0][0]); self.assertIn("courses 1", row[1]); self.assertEqual((row[2], row[3]), (str(j["total"]), "0"))
        self.assertEqual((j["files_removed"], j["files_left"], self.files()), (3, 0, []))     # uploaded files are gone from the folder
        self.assertEqual(j["kept"]["admins"], 2)
        self.assertEqual(self.reset()[1]["total"], 0)                               # nothing left to delete
        # sign-ins: both admins still get in with their passwords; the teacher and students do not
        self.assertEqual(self.c.get("/api/auth/me", headers=self.H).status_code, 200)
        self.assertEqual(self.c.post("/api/auth/login", json={"login": "lim@s41.test", "password": PW}).status_code, 200)
        self.assertEqual(self.c.post("/api/auth/login", json={"login": admins[0][2], "password": "AdminPass123"}).status_code, 200)   # by login ID
        self.assertEqual(self.c.post("/api/auth/login", json={"login": "s1@s41.test", "password": PW}).status_code, 401)
        self.assertIn(self.c.get("/api/auth/me", headers=self.S1).status_code, (401, 403))
        # the portal works afterwards, and IDs carry on from where they were
        for path in ("/api/courses", "/api/batches", "/api/users", "/api/invoices", "/api/expenses", "/api/admin/todo", "/api/dashboard", "/api/earnings?month=2027-03"):
            self.assertEqual(self.c.get(path, headers=self.H).status_code, 200, path)
        self.assertEqual(self.c.get("/api/settings", headers=self.H).status_code, 200)
        self.assertEqual(self.c.get("/api/public/info").get_json().get("academy_name"), "Test Academy 41")
        P = lambda p, jn: self.c.post(p, json=jn, headers=self.H)
        t = P("/api/users", {"email": "new-t@s41.test", "password": PW, "full_name": "New Teacher", "role": "teacher"}); self.assertEqual(t.status_code, 201, t.get_json())
        self.assertEqual(self.sql("SELECT teacher_code FROM teachers")[0][0], "BAL/T/002")
        self.assertEqual(P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 500, "status": "open"}).status_code, 201)

    def test_05_numbers_can_start_again(self):
        self.sql("UPDATE counters SET value=41 WHERE name='receipt'")
        admin_no = self.sql("SELECT value FROM counters WHERE name='admin'")
        code, j = self.reset(**self.APPLY, reset_numbers=True)
        self.assertEqual(code, 200, j)
        self.assertEqual(sorted(self.sql("SELECT name, value FROM counters")), sorted([("receipt", 0)] + [("admin", v) for (v,) in admin_no]))
        self.assertIn("numbers restarted", self.sql("SELECT detail FROM audit_log WHERE action='reset_data'")[0][0])
        t = self.c.post("/api/users", json={"email": "new-t@s41.test", "password": PW, "full_name": "New Teacher", "role": "teacher"}, headers=self.H)
        self.assertEqual(t.status_code, 201); self.assertEqual(self.sql("SELECT teacher_code FROM teachers")[0][0], "BAL/T/001")
        a = self.c.post("/api/users", json={"email": "new-a@s41.test", "password": PW, "full_name": "New Admin", "role": "admin"}, headers=self.H)
        self.assertEqual(a.status_code, 201)                                         # admin IDs did not restart: no clash with the admins that stayed
        self.assertEqual(len(set(r[0] for r in self.sql("SELECT login_id FROM users"))), self.n("users"))

    def test_06_all_or_nothing(self):
        before, users, files = self.rows_left(), self.n("users"), self.files()
        real = self.rd.wipe
        def half(conn, script, reset_numbers=False):
            real(conn, script, reset_numbers); raise RuntimeError("the database went away half way")
        with mock.patch.object(self.rd, "wipe", half):
            self.assertEqual(self.reset(**self.APPLY)[0], 500)
        self.assertEqual((self.rows_left(), self.n("users"), self.files()), (before, users, files))   # nothing was deleted, no file removed
        self.assertEqual(self.n("audit_log", "WHERE action='reset_data'"), 0)

    def test_07_works_with_rows_in_the_postgresql_shape(self):
        import dbx
        shape = lambda cur, r: None if r is None else dbx.Row(r.keys(), [dbx._py(v) for v in tuple(r)])
        with mock.patch.object(dbx.Cur, "_wrap", shape):
            code, j = self.reset(); self.assertEqual(code, 200, j); self.assertGreater(j["total"], 20)
            code, j = self.reset(**self.APPLY); self.assertEqual(code, 200, j)
        self.assertEqual((self.rows_left(), self.n("users"), self.files()), ({}, 2, []))

    def test_08_files_kept_in_the_database_go_too(self):
        from app import create_app   # the same portal, with files in the database as on Vercel
        app = create_app({"DATABASE_PATH": self.path, "FILE_STORAGE": "db"}); c = app.test_client()
        app.config["NOW"] = self.app.config["NOW"]
        b1 = self.sql("SELECT id FROM batches")[0][0]
        r = c.post(f"/api/batches/{b1}/materials", data={"title": "In db", "file": (io.BytesIO(PDF), "db.pdf")}, headers=self.T1, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201, r.get_json()); self.assertEqual(self.n("stored_files"), 1)
        r = c.post("/api/admin/reset-data", json=self.APPLY, headers=self.H)
        self.assertEqual(r.status_code, 200, r.get_json()); self.assertEqual(r.get_json()["files_removed"], 0)   # they went with the table
        self.assertEqual((self.n("stored_files"), self.rows_left()), (0, {}))

    def test_09_command_line_is_a_dry_run_unless_asked(self):
        env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "POSTGRES_URL")}; env["DATABASE_PATH"] = self.path
        run = lambda *a: subprocess.run([sys.executable, os.path.join(ROOT, "resetdata.py"), *a], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        before = self.rows_left()
        r = run(); self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("Dry run: nothing was changed", r.stdout); self.assertIn("Courses (courses)", r.stdout)
        r = run("--apply"); self.assertEqual(r.returncode, 2); self.assertIn("backup", r.stdout)
        self.assertEqual((self.rows_left(), self.n("users")), (before, 5))
        r = run("--apply", "--i-have-a-backup"); self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.rows_left(), self.n("users"), self.n("users", "WHERE role='admin'")), ({}, 2, 2))
        self.assertEqual(self.n("audit_log", "WHERE action='reset_data' AND user_role='system'"), 1)

    def test_10_screen(self):
        js = open(os.path.join(ROOT, "static/admin.js"), encoding="utf-8").read()
        self.assertIn('if (S.user.role !== "admin" || S.user.permissions) return "";', js)   # the panel is drawn for full admins only
        self.assertIn('api("/admin/reset-data", "POST", {})', js)                             # the preview comes first
        self.assertIn("x.confirm === p.phrase", js)
        import json
        en = json.load(open(os.path.join(ROOT, "static/i18n/en.json"), encoding="utf-8"))
        for k in ("rd_title", "rd_hint", "rd_button", "rd_confirm", "rd_kept", "rd_type", "rd_done", "rd_nothing", *self.rd.LABELS.values()): self.assertIn(k, en, k)


if __name__ == "__main__":
    unittest.main()
