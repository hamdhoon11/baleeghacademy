"""v0.8.59: installable app (manifest, icons, service worker) and "Keep me signed in on this device"."""
import datetime as dt, io, json, os, struct, sys, tempfile, time, unittest, zlib
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import jwt
PW = "Password123"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def png(w, h):
    """A plain teal PNG of w x h, made without Pillow (the server does not have it)."""
    raw = b"".join(b"\x00" + b"\x0b\x4f\x5c" * w for _ in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class V0859(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@v59.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.H = cls.hdr(cls.login("admin@v59.test", "AdminPass123"))
        r = cls.c.post("/api/users", json={"email": "s1@v59.test", "password": PW, "full_name": "Student One", "role": "student", "phone": "7771234"}, headers=cls.H)
        cls.sid = r.get_json()["id"]

    @classmethod
    def login(cls, who, pw, **k):
        return cls.c.post("/api/auth/login", json={"login": who, "password": pw, **k}).get_json()

    @staticmethod
    def hdr(r): return {"Authorization": "Bearer " + r["token"]}

    def claims(self, tok): return jwt.decode(tok, self.app.config["SECRET_KEY"], algorithms=["HS256"])

    def life_hours(self, tok): return (self.claims(tok)["exp"] - time.time()) / 3600

    def setting(self, **kv):
        r = self.c.put("/api/settings", json=kv, headers=self.H); self.assertEqual(r.status_code, 200, r.get_json())

    def set_logo(self, data):
        if data is None: return self.c.delete("/api/settings/logo", headers=self.H)
        r = self.c.post("/api/settings/logo", data={"file": (io.BytesIO(data), "logo.png")}, headers=self.H, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 200, r.get_json())

    # ---------- manifest and icons ----------
    def test_01_manifest_builtin_icons(self):
        self.set_logo(None)
        r = self.c.get("/manifest.webmanifest")
        self.assertEqual(r.status_code, 200); self.assertEqual(r.mimetype, "application/manifest+json")
        self.assertEqual(r.headers["Cache-Control"], "no-cache")
        m = json.loads(r.data)
        self.assertEqual((m["display"], m["start_url"], m["scope"]), ("standalone", "/", "/"))
        self.assertIn("Baleegh", m["name"]); self.assertLessEqual(len(m["short_name"]), 12)
        sizes = {(i["sizes"], i["purpose"]) for i in m["icons"]}
        self.assertTrue({("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= sizes)
        for i in m["icons"]:   # every icon file is really there
            self.assertEqual(self.c.get(i["src"]).status_code, 200, i["src"])

    def test_02_square_logo_becomes_the_app_icon(self):
        self.set_logo(png(256, 256))
        m = json.loads(self.c.get("/manifest.webmanifest").data)
        self.assertEqual(len(m["icons"]), 1); self.assertTrue(m["icons"][0]["src"].startswith("/api/public/logo"))
        self.assertEqual(m["icons"][0]["sizes"], "256x256")
        r = self.c.get("/apple-touch-icon.png"); self.assertEqual(r.status_code, 302); self.assertIn("/api/public/logo", r.headers["Location"])
        self.assertTrue(self.c.get("/api/public/info").get_json()["app_icon_url"].startswith("/api/public/logo"))
        self.set_logo(None)

    def test_03_wide_or_small_logo_is_not_used(self):
        for w, h in ((600, 200), (100, 100)):
            self.set_logo(png(w, h))
            m = json.loads(self.c.get("/manifest.webmanifest").data)
            self.assertTrue(all(i["src"].startswith("/icons/") for i in m["icons"]), (w, h))
            r = self.c.get("/apple-touch-icon.png"); self.assertEqual(r.status_code, 200); self.assertEqual(r.data[:8], b"\x89PNG\r\n\x1a\n")
        self.set_logo(None)

    def test_04_manifest_uses_academy_name(self):
        self.setting(academy_name="Test Institute")
        m = json.loads(self.c.get("/manifest.webmanifest").data)
        self.assertEqual(m["name"], "Test Institute Portal"); self.assertEqual(m["short_name"], "Test")
        self.setting(academy_name="")

    # ---------- service worker ----------
    def test_05_service_worker_served_fresh(self):
        r = self.c.get("/sw.js")
        self.assertEqual(r.status_code, 200); self.assertEqual(r.headers["Cache-Control"], "no-cache")
        self.assertIn("javascript", r.mimetype)

    def test_06_service_worker_never_stores_api(self):
        src = open(os.path.join(ROOT, "static", "sw.js")).read()
        self.assertIn('url.pathname.startsWith("/api/")', src)
        # the /api/ check comes before any respondWith: those requests go straight to the network
        self.assertLess(src.index('startsWith("/api/")'), src.index("respondWith"))
        for f in ("/", "/ui.js", "/learning.js", "/fees.js", "/admin.js", "/notify.js", "/staffroom.js", "/i18n/en.json", "/icons/icon-192.png"):
            self.assertIn(f'"{f}"', src); self.assertEqual(self.c.get(f).status_code, 200, f)

    def test_07_page_links_manifest_and_worker(self):
        s = self.c.get("/").get_data(as_text=True)
        for x in ('rel="manifest" href="/manifest.webmanifest"', 'rel="apple-touch-icon"', 'serviceWorker.register("/sw.js")', "TOK.get()"):
            self.assertIn(x, s)
        self.assertEqual(s.count('setItem("tok"'), 2)   # the token is only stored inside TOK.set (this device / this tab)
        en = json.load(open(os.path.join(ROOT, "static", "i18n", "en.json")))
        for k in ("keep_signed_in", "keep_signed_in_hint", "install_app", "app_installed", "install_ios_1", "install_ios_2", "install_ios_3", "install_ios_safari"):
            self.assertIn(k, en)

    # ---------- keep me signed in ----------
    def test_08_normal_sign_in_is_short(self):
        r = self.login("s1@v59.test", PW)
        self.assertFalse(r["remembered"]); self.assertNotIn("rm", self.claims(r["token"]))
        self.assertAlmostEqual(self.life_hours(r["token"]), 8, delta=0.1)

    def test_09_remembered_sign_in_lasts_days(self):
        self.assertEqual(self.c.get("/api/public/info").get_json()["remember_days"], 30)
        r = self.login("s1@v59.test", PW, remember=True)
        self.assertTrue(r["remembered"]); self.assertEqual(self.claims(r["token"])["rm"], 1)
        self.assertAlmostEqual(self.life_hours(r["token"]), 30 * 24, delta=0.1)
        self.assertEqual(self.c.get("/api/auth/me", headers=self.hdr(r)).status_code, 200)

    def test_10_setting_changes_or_turns_it_off(self):
        self.setting(remember_days="7")
        r = self.login("s1@v59.test", PW, remember=True)
        self.assertAlmostEqual(self.life_hours(r["token"]), 7 * 24, delta=0.1)
        self.setting(remember_days="0")
        self.assertEqual(self.c.get("/api/public/info").get_json()["remember_days"], 0)
        r = self.login("s1@v59.test", PW, remember=True)
        self.assertFalse(r["remembered"]); self.assertAlmostEqual(self.life_hours(r["token"]), 8, delta=0.1)
        self.assertEqual(self.c.put("/api/settings", json={"remember_days": "200"}, headers=self.H).status_code, 400)
        self.setting(remember_days="")

    def test_11_password_change_keeps_device_remembered(self):
        r = self.login("s1@v59.test", PW, remember=True)
        x = self.c.post("/api/auth/change-password", json={"current_password": PW, "new_password": "NewPass12345"}, headers=self.hdr(r)).get_json()
        self.assertEqual(self.claims(x["token"])["rm"], 1)
        self.assertEqual(self.c.get("/api/auth/me", headers=self.hdr(r)).status_code, 401)   # the old token is still ended
        y = self.c.post("/api/auth/change-password", json={"current_password": "NewPass12345", "new_password": PW}, headers=self.hdr(x)).get_json()
        self.assertTrue(y["ok"])
        s = self.login("s1@v59.test", PW)   # not remembered: the new token is not remembered either
        z = self.c.post("/api/auth/change-password", json={"current_password": PW, "new_password": PW + "x"}, headers=self.hdr(s)).get_json()
        self.assertNotIn("rm", self.claims(z["token"]))
        self.c.post("/api/auth/change-password", json={"current_password": PW + "x", "new_password": PW}, headers=self.hdr(z))

    def test_12_admin_reset_ends_a_remembered_sign_in(self):
        r = self.login("s1@v59.test", PW, remember=True)
        self.assertEqual(self.c.post(f"/api/users/{self.sid}/reset-password", headers=self.H).status_code, 200)
        self.assertEqual(self.c.get("/api/auth/me", headers=self.hdr(r)).status_code, 401)
        self.c.put(f"/api/users/{self.sid}", json={"password": PW}, headers=self.H)

    def test_13_login_log_says_kept_signed_in(self):
        import sqlite3
        self.login("s1@v59.test", PW, remember=True)
        con = sqlite3.connect(self.path)
        try: row = con.execute("SELECT detail FROM audit_log WHERE action='login' ORDER BY id DESC LIMIT 1").fetchone()
        finally: con.close()
        self.assertEqual(row[0], "kept signed in on this device")


if __name__ == "__main__":
    unittest.main()
