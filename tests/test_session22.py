"""Session 22: substitute teachers. Access exists only on the assigned dates, only for class information, and ends by itself."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
MVT = dt.timezone(dt.timedelta(hours=5))


class S22(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s22.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path})
        cls.c = cls.app.test_client(); cls.n = 0
        cls.clock("2027-03-10")                                     # a Wednesday
        cls.H = cls.tok("admin@s22.test", "AdminPass123")
        cls.t1, cls.t2, cls.t3 = (cls.make("teacher", f"T{i}") for i in (1, 2, 3))
        cls.s1, cls.s2 = cls.make("student", "Student One"), cls.make("student", "Student Two")
        post = lambda p, j: cls.c.post(p, json=j, headers=cls.H).get_json()["id"]
        cls.course = post("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 100, "status": "open"})
        mk = lambda code, t, days: post("/api/batches", {"course_id": cls.course, "code": code, "teacher_id": t[0], "capacity": 9, "days": days, "start_time": "16:00"})
        cls.b1, cls.b2 = mk("B1", cls.t1, "Mon,Wed"), mk("B2", cls.t3, "Tue")
        for s in (cls.s1, cls.s2): cls.c.post("/api/enrollments", json={"student_id": s[0], "batch_id": cls.b1}, headers=cls.H)
        cls.T1, cls.T2, cls.T3 = (cls.tok(x[1], PW) for x in (cls.t1, cls.t2, cls.t3)); cls.S = cls.tok(cls.s1[1], PW)

    @classmethod
    def clock(cls, day):
        y, m, d = map(int, day.split("-")); cls.app.config["NOW"] = lambda: dt.datetime(y, m, d, 12, 0, tzinfo=MVT)

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def make(cls, role, name, **kw):
        cls.n += 1; email = f"p{cls.n}@s22.test"
        r = cls.c.post("/api/users", json={"email": email, "password": PW, "full_name": name, "role": role, **kw}, headers=cls.H)
        return r.get_json()["id"], email

    def setUp(self): self.clock("2027-03-10")

    def sql(self, q, a=()):
        con = sqlite3.connect(self.path)
        try: return con.execute(q, a).fetchall()
        finally: con.close()

    def sub(self, **kw):
        j = {"batch_id": self.b1, "substitute_teacher_id": self.t2[0], "class_date": "2027-03-10", "ends_on": "2027-03-12", "reason": "sick leave", **kw}
        return self.c.post("/api/substitutions", json=j, headers=self.H)

    def clear(self):
        for r in self.c.get("/api/substitutions", headers=self.H).get_json():
            if not r["removed_at"]: self.c.delete(f"/api/substitutions/{r['id']}", headers=self.H)

    def test_01_no_access_before_a_substitution(self):
        self.clear()
        self.assertEqual(self.c.get("/api/my/batches", headers=self.T2).get_json(), [])
        self.assertEqual(self.c.get(f"/api/batches/{self.b1}/attendance", headers=self.T2).status_code, 403)
        self.assertEqual(self.c.get("/api/timetable?from=2027-03-08&to=2027-03-20", headers=self.T2).get_json(), [])

    def test_02_substitute_sees_class_information_on_the_dates_only(self):
        self.clear(); r = self.sub(); self.assertEqual(r.status_code, 201, r.get_json())
        log = self.sql("SELECT user_role,batch_id,old_value,new_value FROM audit_log WHERE action='substitute_assign' ORDER BY id DESC")[0]
        self.assertEqual(log, ("admin", self.b1, str(self.t1[0]), str(self.t2[0])))
        mine = self.c.get("/api/my/batches", headers=self.T2).get_json()
        self.assertEqual([(b["id"], b["substitute_until"]) for b in mine], [(self.b1, "2027-03-12")])
        self.assertNotIn("substitute_until", self.c.get("/api/my/batches", headers=self.T1).get_json()[0])
        tt = self.c.get("/api/timetable?from=2027-03-08&to=2027-03-20", headers=self.T2).get_json()
        self.assertEqual([o["date"] for o in tt], ["2027-03-10"])                       # Mon 8, Mon 15, Wed 17 are not his
        self.assertEqual([o["date"] for o in self.c.get("/api/timetable?from=2027-03-08&to=2027-03-20", headers=self.T1).get_json()], ["2027-03-08", "2027-03-10", "2027-03-15", "2027-03-17"])
        a = self.c.get(f"/api/batches/{self.b1}/attendance?date=2027-03-10", headers=self.T2); self.assertEqual(a.status_code, 200)
        self.assertEqual(sorted(s["full_name"] for s in a.get_json()["students"]), ["Student One", "Student Two"])
        self.assertEqual(self.c.get(f"/api/batches/{self.b1}/attendance?date=2027-03-08", headers=self.T2).status_code, 403)   # earlier dates are not his
        save = lambda day: self.c.post(f"/api/batches/{self.b1}/attendance", json={"date": day, "records": [{"student_id": self.s1[0], "status": "present"}]}, headers=self.T2).status_code
        self.assertEqual(save("2027-03-08"), 403); self.assertEqual(save("2027-03-10"), 200)
        row = self.sql("SELECT user_role,detail,batch_id FROM audit_log WHERE action='mark_attendance' ORDER BY id DESC")[0]
        self.assertEqual((row[0], row[2]), ("teacher", self.b1)); self.assertIn("as substitute", row[1])
        self.assertEqual(self.sql("SELECT teacher_id FROM batches WHERE id=?", (self.b1,))[0][0], self.t1[0])      # the original teacher record is unchanged
        self.assertEqual(self.c.get(f"/api/batches/{self.b1}/attendance", headers=self.T1).status_code, 200)       # and still works for them
        self.assertEqual(self.c.get(f"/api/batches/{self.b2}/attendance", headers=self.T2).status_code, 403)       # other batches stay closed

    def test_03_substitute_cannot_do_more_than_class_information(self):
        self.clear(); self.sub(); H = self.T2; b = self.b1
        denied = [("post", f"/api/batches/{b}/assignments", {"title": "x", "max_points": 5}), ("get", f"/api/batches/{b}/gradebook", None),
                  ("post", f"/api/batches/{b}/materials", {"title": "x", "url": "https://example.com"}), ("post", f"/api/batches/{b}/sessions", {"date": "2027-03-10", "status": "cancelled"}),
                  ("put", f"/api/batches/{b}/meet-link", {"meet_link": "https://meet.example/x"}), ("get", f"/api/assignments?batch_id={b}", None),
                  ("get", f"/api/materials?batch_id={b}", None), ("get", f"/api/batches/{b}/attendance/summary", None), ("get", f"/api/teacher/dashboard?batch_id={b}", None),
                  ("post", f"/api/batches/{b}/recordings", {"title": "x", "url": "https://drive.google.com/x", "recorded_on": "2027-03-09"})]
        for m, path, j in denied:
            r = getattr(self.c, m)(path, json=j, headers=H) if j is not None else getattr(self.c, m)(path, headers=H)
            self.assertEqual(r.status_code, 403, (m, path, r.get_data(as_text=True)[:100]))
        info = self.c.get("/api/my/information", headers=H).get_json()
        self.assertNotIn("B1", str(info.get("batches")))                                   # a substitute does not become the assigned teacher
        self.assertEqual(self.c.get("/api/batches", headers=H).get_json(), [])

    def test_04_access_ends_by_itself_and_starts_on_the_first_day(self):
        self.clear(); self.sub(class_date="2027-03-10", ends_on="2027-03-12")
        ok = lambda: self.c.get(f"/api/batches/{self.b1}/attendance", headers=self.T2).status_code
        self.clock("2027-03-09"); self.assertEqual(ok(), 403)                              # not yet
        self.assertEqual([r["state"] for r in self.c.get("/api/my/substitutions", headers=self.T2).get_json()], ["upcoming"])   # but he can see it is coming
        self.clock("2027-03-10"); self.assertEqual(ok(), 200)
        self.clock("2027-03-12"); self.assertEqual(ok(), 200)                              # last day counts
        self.clock("2027-03-13"); self.assertEqual(ok(), 403)                              # gone, nothing was run
        self.assertEqual(self.c.get("/api/my/batches", headers=self.T2).get_json(), [])
        self.assertEqual(self.c.get("/api/my/substitutions", headers=self.T2).get_json(), [])

    def test_05_removal_ends_access_now_and_keeps_history(self):
        self.clear(); sid = self.sub().get_json()["id"]
        self.assertEqual(self.c.get(f"/api/batches/{self.b1}/attendance", headers=self.T2).status_code, 200)
        self.assertEqual(self.c.delete(f"/api/substitutions/{sid}", headers=self.H).status_code, 200)
        self.assertEqual(self.c.get(f"/api/batches/{self.b1}/attendance", headers=self.T2).status_code, 403)
        row = self.sql("SELECT user_role,batch_id,old_value FROM audit_log WHERE action='substitute_remove' ORDER BY id DESC")[0]
        self.assertEqual(row, ("admin", self.b1, str(self.t2[0])))
        h = [r for r in self.c.get("/api/substitutions", headers=self.H).get_json() if r["id"] == sid][0]
        self.assertEqual((h["state"], h["substitute_teacher"], h["original_teacher"], h["reason"]), ("removed", "T2", "T1", "sick leave"))
        self.assertEqual(self.c.delete(f"/api/substitutions/{sid}", headers=self.H).status_code, 409)
        self.assertEqual(self.c.delete("/api/substitutions/99999", headers=self.H).status_code, 404)

    def test_06_validation(self):
        self.clear()
        self.assertEqual(self.sub(substitute_teacher_id=self.t1[0]).status_code, 400)       # the batch's own teacher
        self.assertEqual(self.sub(substitute_teacher_id=self.s1[0]).status_code, 400)       # a student
        self.assertEqual(self.sub(class_date="2027-03-01", ends_on="2027-03-05").status_code, 400)   # past
        self.assertEqual(self.sub(ends_on="2027-03-09").status_code, 400)                   # ends before it starts
        self.assertEqual(self.sub(class_date="bad").status_code, 400)
        self.assertEqual(self.sub(batch_id=99999).status_code, 404)
        self.assertEqual(self.sub(ends_on="2027-09-30").status_code, 400)                   # longer than 92 days
        self.assertEqual(self.sub().status_code, 201)
        self.assertEqual(self.sub(substitute_teacher_id=self.t3[0], class_date="2027-03-12", ends_on="2027-03-14").status_code, 409)   # overlaps
        self.assertEqual(self.sub(substitute_teacher_id=self.t3[0], class_date="2027-03-13", ends_on="2027-03-14").status_code, 201)   # next one is fine
        self.assertEqual(self.sub(batch_id=self.b2, substitute_teacher_id=self.t3[0]).status_code, 400)   # T3 owns B2
        self.assertEqual(self.sub(batch_id=self.b2).status_code, 201)                       # another batch, same dates: fine

    def test_07_single_class_by_session_and_single_date(self):
        self.clear()
        self.c.post(f"/api/batches/{self.b1}/sessions", json={"date": "2027-03-17", "status": "scheduled"}, headers=self.H)
        sid = self.sql("SELECT id FROM sessions WHERE batch_id=? AND session_date='2027-03-17'", (self.b1,))[0][0]
        other = self.c.post(f"/api/batches/{self.b2}/sessions", json={"date": "2027-03-16", "status": "scheduled"}, headers=self.H)
        osid = self.sql("SELECT id FROM sessions WHERE batch_id=? AND session_date='2027-03-16'", (self.b2,))[0][0]
        self.assertEqual(self.sub(session_id=osid).status_code, 400)                        # a class of another batch
        r = self.sub(session_id=sid, class_date="2020-01-01", ends_on="2030-01-01"); self.assertEqual(r.status_code, 201)
        row = self.sql("SELECT class_date,ends_on,session_id FROM substitutions WHERE id=?", (r.get_json()["id"],))[0]
        self.assertEqual(row, ("2027-03-17", None, sid))                                    # the class decides the date; one class only
        self.clock("2027-03-17"); self.assertEqual(self.c.get(f"/api/batches/{self.b1}/attendance", headers=self.T2).status_code, 200)
        self.clock("2027-03-18"); self.assertEqual(self.c.get(f"/api/batches/{self.b1}/attendance", headers=self.T2).status_code, 403)
        self.clock("2027-03-10"); self.clear(); self.assertEqual(self.sub(class_date="2027-03-10", ends_on=None).status_code, 201)
        self.assertEqual(self.sql("SELECT ends_on FROM substitutions ORDER BY id DESC")[0][0], None)
        self.clock("2027-03-11"); self.assertEqual(self.c.get(f"/api/batches/{self.b1}/attendance", headers=self.T2).status_code, 403)

    def test_08_who_may_manage_substitutions(self):
        self.clear(); lim = self.tok(self.make("admin", "Lim", permissions=["courses"])[1], PW); sid = self.sub().get_json()["id"]
        for m, path in (("get", "/api/substitutions"), ("post", "/api/substitutions"), ("delete", f"/api/substitutions/{sid}")):
            self.assertEqual(getattr(self.c, m)(path).status_code, 401, path)
            for H in (self.T1, self.T2, self.S, lim): self.assertEqual(getattr(self.c, m)(path, json={}, headers=H).status_code, 403, (m, path))
        self.assertEqual(self.c.get("/api/my/substitutions").status_code, 401); self.assertEqual(self.c.get("/api/my/substitutions", headers=self.S).status_code, 403)
        self.assertEqual(self.c.get("/api/my/substitutions", headers=self.T3).get_json(), [])        # only your own
        mine = self.c.get("/api/my/substitutions", headers=self.T2).get_json()
        self.assertEqual(len(mine), 1); self.assertNotIn("students", str(mine))
        self.assertEqual(self.c.get(f"/api/substitutions?batch_id={self.b1}&when=active", headers=self.H).get_json()[0]["state"], "active")
        self.assertEqual(self.c.get("/api/substitutions?batch_id=x", headers=self.H).status_code, 400)


if __name__ == "__main__":
    unittest.main()
