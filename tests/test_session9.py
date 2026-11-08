"""Session 9: invoices for new courses, skip reasons, cron endpoint, catch-up, invoice PDF."""
import os, sys, tempfile, unittest, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PW = "Passw0rd!x1"


class S9(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ.update(DATABASE_PATH=os.path.join(cls.tmp, "t.db"), ADMIN_EMAIL="admin@t.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"], "CRON_SECRET": "s3cret-value"})
        cls.n = 0

    def setUp(self):
        self.c = self.app.test_client()
        r = self.c.post("/api/auth/login", json={"email": "admin@t.test", "password": "AdminPass123"})
        self.H = {"Authorization": "Bearer " + r.get_json()["token"]}
        self.month = dt.datetime.now(dt.timezone(dt.timedelta(hours=5))).strftime("%Y-%m")

    def J(self, m, u, **k):
        k.setdefault("headers", self.H)
        return getattr(self.c, m)(u, **k)

    def setup_enrolment(self, fee):
        S9.n += 1; n = S9.n
        body = {"name": f"Course {n}", "status": "open"}
        if fee is not None: body["monthly_fee_mvr"] = fee
        cr = self.J("post", "/api/courses", json=body); self.assertEqual(cr.status_code, 201)
        cid = cr.get_json()["id"]
        t = self.J("post", "/api/users", json={"email": f"t{n}@t.test", "password": PW, "full_name": "T", "role": "teacher"}).get_json()["id"]
        bid = self.J("post", "/api/batches", json={"course_id": cid, "code": f"X{n}", "teacher_id": t, "capacity": 5, "days": "Mon,Wed", "start_time": "16:00"}).get_json()["id"]
        sid = self.J("post", "/api/users", json={"email": f"s{n}@t.test", "password": PW, "full_name": f"Student {n}", "role": "student"}).get_json()["id"]
        return cr, cid, bid, sid

    def invoices(self, sid):
        return self.J("get", f"/api/invoices?student_id={sid}").get_json()

    # ---- the reported case: new course, new batch, enrolled student
    def test_01_new_course_enrolment_gets_one_invoice_linked_to_enrolment(self):
        _, cid, bid, sid = self.setup_enrolment(800)
        r = self.J("post", "/api/enrollments", json={"student_id": sid, "batch_id": bid})
        self.assertEqual(r.status_code, 201)
        inv = self.invoices(sid)
        self.assertEqual(len(inv), 1)
        self.assertEqual((inv[0]["enrollment_id"], inv[0]["course_id"], inv[0]["batch_id"], inv[0]["amount_mvr"]), (r.get_json()["id"], cid, bid, 800))
        self.assertEqual(r.get_json()["invoice_id"], inv[0]["id"])
        # visible in the student's own Fees tab straight away
        st = self.c.post("/api/auth/login", json={"email": f"s{S9.n}@t.test", "password": PW}).get_json()["token"]
        mine = self.c.get("/api/my/fees", headers={"Authorization": "Bearer " + st}).get_json()["invoices"]
        self.assertEqual([i["id"] for i in mine], [inv[0]["id"]])

    def test_02_repeat_generation_creates_no_duplicate(self):
        _, _, bid, sid = self.setup_enrolment(600)
        self.J("post", "/api/enrollments", json={"student_id": sid, "batch_id": bid})
        for _ in range(2):
            self.assertEqual(self.J("post", "/api/invoices/generate", json={"month": self.month}).status_code, 200)
        self.assertEqual(self.J("post", "/api/invoices/catch-up").status_code, 200)
        self.assertEqual(len(self.invoices(sid)), 1)

    # ---- fee 0: explained, warned about, and fixed when the fee is set
    def test_03_fee_zero_is_explained_everywhere(self):
        cr, cid, bid, sid = self.setup_enrolment(None)
        self.assertEqual(cr.get_json()["warning"], "fee_zero")
        r = self.J("post", "/api/enrollments", json={"student_id": sid, "batch_id": bid}).get_json()
        self.assertEqual((r["invoice_id"], r["invoice_skipped"]), (None, "fee_zero"))
        self.assertTrue(r["invoice_message"])
        g = self.J("post", "/api/invoices/generate", json={"month": self.month}).get_json()
        d = [x for x in g["details"] if x["enrollment_id"] == r["id"]]
        self.assertEqual(len(d), 1); self.assertEqual((d[0]["reason"], d[0]["course"], d[0]["batch"]), ("fee_zero", f"Course {S9.n}", f"X{S9.n}"))
        self.assertEqual(self.invoices(sid), [])
        # setting the fee bills the enrolment that was skipped
        p = self.J("patch", f"/api/courses/{cid}", json={"monthly_fee_mvr": 450})
        self.assertEqual(p.get_json()["invoices_created"], 1)
        inv = self.invoices(sid); self.assertEqual((len(inv), inv[0]["amount_mvr"]), (1, 450))

    def test_04_already_invoiced_reason_and_totals(self):
        _, _, bid, sid = self.setup_enrolment(300)
        a = self.J("post", "/api/enrollments", json={"student_id": sid, "batch_id": bid}).get_json()
        g = self.J("post", "/api/invoices/generate", json={"month": self.month}).get_json()
        d = [x for x in g["details"] if x["enrollment_id"] == a["id"]]
        self.assertEqual(d[0]["reason"], "already_invoiced")
        self.assertEqual(g["skipped_total"], sum(g["skipped"].values()))

    # ---- scheduler
    def test_05_cron_rejects_wrong_or_missing_secret(self):
        for h in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "s3cret-value"}, {"Authorization": "Basic s3cret-value"}):
            self.assertEqual(self.c.get("/api/cron/generate-invoices", headers=h).status_code, 401, h)
        self.assertEqual(self.c.get("/api/cron/generate-invoices?secret=s3cret-value").status_code, 401)   # never accepted in the URL
        self.assertEqual(self.c.get("/api/cron/generate-invoices", headers=self.H).status_code, 401)       # an admin token is not the cron secret

    def test_06_cron_with_secret_generates_once(self):
        _, _, bid, sid = self.setup_enrolment(700)
        self.J("post", "/api/enrollments", json={"student_id": sid, "batch_id": bid})
        ok = {"Authorization": "Bearer s3cret-value"}
        r = self.c.get("/api/cron/generate-invoices", headers=ok)
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True)); self.assertEqual(r.get_json()["period"], self.month)
        self.c.get("/api/cron/generate-invoices", headers=ok)
        self.assertEqual(len(self.invoices(sid)), 1)

    def test_07_cron_closed_without_secret(self):
        from app import create_app
        old = os.environ.pop("CRON_SECRET", None)
        try:
            app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})
            self.assertEqual(app.test_client().get("/api/cron/generate-invoices", headers={"Authorization": "Bearer "}).status_code, 401)
            self.assertEqual(app.test_client().get("/api/cron/generate-invoices").status_code, 401)
        finally:
            if old: os.environ["CRON_SECRET"] = old

    def test_08_vercel_json_registers_the_cron(self):
        import json
        v = json.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "vercel.json")))
        self.assertIn("/api/cron/generate-invoices", [c["path"] for c in v["crons"]])

    # ---- permissions and PDF
    def test_09_catch_up_and_pdf_are_admin_only(self):
        _, _, bid, sid = self.setup_enrolment(500)
        self.J("post", "/api/enrollments", json={"student_id": sid, "batch_id": bid})
        iid = self.invoices(sid)[0]["id"]
        st = {"Authorization": "Bearer " + self.c.post("/api/auth/login", json={"email": f"s{S9.n}@t.test", "password": PW}).get_json()["token"]}
        for m, u in (("post", "/api/invoices/catch-up"), ("get", f"/api/invoices/{iid}/invoice.pdf")):
            self.assertEqual(self.J(m, u, headers=st).status_code, 403, u)
            self.assertEqual(self.J(m, u, headers={}).status_code, 401, u)

    def test_10_invoice_pdf_downloads(self):
        _, _, bid, sid = self.setup_enrolment(500)
        self.J("post", "/api/enrollments", json={"student_id": sid, "batch_id": bid})
        i = self.invoices(sid)[0]
        r = self.J("get", f"/api/invoices/{i['id']}/invoice.pdf")
        self.assertEqual((r.status_code, r.mimetype), (200, "application/pdf"))
        self.assertTrue(r.get_data().startswith(b"%PDF"))
        self.assertIn(i["number"], r.headers["Content-Disposition"])
        self.assertEqual(self.J("get", "/api/invoices/99999/invoice.pdf").status_code, 404)


if __name__ == "__main__":
    unittest.main()
