"""Session 28: in-app notifications, event hooks, announcements and the scheduled reminder run."""
import datetime as dt, io, os, sqlite3, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
MVT = dt.timezone(dt.timedelta(hours=5))
PDF = b"%PDF-1.4 slip"


def make_app(tag):
    tmp = tempfile.mkdtemp(); path = os.path.join(tmp, "t.db")
    old = os.environ.get("SEED_DEMO")
    os.environ.update(DATABASE_PATH=path, ADMIN_EMAIL=f"admin@{tag}.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
    import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
    os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
    from app import create_app
    app = create_app({"DATABASE_PATH": path}); c = app.test_client()
    app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 12, 0, tzinfo=MVT)
    tok = c.post("/api/auth/login", json={"login": f"admin@{tag}.test", "password": "AdminPass123"}).get_json()["token"]
    return app, c, {"Authorization": "Bearer " + tok}, path


class S28(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.c, cls.H, cls.path = make_app("a28")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": kw.pop("n", e), "role": role, **kw}).get_json()["id"]
        cls.t1, cls.t2 = mk("t1@a28.test", "teacher", n="Teacher One"), mk("t2@a28.test", "teacher", n="Teacher Two")
        cls.ar = P("/api/courses", {"name": "Arabic", "code": "AR1", "monthly_fee_mvr": 1000, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": cls.ar, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Wed", "start_time": "16:00"}).get_json()["id"]
        cls.s1 = mk("s1@a28.test", "student", n="Student One", course_id=cls.ar)
        cls.s2 = mk("s2@a28.test", "student", n="Student Two", course_id=cls.ar)
        cls.s3 = mk("s3@a28.test", "student", n="Student Three")        # not enrolled anywhere
        for s in (cls.s1, cls.s2): assert P("/api/enrollments", {"student_id": s, "batch_id": cls.b1}).status_code == 201
        cls.lim = mk("lim@a28.test", "admin", permissions=["people"])
        cls.S1, cls.S2, cls.S3, cls.T1, cls.T2, cls.L = (cls.tok(x) for x in ("s1@a28.test", "s2@a28.test", "s3@a28.test", "t1@a28.test", "t2@a28.test", "lim@a28.test"))

    @classmethod
    def tok(cls, login, pw=PW):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    def sql(self, q, a=()):
        db = sqlite3.connect(self.path); db.row_factory = sqlite3.Row
        try:
            r = [dict(x) for x in db.execute(q, a).fetchall()]; db.commit(); return r
        finally: db.close()

    def inbox(self, h, **q):
        r = self.c.get("/api/notifications", query_string=q, headers=h); self.assertEqual(r.status_code, 200); return r.get_json()

    def kinds(self, h): return [i["kind"] for i in self.inbox(h)["items"]]
    def count(self, kind=None, uid=None):
        w, a = [], []
        if kind: w.append("kind=?"); a.append(kind)
        if uid: w.append("user_id=?"); a.append(uid)
        return self.sql("SELECT COUNT(*) n FROM notifications" + (" WHERE " + " AND ".join(w) if w else ""), a)[0]["n"]
    def setclock(self, y, m, d): self.app.config["NOW"] = lambda: dt.datetime(y, m, d, 12, 0, tzinfo=MVT)
    def put(self, **kw): self.assertEqual(self.c.put("/api/settings", json=kw, headers=self.H).status_code, 200)

    # ---------------- my notifications ----------------
    def test_01_needs_sign_in_and_starts_empty(self):
        for p in ("/api/notifications", "/api/notifications/unread-count"): self.assertEqual(self.c.get(p).status_code, 401)
        self.assertEqual(self.c.post("/api/notifications/read-all").status_code, 401)
        r = self.inbox(self.S3); self.assertEqual((r["items"], r["unread"]), ([], 0))
        self.assertEqual(self.c.get("/api/notifications?limit=x", headers=self.S3).status_code, 400)

    def test_02_assignment_notifies_enrolled_students_only(self):
        r = self.c.post(f"/api/batches/{self.b1}/assignments", json={"title": "Essay", "due_date": "2027-03-15", "max_points": 10}, headers=self.T1); self.assertEqual(r.status_code, 201)
        type(self).aid = r.get_json()["id"]
        for h in (self.S1, self.S2):
            it = [i for i in self.inbox(h)["items"] if i["kind"] == "assignment_new"]
            self.assertEqual(len(it), 1); self.assertIn("Essay", it[0]["body"]); self.assertIn("2027-03-15", it[0]["body"]); self.assertEqual(it[0]["link"], f"assignments:{self.aid}")   # v0.8.33: tab:id
        self.assertNotIn("assignment_new", self.kinds(self.S3)); self.assertNotIn("assignment_new", self.kinds(self.T1))

    def test_03_grade_and_grade_change(self):
        self.assertEqual(self.c.post(f"/api/assignments/{self.aid}/submit", data={"text": "my essay"}, headers=self.S1).status_code, 201)
        n0 = self.count("grade", self.s1)
        g = lambda h, v: self.c.post(f"/api/assignments/{self.aid}/grades", json={"student_id": self.s1, "grade": v}, headers=h)
        self.assertEqual(g(self.T1, 8).status_code, 200)
        it = [i for i in self.inbox(self.S1)["items"] if i["kind"] == "grade"]
        self.assertEqual((len(it), it[0]["title"]), (n0 + 1, "Assignment graded"))
        self.assertIn("8", it[0]["body"]); self.assertIn("/ 10", it[0]["body"])
        self.assertEqual(g(self.T1, 8).status_code, 200)                       # same value again: nothing new
        self.assertEqual(self.count("grade", self.s1), n0 + 1)
        self.assertEqual(g(self.T1, 9).status_code, 403)                       # teacher cannot change a saved grade: no notification either
        self.assertEqual(self.count("grade", self.s1), n0 + 1)
        self.assertEqual(g(self.H, 9).status_code, 200)
        self.assertEqual(self.count("grade", self.s1), n0 + 2)
        self.assertEqual(self.inbox(self.S1)["items"][0]["title"], "Grade updated")
        self.assertEqual(self.count("grade", self.s2), 0)

    def test_04_class_cancel_and_reinstate(self):
        s = lambda st, h=None, **kw: self.c.post(f"/api/batches/{self.b1}/sessions", json={"date": "2027-03-17", "start_time": "16:00", "status": st, **kw}, headers=h or self.H)
        self.assertEqual(s("cancelled", note="Public holiday").status_code, 201)
        for u in (self.s1, self.s2, self.t1): self.assertEqual(self.count("class_cancelled", u), 1, u)
        body = [i for i in self.inbox(self.S1)["items"] if i["kind"] == "class_cancelled"][0]["body"]
        self.assertIn("Public holiday", body); self.assertIn("16:00", body)
        self.assertEqual(s("cancelled").status_code, 201)                      # already cancelled: no second message
        self.assertEqual(self.count("class_cancelled"), 3)
        self.assertEqual(self.count("class_cancelled", self.s3), 0)
        self.assertEqual(s("scheduled").status_code, 201)
        for u in (self.s1, self.s2, self.t1): self.assertEqual(self.count("class_reinstated", u), 1, u)
        self.assertEqual(s("scheduled").status_code, 201); self.assertEqual(self.count("class_reinstated"), 3)

    def test_05_teacher_cancelling_does_not_notify_themselves(self):
        self.assertEqual(self.c.patch(f"/api/users/{self.t1}", json={"permissions": ["classroom", "cancel_class"]}, headers=self.H).status_code, 200)
        T1 = self.tok("t1@a28.test")
        n = self.count("class_cancelled", self.t1)
        r = self.c.post(f"/api/batches/{self.b1}/sessions", json={"date": "2027-03-24", "start_time": "16:00", "status": "cancelled"}, headers=T1); self.assertEqual(r.status_code, 201)
        self.assertEqual(self.count("class_cancelled", self.t1), n)            # the teacher did it
        self.assertEqual(self.count("class_cancelled", self.s1), 2)
        type(self).T1 = T1

    def test_06_substitution_notifies_everyone_involved(self):
        r = self.c.post("/api/substitutions", json={"batch_id": self.b1, "substitute_teacher_id": self.t2, "class_date": "2027-03-31", "reason": "Sick"}, headers=self.H); self.assertEqual(r.status_code, 201)
        sid = r.get_json()["id"]
        self.assertEqual(self.count("substitute_assigned", self.t2), 1); self.assertEqual(self.count("substitute_for_you", self.t1), 1)
        self.assertEqual((self.count("substitute_class", self.s1), self.count("substitute_class", self.s2), self.count("substitute_class", self.s3)), (1, 1, 0))
        self.assertIn("Sick", [i for i in self.inbox(self.T2)["items"] if i["kind"] == "substitute_assigned"][0]["body"])
        self.assertEqual(self.c.delete(f"/api/substitutions/{sid}", headers=self.H).status_code, 200)
        self.assertEqual((self.count("substitute_removed", self.t2), self.count("substitute_removed", self.t1), self.count("substitute_removed", self.s1)), (1, 1, 1))

    def test_07_slip_events(self):
        inv = self.sql("SELECT id FROM invoices WHERE student_id=? ORDER BY id", (self.s1,))[0]["id"]
        up = lambda amt: self.c.post(f"/api/invoices/{inv}/slips", data={"amount_mvr": str(amt), "transfer_date": "2027-03-09", "file": (io.BytesIO(PDF), "s.pdf")}, headers=self.S1, content_type="multipart/form-data")
        r = up(400); self.assertEqual(r.status_code, 201); sid = r.get_json()["id"]
        self.assertEqual(self.count("slip_uploaded", 1), 1)                    # the full admin (user 1) is told
        self.assertEqual(self.count("slip_uploaded", self.lim), 0)             # an admin without the fees area is not
        self.assertEqual(self.c.post(f"/api/slips/{sid}/verify", json={}, headers=self.H).status_code, 200)
        it = [i for i in self.inbox(self.S1)["items"] if i["kind"] == "slip_verified"]
        self.assertEqual(len(it), 1); self.assertIn("400", it[0]["body"]); self.assertEqual(it[0]["link"], f"fees:{inv}")
        sid2 = up(100).get_json()["id"]
        self.assertEqual(self.c.post(f"/api/slips/{sid2}/reject", json={"reason": "Blurry photo"}, headers=self.H).status_code, 200)
        it = [i for i in self.inbox(self.S1)["items"] if i["kind"] == "slip_rejected"]
        self.assertEqual(len(it), 1); self.assertIn("Blurry photo", it[0]["body"])
        self.assertEqual(self.count("slip_verified", self.s2), 0)
        self.assertEqual(self.c.post(f"/api/slips/{sid}/verify", json={}, headers=self.H).status_code, 409)   # already verified: no second message
        self.assertEqual(self.count("slip_verified", self.s1), 1)

    def test_08_a_failed_request_leaves_no_notification(self):
        n = self.count()
        r = self.c.post(f"/api/slips/99999/reject", json={"reason": "x"}, headers=self.H); self.assertEqual(r.status_code, 404)
        r = self.c.post(f"/api/batches/{self.b1}/assignments", json={"title": "Bad", "max_points": -5}, headers=self.T1); self.assertEqual(r.status_code, 400)
        self.assertEqual(self.count(), n)

    # ---------------- reading and marking ----------------
    def test_09_read_unread_and_privacy(self):
        r = self.inbox(self.S1); total, un = len(r["items"]), r["unread"]; self.assertEqual(un, total); self.assertGreater(total, 3)
        self.assertEqual(self.c.get("/api/notifications/unread-count", headers=self.S1).get_json()["unread"], un)
        first, other = r["items"][0]["id"], self.inbox(self.S2)["items"][0]["id"]
        rr = self.c.post(f"/api/notifications/{first}/read", headers=self.S1); self.assertEqual((rr.status_code, rr.get_json()["unread"]), (200, un - 1))
        self.assertEqual(self.c.post(f"/api/notifications/{first}/read", headers=self.S1).status_code, 200)        # twice is fine
        self.assertEqual(self.c.post(f"/api/notifications/{other}/read", headers=self.S1).status_code, 404)         # somebody else's
        self.assertEqual(self.c.post("/api/notifications/999999/read", headers=self.S1).status_code, 404)
        self.assertIsNone([i for i in self.inbox(self.S2)["items"] if i["id"] == other][0]["read_at"])
        self.assertEqual(len(self.inbox(self.S1, unread=1)["items"]), un - 1)
        page = self.inbox(self.S1, limit=2); self.assertEqual(len(page["items"]), 2)
        older = self.inbox(self.S1, limit=2, before=page["items"][-1]["id"]); self.assertTrue(all(i["id"] < page["items"][-1]["id"] for i in older["items"]))
        self.assertEqual(self.c.get("/api/notifications", headers=self.S1).headers["Cache-Control"], "private, no-store")
        ra = self.c.post("/api/notifications/read-all", headers=self.S1).get_json(); self.assertEqual((ra["marked"], ra["unread"]), (un - 1, 0))
        self.assertGreater(self.inbox(self.S2)["unread"], 0)                   # S2 untouched
        self.assertEqual(self.inbox(self.S1, unread=1)["items"], [])

    # ---------------- announcements ----------------
    def test_10_announcements(self):
        a = lambda j, h=None: self.c.post("/api/announcements", json=j, headers=h or self.H)
        r = a({"title": "Eid holiday", "message": "No classes on Monday", "audience": "batch", "batch_id": self.b1}); self.assertEqual((r.status_code, r.get_json()["sent"]), (201, 3))   # 2 students + the teacher
        self.assertEqual((self.count("announcement", self.s1), self.count("announcement", self.t1), self.count("announcement", self.s3), self.count("announcement", self.t2)), (1, 1, 0, 0))
        self.assertEqual(a({"title": "T", "audience": "students"}).get_json()["sent"], 3)
        self.assertEqual(a({"title": "T", "audience": "teachers"}).get_json()["sent"], 2)
        self.assertEqual(a({"title": "T", "audience": "everyone"}).get_json()["sent"], 5)
        for bad, code in (({"title": "", "audience": "students"}, 400), ({"title": "x" * 101, "audience": "students"}, 400), ({"title": "T", "message": "m" * 501, "audience": "students"}, 400),
                          ({"title": "T", "audience": "nobody"}, 400), ({"title": "T", "audience": "batch"}, 400), ({"title": "T", "audience": "batch", "batch_id": 9999}, 404)):
            self.assertEqual(a(bad).status_code, code, bad)
        self.assertEqual(a({"title": "T", "audience": "students"}, self.T1).status_code, 403)
        self.assertEqual(a({"title": "T", "audience": "students"}, self.S1).status_code, 403)
        self.assertEqual(a({"title": "T", "audience": "students"}, self.L).status_code, 403)       # limited admin without the classroom area
        self.assertEqual(self.c.post("/api/announcements", json={"title": "T", "audience": "students"}).status_code, 401)
        log = self.c.get("/api/audit?action=send_announcement", headers=self.H).get_json()
        rows = log if isinstance(log, list) else log.get("items", log.get("rows", []))
        self.assertTrue(any("Eid holiday" in (r.get("detail") or "") for r in rows))
        self.c.post("/api/notifications/read-all", headers=self.S1); self.c.post("/api/notifications/read-all", headers=self.S2)

    # ---------------- scheduled reminders ----------------
    def prep_invoices(self):
        self.sql("UPDATE invoices SET status='unpaid', paid_mvr=0, waived_mvr=0, due_date=? WHERE student_id=?", ("2027-03-12", self.s1))     # due in 2 days
        self.sql("UPDATE invoices SET status='unpaid', paid_mvr=0, waived_mvr=0, due_date=? WHERE student_id=?", ("2027-03-01", self.s2))     # 9 days overdue
        self.sql("UPDATE assignments SET due_date='2027-03-30' WHERE id=?", (self.aid,))                                                      # not soon

    def test_11_run_is_a_dry_run_by_default(self):
        self.prep_invoices(); n = self.count()
        r = self.c.post("/api/notifications/run", headers=self.H); j = r.get_json()
        self.assertEqual((r.status_code, j["dry_run"], j["fee_due_soon"], j["fee_overdue"], j["assignment_due"], j["admin_digest"]), (200, True, 1, 1, 0, 1))
        self.assertEqual(self.count(), n)
        self.assertIsNone(self.c.get("/api/notifications/status", headers=self.H).get_json()["last_run"])      # a dry run is not a run

    def test_12_real_run_then_repeat_sends_nothing_twice(self):
        j = self.c.post("/api/notifications/run?dry_run=0", headers=self.H).get_json()
        self.assertEqual((j["dry_run"], j["fee_due_soon"], j["fee_overdue"], j["admin_digest"]), (False, 1, 1, 1))
        due = [i for i in self.inbox(self.S1)["items"] if i["kind"] == "fee_due_soon"]; self.assertEqual(len(due), 1)
        self.assertIn("12 Mar 2027", due[0]["body"]); self.assertIn("MVR 1,000", due[0]["body"])   # v0.8.48: total and months, one notice per student
        od = [i for i in self.inbox(self.S2)["items"] if i["kind"] == "fee_overdue"]; self.assertEqual(len(od), 1)
        self.assertIn("9 days", od[0]["body"]); self.assertIn("MVR 1,000", od[0]["body"]); self.assertIn("Mar 2027", od[0]["body"])
        self.assertEqual(self.kinds(self.S3).count("fee_overdue"), 0)
        self.assertEqual(self.count("admin_overdue", 1), 1); self.assertEqual(self.count("admin_overdue", self.lim), 0)
        n = self.count()
        j2 = self.c.post("/api/notifications/run?dry_run=0", headers=self.H).get_json()
        self.assertEqual((j2["fee_due_soon"], j2["fee_overdue"], j2["assignment_due"], j2["admin_digest"]), (0, 0, 0, 0)); self.assertEqual(self.count(), n)
        st = self.c.get("/api/notifications/status", headers=self.H).get_json()
        self.assertTrue(st["last_run"]); self.assertEqual((st["fee_days_before"], st["overdue_every_days"], st["assignment_days_before"]), (5, 7, 1))   # v0.8.48: 5 days before by default
        self.assertTrue(any(r["action"] == "run_reminders" for r in self.sql("SELECT action FROM audit_log")))

    def test_13_overdue_repeats_every_n_days_and_digest_every_day(self):
        # buckets: days 1-7 late = 0, 8-14 = 1, 15-21 = 2 ... so the message comes on day 1, 8, 15
        self.setclock(2027, 3, 15)      # s2: 14 days late, still bucket 1 (first sent at 9 days): nothing new. s1: 3 days late, first overdue message.
        j = self.c.post("/api/notifications/run?dry_run=0", headers=self.H).get_json()
        self.assertEqual(j["fee_overdue"], 1); self.assertEqual((self.count("fee_overdue", self.s1), self.count("fee_overdue", self.s2)), (1, 1))
        self.assertEqual(j["admin_digest"], 1)                                 # a new day, a new digest line
        self.setclock(2027, 3, 16)      # s2: 15 days late -> bucket 2, a new message; s1 still bucket 0
        j = self.c.post("/api/notifications/run?dry_run=0", headers=self.H).get_json(); self.assertEqual(j["fee_overdue"], 1)
        self.assertEqual(self.kinds(self.S2).count("fee_overdue"), 2); self.assertEqual(self.kinds(self.S1).count("fee_overdue"), 1)
        self.setclock(2027, 3, 10)

    def test_14_slip_submitted_and_paid_invoices_are_left_alone(self):
        self.sql("UPDATE invoices SET status='slip_submitted' WHERE student_id=?", (self.s2,))
        self.sql("UPDATE invoices SET due_date='2027-03-11' WHERE student_id=?", (self.s1,))
        self.sql("UPDATE invoices SET status='paid', paid_mvr=amount_due_mvr WHERE student_id=?", (self.s1,))
        self.setclock(2027, 3, 20)
        before = self.count("fee_overdue") + self.count("fee_due_soon")
        j = self.c.post("/api/notifications/run?dry_run=1", headers=self.H).get_json()
        self.assertEqual((j["fee_due_soon"], j["fee_overdue"]), (0, 0)); self.assertEqual(self.count("fee_overdue") + self.count("fee_due_soon"), before)
        self.setclock(2027, 3, 10); self.prep_invoices()

    def test_15_assignment_due_soon_skips_students_who_handed_in(self):
        self.sql("UPDATE assignments SET due_date='2027-03-11' WHERE id=?", (self.aid,))
        j = self.c.post("/api/notifications/run?dry_run=0", headers=self.H).get_json(); self.assertEqual(j["assignment_due"], 1)    # s2 only; s1 handed in
        self.assertEqual((self.count("assignment_due", self.s2), self.count("assignment_due", self.s1)), (1, 0))
        self.assertEqual(self.c.post("/api/notifications/run?dry_run=0", headers=self.H).get_json()["assignment_due"], 0)
        self.sql("UPDATE assignments SET due_date='2027-03-30' WHERE id=?", (self.aid,))

    def test_16_each_reminder_can_be_switched_off(self):
        self.setclock(2027, 4, 1); self.prep_invoices()
        self.sql("UPDATE invoices SET due_date='2027-04-03' WHERE student_id=?", (self.s1,)); self.sql("UPDATE invoices SET due_date='2027-03-30' WHERE student_id=?", (self.s2,))
        self.sql("UPDATE assignments SET due_date='2027-04-02' WHERE id=?", (self.aid,))
        self.sql("DELETE FROM notifications WHERE dedupe_key LIKE 'due:%' OR dedupe_key LIKE 'assign:%'")      # those two fire once ever per invoice / assignment
        self.put(remind_fee_days_before="0", remind_overdue_every_days="0", remind_assignment_days_before="0")
        j = self.c.post("/api/notifications/run?dry_run=1", headers=self.H).get_json()
        self.assertEqual((j["fee_due_soon"], j["fee_overdue"], j["assignment_due"]), (0, 0, 0))
        self.put(remind_fee_days_before="3", remind_overdue_every_days="7", remind_assignment_days_before="1")
        j = self.c.post("/api/notifications/run?dry_run=1", headers=self.H).get_json()
        self.assertEqual((j["fee_due_soon"], j["fee_overdue"], j["assignment_due"]), (1, 1, 1))
        self.assertEqual(self.c.put("/api/settings", json={"remind_fee_days_before": "99"}, headers=self.H).status_code, 400)
        self.setclock(2027, 3, 10)

    def test_17_notifications_off_creates_nothing(self):
        self.put(notify_enabled="0"); n = self.count()
        j = self.c.post("/api/notifications/run?dry_run=0", headers=self.H).get_json(); self.assertTrue(j["skipped"]); self.assertEqual(self.count(), n)
        self.assertEqual(self.c.post(f"/api/batches/{self.b1}/assignments", json={"title": "Quiet"}, headers=self.T1).status_code, 201)
        self.assertEqual(self.c.post("/api/announcements", json={"title": "T", "audience": "students"}, headers=self.H).status_code, 409)
        self.assertEqual(self.count(), n)
        self.assertEqual(self.c.get("/api/notifications", headers=self.S1).status_code, 200)        # old ones stay visible
        self.assertFalse(self.c.get("/api/notifications/status", headers=self.H).get_json()["enabled"])
        self.put(notify_enabled="1")
        self.assertEqual(self.c.post(f"/api/batches/{self.b1}/assignments", json={"title": "Loud"}, headers=self.T1).status_code, 201)
        self.assertEqual(self.count(), n + 2)

    def test_18_old_notifications_are_removed(self):
        self.sql("INSERT INTO notifications(user_id,kind,title,created_at,read_at) VALUES(?,?,?,?,?)", (self.s3, "x", "old read", "2026-10-01 00:00:00", "2026-11-01 00:00:00"))
        self.sql("INSERT INTO notifications(user_id,kind,title,created_at) VALUES(?,?,?,?)", (self.s3, "x", "old unread", "2026-08-01 00:00:00"))
        self.sql("INSERT INTO notifications(user_id,kind,title,created_at) VALUES(?,?,?,?)", (self.s3, "x", "recent unread", "2027-03-01 00:00:00"))
        j = self.c.post("/api/notifications/run?dry_run=1", headers=self.H).get_json(); self.assertEqual(j["removed_old"], 2)
        self.assertEqual(self.count("x"), 3)                                   # dry run keeps them
        j = self.c.post("/api/notifications/run?dry_run=0", headers=self.H).get_json(); self.assertEqual(j["removed_old"], 2)
        self.assertEqual([i["title"] for i in self.inbox(self.S3)["items"] if i["kind"] == "x"], ["recent unread"])

    def test_19_cron_needs_the_secret(self):
        self.assertEqual(self.c.get("/api/cron/reminders").status_code, 401)
        self.app.config["CRON_SECRET"] = "s3cret-s3cret"
        try:
            self.assertEqual(self.c.get("/api/cron/reminders", headers={"Authorization": "Bearer nope"}).status_code, 401)
            self.assertEqual(self.c.get("/api/cron/reminders?secret=s3cret-s3cret").status_code, 401)           # never accepted in the URL
            self.assertEqual(self.c.get("/api/cron/reminders", headers=self.H).status_code, 401)                # an admin token is not the cron secret
            for m in (self.c.get, self.c.post):
                r = m("/api/cron/reminders", headers={"Authorization": "Bearer s3cret-s3cret"}); self.assertEqual(r.status_code, 200)
                self.assertEqual(set(r.get_json()) & {"fee_due_soon", "fee_overdue", "assignment_due", "admin_digest", "removed_old"}, {"fee_due_soon", "fee_overdue", "assignment_due", "admin_digest", "removed_old"})
            self.assertTrue(self.c.get("/api/notifications/status", headers=self.H).get_json()["cron_secret_set"])
        finally: self.app.config.pop("CRON_SECRET", None)
        import json
        self.assertIn("/api/cron/reminders", [x["path"] for x in json.load(open(os.path.join(ROOT, "vercel.json"), encoding="utf-8"))["crons"]])

    def test_20a_links_open_the_item(self):
        """Session 16 (v0.8.33): links are "tab:id" so the page opens the assignment, invoice or batch; students' class messages stay on Home."""
        links = lambda h, kind: {i["link"] for i in self.inbox(h)["items"] if i["kind"] == kind}
        self.assertEqual(links(self.S1, "grade"), {f"assignments:{self.aid}"})
        inv = self.sql("SELECT id FROM invoices WHERE student_id=? ORDER BY id", (self.s1,))[0]["id"]
        self.assertEqual(links(self.S1, "slip_rejected"), {f"fees:{inv}"})
        self.assertEqual(links(self.S1, "class_cancelled"), {"home"})
        self.assertEqual(links(self.T1, "class_cancelled"), {f"classroom:{self.b1}"})
        self.assertEqual(links(self.T2, "substitute_assigned"), {f"classroom:{self.b1}"})
        self.assertEqual(links(self.T2, "substitute_removed"), {"home"})
        for tab_id in links(self.S1, "grade") | links(self.T1, "class_cancelled"):   # the tab part is always a real tab name the page knows
            self.assertRegex(tab_id, r"^[a-z_]+(:\d+)?$")

    def test_20_admin_screens_are_admin_only(self):
        for h in (self.T1, self.S1, self.L):
            self.assertEqual(self.c.post("/api/notifications/run", headers=h).status_code, 403)
            self.assertEqual(self.c.get("/api/notifications/status", headers=h).status_code, 403)
        for m, p in ((self.c.post, "/api/notifications/run"), (self.c.get, "/api/notifications/status")): self.assertEqual(m(p).status_code, 401)
        self.assertEqual(self.inbox(self.L)["unread"], 0)                      # every role has its own inbox


if __name__ == "__main__":
    unittest.main()
