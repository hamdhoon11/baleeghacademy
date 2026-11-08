"""Session 29: WhatsApp click-to-chat by phone number (prepare links, log what was opened, permissions)."""
import datetime as dt, os, sys, unittest
from urllib.parse import urlparse, parse_qs
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tests.test_session28 import make_app, PW


class S29(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app, cls.c, cls.H, cls.path = make_app("a29")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role, **kw: P("/api/users", {"email": e, "password": PW, "full_name": kw.pop("n", e), "role": role, **kw}).get_json()["id"]
        cls.t1 = mk("t1@a29.test", "teacher", n="Teacher One", phone="7770001")
        cls.t2 = mk("t2@a29.test", "teacher", n="Teacher NoPhone")
        ar = P("/api/courses", {"name": "Arabic", "code": "AR1", "monthly_fee_mvr": 1000, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": ar, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Wed", "start_time": "16:00"}).get_json()["id"]
        cls.s1 = mk("s1@a29.test", "student", n="Student One", phone="7771111", guardian_name="Guardian One", guardian_phone="+960 777 2222", course_id=ar)
        cls.s2 = mk("s2@a29.test", "student", n="Student Two", course_id=ar)                  # no phone
        cls.s3 = mk("s3@a29.test", "student", n="Student Three", phone="9601234567")          # not enrolled
        for s in (cls.s1, cls.s2): assert P("/api/enrollments", {"student_id": s, "batch_id": cls.b1}).status_code == 201
        cls.lim = mk("lim@a29.test", "admin", permissions=["student_information"])
        tok = lambda e: {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": e, "password": PW}).get_json()["token"]}
        cls.L, cls.T, cls.S = tok("lim@a29.test"), tok("t1@a29.test"), tok("s1@a29.test")

    def prep(self, h=None, **j):
        j.setdefault("message", "Hello {name}, from {academy}"); return self.c.post("/api/whatsapp/prepare", json=j, headers=h or self.H)
    def text(self, it): return parse_qs(urlparse(it["url"]).query)["text"][0]

    def test_01_one_student_link_uses_the_number(self):
        r = self.prep(audience="student", student_id=self.s1); j = r.get_json(); self.assertEqual(r.status_code, 200)
        it = j["items"][0]; self.assertEqual((j["count"], it["to"], it["sent_today"]), (1, "student", False))
        self.assertTrue(it["url"].startswith("https://wa.me/9607771111?text="))               # 7-digit number gets 960
        self.assertEqual(self.text(it), "Hello Student One, from Baleegh Academy")
        self.assertEqual(r.headers["Cache-Control"], "private, no-store")

    def test_02_batch_students_plus_teacher_and_missing_numbers(self):
        j = self.prep(audience="batch", batch_id=self.b1).get_json()
        self.assertEqual(sorted(i["name"] for i in j["items"]), ["Student One", "Teacher One"])
        self.assertEqual([m["name"] for m in j["missing"]], ["Student Two"])

    def test_03_guardians_only_when_asked(self):
        self.assertEqual(len(self.prep(audience="batch", batch_id=self.b1).get_json()["items"]), 2)
        j = self.prep(audience="students", guardians=True, message="Dear {name}: {student}").get_json()
        g = [i for i in j["items"] if i["to"] == "guardian"]; self.assertEqual(len(g), 1)
        self.assertTrue(g[0]["url"].startswith("https://wa.me/9607772222?")); self.assertEqual(self.text(g[0]), "Dear Guardian One: Student One")
        self.assertIn("Parent/Guardian of Student Two (guardian)", [m["name"] for m in j["missing"]])
        self.assertEqual(sorted(i["name"] for i in j["items"] if i["to"] == "student"), ["Student One", "Student Three"])
        self.assertIn("https://wa.me/9601234567?", [i["url"][:25] for i in j["items"] if i["name"] == "Student Three"][0])

    def test_04_audiences(self):
        self.assertEqual(sorted(i["name"] for i in self.prep(audience="teachers").get_json()["items"]), ["Teacher One"])
        self.assertEqual(len(self.prep(audience="everyone").get_json()["items"]), 3)       # S1, S3, T1 (the rest have no number)

    def test_05_bad_input(self):
        for j, code in (({"audience": "students", "message": " "}, 400), ({"audience": "nobody"}, 400), ({"audience": "students", "message": "x" * 1001}, 400), ({"audience": "student"}, 400),
                        ({"audience": "student", "student_id": 9999}, 404), ({"audience": "batch"}, 400), ({"audience": "batch", "batch_id": 9999}, 404)):
            self.assertEqual(self.prep(**j).status_code, code, j)
        self.assertEqual(self.prep(audience="student", student_id=self.t1).status_code, 404)  # a teacher is not a student

    def test_06_message_is_url_safe(self):
        it = self.prep(audience="student", student_id=self.s1, message="A&B=C #1 100% {unknown} \u0786").get_json()["items"][0]
        self.assertEqual(self.text(it), "A&B=C #1 100% {unknown} \u0786"); self.assertEqual(it["url"].count("?"), 1)

    def test_07_sent_log_marks_today_and_audits(self):
        r = self.c.post("/api/whatsapp/sent", json={"user_id": self.s1, "to": "student", "preview": "Hello"}, headers=self.H); self.assertEqual(r.status_code, 201)
        j = self.prep(audience="batch", batch_id=self.b1, guardians=True).get_json()
        self.assertEqual({(i["name"], i["to"]): i["sent_today"] for i in j["items"]}, {("Student One", "student"): True, ("Guardian One", "guardian"): False, ("Teacher One", "teacher"): False})
        self.assertEqual(self.c.post("/api/whatsapp/sent", json={"user_id": self.s1, "to": "guardian"}, headers=self.H).status_code, 201)
        self.app.config["NOW"] = lambda: dt.datetime(2027, 3, 11, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=5)))     # next day: free again
        self.assertFalse(self.prep(audience="student", student_id=self.s1).get_json()["items"][0]["sent_today"])
        log = self.c.get("/api/audit?action=whatsapp_sent", headers=self.H).get_json(); rows = log if isinstance(log, list) else log.get("items", log.get("rows", []))
        self.assertGreaterEqual(len([r for r in rows if r["action"] == "whatsapp_sent"]), 2)
        for j, code in (({"user_id": self.s1, "to": "x"}, 400), ({"to": "student"}, 400), ({"user_id": 9999, "to": "student"}, 404), ({"user_id": self.t1, "to": "student"}, 404), ({"user_id": self.s1, "to": "teacher"}, 404)):
            self.assertEqual(self.c.post("/api/whatsapp/sent", json=j, headers=self.H).status_code, code, j)

    def test_08_permissions(self):
        for h in (self.T, self.S):
            self.assertEqual(self.prep(h, audience="students").status_code, 403)
            self.assertEqual(self.c.post("/api/whatsapp/sent", json={"user_id": self.s1, "to": "student"}, headers=h).status_code, 403)
        self.assertEqual(self.c.post("/api/whatsapp/prepare", json={"audience": "students", "message": "x"}).status_code, 401)
        self.assertEqual(self.prep(self.L, audience="students").status_code, 200)             # student_information only
        self.assertEqual(self.prep(self.L, audience="teachers").status_code, 403)             # needs teacher_information
        self.assertEqual(self.prep(self.L, audience="everyone").status_code, 403)
        j = self.prep(self.L, audience="batch", batch_id=self.b1).get_json(); self.assertEqual([i["name"] for i in j["items"]], ["Student One"])   # no teacher number without the area


if __name__ == "__main__":
    unittest.main()
