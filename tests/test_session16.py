"""Session 16: My Information (student and teacher): own data only, read-only, no fees/secrets."""
import os, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"


class S16(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ.update(DATABASE_PATH=os.path.join(tmp, "t.db"), ADMIN_EMAIL="admin@s16.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})
        cls.c = cls.app.test_client()
        cls.H = cls.tok("admin@s16.test", "AdminPass123")
        cls.n = 0
        cls.t1 = cls.make("teacher", "Teacher One"); cls.t2 = cls.make("teacher", "Teacher Two")
        cls.s1 = cls.make("student", "Student One", phone="7771111"); cls.s2 = cls.make("student", "Student Two", phone="7772222")
        c1 = cls.c.post("/api/courses", json={"name": "Arabic Level 1", "monthly_fee_mvr": 100, "status": "open"}, headers=cls.H).get_json()["id"]
        c2 = cls.c.post("/api/courses", json={"name": "Grade 8 Mathematics", "kind": "tuition", "monthly_fee_mvr": 200, "status": "open"}, headers=cls.H).get_json()["id"]
        mk = lambda c, code, t: cls.c.post("/api/batches", json={"course_id": c, "code": code, "teacher_id": t[0], "capacity": 5, "days": "Mon,Wed", "start_time": "16:00"}, headers=cls.H).get_json()["id"]
        cls.b1, cls.b2, cls.b3 = mk(c1, "A1", cls.t1), mk(c2, "M8", cls.t1), mk(c1, "B1", cls.t2)
        for s, b in ((cls.s1, cls.b1), (cls.s1, cls.b2), (cls.s2, cls.b3)):
            r = cls.c.post("/api/enrollments", json={"student_id": s[0], "batch_id": b}, headers=cls.H); assert r.status_code in (200, 201), r.get_json()
        cls.T1, cls.T2, cls.S1, cls.S2 = (cls.tok(x[1], PW) for x in (cls.t1, cls.t2, cls.s1, cls.s2))

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def make(cls, role, name, **extra):
        cls.n += 1; email = f"p{cls.n}@s16.test"
        r = cls.c.post("/api/users", json={"email": email, "password": PW, "full_name": name, "role": role, **extra}, headers=cls.H)
        return r.get_json()["id"], email

    def info(self, H): return self.c.get("/api/my/information", headers=H)

    def test_01_student_sees_own_page(self):
        r = self.info(self.S1); self.assertEqual(r.status_code, 200); j = r.get_json()
        self.assertEqual(j["role"], "student"); self.assertEqual(j["profile"]["full_name"], "Student One"); self.assertEqual(j["profile"]["phone"], "7771111")
        self.assertTrue(j["profile"].get("student_code")); self.assertTrue(j["profile"].get("login_id"))
        self.assertEqual(sorted(b["code"] for b in j["batches"]), ["A1", "M8"])
        self.assertEqual({b["course_kind"] for b in j["batches"]}, {"course", "tuition"})
        self.assertTrue(all(b["enrol_code"] for b in j["batches"]))
        self.assertEqual([b["code"] for b in self.info(self.S2).get_json()["batches"]], ["B1"])

    def test_02_teacher_sees_own_page(self):
        j = self.info(self.T1).get_json()
        self.assertEqual(j["role"], "teacher"); self.assertEqual(j["profile"]["full_name"], "Teacher One"); self.assertTrue(j["profile"].get("teacher_code"))
        self.assertEqual(sorted(b["code"] for b in j["batches"]), ["A1", "M8"])
        self.assertEqual([b["code"] for b in self.info(self.T2).get_json()["batches"]], ["B1"])

    def test_03_no_fees_notes_or_secrets(self):
        for H in (self.S1, self.T1):
            txt = self.info(H).get_data(as_text=True).lower()
            for bad in ("password", "hash", "invoice", "balance", "amount", "fee", "permissions", "id_card", "notes"):
                self.assertNotIn(bad, txt, bad)

    def test_04_no_way_to_ask_for_someone_else(self):
        # the person is the token; an id in the query or path changes nothing
        a = self.c.get(f"/api/my/information?id={self.s2[0]}&user_id={self.s2[0]}", headers=self.S1).get_json()
        self.assertEqual(a["profile"]["full_name"], "Student One")
        self.assertEqual(self.c.get(f"/api/my/information/{self.s2[0]}", headers=self.S1).status_code, 404)
        for path in (f"/api/student-information/{self.s2[0]}", f"/api/teacher-information/{self.t2[0]}", f"/api/users/{self.s2[0]}", "/api/users"):
            self.assertEqual(self.c.get(path, headers=self.S1).status_code, 403, path)
            self.assertEqual(self.c.get(path, headers=self.T1).status_code, 403, path)

    def test_05_locked_fields_cannot_be_changed(self):
        for H, uid in ((self.S1, self.s1[0]), (self.T1, self.t1[0])):
            for m in (self.c.patch, self.c.put, self.c.post):
                self.assertIn(m("/api/my/information", json={"full_name": "Hacked", "phone": "1"}, headers=H).status_code, (403, 405))
            self.assertEqual(self.c.patch(f"/api/users/{uid}", json={"full_name": "Hacked", "login_id": "BAL/X/999"}, headers=H).status_code, 403)
        self.assertEqual(self.info(self.S1).get_json()["profile"]["full_name"], "Student One")
        self.assertEqual(self.info(self.T1).get_json()["profile"]["full_name"], "Teacher One")

    def test_06_access_rules_and_tab(self):
        self.assertEqual(self.c.get("/api/my/information").status_code, 401)
        self.assertEqual(self.info(self.H).status_code, 403)        # admins have the directories instead
        for H in (self.S1, self.T1):
            self.assertIn("my_information", self.c.get("/api/auth/me", headers=H).get_json()["user"]["tabs"])
        self.assertNotIn("my_information", self.c.get("/api/auth/me", headers=self.H).get_json()["user"]["tabs"])

    def test_07_dropped_batch_leaves_the_page(self):
        eid = [e for e in self.c.get(f"/api/batches/{self.b2}/students", headers=self.H).get_json() if e.get("student_id", e.get("id")) == self.s1[0] or True][0]["enrollment_id"]
        self.assertEqual(self.c.patch(f"/api/enrollments/{eid}", json={"status": "dropped"}, headers=self.H).status_code, 200)
        self.assertEqual([b["code"] for b in self.info(self.S1).get_json()["batches"]], ["A1"])


if __name__ == "__main__":
    unittest.main()
