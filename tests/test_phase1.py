import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class P1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ["DATABASE_PATH"] = os.path.join(tmp, "t.db")
        os.environ["ADMIN_EMAIL"] = "admin@t.test"
        os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")  # fresh demo data per suite
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})

    def setUp(self):
        self.c = self.app.test_client()

    def login(self, email, pw):
        r = self.c.post("/api/auth/login", json={"email": email, "password": pw})
        return r, {"Authorization": "Bearer " + (r.get_json() or {}).get("token", "x")}

    def adm(self): return self.login("admin@t.test", "AdminPass123")[1]
    def tch(self): return self.login("teacher@baleegh.test", "ChangeMe-Teach1")[1]
    def stu(self): return self.login("student@baleegh.test", "ChangeMe-Stud1")[1]

    def mkstudent(self, h, email):
        return self.c.post("/api/users", json={"email": email, "password": "Password123", "full_name": email, "role": "student"}, headers=h).get_json()["id"]

    def test_01_login(self):
        r, _ = self.login("admin@t.test", "AdminPass123"); self.assertEqual(r.status_code, 200)
        r, _ = self.login("admin@t.test", "wrong"); self.assertEqual(r.status_code, 401)
        self.assertEqual(self.c.get("/api/users").status_code, 401)

    def test_02_roles_blocked(self):
        for h in (self.stu(), self.tch()):
            self.assertEqual(self.c.get("/api/users", headers=h).status_code, 403)
            self.assertEqual(self.c.post("/api/courses", json={"name": "X"}, headers=h).status_code, 403)
            self.assertEqual(self.c.get("/api/audit", headers=h).status_code, 403)
            self.assertEqual(self.c.get("/api/settings", headers=h).status_code, 403)

    def test_03_course_batch_create(self):
        h = self.adm()
        r = self.c.post("/api/courses", json={"name": "Tajweed", "monthly_fee_mvr": 300, "status": "open"}, headers=h)
        self.assertEqual(r.status_code, 201); cid = r.get_json()["id"]
        self.assertEqual(self.c.post("/api/courses", json={"name": "Bad", "monthly_fee_mvr": -5}, headers=h).status_code, 400)
        self.assertEqual(self.c.post("/api/batches", json={"course_id": cid, "code": "001", "capacity": 1}, headers=h).status_code, 201)
        self.assertEqual(self.c.post("/api/batches", json={"course_id": cid, "code": "001"}, headers=h).status_code, 409)

    def test_04_capacity_waitlist_transfer(self):
        h = self.adm()
        cid = self.c.post("/api/courses", json={"name": "Cap", "status": "open"}, headers=h).get_json()["id"]
        b1 = self.c.post("/api/batches", json={"course_id": cid, "code": "A", "capacity": 1}, headers=h).get_json()["id"]
        b2 = self.c.post("/api/batches", json={"course_id": cid, "code": "B", "capacity": 5}, headers=h).get_json()["id"]
        s0, s1 = self.mkstudent(h, "s0@t.test"), self.mkstudent(h, "s1@t.test")
        e1 = self.c.post("/api/enrollments", json={"student_id": s0, "batch_id": b1}, headers=h).get_json()
        e2 = self.c.post("/api/enrollments", json={"student_id": s1, "batch_id": b1}, headers=h).get_json()
        self.assertEqual((e1["status"], e2["status"]), ("active", "waitlist"))
        self.assertEqual(self.c.post("/api/enrollments", json={"student_id": s0, "batch_id": b1}, headers=h).status_code, 409)
        self.assertEqual(self.c.patch(f"/api/enrollments/{e1['id']}", json={"transfer_to_batch_id": b2}, headers=h).status_code, 200)

    def test_05_student_sees_only_own(self):
        h = self.stu()
        en = self.c.get("/api/enrollments", headers=h).get_json()
        self.assertTrue(en and all(e["student_name"] == "Demo Student" for e in en))
        self.assertEqual(self.c.get("/api/enrollments", headers=self.tch()).status_code, 403)
        self.assertEqual([b["code"] for b in self.c.get("/api/batches", headers=h).get_json()], ["004"])

    def test_06_teacher_only_own_batch(self):
        a = self.adm()
        other = self.c.post("/api/users", json={"email": "t2@t.test", "password": "Password123", "full_name": "T2", "role": "teacher"}, headers=a).get_json()["id"]
        cid = self.c.post("/api/courses", json={"name": "Other"}, headers=a).get_json()["id"]
        bid = self.c.post("/api/batches", json={"course_id": cid, "code": "Z", "teacher_id": other}, headers=a).get_json()["id"]
        t = self.tch()
        self.assertEqual(self.c.get(f"/api/batches/{bid}/students", headers=t).status_code, 403)
        self.assertEqual(self.c.get("/api/batches/1/students", headers=t).status_code, 200)
        self.assertNotIn(bid, [b["id"] for b in self.c.get("/api/batches", headers=t).get_json()])

    def test_07_user_validation_and_disable(self):
        h = self.adm()
        self.assertEqual(self.c.post("/api/users", json={"email": "bad", "password": "Password123", "full_name": "X", "role": "student"}, headers=h).status_code, 400)
        self.assertEqual(self.c.post("/api/users", json={"email": "admin@t.test", "password": "Password123", "full_name": "X", "role": "admin"}, headers=h).status_code, 409)
        uid = self.mkstudent(h, "off@t.test")
        self.c.patch(f"/api/users/{uid}", json={"is_active": False}, headers=h)
        self.assertEqual(self.login("off@t.test", "Password123")[0].status_code, 401)

    def test_08_password_settings_audit_public(self):
        h = self.adm()
        self.assertEqual(self.c.post("/api/auth/change-password", json={"current_password": "nope", "new_password": "NewPass1234"}, headers=h).status_code, 400)
        self.assertEqual(self.c.put("/api/settings", json={"bank_name": "BML"}, headers=h).status_code, 200)
        self.assertEqual(self.c.get("/api/settings", headers=h).get_json()["bank_name"], "BML")
        self.assertTrue(len(self.c.get("/api/audit", headers=h).get_json()) > 3)
        self.assertTrue(any(c["name"] == "Arabic" for c in self.c.get("/api/public/courses").get_json()))
        self.assertIn("students", self.c.get("/api/dashboard", headers=h).get_json())

    def test_09_no_language_switch(self):
        # the portal is English only: the language endpoint and the Dhivehi file are gone
        h = self.stu()
        self.assertIn(self.c.patch("/api/auth/language", json={"lang": "dv"}, headers=h).status_code, (404, 405))
        self.assertEqual(self.c.get("/i18n/dv.json").status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
