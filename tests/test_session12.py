"""Session 12: courses and tuition classes, batches (teacher, students), inactive courses, no link field on the Batches screen."""
import os, sys, tempfile, unittest, datetime as dt
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"


class S12(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ.update(DATABASE_PATH=os.path.join(tmp, "t.db"), ADMIN_EMAIL="admin@s12.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})
        cls.c = cls.app.test_client()
        r = cls.c.post("/api/auth/login", json={"login": "admin@s12.test", "password": "AdminPass123"})
        cls.H = {"Authorization": "Bearer " + r.get_json()["token"]}
        cls.n = 0
        cls.month = dt.datetime.now(dt.timezone(dt.timedelta(hours=5))).strftime("%Y-%m")

    def J(self, m, u, **k):
        k.setdefault("headers", self.H)
        return getattr(self.c, m)(u, **k)

    def person(self, role, name):
        S12.n += 1
        r = self.J("post", "/api/users", json={"email": f"p{S12.n}@s12.test", "password": PW, "full_name": name, "role": role})
        self.assertEqual(r.status_code, 201); return r.get_json()["id"]

    def tuition(self, name="Grade 8 Mathematics", fee=300):
        r = self.J("post", "/api/courses", json={"name": name, "kind": "tuition", "monthly_fee_mvr": fee, "status": "open"})
        self.assertEqual(r.status_code, 201, r.get_json()); return r.get_json()["id"]

    def test_01_tuition_class_gets_batch_teacher_student_and_invoice(self):
        cid = self.tuition()
        c = [x for x in self.J("get", "/api/courses").get_json() if x["id"] == cid][0]
        self.assertEqual((c["kind"], c["code"], c["is_active"]), ("tuition", "G8M", 1))
        t = self.person("teacher", "Maths Teacher"); s = self.person("student", "Maths Kid")
        bid = self.J("post", "/api/batches", json={"course_id": cid, "code": "A", "teacher_id": t, "capacity": 10, "days": "Mon,Wed", "start_time": "16:00"}).get_json()["id"]
        b = [x for x in self.J("get", "/api/batches").get_json() if x["id"] == bid][0]
        self.assertEqual((b["course_kind"], b["course_active"], b["teacher_id"]), ("tuition", 1, t))
        sn = S12.n   # s is the newest person: its email is p<sn>
        r = self.J("post", "/api/enrollments", json={"student_id": s, "batch_id": bid}); self.assertEqual(r.status_code, 201)
        iid = r.get_json()["invoice_id"]; self.assertTrue(iid)
        # it shows in the student's own invoices, the invoice list and the monthly report with no extra step
        tok = self.c.post("/api/auth/login", json={"login": f"p{sn}@s12.test", "password": PW}).get_json()["token"]
        mine = self.c.get("/api/my/fees", headers={"Authorization": "Bearer " + tok}).get_json()
        mine = mine if isinstance(mine, list) else mine.get("invoices", mine)
        self.assertTrue(any(i["id"] == iid and "Grade 8 Mathematics" in str(i) for i in mine), mine)   # the student's Fees tab
        rep = self.J("get", f"/api/fees/report?month={self.month}").get_json()
        self.assertTrue(any(x["course_name"] == "Grade 8 Mathematics" for x in rep["by_course"]))
        # generating again makes no duplicate
        self.J("post", "/api/invoices/generate", json={"month": self.month})                 # may bill the seeded demo student, which is not ours
        g = self.J("post", "/api/invoices/generate", json={"month": self.month}).get_json()
        self.assertEqual(g["created"], 0)
        self.assertEqual(len([i for i in self.J("get", "/api/invoices").get_json() if i["enrollment_id"] == r.get_json()["id"]]), 1)

    def test_02_students_in_batch_enrol_and_remove(self):
        cid = self.tuition("Grade 9 Science", 250)
        bid = self.J("post", "/api/batches", json={"course_id": cid, "code": "A", "capacity": 5}).get_json()["id"]
        s = self.person("student", "Sci Kid")
        eid = self.J("post", "/api/enrollments", json={"student_id": s, "batch_id": bid}).get_json()["id"]
        lst = self.J("get", f"/api/batches/{bid}/students").get_json()
        self.assertEqual([(x["id"], x["enrollment_id"]) for x in lst], [(s, eid)])
        self.assertEqual(self.J("patch", f"/api/enrollments/{eid}", json={"status": "dropped"}).status_code, 200)
        self.assertEqual(self.J("get", f"/api/batches/{bid}/students").get_json(), [])
        self.assertEqual(self.c.get(f"/api/batches/{bid}/students").status_code, 401)

    def test_03_inactive_course_vanishes_from_new_work_but_stays_in_reports(self):
        cid = self.tuition("Grade 7 English", 200)
        t = self.person("teacher", "Eng Teacher"); s1 = self.person("student", "Old Student"); s2 = self.person("student", "New Student")
        bid = self.J("post", "/api/batches", json={"course_id": cid, "code": "A", "teacher_id": t, "capacity": 5}).get_json()["id"]
        self.J("post", "/api/enrollments", json={"student_id": s1, "batch_id": bid})
        other = self.J("post", "/api/batches", json={"course_id": self.tuition("Grade 7 Dhivehi", 100), "code": "A", "capacity": 5}).get_json()["id"]
        self.assertEqual(self.J("patch", f"/api/courses/{cid}", json={"is_active": False}).status_code, 200)
        names = lambda path: [x["name"] for x in self.J("get", path).get_json()]
        self.assertNotIn("Grade 7 English", names("/api/courses?active=1"))
        self.assertIn("Grade 7 English", names("/api/courses"))                                   # admin list and reports keep it
        self.assertNotIn("Grade 7 English", names("/api/public/courses"))
        self.assertEqual(self.J("post", "/api/enrollments", json={"student_id": s2, "batch_id": bid}).status_code, 409)
        self.assertEqual(self.J("post", "/api/batches", json={"course_id": cid, "code": "B", "capacity": 5}).status_code, 409)
        e2 = self.J("post", "/api/enrollments", json={"student_id": s2, "batch_id": other}).get_json()["id"]
        self.assertEqual(self.J("patch", f"/api/enrollments/{e2}", json={"transfer_to_batch_id": bid}).status_code, 409)
        # no new invoice for the inactive course next month, and the skip says why; the old invoice is still in the report
        nxt = (dt.date.today().replace(day=1) + dt.timedelta(days=40)).strftime("%Y-%m")
        g = self.J("post", "/api/invoices/generate", json={"month": nxt}).get_json()
        self.assertTrue(any(d["course"] == "Grade 7 English" and d["reason"] == "course_inactive" for d in g["details"]))
        rep = self.J("get", f"/api/fees/report?month={self.month}").get_json()
        self.assertTrue(any(x["course_name"] == "Grade 7 English" for x in rep["by_course"]))
        self.assertEqual(self.J("patch", f"/api/courses/{cid}", json={"is_active": True}).status_code, 200)   # and it can come back
        self.assertEqual(self.J("post", "/api/enrollments", json={"student_id": s2, "batch_id": bid}).status_code, 201)

    def test_04_course_type_and_code_validation(self):
        r = self.J("post", "/api/courses", json={"name": "Odd", "kind": "club"}); self.assertEqual(r.status_code, 400)
        a = self.J("post", "/api/courses", json={"name": "Quran Recitation", "code": "QR1"}).get_json()["id"]
        self.assertEqual(self.J("post", "/api/courses", json={"name": "Quran Two", "code": "qr1"}).status_code, 409)
        self.assertEqual(self.J("patch", f"/api/courses/{a}", json={"kind": "tuition"}).status_code, 200)
        self.assertEqual(self.c.post("/api/courses", json={"name": "x"}).status_code, 401)
        t = self.person("teacher", "Not Admin")
        tok = self.c.post("/api/auth/login", json={"login": f"p{S12.n}@s12.test", "password": PW}).get_json()["token"]
        self.assertEqual(self.c.post("/api/courses", json={"name": "x"}, headers={"Authorization": "Bearer " + tok}).status_code, 403)

    def test_05_batch_link_is_not_on_the_batches_screen_but_stays_in_classroom(self):
        read = lambda f: open(os.path.join(ROOT, "static", f), encoding="utf-8").read()
        L, A = read("learning.js"), read("admin.js")
        self.assertNotIn('id="be_m"', L); self.assertNotIn('field("bm"', L); self.assertNotIn('val("be_m")', L + A); self.assertNotIn('val("bm")', L)
        self.assertIn('id="ml"', L)                                                                # Classroom still edits it
        cid = self.tuition("Link Class", 100)
        bid = self.J("post", "/api/batches", json={"course_id": cid, "code": "A", "capacity": 5}).get_json()["id"]
        self.assertEqual(self.J("put", f"/api/batches/{bid}/meet-link", json={"meet_link": "https://meet.google.com/abc-defg-hij"}).status_code, 200)
        self.assertEqual(self.J("patch", f"/api/batches/{bid}", json={"capacity": 8}).status_code, 200)   # what the Batches screen now sends
        b = [x for x in self.J("get", "/api/batches").get_json() if x["id"] == bid][0]
        self.assertEqual(b["meet_link"], "https://meet.google.com/abc-defg-hij")                   # saving the screen does not erase the link


if __name__ == "__main__":
    unittest.main()
