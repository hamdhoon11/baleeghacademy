"""v0.8.34: downloads that failed after upload.

1. A file named in Arabic or Dhivehi crashed the download (the name went raw into a Latin-1 header).
2. On Vercel without a bucket, files were kept on a temporary disk that is not shared between the app's copies and is wiped:
   "The file could not be found" right after uploading. Files now go into the database there (FILE_STORAGE=db, automatic on Vercel).
3. Admins can see where files live and which records lost their file."""
import io, os, sys, tempfile, unittest
from urllib.parse import unquote
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_session28 import make_app  # noqa: E402
import common, dbx, storage  # noqa: E402

PDF = b"%PDF-1.4 portal test file"
NAMES = ["lesson.pdf", "درس النحو.pdf", "ދަރުސް 1.pdf", "Leçon été.pdf", "a\"b;c.pdf"]


def disposition_name(h):
    """What a browser shows: filename* (UTF-8) when present, else filename."""
    if "filename*=UTF-8''" in h: return unquote(h.split("filename*=UTF-8''", 1)[1].split(";")[0])
    return h.split('filename="', 1)[1].split('"', 1)[0]


class Headers(unittest.TestCase):
    def test_01_every_name_fits_a_real_header_and_comes_back_whole(self):
        from flask import Flask, Response
        with Flask(__name__).app_context():
            for n in NAMES:
                h = common.file_headers(Response(b"x"), n, attachment=True).headers["Content-Disposition"]
                h.encode("latin-1")                                   # a real server (gunicorn, Vercel) must be able to send it
                self.assertTrue(h.startswith("attachment; filename=\""))
                want = n.replace('"', "_")
                self.assertEqual(disposition_name(h), want, h)
                self.assertRegex(h.split('filename="')[1].split('"')[0], r"^[A-Za-z0-9._\- ]+\.pdf$")   # the old-style fallback is plain ASCII

    def test_02_shown_names_keep_dhivehi_and_arabic_marks(self):
        self.assertEqual(common.shown_name("ދަރުސް.pdf"), "ދަރުސް.pdf")
        self.assertEqual(common.shown_name("دَرْس.pdf"), "دَرْس.pdf")
        self.assertEqual(common.shown_name("../../etc/pass wd?.pdf"), "pass wd_.pdf")
        self.assertEqual(common.ascii_name("ދަރުސް.pdf"), "file.pdf")

    def test_03_postgres_gets_bytea(self):
        pg = dbx.schema_to_pg(dbx.read_schema(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        self.assertIn("data BYTEA NOT NULL", pg)
        self.assertNotIn("BLOB", pg)


class DbFiles(unittest.TestCase):
    """The Vercel case: every request may hit a fresh copy of the app. With FILE_STORAGE=db the file is in the database, so it is still there."""

    @classmethod
    def setUpClass(cls):
        os.environ["FILE_STORAGE"] = "db"
        try:
            cls.app, cls.c, cls.H, cls.path = make_app("s34")
        finally:
            os.environ.pop("FILE_STORAGE", None)
        c, H = cls.c, cls.H
        cls.course = c.post("/api/courses", json={"name": "Arabic", "monthly_fee_mvr": 100, "status": "open"}, headers=H).get_json()["id"]
        cls.tid = c.post("/api/users", json={"full_name": "T", "email": "t@s34.test", "password": "Password123", "role": "teacher"}, headers=H).get_json()["id"]
        cls.sid = c.post("/api/users", json={"full_name": "S", "email": "s@s34.test", "password": "Password123", "role": "student"}, headers=H).get_json()["id"]
        cls.b = c.post("/api/batches", json={"course_id": cls.course, "code": "B1", "capacity": 5, "teacher_id": cls.tid, "days": "Mon"}, headers=H).get_json()["id"]
        c.post("/api/enrollments", json={"student_id": cls.sid, "batch_id": cls.b}, headers=H)
        import sqlite3
        con = sqlite3.connect(cls.path); con.execute("UPDATE users SET must_change_password=0"); con.commit(); con.close()
        tok = lambda e: {"Authorization": "Bearer " + c.post("/api/auth/login", json={"login": e, "password": "Password123"}).get_json()["token"]}
        cls.T, cls.S = tok("t@s34.test"), tok("s@s34.test")

    def upload(self, name):
        r = self.c.post(f"/api/batches/{self.b}/materials", data={"title": "M " + name, "file": (io.BytesIO(PDF), name)}, headers=self.T, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True)); return r.get_json()["id"]

    def test_01_storage_is_the_database(self):
        self.assertEqual(self.app.extensions["store"].kind, "db")

    def test_02_upload_then_download_every_name(self):
        for n in NAMES[:4]:
            mid = self.upload(n)
            g = self.c.get(f"/api/materials/{mid}/file", headers=self.S)
            self.assertEqual(g.status_code, 200); self.assertEqual(g.data, PDF)
            g.headers["Content-Disposition"].encode("latin-1")
            self.assertEqual(disposition_name(g.headers["Content-Disposition"]), n)

    def test_03_a_fresh_copy_of_the_app_still_has_the_file(self):
        mid = self.upload("survives.pdf")
        from app import create_app
        other = create_app({"DATABASE_PATH": self.path, "FILE_STORAGE": "db"}).test_client()   # like the next Vercel request on another copy
        g = other.get(f"/api/materials/{mid}/file", headers=self.S)
        self.assertEqual(g.status_code, 200); self.assertEqual(g.data, PDF)

    def test_04_a_failed_upload_leaves_no_file_behind(self):
        n = self.app.extensions["store"]
        before = self.c.get("/api/admin/storage", headers=self.H).get_json()["files"]
        r = self.c.post(f"/api/batches/{self.b}/materials", data={"title": "", "file": (io.BytesIO(PDF), "x.pdf")}, headers=self.T, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.c.get("/api/admin/storage", headers=self.H).get_json()["files"], before)
        self.assertEqual(n.kind, "db")

    def test_05_storage_health_and_missing_files(self):
        h = self.c.get("/api/admin/storage", headers=self.H).get_json()
        self.assertEqual(h["storage"], "db"); self.assertTrue(h["persistent"]); self.assertEqual(h["advice"], "")
        self.assertGreaterEqual(h["files"], 1)
        mid = self.upload("will-vanish.pdf")
        import sqlite3
        con = sqlite3.connect(self.path)
        stored = con.execute("SELECT file FROM materials WHERE id=?", (mid,)).fetchone()[0]
        con.execute("DELETE FROM stored_files WHERE name=?", (stored,)); con.commit(); con.close()
        m = self.c.get("/api/admin/storage/missing", headers=self.H).get_json()
        self.assertTrue(m["complete"]); self.assertEqual(m["missing"], 1)
        self.assertEqual(m["items"][0]["kind"], "Class material"); self.assertEqual(m["items"][0]["id"], mid)
        g = self.c.get(f"/api/materials/{mid}/file", headers=self.S)
        self.assertEqual(g.status_code, 404)
        self.assertIn("upload it again", g.get_json()["error"])

    def test_06_admin_only(self):
        self.assertEqual(self.c.get("/api/admin/storage", headers=self.S).status_code, 403)
        self.assertEqual(self.c.get("/api/admin/storage/missing", headers=self.T).status_code, 403)


class Choice(unittest.TestCase):
    def test_01_which_storage_is_picked(self):
        tmp = tempfile.mkdtemp()
        self.assertEqual(storage.make({}, tmp).kind, "local")
        self.assertEqual(storage.make({"ON_VERCEL": True}, tmp, conn=lambda: None).kind, "db")             # Vercel without a bucket: database
        self.assertEqual(storage.make({"ON_VERCEL": True, "FILE_STORAGE": "local"}, tmp).kind, "local")   # forced
        self.assertEqual(storage.make({"FILE_STORAGE": "db"}, tmp, conn=lambda: None).kind, "db")
        with self.assertRaises(RuntimeError): storage.make({"FILE_STORAGE": "s3"}, tmp)

    def test_02_health_says_when_files_will_vanish(self):
        import filecheck
        class A: config = {"USE_POSTGRES": False, "ON_VERCEL": True}
        class Loc: kind = "local"; describe = lambda self: "x"
        class Db: kind = "db"; describe = lambda self: "x"
        self.assertFalse(filecheck.health(A, Loc())["persistent"])
        self.assertFalse(filecheck.health(A, Db())["persistent"])          # database itself is temporary SQLite on Vercel
        A.config = {"USE_POSTGRES": True, "ON_VERCEL": True}
        self.assertTrue(filecheck.health(A, Db())["persistent"])


if __name__ == "__main__":
    unittest.main()
