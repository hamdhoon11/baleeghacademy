"""Session 17: grading rules. Saved grades change only by admin or a teacher with edit_grades; every change logged old -> new; student columns and status."""
import os, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"


class S17(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ.update(DATABASE_PATH=os.path.join(tmp, "t.db"), ADMIN_EMAIL="admin@s17.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})
        cls.c = cls.app.test_client()
        cls.H = cls.tok("admin@s17.test", "AdminPass123")
        cls.n = 0
        cls.t1 = cls.make("teacher", "Teacher One"); cls.t2 = cls.make("teacher", "Teacher Two")
        cls.s1 = cls.make("student", "Student One"); cls.s2 = cls.make("student", "Student Two"); cls.s3 = cls.make("student", "Student Three")
        cid = cls.c.post("/api/courses", json={"name": "Arabic Level 1", "monthly_fee_mvr": 100, "status": "open"}, headers=cls.H).get_json()["id"]
        cls.b = cls.c.post("/api/batches", json={"course_id": cid, "code": "A1", "teacher_id": cls.t1[0], "capacity": 9, "days": "Mon", "start_time": "16:00"}, headers=cls.H).get_json()["id"]
        for s in (cls.s1, cls.s2, cls.s3):
            assert cls.c.post("/api/enrollments", json={"student_id": s[0], "batch_id": cls.b}, headers=cls.H).status_code in (200, 201)
        cls.a = cls.c.post(f"/api/batches/{cls.b}/assignments", json={"title": "HW1", "max_points": 10}, headers=cls.H).get_json()["id"]
        cls.T1, cls.T2, cls.S1, cls.S2 = (cls.tok(x[1], PW) for x in (cls.t1, cls.t2, cls.s1, cls.s2))

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def make(cls, role, name):
        cls.n += 1; email = f"p{cls.n}@s17.test"
        r = cls.c.post("/api/users", json={"email": email, "password": PW, "full_name": name, "role": role}, headers=cls.H)
        return r.get_json()["id"], email

    def grade(self, H, sid, g, fb=""): return self.c.post(f"/api/assignments/{self.a}/grades", json={"student_id": sid, "grade": g, "feedback": fb}, headers=H)

    def log(self, action):
        return [r for r in self.c.get("/api/audit", headers=self.H).get_json() if r["action"] == action and r["entity_id"] == self.a]

    def test_01_first_grade_ok_change_blocked_for_plain_teacher(self):
        r = self.grade(self.T1, self.s1[0], 6, "ok"); self.assertEqual(r.status_code, 200)
        r = self.grade(self.T1, self.s1[0], 9, "better"); self.assertEqual(r.status_code, 403); self.assertIn("error", r.get_json())
        mine = self.c.get(f"/api/my/grades?batch_id={self.b}", headers=self.S1).get_json()[0]["items"][0]
        self.assertEqual((mine["grade"], mine["feedback"]), (6, "ok"))                  # unchanged
        self.assertEqual(self.grade(self.T1, self.s1[0], 6, "ok").get_json()["changed"], False)   # same values: harmless no-op
        self.assertFalse(self.c.get(f"/api/assignments/{self.a}/submissions", headers=self.T1).get_json()["can_edit_grades"])

    def test_02_admin_can_change_and_log_has_old_and_new(self):
        before = len(self.log("grade_change"))
        self.assertEqual(self.grade(self.H, self.s1[0], 8, "revised").status_code, 200)
        rows = self.log("grade_change"); self.assertEqual(len(rows), before + 1)
        d = rows[0]["detail"]; self.assertIn("6.0 -> 8.0", d.replace("6 ->", "6.0 ->")); self.assertIn(f"student {self.s1[0]}", d); self.assertIn("ok -> revised", d)
        first = [r for r in self.log("grade") if f"student {self.s1[0]}:" in r["detail"]]
        self.assertEqual(len(first), 1); self.assertIn("none -> 6", first[0]["detail"])

    def test_03_admin_grants_and_revokes_edit_grades(self):
        t = self.t1[0]
        # "everything a teacher has" does NOT include it
        self.assertEqual(self.grade(self.T1, self.s1[0], 9).status_code, 403)
        r = self.c.patch(f"/api/users/{t}", json={"permissions": ["classroom", "edit_grades"]}, headers=self.H); self.assertEqual(r.status_code, 200, r.get_json())
        T = self.tok(self.t1[1], PW)
        self.assertEqual(self.grade(T, self.s1[0], 9, "teacher edit").status_code, 200)
        self.assertTrue(self.c.get(f"/api/assignments/{self.a}/submissions", headers=T).get_json()["can_edit_grades"])
        self.assertTrue(any("-> 9.0" in r["detail"] or "-> 9" in r["detail"] for r in self.log("grade_change")))
        self.assertEqual(self.c.patch(f"/api/users/{t}", json={"permissions": ["classroom"]}, headers=self.H).status_code, 200)
        self.assertEqual(self.grade(self.tok(self.t1[1], PW), self.s1[0], 3).status_code, 403)              # revoked
        self.assertEqual(self.c.patch(f"/api/users/{t}", json={"permissions": "all"}, headers=self.H).status_code, 200)
        self.assertEqual(self.grade(self.tok(self.t1[1], PW), self.s1[0], 3).status_code, 403)              # back to "everything": still no

    def test_04_other_teacher_and_student_cannot_grade(self):
        self.assertEqual(self.grade(self.T2, self.s2[0], 5).status_code, 403)
        self.assertEqual(self.grade(self.S2, self.s2[0], 10).status_code, 403)
        self.assertEqual(self.c.patch(f"/api/users/{self.t2[0]}", json={"permissions": ["classroom", "edit_grades"]}, headers=self.H).status_code, 200)
        self.assertEqual(self.grade(self.tok(self.t2[1], PW), self.s2[0], 5).status_code, 403)   # edit_grades does not reach a batch that is not theirs
        self.assertEqual(self.c.patch(f"/api/users/{self.s1[0]}", json={"permissions": ["edit_grades"]}, headers=self.H).status_code, 400)  # students cannot hold it

    def test_05_teacher_sees_grades_they_gave(self):
        j = self.c.get(f"/api/my/given-grades?batch_id={self.b}", headers=self.tok(self.t1[1], PW)).get_json()
        self.assertEqual([(x["student_id"], x["grade"]) for x in j["grades"]], [(self.s1[0], 9)])
        self.assertFalse(j["can_edit_grades"])
        self.assertEqual(self.c.get("/api/my/given-grades", headers=self.tok(self.t2[1], PW)).get_json()["grades"], [])
        self.assertEqual(self.c.get(f"/api/my/given-grades?batch_id={self.b}", headers=self.tok(self.t2[1], PW)).status_code, 403)
        self.assertEqual(self.c.get("/api/my/given-grades", headers=self.S1).status_code, 403)
        self.assertEqual(self.c.get("/api/my/given-grades").status_code, 401)

    def test_06_student_status_and_separate_columns(self):
        import io
        self.assertEqual(self.c.post(f"/api/assignments/{self.a}/submit", data={"text": "my answer"}, headers=self.S2, content_type="multipart/form-data").status_code, 201)
        it = lambda H: self.c.get(f"/api/my/grades?batch_id={self.b}", headers=H).get_json()[0]["items"][0]
        self.assertEqual(it(self.S2)["status"], "submitted"); self.assertIsNone(it(self.S2)["grade"])
        S3 = self.tok(self.s3[1], PW); self.assertEqual(it(S3)["status"], "pending")
        self.assertEqual(self.grade(self.H, self.s2[0], 7, "nice work").status_code, 200)
        x = it(self.S2); self.assertEqual((x["status"], x["grade"], x["feedback"]), ("graded", 7, "nice work"))
        self.assertEqual(it(self.S1)["status"], "graded")
        js = open(os.path.join(ROOT, "static/learning.js"), encoding="utf-8").read()
        self.assertIn('t("teacher_comment")', js); self.assertIn('t("status")', js)

    def test_07_validation_and_no_log_on_refusal(self):
        n = len(self.log("grade_change")) + len(self.log("grade"))
        self.assertEqual(self.grade(self.H, self.s3[0], 99).status_code, 400)
        self.assertEqual(self.grade(self.T2, self.s3[0], 5).status_code, 403)
        self.assertEqual(len(self.log("grade_change")) + len(self.log("grade")), n)


if __name__ == "__main__":
    unittest.main()
