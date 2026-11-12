"""Session 13: transfers and withdrawals: events, hidden old-batch content, kept history, admin report + CSV, backfill migration."""
import io, os, sys, tempfile, unittest, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
PDF = b"%PDF-1.4\n%test\n"


def one_row(app, sql, *a):
    import dbx
    conn = dbx.connect(app.config, ROOT)
    try: return conn.execute(sql, a).fetchone()[0]
    finally: conn.close()


class S13(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ.update(DATABASE_PATH=os.path.join(tmp, "t.db"), ADMIN_EMAIL="admin@s13.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})
        cls.c = cls.app.test_client()
        cls.H = cls.tok("admin@s13.test", "AdminPass123")
        cls.n = 0
        cls.teacher = cls.make("teacher", "T13 Teacher")[0]
        cid = cls.c.post("/api/courses", json={"name": "Arabic Level 1", "monthly_fee_mvr": 200, "status": "open"}, headers=cls.H).get_json()["id"]
        cls.cid = cid
        cls.A = cls.c.post("/api/batches", json={"course_id": cid, "code": "S13A", "teacher_id": cls.teacher, "capacity": 5}, headers=cls.H).get_json()["id"]
        cls.B = cls.c.post("/api/batches", json={"course_id": cid, "code": "S13B", "teacher_id": cls.teacher, "capacity": 5}, headers=cls.H).get_json()["id"]

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def make(cls, role, name):
        cls.n += 1
        email = f"p{cls.n}@s13.test"
        r = cls.c.post("/api/users", json={"email": email, "password": PW, "full_name": name, "role": role}, headers=cls.H)
        assert r.status_code == 201, r.get_json()
        return r.get_json()["id"], email

    def J(self, m, u, **k):
        k.setdefault("headers", self.H)
        return getattr(self.c, m)(u, **k)

    def student_in(self, batch, name="S13 Student"):
        sid, email = self.make("student", name)
        r = self.J("post", "/api/enrollments", json={"student_id": sid, "batch_id": batch}); self.assertEqual(r.status_code, 201)
        return sid, r.get_json()["id"], self.tok(email, PW)

    def content(self, batch):
        a = self.J("post", f"/api/batches/{batch}/assignments", data={"title": "HW", "file": (io.BytesIO(PDF), "hw.pdf")}, content_type="multipart/form-data")
        m = self.J("post", f"/api/batches/{batch}/materials", data={"title": "Notes", "file": (io.BytesIO(PDF), "n.pdf")}, content_type="multipart/form-data")
        self.assertEqual((a.status_code, m.status_code), (201, 201), (a.get_json(), m.get_json()))
        return a.get_json()["id"], m.get_json()["id"]

    def test_01_transfer_hides_old_batch_content_keeps_history(self):
        aid, mid = self.content(self.A)
        sid, eid, S = self.student_in(self.A)
        # before: the student can see and use batch A
        self.assertEqual(len(self.J("get", f"/api/assignments?batch_id={self.A}", headers=S).get_json()), 1)
        self.assertEqual(self.J("get", f"/api/assignments/{aid}/attachment", headers=S).status_code, 200)
        self.assertEqual(self.J("post", f"/api/assignments/{aid}/submit", data={"text": "my answer"}, headers=S, content_type="multipart/form-data").status_code, 201)
        self.assertEqual(self.J("post", f"/api/assignments/{aid}/grades", json={"student_id": sid, "grade": 80, "feedback": "good"}).status_code, 200)
        r = self.J("patch", f"/api/enrollments/{eid}", json={"transfer_to_batch_id": self.B, "reason": "Moved to evening class", "effective_date": "2026-03-15"})
        self.assertEqual(r.status_code, 200, r.get_json())
        # after: everything of batch A is gone for the student
        self.assertEqual(self.J("get", f"/api/assignments?batch_id={self.A}", headers=S).status_code, 403)
        self.assertEqual(self.J("get", f"/api/materials?batch_id={self.A}", headers=S).status_code, 403)
        self.assertEqual(self.J("get", f"/api/recordings?batch_id={self.A}", headers=S).status_code, 403)
        self.assertEqual(self.J("get", f"/api/timetable?batch_id={self.A}", headers=S).status_code, 403)
        self.assertEqual(self.J("get", f"/api/assignments/{aid}/attachment", headers=S).status_code, 403)
        self.assertEqual(self.J("get", f"/api/materials/{mid}/file", headers=S).status_code, 403)
        self.assertEqual(self.J("post", f"/api/assignments/{aid}/submit", data={"text": "again"}, headers=S, content_type="multipart/form-data").status_code, 403)
        self.assertNotIn(self.A, [b["batch_id"] for b in self.J("get", "/api/my/grades", headers=S).get_json()])
        self.assertNotIn(self.A, [b["batch_id"] for b in self.J("get", "/api/my/attendance", headers=S).get_json()])
        # the admin keeps the history: submission and grade are still there, and one event was written
        info = self.J("get", f"/api/student-information/{sid}").get_json()
        old_batch = [p for p in info["progress"] if p["batch_id"] == self.A][0]
        self.assertEqual(old_batch["enrollment_status"], "dropped")
        self.assertEqual([i["grade"] for i in old_batch["items"] if i["id"] == aid], [80])       # the grade is still there for the admin
        self.assertEqual(one_row(self.app, "SELECT COUNT(*) FROM submissions WHERE student_id=?", sid), 1)
        ev = [x for x in self.J("get", f"/api/enrollment-events?student_id={sid}").get_json()]
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["kind"], ev[0]["from_batch_id"], ev[0]["to_batch_id"], ev[0]["effective_date"], ev[0]["reason"]),
                         ("transfer", self.A, self.B, "2026-03-15", "Moved to evening class"))
        self.assertEqual(ev[0]["from_batch_code"], "S13A"); self.assertEqual(ev[0]["to_batch_code"], "S13B")
        self.assertEqual(len(self.J("get", f"/api/assignments?batch_id={self.A}").get_json()), 1)   # admin still sees the batch content

    def test_02_withdrawal_event_once_and_bad_input(self):
        sid, eid, S = self.student_in(self.A, "Leaver")
        r = self.J("patch", f"/api/enrollments/{eid}", json={"status": "dropped", "effective_date": "2026-13-45"}); self.assertEqual(r.status_code, 400)
        self.assertEqual(self.J("get", f"/api/enrollment-events?student_id={sid}").get_json(), [])      # a refused request writes nothing
        self.assertEqual(self.J("patch", f"/api/enrollments/{eid}", json={"status": "dropped", "reason": "Family moved"}).status_code, 200)
        self.J("patch", f"/api/enrollments/{eid}", json={"status": "dropped"})                           # dropping again adds nothing
        ev = self.J("get", f"/api/enrollment-events?student_id={sid}").get_json()
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["kind"], ev[0]["from_batch_id"], ev[0]["to_batch_id"], ev[0]["reason"]), ("withdrawal", self.A, None, "Family moved"))
        self.assertEqual(ev[0]["effective_date"], dt.datetime.now(dt.timezone(dt.timedelta(hours=5))).strftime("%Y-%m-%d"))   # default = today (Maldives)
        self.assertEqual(self.J("get", f"/api/assignments?batch_id={self.A}", headers=S).status_code, 403)
        # a transfer into a full batch fails and writes no event
        full = self.J("post", "/api/batches", json={"course_id": self.cid, "code": "S13F", "capacity": 1}).get_json()["id"]
        self.student_in(full, "Fills it")
        s2, e2, _ = self.student_in(self.A, "Blocked")
        self.assertEqual(self.J("patch", f"/api/enrollments/{e2}", json={"transfer_to_batch_id": full}).status_code, 409)
        self.assertEqual(self.J("get", f"/api/enrollment-events?student_id={s2}").get_json(), [])

    def test_03_tutorials_follow_active_enrolment(self):
        t_course = self.J("post", "/api/tutorials", data={"title": "Course tutorial", "text": "hello", "course_id": str(self.cid), "file": (io.BytesIO(PDF), "t.pdf")}, content_type="multipart/form-data").get_json()["id"]
        t_open = self.J("post", "/api/tutorials", json={"title": "General tutorial", "text": "for all"}).get_json()["id"]
        sid, eid, S = self.student_in(self.B, "Tutorial kid")
        ids = lambda: [t["id"] for t in self.J("get", "/api/tutorials", headers=S).get_json()]
        self.assertIn(t_course, ids()); self.assertIn(t_open, ids())
        self.assertEqual(self.J("get", f"/api/tutorials/{t_course}/file", headers=S).status_code, 200)
        self.J("patch", f"/api/enrollments/{eid}", json={"status": "dropped"})
        self.assertNotIn(t_course, ids()); self.assertIn(t_open, ids())            # general tutorials stay
        self.assertEqual(self.J("get", f"/api/tutorials/{t_course}", headers=S).status_code, 403)
        self.assertEqual(self.J("get", f"/api/tutorials/{t_course}/file", headers=S).status_code, 403)
        self.assertEqual(self.J("get", f"/api/tutorials/{t_course}/submission", headers=S).status_code, 403)
        self.assertEqual(self.J("post", f"/api/tutorials/{t_course}/submission", data={"text": "x"}, headers=S, content_type="multipart/form-data").status_code, 403)
        self.assertEqual(self.J("get", "/api/tutorials/999999", headers=S).status_code, 404)    # missing is still 404
        self.assertEqual(self.J("get", f"/api/tutorials/{t_course}").status_code, 200)          # admin unaffected

    def test_04_completed_and_waitlist_students_do_not_see_batch_content(self):
        aid, mid = self.content(self.B)
        sid, eid, S = self.student_in(self.B, "Finisher")
        self.assertEqual(self.J("get", f"/api/materials/{mid}/file", headers=S).status_code, 200)
        self.J("patch", f"/api/enrollments/{eid}", json={"status": "completed"})
        self.assertEqual(self.J("get", f"/api/materials/{mid}/file", headers=S).status_code, 403)

    def test_05_report_filters_csv_and_permissions(self):
        sid, eid, _ = self.student_in(self.A, "=cmd Report kid")
        self.J("patch", f"/api/enrollments/{eid}", json={"transfer_to_batch_id": self.B, "effective_date": "2026-05-02", "reason": "r1"})
        r = self.J("get", "/api/enrollment-events?kind=transfer&from=2026-05-01&to=2026-05-31").get_json()
        self.assertTrue(any(x["student_id"] == sid for x in r)); self.assertTrue(all(x["kind"] == "transfer" for x in r))
        self.assertFalse(any(x["student_id"] == sid for x in self.J("get", "/api/enrollment-events?kind=withdrawal").get_json()))
        self.assertEqual([x["student_id"] for x in self.J("get", f"/api/enrollment-events?batch_id={self.B}&from=2026-05-01&to=2026-05-31").get_json() if x["student_id"] == sid], [sid])
        self.assertEqual(self.J("get", "/api/enrollment-events?kind=bogus").status_code, 400)
        self.assertEqual(self.J("get", "/api/enrollment-events?from=yesterday").status_code, 400)
        csv_r = self.J("get", "/api/enrollment-events.csv?from=2026-05-01&to=2026-05-31")
        self.assertEqual(csv_r.status_code, 200); self.assertIn("text/csv", csv_r.headers["Content-Type"]); self.assertIn("attachment", csv_r.headers["Content-Disposition"])
        text = csv_r.get_data(as_text=True).lstrip("\ufeff")   # v0.8.34: BOM for Excel
        self.assertTrue(text.startswith("date,type,student_id,student,previous_course,previous_batch,new_course,new_batch"))
        self.assertIn("2026-05-02,transfer", text); self.assertIn("'=cmd", text)            # formula text is neutralised
        self.assertTrue(self.J("get", "/api/audit").get_json()[0]["action"] == "export_enrollment_events_csv")
        # who may read it
        _, em = self.make("student", "Nosy"); _, tm = self.make("teacher", "Nosy teacher")
        self.assertEqual(self.c.get("/api/enrollment-events").status_code, 401)
        for e in (em, tm):
            H = self.tok(e, PW)
            self.assertEqual(self.c.get("/api/enrollment-events", headers=H).status_code, 403)
            self.assertEqual(self.c.get("/api/enrollment-events.csv", headers=H).status_code, 403)
        uid, lim = self.make("admin", "Limited admin")
        self.assertEqual(self.J("patch", f"/api/users/{uid}", json={"permissions": ["fees"]}).status_code, 200)
        self.assertEqual(self.c.get("/api/enrollment-events", headers=self.tok(lim, PW)).status_code, 403)

    def test_06_migration_backfills_old_dropped_enrolments_once(self):
        import dbx, migrate_session13 as mg
        conn = dbx.connect(self.app.config, ROOT)
        try:
            # old-style rows: a logged transfer, a logged drop, an unlogged drop with a later enrolment in the same course, an unlogged lone drop
            def stu(tag):
                conn.execute("INSERT INTO users(email,password_hash,full_name,role) VALUES(?,?,?,'student')", (f"{tag}@old.test", "x", tag))
                return conn.execute("SELECT id FROM users WHERE email=?", (f"{tag}@old.test",)).fetchone()[0]
            def enr(s, b, status, at):
                conn.execute("INSERT INTO enrollments(student_id,batch_id,status,enrolled_at) VALUES(?,?,?,?)", (s, b, status, at))
                return conn.execute("SELECT id FROM enrollments WHERE student_id=? AND batch_id=?", (s, b)).fetchone()[0]
            s1, s2, s3, s4 = stu("o1"), stu("o2"), stu("o3"), stu("o4")
            e1 = enr(s1, self.A, "dropped", "2025-01-01 10:00:00"); enr(s1, self.B, "active", "2025-03-01 10:00:00")
            conn.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,detail,at) VALUES(1,'transfer','enrollment',?,?,?)", (e1, f"to batch {self.B}", "2025-03-01 10:00:00"))
            e2 = enr(s2, self.A, "dropped", "2025-01-01 10:00:00")
            conn.execute("INSERT INTO audit_log(user_id,action,entity,entity_id,detail,at) VALUES(1,'enrollment_status','enrollment',?,'dropped',?)", (e2, "2025-04-10 09:00:00"))
            enr(s3, self.A, "dropped", "2025-01-01 10:00:00"); enr(s3, self.B, "active", "2025-02-01 10:00:00")
            enr(s4, self.A, "dropped", "2025-01-01 10:00:00")
            conn.commit()
            n_enr = conn.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0]
            before = conn.execute("SELECT COUNT(*) FROM enrollment_events").fetchone()[0]
            ev, _, _ = mg.run(conn, apply=False, log=lambda *_: None)        # dry run changes nothing
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM enrollment_events").fetchone()[0], before)
            self.assertEqual(len([e for e in ev if e["student_id"] in (s1, s2, s3, s4)]), 4)
            ev, b, a = mg.run(conn, apply=True, log=lambda *_: None)
            self.assertEqual(a - b, len(ev)); self.assertEqual(conn.execute("SELECT COUNT(*) FROM enrollments").fetchone()[0], n_enr)
            get = lambda s: dict(conn.execute("SELECT kind,from_batch_id,to_batch_id,effective_date,by_user FROM enrollment_events WHERE student_id=?", (s,)).fetchone())
            self.assertEqual(get(s1), {"kind": "transfer", "from_batch_id": self.A, "to_batch_id": self.B, "effective_date": "2025-03-01", "by_user": 1})
            self.assertEqual(get(s2), {"kind": "withdrawal", "from_batch_id": self.A, "to_batch_id": None, "effective_date": "2025-04-10", "by_user": 1})
            g3 = get(s3); self.assertEqual((g3["kind"], g3["to_batch_id"], g3["effective_date"]), ("transfer", self.B, "2025-02-01"))
            g4 = get(s4); self.assertEqual((g4["kind"], g4["effective_date"]), ("withdrawal", None))
            ev2, b2, a2 = mg.run(conn, apply=True, log=lambda *_: None)      # second run: nothing to do
            self.assertEqual((ev2, a2 - b2), ([], 0))
        finally: conn.close()
        with self.assertRaises(SystemExit): mg.main(["--apply"])             # refuses without the backup flag


if __name__ == "__main__":
    unittest.main()
