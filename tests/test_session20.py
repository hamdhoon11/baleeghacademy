"""Session 20: activity log v2. Each action is performed through the API and the log row is checked for user, role, login ID, batch/course and old/new values."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
MVT = dt.timezone(dt.timedelta(hours=5))


class S20(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s20.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path, "CRON_SECRET": "s20-secret"})
        cls.app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 12, 0, tzinfo=MVT)
        cls.c = cls.app.test_client()
        cls.H = cls.tok("admin@s20.test", "AdminPass123"); cls.n = 0
        cls.t1, cls.t2 = cls.make("teacher", "T One"), cls.make("teacher", "T Two")
        cls.s1, cls.s2 = cls.make("student", "S One"), cls.make("student", "S Two")
        cls.course = cls.c.post("/api/courses", json={"name": "Arabic L1", "monthly_fee_mvr": 100, "status": "open"}, headers=cls.H).get_json()["id"]
        cls.batch = cls.c.post("/api/batches", json={"course_id": cls.course, "code": "A1", "teacher_id": cls.t1[0], "capacity": 9, "days": "Mon", "start_time": "16:00"}, headers=cls.H).get_json()["id"]
        cls.batch2 = cls.c.post("/api/batches", json={"course_id": cls.course, "code": "A2", "capacity": 9, "days": "Tue", "start_time": "16:00"}, headers=cls.H).get_json()["id"]

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def make(cls, role, name):
        cls.n += 1; email = f"p{cls.n}@s20.test"
        r = cls.c.post("/api/users", json={"email": email, "password": PW, "full_name": name, "role": role}, headers=cls.H)
        return r.get_json()["id"], email

    def log(self, action, **where):
        q = "SELECT * FROM audit_log WHERE action=?" + "".join(f" AND {k}=?" for k in where) + " ORDER BY id DESC"
        con = sqlite3.connect(self.path); con.row_factory = sqlite3.Row
        try: return [dict(r) for r in con.execute(q, (action, *where.values()))]
        finally: con.close()

    def admin_row(self):
        con = sqlite3.connect(self.path)
        try: return con.execute("SELECT id,login_id FROM users WHERE email='admin@s20.test'").fetchone()
        finally: con.close()

    def test_01_course_batch_teacher_rows(self):
        aid, alogin = self.admin_row()
        r = self.log("create_batch", entity_id=self.batch)[0]
        self.assertEqual((r["user_id"], r["user_role"], r["login_id"], r["batch_id"], r["course_id"]), (aid, "admin", alogin, self.batch, self.course))
        self.assertTrue(r["ip"])
        c = self.log("create_course", entity_id=self.course)[0]
        self.assertEqual((c["course_id"], c["user_role"]), (self.course, "admin"))
        t = self.log("assign_teacher", batch_id=self.batch)[0]
        self.assertEqual((t["old_value"], t["new_value"]), (None, str(self.t1[0])))
        self.assertEqual(self.c.patch(f"/api/batches/{self.batch}", json={"teacher_id": self.t2[0]}, headers=self.H).status_code, 200)
        t = self.log("assign_teacher", batch_id=self.batch)[0]
        self.assertEqual((t["old_value"], t["new_value"]), (str(self.t1[0]), str(self.t2[0])))
        self.assertEqual(self.c.patch(f"/api/batches/{self.batch}", json={"teacher_id": self.t1[0]}, headers=self.H).status_code, 200)

    def test_02_login_logout_failed_login_without_secrets(self):
        T = self.tok(self.t1[1], PW)
        self.assertEqual(self.c.post("/api/auth/logout", headers=T).status_code, 200)
        self.assertEqual(self.c.post("/api/auth/logout").status_code, 401)
        con = sqlite3.connect(self.path); tid, tlogin = con.execute("SELECT id,login_id FROM users WHERE email=?", (self.t1[1],)).fetchone(); con.close()
        lo = self.log("logout", user_id=tid)[0]; self.assertEqual((lo["user_role"], lo["login_id"]), ("teacher", tlogin))
        li = self.log("login", user_id=tid)[0]; self.assertEqual(li["user_role"], "teacher")
        self.assertEqual(self.c.post("/api/auth/login", json={"login": self.t1[1], "password": "WRONG-pass-123"}).status_code, 401)
        self.assertEqual(self.c.post("/api/auth/login", json={"login": "NOBODY/X/1", "password": "WRONG-pass-456"}).status_code, 401)
        f = self.log("failed_login")
        self.assertEqual(f[0]["detail"], "unknown ID"); self.assertEqual((f[0]["user_role"], f[0]["login_id"], f[0]["user_id"]), ("anonymous", "NOBODY/X/1", None))
        self.assertEqual((f[1]["detail"], f[1]["entity_id"], f[1]["user_id"]), ("wrong password", tid, None))   # the attempt is on that account, not by it
        con = sqlite3.connect(self.path); dump = " ".join(str(v) for r in con.execute("SELECT * FROM audit_log") for v in r); con.close()
        for secret in ("WRONG-pass-123", "WRONG-pass-456", PW, "AdminPass123"): self.assertNotIn(secret, dump)

    def test_03_enrol_transfer_status_attendance(self):
        e = self.c.post("/api/enrollments", json={"student_id": self.s1[0], "batch_id": self.batch}, headers=self.H).get_json()["id"]
        r = self.log("enroll", entity_id=e)[0]; self.assertEqual((r["batch_id"], r["course_id"], r["new_value"], r["user_role"]), (self.batch, self.course, "active", "admin"))
        self.c.post("/api/enrollments", json={"student_id": self.s2[0], "batch_id": self.batch}, headers=self.H)
        T = self.tok(self.t1[1], PW)
        att = lambda recs: self.c.post(f"/api/batches/{self.batch}/attendance", json={"date": "2027-03-08", "records": [{"student_id": s, "status": st} for s, st in recs]}, headers=T).status_code
        self.assertEqual(att([(self.s1[0], "present"), (self.s2[0], "absent")]), 200)
        first = self.log("mark_attendance", batch_id=self.batch)[0]
        self.assertEqual((first["old_value"], first["user_role"]), (None, "teacher")); self.assertIn(f"{self.s2[0]}:absent", first["new_value"])
        self.assertEqual(att([(self.s1[0], "present"), (self.s2[0], "late")]), 200)
        second = self.log("mark_attendance", batch_id=self.batch)[0]
        self.assertEqual((second["old_value"], second["new_value"]), (f"{self.s2[0]}:absent", f"{self.s2[0]}:late"))   # only the changed mark
        self.assertEqual(self.c.patch(f"/api/enrollments/{e}", json={"transfer_to_batch_id": self.batch2}, headers=self.H).status_code, 200)
        tr = self.log("transfer", entity_id=e)[0]; self.assertEqual((tr["batch_id"], tr["old_value"], tr["new_value"]), (self.batch, str(self.batch), str(self.batch2)))
        e2 = self.c.get("/api/enrollments", headers=self.H).get_json()
        eid2 = [x["id"] for x in e2 if x["student_id"] == self.s1[0] and x["batch_id"] == self.batch2][0]
        self.assertEqual(self.c.patch(f"/api/enrollments/{eid2}", json={"status": "dropped"}, headers=self.H).status_code, 200)
        st = self.log("enrollment_status", entity_id=eid2)[0]; self.assertEqual((st["batch_id"], st["old_value"], st["new_value"]), (self.batch2, "active", "dropped"))

    def test_04_assignment_submission_grade_change(self):
        T = self.tok(self.t1[1], PW)
        aid = self.c.post(f"/api/batches/{self.batch}/assignments", json={"title": "W1", "max_points": 10}, headers=T).get_json()["id"]
        r = self.log("create_assignment", entity_id=aid)[0]; self.assertEqual((r["batch_id"], r["course_id"], r["user_role"]), (self.batch, self.course, "teacher"))
        S = self.tok(self.s2[1], PW)
        self.assertIn(self.c.post(f"/api/assignments/{aid}/submit", data={"text": "a"}, headers=S, content_type="multipart/form-data").status_code, (200, 201))
        self.assertIn(self.c.post(f"/api/assignments/{aid}/submit", data={"text": "b"}, headers=S, content_type="multipart/form-data").status_code, (200, 201))
        subs = self.log("submit_assignment", batch_id=self.batch)
        self.assertEqual((subs[0]["old_value"], subs[0]["new_value"], subs[1]["old_value"], subs[0]["user_role"]), ("resubmitted", "submitted", None, "student"))
        g = lambda H, v: self.c.post(f"/api/assignments/{aid}/grades", json={"student_id": self.s2[0], "grade": v}, headers=H).status_code
        self.assertEqual(g(T, 6), 200)
        r = self.log("grade", batch_id=self.batch)[0]; self.assertEqual((r["old_value"], r["new_value"], r["user_role"]), (None, "6", "teacher"))
        self.assertEqual(g(T, 9), 403)                       # no edit_grades: refused and nothing logged
        self.assertEqual(len(self.log("grade_change", batch_id=self.batch)), 0)
        self.assertEqual(g(self.H, 9), 200)
        r = self.log("grade_change", batch_id=self.batch)[0]; self.assertEqual((r["old_value"], r["new_value"], r["user_role"], r["course_id"]), ("6", "9", "admin", self.course))

    def test_05_permission_change_and_password_reset(self):
        self.assertEqual(self.c.patch(f"/api/users/{self.t1[0]}", json={"permissions": ["classroom", "edit_grades"]}, headers=self.H).status_code, 200)
        r = self.log("permission_change", entity_id=self.t1[0])[0]
        self.assertEqual((r["old_value"], r["user_role"]), ("all", "admin")); self.assertIn("edit_grades", r["new_value"])
        self.assertEqual(self.c.patch(f"/api/users/{self.t1[0]}", json={"permissions": "all"}, headers=self.H).status_code, 200)
        r = self.log("permission_change", entity_id=self.t1[0])[0]; self.assertEqual(r["new_value"], "all"); self.assertIn("edit_grades", r["old_value"])
        out = self.c.post(f"/api/users/{self.s1[0]}/reset-password", headers=self.H); self.assertEqual(out.status_code, 200)
        rp = self.log("reset_password", entity_id=self.s1[0])[0]; self.assertEqual(rp["user_role"], "admin")
        secrets_ = [v for k, v in out.get_json().items() if "password" in k and isinstance(v, str)]
        self.assertTrue(secrets_)
        for v in secrets_: self.assertNotIn(v, str(rp))   # the temporary password is not in the log row

    def test_06_invoice_generation_admin_and_cron(self):
        self.assertEqual(self.c.post("/api/invoices/generate", json={"month": "2027-03"}, headers=self.H).status_code, 200)
        a = self.log("generate_invoices")[0]; self.assertEqual(a["user_role"], "admin")
        c0 = self.c.post("/api/courses", json={"name": "Free at first", "monthly_fee_mvr": 0, "status": "open"}, headers=self.H).get_json()["id"]
        b0 = self.c.post("/api/batches", json={"course_id": c0, "code": "F1", "capacity": 9, "days": "Mon", "start_time": "16:00"}, headers=self.H).get_json()["id"]
        self.c.post("/api/enrollments", json={"student_id": self.s1[0], "batch_id": b0}, headers=self.H)            # fee 0: no invoice yet
        self.assertEqual(self.c.patch(f"/api/courses/{c0}", json={"monthly_fee_mvr": 100}, headers=self.H).status_code, 200)   # now the scheduled run has something to create
        con = sqlite3.connect(self.path); con.execute("DELETE FROM invoices WHERE batch_id=?", (b0,)); con.commit(); con.close()   # test only: make one invoice missing again
        r = self.c.post("/api/cron/generate-invoices", headers={"Authorization": "Bearer s20-secret"}); self.assertEqual(r.status_code, 200)
        rows = self.log("generate_invoices"); sysrows = [x for x in rows if x["user_role"] == "system"]
        self.assertTrue(sysrows, rows); self.assertIsNone(sysrows[0]["user_id"])

    def test_07_old_rows_stay_readable_and_backfill_is_safe_twice(self):
        con = sqlite3.connect(self.path)
        aid, = con.execute("SELECT id FROM users WHERE email='admin@s20.test'").fetchone()
        con.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,detail) VALUES(?,?,?,?,?)", (aid, "update_batch", "batch", self.batch, "old style row"))
        con.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,detail) VALUES(?,?,?,?,?)", (aid, "grade_change", "assignment", 1, "student 5: grade 6 -> 9 (max 10); feedback unchanged"))
        con.commit(); con.close()
        self.assertEqual(self.c.get("/api/audit", headers=self.H).status_code, 200)       # the viewer still reads mixed rows
        import dbx, auditlog, migrate_session20
        conn = dbx.connect(self.app.config, ROOT)
        try:
            ch, before, after = migrate_session20.run(conn, apply=False, log=lambda *a: None)       # dry run changes nothing
            self.assertEqual(before, after)
            self.assertIsNone(conn.execute("SELECT user_role FROM audit_log WHERE detail='old style row'").fetchone()[0])
            migrate_session20.run(conn, apply=True, log=lambda *a: None)
            r = conn.execute("SELECT user_role,login_id,batch_id,course_id FROM audit_log WHERE detail='old style row'").fetchone()
            self.assertEqual((r[0], r[2], r[3]), ("admin", self.batch, self.course)); self.assertTrue(r[1])
            g = conn.execute("SELECT old_value,new_value FROM audit_log WHERE detail LIKE 'student 5: grade 6 -> 9%'").fetchone(); self.assertEqual(tuple(g), ("6", "9"))
            again = auditlog.backfill(conn); conn.rollback()
            self.assertEqual(sum(again.values()), 0)                                                  # second run finds nothing
        finally: conn.close()

    def test_08_upgrade_of_an_old_database_adds_columns_and_keeps_rows(self):
        import dbx
        p = os.path.join(tempfile.mkdtemp(), "old.db")
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE audit_log (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT NOT NULL, entity TEXT, entity_id INTEGER, detail TEXT, at TEXT NOT NULL DEFAULT (datetime('now')))")
        con.execute("INSERT INTO audit_log(user_id,action,detail) VALUES(7,'enroll','kept')"); con.commit(); con.close()
        conn = dbx.connect({"DATABASE_PATH": p}, ROOT)
        try:
            dbx.init_schema(conn, ROOT); dbx.init_schema(conn, ROOT)                                   # twice is fine
            self.assertTrue({"user_role", "login_id", "course_id", "batch_id", "old_value", "new_value", "ip"} <= conn.columns("audit_log"))
            r = conn.execute("SELECT detail,user_role FROM audit_log").fetchone(); self.assertEqual((r[0], r[1]), ("kept", None))
        finally: conn.close()


if __name__ == "__main__":
    unittest.main()
