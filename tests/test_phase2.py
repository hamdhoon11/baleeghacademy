import io, os, sys, tempfile, unittest, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PDF = b"%PDF-1.4 test"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def dob(years):
    t = dt.date.today()
    return f"{t.year - years - 1}-{t.month:02d}-{min(t.day, 28):02d}"  # always at least `years` old, under years+1


class P2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ["DATABASE_PATH"] = os.path.join(tmp, "t.db")
        os.environ["ADMIN_EMAIL"] = "admin@t.test"; os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")  # fresh demo data per suite
        from app import create_app
        cls.mk = staticmethod(create_app)
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"], "APPLY_LIMIT": 100})

    def setUp(self):
        self.c = self.app.test_client()

    def admin(self):
        r = self.c.post("/api/auth/login", json={"email": "admin@t.test", "password": "AdminPass123"})
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    def apply(self, **over):
        d = {"full_name": "Aisha Ali", "date_of_birth": dob(25), "phone": "7771234", "email": "aisha@x.test", "island": "Naifaru",
             "course_id": "1", "batch_id": "1", "id_card": (io.BytesIO(PDF), "id.pdf")}
        d.update(over)
        d = {k: v for k, v in d.items() if v is not None}
        return self.c.post("/api/public/apply", data=d, content_type="multipart/form-data")

    def minor(self, email, **over):
        return self.apply(email=email, date_of_birth=dob(12), guardian_name="Ali", guardian_relationship="Father", guardian_phone="7770000",
                          guardian_id=(io.BytesIO(PNG), "g.png"), **over)

    def test_01_adult_application(self):
        r = self.apply(email="adult1@x.test")
        self.assertEqual(r.status_code, 201); self.assertTrue(r.get_json()["ref"].startswith("BA-"))
        self.assertFalse(r.get_json()["is_minor"])

    def test_02_minor_needs_guardian(self):
        r = self.apply(email="m1@x.test", date_of_birth=dob(12))
        self.assertEqual(r.status_code, 400); self.assertIn("guardian", r.get_json()["error"].lower())
        r = self.apply(email="m2@x.test", date_of_birth=dob(12), guardian_name="A", guardian_relationship="Mother", guardian_phone="777")
        self.assertEqual(r.status_code, 400)  # guardian ID missing
        self.assertEqual(self.minor("m3@x.test").status_code, 201)

    def test_03_file_validation(self):
        self.assertEqual(self.apply(email="f1@x.test", id_card=(io.BytesIO(b"MZ exe"), "a.exe")).status_code, 400)
        self.assertEqual(self.apply(email="f2@x.test", id_card=(io.BytesIO(b"not a pdf"), "a.pdf")).status_code, 400)  # content mismatch
        self.assertEqual(self.apply(email="f3@x.test", id_card=(io.BytesIO(PDF + b"0" * 5_300_000), "big.pdf")).status_code, 400)
        self.assertEqual(self.apply(email="f4@x.test", id_card=None).status_code, 400)

    def test_04_validation(self):
        self.assertEqual(self.apply(email="bad").status_code, 400)
        self.assertEqual(self.apply(email="v1@x.test", date_of_birth="not-a-date").status_code, 400)
        self.assertEqual(self.apply(email="v2@x.test", course_id="2").status_code, 400)  # upcoming course is not open
        self.assertEqual(self.apply(email="v3@x.test", full_name="").status_code, 400)

    def test_05_honeypot_stores_nothing(self):
        n = lambda: len(self.c.get("/api/applications", headers=self.admin()).get_json())
        before = n(); self.apply(email="bot@x.test", website="http://spam"); self.assertEqual(n(), before)

    def test_06_rate_limit(self):
        app = self.mk({"DATABASE_PATH": os.environ["DATABASE_PATH"], "APPLY_LIMIT": 2}); c = app.test_client()
        codes = [c.post("/api/public/apply", data={"full_name": "R", "date_of_birth": dob(30), "phone": "7", "email": f"rl{i}@x.test", "course_id": "1",
                                                   "id_card": (io.BytesIO(PDF), "i.pdf")}, content_type="multipart/form-data",
                         environ_base={"REMOTE_ADDR": "10.9.9.9"}).status_code for i in range(3)]   # v0.8.39: the count is in the database now, so this test uses its own address
        self.assertEqual(codes, [201, 201, 429])

    def test_07_files_admin_only(self):
        self.apply(email="priv@x.test")
        a = [x for x in self.c.get("/api/applications", headers=self.admin()).get_json() if x["email"] == "priv@x.test"][0]
        self.assertEqual(self.c.get(f"/api/applications/{a['id']}/file/id").status_code, 401)
        s = self.c.post("/api/auth/login", json={"email": "student@baleegh.test", "password": "ChangeMe-Stud1"}).get_json()["token"]
        self.assertEqual(self.c.get(f"/api/applications/{a['id']}/file/id", headers={"Authorization": "Bearer " + s}).status_code, 403)
        self.assertEqual(self.c.get("/api/applications", headers={"Authorization": "Bearer " + s}).status_code, 403)
        r = self.c.get(f"/api/applications/{a['id']}/file/id", headers=self.admin())
        self.assertEqual((r.status_code, r.data[:4]), (200, b"%PDF"))
        self.assertNotIn("id_file", a)  # stored filename never exposed in listings
        self.assertEqual(self.c.get("/uploads/x.pdf").status_code, 404)

    def test_08_approve_creates_account_and_enrollment(self):
        h = self.admin()
        ref = self.minor("kid@x.test").get_json()["ref"]
        a = [x for x in self.c.get("/api/applications?status=pending", headers=h).get_json() if x["ref"] == ref][0]
        self.assertEqual(a["is_minor"], 1)
        r = self.c.post(f"/api/applications/{a['id']}/approve", json={"delete_files": True}, headers=h)
        self.assertEqual(r.status_code, 200); j = r.get_json()
        self.assertIn("wa.me/960777", j["whatsapp_link"]); self.assertEqual(j["enrollment_status"], "active")
        login = self.c.post("/api/auth/login", json={"email": "kid@x.test", "password": j["temp_password"]})
        self.assertEqual(login.status_code, 200); self.assertEqual(login.get_json()["user"]["must_change_password"], 1)
        tok = {"Authorization": "Bearer " + login.get_json()["token"]}
        self.assertEqual([b["code"] for b in self.c.get("/api/batches", headers=tok).get_json()], ["004"])
        self.assertEqual(self.c.get(f"/api/applications/{a['id']}/file/id", headers=h).status_code, 404)  # ID copy deleted
        self.assertEqual(self.c.post(f"/api/applications/{a['id']}/approve", json={}, headers=h).status_code, 409)

    def test_09_reject_waitlist_status_lookup(self):
        h = self.admin()
        ref = self.apply(email="rej@x.test", phone="7654321").get_json()["ref"]
        aid = [x for x in self.c.get("/api/applications", headers=h).get_json() if x["ref"] == ref][0]["id"]
        self.assertEqual(self.c.post(f"/api/applications/{aid}/reject", json={}, headers=h).status_code, 400)
        self.assertEqual(self.c.post(f"/api/applications/{aid}/waitlist", headers=h).status_code, 200)
        q = lambda p: self.c.post("/api/public/apply/status", json={"ref": ref, "phone": p})
        self.assertEqual(q("765-4321").get_json()["status"], "waitlist")
        self.assertEqual(q("0000000").status_code, 404)
        self.assertEqual(self.c.post(f"/api/applications/{aid}/reject", json={"reason": "Course full"}, headers=h).status_code, 200)
        self.assertEqual(q("7654321").get_json()["reason"], "Course full")

    def test_10_duplicate_email_and_missing_batch(self):
        h = self.admin()
        ref = self.apply(email="student@baleegh.test", batch_id=None).get_json()["ref"]
        aid = [x for x in self.c.get("/api/applications", headers=h).get_json() if x["ref"] == ref][0]["id"]
        self.assertEqual(self.c.post(f"/api/applications/{aid}/approve", json={}, headers=h).status_code, 400)  # no batch chosen
        self.assertEqual(self.c.post(f"/api/applications/{aid}/approve", json={"batch_id": 1}, headers=h).status_code, 409)  # email exists

    def test_11_public_info_and_batches(self):
        self.assertEqual(self.c.get("/api/public/info").get_json()["whatsapp"], "9607250901")
        self.assertEqual([b["code"] for b in self.c.get("/api/public/batches").get_json()], ["004", "005"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
