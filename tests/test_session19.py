"""Session 19: teacher dashboard. Every number is compared with a hand count of a seeded world."""
import datetime as dt, os, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
MVT = dt.timezone(dt.timedelta(hours=5))


class S19(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ.update(DATABASE_PATH=os.path.join(tmp, "t.db"), ADMIN_EMAIL="admin@s19.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})
        cls.app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 12, 0, tzinfo=MVT)      # Wednesday
        cls.c = cls.app.test_client()
        cls.H = cls.tok("admin@s19.test", "AdminPass123")
        cls.n = 0
        cls.t1, cls.t2 = cls.make("teacher", "Teacher One"), cls.make("teacher", "Teacher Two")
        cls.s = {k: cls.make("student", f"Student {k}") for k in (1, 2, 3, 4, 5)}
        post = lambda path, j: cls.c.post(path, json=j, headers=cls.H).get_json()["id"]
        cls.c1 = post("/api/courses", {"name": "Arabic Level 1", "monthly_fee_mvr": 100, "status": "open"})
        cls.c2 = post("/api/courses", {"name": "Grade 8 Mathematics", "kind": "tuition", "monthly_fee_mvr": 100, "status": "open"})
        cls.c3 = post("/api/courses", {"name": "English", "monthly_fee_mvr": 100, "status": "open"})
        mk = lambda c, code, t, days: post("/api/batches", {"course_id": c, "code": code, "teacher_id": t[0], "capacity": 9, "days": days, "start_time": "16:00"})
        cls.b1, cls.b2, cls.b3 = mk(cls.c1, "A1", cls.t1, "Mon,Wed"), mk(cls.c2, "M8", cls.t1, "Fri"), mk(cls.c3, "E1", cls.t2, "Tue")
        cls.enr = {}
        for k, b in ((1, cls.b1), (2, cls.b1), (3, cls.b1), (4, cls.b1), (1, cls.b2), (5, cls.b2)):
            r = cls.c.post("/api/enrollments", json={"student_id": cls.s[k][0], "batch_id": b}, headers=cls.H); assert r.status_code in (200, 201), r.get_json()
            cls.enr[(k, b)] = r.get_json()["id"]
        cls.T1, cls.T2 = cls.tok(cls.t1[1], PW), cls.tok(cls.t2[1], PW)
        cls.S = {k: cls.tok(v[1], PW) for k, v in cls.s.items()}
        att = lambda b, d, recs: cls.c.post(f"/api/batches/{b}/attendance", json={"date": d, "records": [{"student_id": cls.s[k][0], "status": st} for k, st in recs]}, headers=cls.T1).status_code
        assert att(cls.b1, "2027-03-01", [(1, "present"), (2, "absent"), (3, "late"), (4, "present")]) == 200
        assert att(cls.b1, "2027-03-03", [(1, "present"), (2, "absent"), (3, "present")]) == 200
        assert att(cls.b1, "2027-03-08", [(1, "present"), (2, "absent"), (3, "present")]) == 200
        assert att(cls.b2, "2027-03-05", [(1, "present")]) == 200
        assert cls.c.post(f"/api/batches/{cls.b1}/sessions", json={"date": "2027-03-15", "status": "cancelled"}, headers=cls.H).status_code == 201
        cls.c.patch(f"/api/enrollments/{cls.enr[(4, cls.b1)]}", json={"status": "dropped"}, headers=cls.H)          # s4 leaves: their 'present' no longer counts
        a = lambda b, title, kind="assignment": cls.c.post(f"/api/batches/{b}/assignments", json={"title": title, "kind": kind, "max_points": 10}, headers=cls.T1).get_json()["id"]
        a1, a2, t1, a3 = a(cls.b1, "A1"), a(cls.b1, "A2"), a(cls.b1, "T1", "test"), a(cls.b2, "A3")
        sub = lambda k, aid, txt="x": cls.c.post(f"/api/assignments/{aid}/submit", data={"text": txt}, headers=cls.S[k], content_type="multipart/form-data").status_code
        for k, aid, txt in ((1, a1, "one"), (1, a1, "two"), (2, a1, "x"), (3, a2, "x"), (1, a3, "x")): assert sub(k, aid, txt) in (200, 201)
        gr = lambda aid, k, v: cls.c.post(f"/api/assignments/{aid}/grades", json={"student_id": cls.s[k][0], "grade": v}, headers=cls.T1).status_code
        assert gr(a1, 1, 8) == 200 and gr(t1, 1, 5) == 200 and gr(t1, 2, 6) == 200
        tut = lambda title, **kw: cls.c.post("/api/tutorials", json={"title": title, "text": "x", **kw}, headers=cls.T1).get_json()["id"]
        ta, tm, tg = tut("Arabic", course_id=cls.c1), tut("Maths", course_id=cls.c2), tut("General")
        ans = lambda k, tid: cls.c.post(f"/api/tutorials/{tid}/submission", data={"text": "ans"}, headers=cls.S[k], content_type="multipart/form-data").status_code
        for k, tid in ((1, ta), (2, tg), (5, tm)): assert ans(k, tid) in (200, 201)

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def make(cls, role, name):
        cls.n += 1; email = f"p{cls.n}@s19.test"
        r = cls.c.post("/api/users", json={"email": email, "password": PW, "full_name": name, "role": role}, headers=cls.H)
        return r.get_json()["id"], email

    def dash(self, H=None, q=""):
        r = self.c.get("/api/teacher/dashboard" + q, headers=H or self.T1); self.assertEqual(r.status_code, 200, r.get_data(as_text=True)); return r.get_json()

    def test_01_batch_one_matches_hand_count(self):
        d = self.dash(q=f"?batch_id={self.b1}")
        self.assertEqual((d["scope"], [b["code"] for b in d["batches"]], d["courses"], d["students"]), ("batch", ["A1"], ["Arabic Level 1"], 3))   # s4 dropped
        self.assertEqual({k: d["classes"][k] for k in ("held", "held_30d", "cancelled", "upcoming")}, {"held": 3, "held_30d": 3, "cancelled": 1, "upcoming": 7})
        self.assertEqual(d["assignments"], {"given": 2, "tests": 1, "submissions": 3, "graded": 3, "pending_grading": 2})
        self.assertEqual(d["tutorials"], {"given": 2, "answers": 2})
        a = d["attendance"]       # s1 P,P,P  s2 A,A,A  s3 L,P,P  (the dropped s4 is ignored)
        self.assertEqual((a["present"], a["late"], a["absent"], a["excused"], a["counted"], a["pct"], a["low_students"]), (5, 1, 3, 0, 9, 66.7, 1))

    def test_02_batch_two_and_all(self):
        d = self.dash(q=f"?batch_id={self.b2}")
        self.assertEqual((d["students"], d["classes"]["held"], d["classes"]["upcoming"]), (2, 1, 4))
        self.assertEqual(d["assignments"], {"given": 1, "tests": 0, "submissions": 1, "graded": 0, "pending_grading": 1})
        self.assertEqual(d["tutorials"], {"given": 2, "answers": 1})
        self.assertEqual((d["attendance"]["present"], d["attendance"]["pct"], d["attendance"]["low_students"]), (1, 100.0, 0))
        d = self.dash()
        self.assertEqual((d["scope"], len(d["batches"]), d["students"], d["classes"]["held"], d["classes"]["upcoming"], d["classes"]["cancelled"]), ("all", 2, 4, 4, 11, 1))
        self.assertEqual(d["assignments"], {"given": 3, "tests": 1, "submissions": 4, "graded": 3, "pending_grading": 3})
        self.assertEqual(d["tutorials"], {"given": 3, "answers": 3})
        self.assertEqual((d["attendance"]["present"], d["attendance"]["counted"]), (6, 10))

    def test_03_pending_matches_teacher_home_and_assignment_list(self):
        d = self.dash()
        home = self.c.get("/api/my/home", headers=self.T1).get_json()
        self.assertEqual(d["assignments"]["pending_grading"], home["to_grade"])
        lst = self.c.get("/api/assignments", headers=self.T1).get_json()
        self.assertEqual(sum(x["pending_count"] for x in lst if x["kind"] == "assignment"), d["assignments"]["pending_grading"])
        self.assertEqual(sum(x["submitted_count"] for x in lst), d["assignments"]["submissions"])
        self.assertEqual(sum(x["graded_count"] for x in lst), d["assignments"]["graded"])

    def test_04_grading_updates_the_dashboard(self):
        aid = [x["id"] for x in self.c.get(f"/api/assignments?batch_id={self.b1}", headers=self.T1).get_json() if x["title"] == "A2"][0]
        self.assertEqual(self.c.post(f"/api/assignments/{aid}/grades", json={"student_id": self.s[3][0], "grade": 9}, headers=self.T1).status_code, 200)
        d = self.dash(q=f"?batch_id={self.b1}")
        self.assertEqual((d["assignments"]["pending_grading"], d["assignments"]["graded"]), (1, 4))

    def test_05_recent_activity_is_the_teachers_own(self):
        r = self.dash()["recent_activity"]
        self.assertTrue(0 < len(r) <= 10); self.assertTrue(all({"action", "at"} <= set(x) for x in r))
        self.assertNotIn("session_cancelled", [x["action"] for x in r])          # the admin did that
        self.assertEqual(self.dash(self.T2)["recent_activity"], [])

    def test_06_other_teacher_empty_and_access_rules(self):
        d = self.dash(self.T2)
        self.assertEqual((d["students"], d["classes"]["held"], d["assignments"]["given"], d["tutorials"]["given"], d["attendance"]["pct"]), (0, 0, 0, 0, None))
        self.assertEqual(self.c.get(f"/api/teacher/dashboard?batch_id={self.b1}", headers=self.T2).status_code, 403)
        self.assertEqual(self.c.get("/api/teacher/dashboard?batch_id=999999", headers=self.T1).status_code, 403)
        self.assertEqual(self.c.get("/api/teacher/dashboard", headers=self.S[1]).status_code, 403)
        self.assertEqual(self.c.get("/api/teacher/dashboard", headers=self.H).status_code, 403)
        self.assertEqual(self.c.get("/api/teacher/dashboard").status_code, 401)
        self.c.patch(f"/api/users/{self.t2[0]}", json={"permissions": ["tutorials"]}, headers=self.H)
        self.assertEqual(self.c.get("/api/teacher/dashboard", headers=self.tok(self.t2[1], PW)).status_code, 403)      # needs the Classroom area
        self.c.patch(f"/api/users/{self.t2[0]}", json={"permissions": "all"}, headers=self.H)


if __name__ == "__main__":
    unittest.main()
