"""Session 21: activity log viewer (filters, paging, CSV, drill-down) and protection (no change or delete route, database triggers)."""
import csv, io, os, sqlite3, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"


class S21(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s21.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path})
        cls.c = cls.app.test_client(); cls.n = 0
        cls.H = cls.tok("admin@s21.test", "AdminPass123")
        cls.t = cls.make("teacher", "T"); cls.s = cls.make("student", "S")
        post = lambda p, j: cls.c.post(p, json=j, headers=cls.H).get_json()["id"]
        cls.course = post("/api/courses", {"name": "Maths", "monthly_fee_mvr": 100, "status": "open"})
        cls.b1 = post("/api/batches", {"course_id": cls.course, "code": "M1", "teacher_id": cls.t[0], "capacity": 9, "days": "Mon", "start_time": "16:00"})
        cls.b2 = post("/api/batches", {"course_id": cls.course, "code": "M2", "capacity": 9, "days": "Tue", "start_time": "16:00"})
        cls.c.post("/api/enrollments", json={"student_id": cls.s[0], "batch_id": cls.b1}, headers=cls.H)
        cls.T = cls.tok(cls.t[1], PW)
        cls.c.post(f"/api/batches/{cls.b1}/assignments", json={"title": "W", "max_points": 10}, headers=cls.T)
        con = sqlite3.connect(cls.path)   # rows with a chosen time, to test the date range around Maldives midnight (UTC+5)
        for at, act in (("2027-03-09 18:59:59", "zz_test"), ("2027-03-09 19:00:00", "zz_test"), ("2027-03-10 18:59:59", "zz_test"), ("2027-03-10 19:00:00", "zz_test")):
            con.execute("INSERT INTO audit_log(action,detail,at) VALUES(?,?,?)", (act, "=1+1 danger" if at.endswith("19:00:00") and at.startswith("2027-03-10") else "plain", at))
        con.commit(); con.close()

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def make(cls, role, name, **kw):
        cls.n += 1; email = f"p{cls.n}@s21.test"
        r = cls.c.post("/api/users", json={"email": email, "password": PW, "full_name": name, "role": role, **kw}, headers=cls.H)
        return r.get_json()["id"], email

    def sql(self, q, a=()):
        con = sqlite3.connect(self.path)
        try: return con.execute(q, a).fetchall()
        finally: con.close()

    def get(self, q="", path="/api/audit", H=None):
        return self.c.get(path + ("?" + q if q else ""), headers=H or self.H)

    def test_01_filters_match_direct_counts(self):
        tid = self.t[0]
        cases = [(f"user_id={tid}", "user_id=?", (tid,)), ("role=teacher", "user_role='teacher'", ()), (f"batch_id={self.b1}", "batch_id=?", (self.b1,)),
                 (f"course_id={self.course}", "course_id=?", (self.course,)), ("action=login,logout", "action IN ('login','logout')", ()),
                 ("action=create_batch", "action='create_batch'", ()), ("q=danger", "detail LIKE '%danger%'", ()), ("entity=batch", "entity='batch'", ())]
        for q, cond, a in cases:
            r = self.get(q); self.assertEqual(r.status_code, 200, q)
            want = self.sql(f"SELECT COUNT(*) FROM audit_log WHERE {cond}", a)[0][0]
            self.assertGreater(want, 0, q)
            self.assertEqual(int(r.headers["X-Total-Count"]), want, q); self.assertEqual(len(r.get_json()), min(want, 100), q)
        row = self.get("login_id=" + self.sql("SELECT login_id FROM users WHERE id=?", (tid,))[0][0].lower()).get_json()
        self.assertTrue(row and all(x["user_id"] == tid for x in row))      # login ID filter ignores case
        both = self.get(f"role=teacher&batch_id={self.b1}").get_json()
        self.assertTrue(both and all(x["user_role"] == "teacher" and x["batch_id"] == self.b1 for x in both))   # filters combine
        self.assertEqual(self.get("action=no_such_action").get_json(), [])

    def test_02_date_range_uses_maldives_days(self):
        ids = lambda q: sorted(x["at"] for x in self.get("action=zz_test&" + q).get_json())
        self.assertEqual(ids("date_from=2027-03-10&date_to=2027-03-10"), ["2027-03-09 19:00:00", "2027-03-10 18:59:59"])   # 00:00 to 23:59 Maldives time
        self.assertEqual(ids("date_from=2027-03-10"), ["2027-03-09 19:00:00", "2027-03-10 18:59:59", "2027-03-10 19:00:00"])
        self.assertEqual(ids("date_to=2027-03-09"), ["2027-03-09 18:59:59"])
        self.assertEqual(self.get("date_from=10-03-2027").status_code, 400)

    def test_03_paging(self):
        total = int(self.get().headers["X-Total-Count"]); self.assertGreater(total, 6)
        p1, p2 = self.get("per_page=3&page=1"), self.get("per_page=3&page=2")
        a, b = p1.get_json(), p2.get_json()
        self.assertEqual((len(a), len(b), p1.headers["X-Per-Page"], p2.headers["X-Page"], int(p1.headers["X-Total-Count"])), (3, 3, "3", "2", total))
        self.assertFalse({x["id"] for x in a} & {x["id"] for x in b})
        self.assertGreater(min(x["id"] for x in a), max(x["id"] for x in b))                 # newest first
        last = self.get(f"per_page=3&page={(total + 2) // 3 + 1}").get_json(); self.assertEqual(last, [])
        self.assertEqual(self.get("per_page=100000").headers["X-Per-Page"], "500")           # capped
        self.assertEqual(self.get("page=abc").status_code, 400)

    def test_04_csv_is_filtered_safe_and_logged(self):
        r = self.get("action=zz_test", "/api/audit.csv")
        self.assertEqual((r.status_code, r.mimetype), (200, "text/csv")); self.assertIn("attachment", r.headers["Content-Disposition"])
        rows = list(csv.reader(io.StringIO(r.get_data(as_text=True).lstrip("\ufeff"))))   # v0.8.34: BOM
        self.assertEqual(rows[0][:7], ["id", "at", "user_id", "user_name", "user_role", "login_id", "action"]); self.assertEqual(len(rows) - 1, 4)
        self.assertTrue(any(x[-1] == "'=1+1 danger" for x in rows[1:]))                      # a formula cannot run when opened in Excel
        ex = self.sql("SELECT user_role,detail FROM audit_log WHERE action='export_audit_csv' ORDER BY id DESC")[0]
        self.assertEqual(ex[0], "admin"); self.assertIn("4 rows", ex[1])
        self.assertEqual(self.get("date_from=bad", "/api/audit.csv").status_code, 400)

    def test_05_drill_down_summary(self):
        s = self.get(f"user_id={self.t[0]}", "/api/audit/summary").get_json()
        self.assertEqual(s["total"], self.sql("SELECT COUNT(*) FROM audit_log WHERE user_id=?", (self.t[0],))[0][0])
        self.assertEqual({x["action"]: x["n"] for x in s["by_action"]}, dict(self.sql("SELECT action,COUNT(*) FROM audit_log WHERE user_id=? GROUP BY action", (self.t[0],))))
        self.assertTrue(s["first_at"] <= s["last_at"]); self.assertEqual([x["user_id"] for x in s["by_user"]], [self.t[0]])
        sb = self.get(f"batch_id={self.b1}", "/api/audit/summary").get_json()
        self.assertEqual(sb["total"], self.sql("SELECT COUNT(*) FROM audit_log WHERE batch_id=?", (self.b1,))[0][0])
        self.assertEqual({x["user_role"] for x in sb["by_user"]}, {"admin", "teacher"})
        self.assertEqual(sum(x["n"] for x in sb["by_user"]), sb["total"])
        self.assertIn("create_batch", self.get(path="/api/audit/actions").get_json())

    def test_06_access_rules(self):
        S = self.tok(self.s[1], PW); lim = self.tok(self.make("admin", "Limited", permissions=["courses"])[1], PW)
        for path in ("/api/audit", "/api/audit.csv", "/api/audit/summary", "/api/audit/actions"):
            self.assertEqual(self.c.get(path).status_code, 401, path)
            for H in (self.T, S, lim): self.assertEqual(self.c.get(path, headers=H).status_code, 403, path)
        self.assertEqual(self.get("user_id=x").status_code, 400)

    def test_07_no_route_changes_or_deletes_the_log(self):
        for path in ("/api/audit", "/api/audit/1", "/api/audit.csv", "/api/audit/summary"):
            for m in ("post", "put", "patch", "delete"):
                self.assertIn(getattr(self.c, m)(path, json={"detail": "x"}, headers=self.H).status_code, (404, 405), (m, path))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM audit_log WHERE detail='x'")[0][0], 0)

    def test_08_database_refuses_update_and_delete(self):
        con = sqlite3.connect(self.path)
        try:
            rid, det = con.execute("SELECT id,detail FROM audit_log WHERE action='create_batch' LIMIT 1").fetchone()
            for q in ("UPDATE audit_log SET detail='tampered' WHERE id=%d" % rid, "UPDATE audit_log SET action='x'", "DELETE FROM audit_log WHERE id=%d" % rid, "DELETE FROM audit_log"):
                with self.assertRaises(sqlite3.DatabaseError) as cx: con.execute(q)
                self.assertIn("append-only", str(cx.exception))
            con.rollback()
            self.assertEqual(con.execute("SELECT detail FROM audit_log WHERE id=?", (rid,)).fetchone()[0], det)
            con.execute("INSERT INTO audit_log(action) VALUES('still_append')"); con.commit()   # adding is still fine
            self.assertEqual(con.execute("SELECT COUNT(*) FROM audit_unlock").fetchone()[0], 0)  # the backfill switch is off
        finally: con.close()

    def test_09_backfill_still_works_and_switch_is_off_afterwards(self):
        import dbx, migrate_session20
        con = sqlite3.connect(self.path); con.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,detail) VALUES(1,'update_batch','batch',?, 'legacy')", (self.b1,)); con.commit(); con.close()
        conn = dbx.connect(self.app.config, ROOT)
        try:
            migrate_session20.run(conn, apply=False, log=lambda *a: None)                       # dry run: rolled back
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_unlock").fetchone()[0], 0)
            self.assertIsNone(conn.execute("SELECT batch_id FROM audit_log WHERE detail='legacy'").fetchone()[0])
            migrate_session20.run(conn, apply=True, log=lambda *a: None)
            self.assertEqual(conn.execute("SELECT batch_id FROM audit_log WHERE detail='legacy'").fetchone()[0], self.b1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit_unlock").fetchone()[0], 0)
            with self.assertRaises(Exception): conn.execute("UPDATE audit_log SET detail='x' WHERE detail='legacy'")
            conn.rollback()
        finally: conn.close()

    def test_10_upgrade_installs_triggers_on_old_database(self):
        import dbx
        p = os.path.join(tempfile.mkdtemp(), "old.db"); con = sqlite3.connect(p)
        con.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT NOT NULL, entity TEXT, entity_id INTEGER, detail TEXT, at TEXT NOT NULL DEFAULT (datetime('now')))")
        con.execute("INSERT INTO audit_log(action,detail) VALUES('enroll','kept')"); con.commit(); con.close()
        conn = dbx.connect({"DATABASE_PATH": p}, ROOT)
        try:
            dbx.init_schema(conn, ROOT); dbx.init_schema(conn, ROOT)
            self.assertEqual(conn.execute("SELECT detail FROM audit_log").fetchone()[0], "kept")
            with self.assertRaises(Exception): conn.execute("DELETE FROM audit_log")
            conn.rollback()
        finally: conn.close()


if __name__ == "__main__":
    unittest.main()
