"""Session 18: cancel_class permission, teacher tutorial scope, one definition of assignment counts."""
import os, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"


class S18(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ.update(DATABASE_PATH=os.path.join(tmp, "t.db"), ADMIN_EMAIL="admin@s18.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})
        cls.c = cls.app.test_client()
        cls.H = cls.tok("admin@s18.test", "AdminPass123")
        cls.n = 0
        cls.t1 = cls.make("teacher", "Teacher One"); cls.t2 = cls.make("teacher", "Teacher Two")
        cls.st = [cls.make("student", f"Student {i}") for i in range(4)]
        post = lambda path, j: cls.c.post(path, json=j, headers=cls.H).get_json()["id"]
        cls.c1 = post("/api/courses", {"name": "Arabic Level 1", "monthly_fee_mvr": 100, "status": "open"})
        cls.c2 = post("/api/courses", {"name": "Grade 8 Mathematics", "kind": "tuition", "monthly_fee_mvr": 100, "status": "open"})
        mk = lambda c, code, t: post("/api/batches", {"course_id": c, "code": code, "teacher_id": t[0], "capacity": 9, "days": "Mon,Wed", "start_time": "16:00"})
        cls.b1, cls.b2 = mk(cls.c1, "A1", cls.t1), mk(cls.c2, "M8", cls.t2)
        cls.enr = {}
        for s in cls.st:
            r = cls.c.post("/api/enrollments", json={"student_id": s[0], "batch_id": cls.b1}, headers=cls.H); assert r.status_code in (200, 201), r.get_json()
            cls.enr[s[0]] = r.get_json()["id"]
        cls.T1, cls.T2 = cls.tok(cls.t1[1], PW), cls.tok(cls.t2[1], PW)
        cls.S = [cls.tok(s[1], PW) for s in cls.st]

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def make(cls, role, name):
        cls.n += 1; email = f"p{cls.n}@s18.test"
        r = cls.c.post("/api/users", json={"email": email, "password": PW, "full_name": name, "role": role}, headers=cls.H)
        return r.get_json()["id"], email

    def perms(self, t, areas): self.assertEqual(self.c.patch(f"/api/users/{t[0]}", json={"permissions": areas}, headers=self.H).status_code, 200)

    # ---- cancel_class ----
    def test_01_cancel_needs_permission(self):
        url = f"/api/batches/{self.b1}/sessions"
        r = self.c.post(url, json={"date": "2027-03-01", "status": "cancelled"}, headers=self.T1); self.assertEqual(r.status_code, 403); self.assertIn("error", r.get_json())
        self.c.patch(f"/api/users/{self.t1[0]}", json={"permissions": "all"}, headers=self.H)
        self.assertEqual(self.c.post(url, json={"date": "2027-03-01", "status": "cancelled"}, headers=self.tok(self.t1[1], PW)).status_code, 403)   # "everything" does not include it
        tl = self.c.get("/api/timetable?from=2027-03-01&to=2027-03-01", headers=self.H).get_json()
        self.assertNotIn("cancelled", [o["status"] for o in tl])                                  # nothing was written
        self.assertEqual(self.c.post(url, json={"date": "2027-03-01", "status": "scheduled", "start_time": "16:00"}, headers=self.T1).status_code, 201)   # other session changes still work

    def test_02_granted_revoked_and_scoped(self):
        url = f"/api/batches/{self.b1}/sessions"
        self.perms(self.t1, ["classroom", "cancel_class"]); T = self.tok(self.t1[1], PW)
        self.assertEqual(self.c.post(url, json={"date": "2027-03-03", "status": "cancelled"}, headers=T).status_code, 201)
        self.assertEqual(self.c.post(f"/api/batches/{self.b2}/sessions", json={"date": "2027-03-03", "status": "cancelled"}, headers=T).status_code, 403)   # not their batch
        self.perms(self.t1, ["classroom"])
        self.assertEqual(self.c.post(url, json={"date": "2027-03-08", "status": "cancelled"}, headers=self.tok(self.t1[1], PW)).status_code, 403)     # revoked
        self.assertEqual(self.c.post(url, json={"date": "2027-03-08", "status": "cancelled"}, headers=self.H).status_code, 201)                         # admin always
        self.assertEqual(self.c.patch(f"/api/users/{self.st[0][0]}", json={"permissions": ["cancel_class"]}, headers=self.H).status_code, 400)          # students cannot hold it
        self.c.patch(f"/api/users/{self.t1[0]}", json={"permissions": "all"}, headers=self.H)

    # ---- tutorials ----
    def test_03_teacher_sees_only_own_batch_tutorials(self):
        mk = lambda who, **kw: self.c.post("/api/tutorials", json={"title": kw.pop("title"), "text": "x", **kw}, headers=who)
        ta, tb = mk(self.T1, title="Arabic note", course_id=self.c1).get_json()["id"], mk(self.T2, title="Maths note", course_id=self.c2).get_json()["id"]
        gen = mk(self.T1, title="General by T1").get_json()["id"]
        adm_math = mk(self.H, title="Admin maths", course_id=self.c2).get_json()["id"]
        ids = lambda who, q="": [x["id"] for x in self.c.get("/api/tutorials" + q, headers=who).get_json()]
        self.assertEqual(sorted(ids(self.T1)), sorted([ta, gen]))
        self.assertEqual(sorted(ids(self.T2)), sorted([tb, adm_math]))
        self.assertEqual(sorted(ids(self.T1, f"?batch_id={self.b1}")), sorted([ta, gen]))
        self.assertEqual(self.c.get(f"/api/tutorials?batch_id={self.b2}", headers=self.T1).status_code, 403)
        for path in (f"/api/tutorials/{tb}", f"/api/tutorials/{tb}/submissions"):
            self.assertEqual(self.c.get(path, headers=self.T1).status_code, 403, path)
        self.assertEqual(self.c.get(f"/api/tutorials/{ta}", headers=self.T1).status_code, 200)
        self.assertEqual(self.c.post("/api/tutorials", json={"title": "x", "text": "y", "course_id": self.c2}, headers=self.T1).status_code, 403)
        self.assertGreaterEqual(len(ids(self.H)), 4)                                              # admin sees everything
        self.assertEqual(len(ids(self.S[0])), 2)                                                  # students: unchanged rule (their course + general): ta + gen

    # ---- statistics ----
    def test_04_assignment_counts_match_rows(self):
        mk = lambda title, kind="assignment": self.c.post(f"/api/batches/{self.b1}/assignments", json={"title": title, "kind": kind, "max_points": 10}, headers=self.T1).get_json()["id"]
        a1, a2, t1 = mk("A one"), mk("A two"), mk("Test one", "test")
        sub = lambda i, aid, txt: self.assertIn(self.c.post(f"/api/assignments/{aid}/submit", data={"text": txt}, headers=self.S[i], content_type="multipart/form-data").status_code, (200, 201))
        sub(0, a1, "first"); sub(0, a1, "second"); sub(0, a1, "third")      # deliberate resubmissions
        sub(1, a1, "ok"); sub(3, a1, "will leave"); sub(2, a2, "x")
        grade = lambda aid, sid, g: self.assertEqual(self.c.post(f"/api/assignments/{aid}/grades", json={"student_id": sid, "grade": g}, headers=self.T1).status_code, 200)
        grade(a1, self.st[0][0], 8); grade(t1, self.st[0][0], 5); grade(t1, self.st[1][0], 6)
        self.assertEqual(self.c.patch(f"/api/enrollments/{self.enr[self.st[3][0]]}", json={"status": "dropped"}, headers=self.H).status_code, 200)
        # a tutorial answer must not be counted anywhere
        tid = self.c.post("/api/tutorials", json={"title": "Tut", "text": "x", "course_id": self.c1}, headers=self.T1).get_json()["id"]
        self.assertIn(self.c.post(f"/api/tutorials/{tid}/submission", data={"text": "ans"}, headers=self.S[0], content_type="multipart/form-data").status_code, (200, 201))
        lst = {a["id"]: a for a in self.c.get(f"/api/assignments?batch_id={self.b1}", headers=self.T1).get_json()}
        g = lambda aid: (lst[aid]["student_count"], lst[aid]["submitted_count"], lst[aid]["graded_count"], lst[aid]["pending_count"])
        self.assertEqual(g(a1), (3, 2, 1, 1))     # 3 active students; s0 (3 hand-ins) and s1 submitted; the dropped s3 is ignored; s0 graded; s1 pending
        self.assertEqual(g(a2), (3, 1, 0, 1))
        self.assertEqual(g(t1), (3, 0, 2, 0))     # a test: graded by marks, no hand-in, never pending
        # the same numbers from the raw rows
        with self.app.app_context():
            import dbx
            conn = dbx.Conn(self.app.config["DATABASE_URL"], self.app.config["DATABASE_PATH"], ())
            raw = conn.execute("SELECT COUNT(*) FROM submissions s JOIN assignments a ON a.id=s.assignment_id WHERE a.kind='assignment' AND s.submitted_at IS NOT NULL AND s.grade IS NULL AND s.student_id IN "
                               "(SELECT student_id FROM enrollments WHERE status='active')").fetchone()[0]
            conn.close()
        self.assertEqual(raw, 2)
        home = self.c.get(f"/api/my/home?batch_id={self.b1}", headers=self.T1).get_json()
        self.assertEqual(home["to_grade"], 2)
        self.assertEqual(self.c.get(f"/api/teacher-information/{self.t1[0]}", headers=self.H).get_json()["workload"]["to_grade"], 2)
        # grading removes it from pending everywhere
        grade(a2, self.st[2][0], 7)
        self.assertEqual(self.c.get(f"/api/my/home?batch_id={self.b1}", headers=self.T1).get_json()["to_grade"], 1)
        self.assertEqual(self.c.get(f"/api/teacher-information/{self.t1[0]}", headers=self.H).get_json()["workload"]["to_grade"], 1)
        lst = {a["id"]: a for a in self.c.get(f"/api/assignments?batch_id={self.b1}", headers=self.T1).get_json()}
        self.assertEqual(g(a2), (3, 1, 1, 0))


if __name__ == "__main__":
    unittest.main()
