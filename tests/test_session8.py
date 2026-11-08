"""Session 8: ID copies and other files open and download; the API never answers an error in HTML."""
import io, json, os, sys, tempfile, unittest, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PDF = b"%PDF-1.4 test"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
JPG = b"\xff\xd8\xff\xe0" + b"0" * 20
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def dob(years):
    t = dt.date.today()
    return f"{t.year - years - 1}-{t.month:02d}-{min(t.day, 28):02d}"


class S8(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        os.environ["DATABASE_PATH"] = os.path.join(cls.tmp, "t.db")
        os.environ["ADMIN_EMAIL"] = "admin@t.test"; os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.mk = staticmethod(create_app)
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"], "APPLY_LIMIT": 100})
        cls.uploads = os.path.join(cls.tmp, "uploads")

    def setUp(self):
        self.c = self.app.test_client()

    def login(self, email, pw):
        r = self.c.post("/api/auth/login", json={"email": email, "password": pw})
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    def admin(self): return self.login("admin@t.test", "AdminPass123")

    def apply(self, name, data, email):
        d = {"full_name": "Aisha Ali", "date_of_birth": dob(25), "phone": "7771234", "email": email, "island": "Naifaru",
             "course_id": "1", "batch_id": "1", "id_card": (io.BytesIO(data), name)}
        r = self.c.post("/api/public/apply", data=d, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        lst = self.c.get("/api/applications", headers=self.admin()).get_json()
        return max(a["id"] for a in lst)

    # ---- ID copies open and download in every accepted format
    def test_01_pdf_jpg_png_open_inline_and_download(self):
        for i, (fn, data, ctype) in enumerate([("id.pdf", PDF, "application/pdf"), ("id.jpg", JPG, "image/jpeg"), ("id.png", PNG, "image/png")]):
            aid = self.apply(fn, data, f"fmt{i}@x.test")
            r = self.c.get(f"/api/applications/{aid}/file/id", headers=self.admin())
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.mimetype, ctype)
            self.assertEqual(r.get_data(), data)
            self.assertTrue(r.headers["Content-Disposition"].startswith("inline; filename="), r.headers["Content-Disposition"])
            self.assertIn(os.path.splitext(fn)[1], r.headers["Content-Disposition"])
            self.assertEqual(r.headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("no-store", r.headers["Cache-Control"])
            d = self.c.get(f"/api/applications/{aid}/file/id?download=1", headers=self.admin())
            self.assertTrue(d.headers["Content-Disposition"].startswith("attachment; filename="))
            self.assertEqual(d.get_data(), data)

    def test_02_each_view_is_logged(self):
        aid = self.apply("id.pdf", PDF, "log@x.test")
        self.c.get(f"/api/applications/{aid}/file/id", headers=self.admin())
        log = self.c.get("/api/audit", headers=self.admin()).get_json()
        self.assertTrue(any(l["action"] == "view_id_file" and l["entity_id"] == aid for l in log))

    # ---- a missing file gives a clear JSON message (never an HTML page)
    def test_03_missing_file_is_json(self):
        aid = self.apply("id.pdf", PDF, "gone@x.test")
        for root, _, files in os.walk(self.tmp):
            for f in files:
                if f.endswith(".pdf"): os.remove(os.path.join(root, f))
        r = self.c.get(f"/api/applications/{aid}/file/id", headers=self.admin())
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.mimetype, "application/json")
        self.assertIn("could not be found", r.get_json()["error"])

    def test_04_no_file_recorded_is_json_404(self):
        r = self.c.get("/api/applications/999999/file/id", headers=self.admin())
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.mimetype, "application/json")

    # ---- access
    def test_05_access_rules(self):
        aid = self.apply("id.pdf", PDF, "acc@x.test")
        url = f"/api/applications/{aid}/file/id"
        self.assertEqual(self.c.get(url).status_code, 401)
        for email, pw in (("student@baleegh.test", "ChangeMe-Stud1"), ("teacher@baleegh.test", "ChangeMe-Teach1")):
            r = self.c.get(url, headers=self.login(email, pw))
            self.assertEqual(r.status_code, 403)
            self.assertEqual(r.mimetype, "application/json")

    # ---- the API never answers an error in HTML
    def test_06_errors_are_json(self):
        r = self.c.get("/api/no-such-route")
        self.assertEqual((r.status_code, r.mimetype), (404, "application/json"))
        self.assertEqual(r.get_json()["error"], "Not found")
        r = self.c.delete("/api/health")
        self.assertEqual((r.status_code, r.mimetype), (405, "application/json"))

    def test_07_too_large_upload_is_json_413(self):
        small = self.mk({"DATABASE_PATH": os.environ["DATABASE_PATH"], "APPLY_LIMIT": 100, "MAX_CONTENT_LENGTH": 2000}).test_client()
        d = {"full_name": "Big File", "date_of_birth": dob(25), "phone": "7771234", "email": "big@x.test", "island": "X",
             "course_id": "1", "batch_id": "1", "id_card": (io.BytesIO(PDF + b"0" * 50000), "big.pdf")}
        r = small.post("/api/public/apply", data=d, content_type="multipart/form-data")
        self.assertEqual((r.status_code, r.mimetype), (413, "application/json"))
        self.assertIn("too large", r.get_json()["error"])

    def test_08_static_pages_still_served(self):
        r = self.c.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.mimetype)
        self.assertEqual(self.c.get("/not-a-page.html").status_code, 404)   # non-API 404 stays Flask's normal one

    # ---- front end: one shared helper, no blind .json() on file or error responses
    def test_09_front_end_uses_fetchfile(self):
        idx = open(os.path.join(ROOT, "static/index.html")).read()
        learn = open(os.path.join(ROOT, "static/learning.js")).read()
        fees = open(os.path.join(ROOT, "static/fees.js")).read()
        self.assertIn("async function fetchFile(", idx)
        self.assertIn("async function readError(", idx)
        self.assertNotIn("(await r.json()).error", idx)
        self.assertIn("fetchFile(", learn)
        self.assertNotIn("(await r.json().catch(() => ({}))).error || t(\"download_failed\")", learn)
        self.assertIn("viewFile(`/slips/", fees)
        en = json.load(open(os.path.join(ROOT, "static/i18n/en.json")))
        for k in ("file_too_large_server", "file_missing", "file_forbidden", "file_open_failed", "download_failed"):
            self.assertIn(k, en)


if __name__ == "__main__":
    unittest.main()
