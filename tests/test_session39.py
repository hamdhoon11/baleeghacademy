"""v0.8.39 (security fixes): SECRET_KEY is required on a hosted portal, no admin with the example password on a hosted portal,
Maldives dates after midnight, attempt limits in the database with the person's real address, sign-out and password changes end old sign-ins."""
import datetime as dt, os, sqlite3, subprocess, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"
GOOD_KEY = "k9" * 24
CLOCK = {"now": dt.datetime(2027, 3, 10, 2, 0, tzinfo=MVT)}   # 02:00 in the Maldives = 21:00 on 9 March in UTC


class Fixes39(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s39.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.create_app = staticmethod(create_app)
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: CLOCK["now"]
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.H = cls.tok("admin@s39.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role: P("/api/users", {"email": e, "password": PW, "full_name": e.split("@")[0], "role": role}).get_json()["id"]
        cls.t1, cls.s1, cls.s2, cls.s3 = mk("t1@s39.test", "teacher"), mk("s1@s39.test", "student"), mk("s2@s39.test", "student"), mk("s3@s39.test", "student")
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.course = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 500, "status": "open"}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": cls.course, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Mon,Wed", "start_time": "16:00"}).get_json()["id"]
        cls.e1 = P("/api/enrollments", {"student_id": cls.s1, "batch_id": cls.b1}).get_json()["id"]

    @classmethod
    def tok(cls, login, pw, c=None):
        return {"Authorization": "Bearer " + (c or cls.c).post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def me(self, h, c=None):
        return (c or self.c).get("/api/auth/me", headers=h).status_code

    # ---- 1. SECRET_KEY ----
    def test_01_hosted_portal_needs_a_real_secret_key(self):
        import common
        for bad in ("", "   ", "dev-only-change-me", "change-me-to-a-long-random-string", "Change-Me", "short"):
            self.assertTrue(common.weak_secret(bad), bad)
        self.assertIsNone(common.weak_secret(GOOD_KEY))
        for hosted in ({"ON_VERCEL": True}, {"DATABASE_URL": "postgresql://nobody@127.0.0.1:1/none"}):
            for bad in ("dev-only-change-me", "change-me-to-a-long-random-string", "abc"):
                with self.assertRaises(RuntimeError) as x:   # refused before any database connection is tried
                    self.create_app({"DATABASE_PATH": self.path, "SECRET_KEY": bad, **hosted})
                self.assertIn("SECRET_KEY", str(x.exception))
        self.assertEqual(self.create_app({"DATABASE_PATH": self.path, "ON_VERCEL": True, "SECRET_KEY": GOOD_KEY}).test_client().get("/api/health").status_code, 200)
        self.assertEqual(self.create_app({"DATABASE_PATH": self.path, "SECRET_KEY": "dev-only-change-me"}).test_client().get("/api/health").status_code, 200)   # local copy still starts
        # a token signed with the public example key is worth nothing on an app with a real key
        import jwt
        forged = jwt.encode({"sub": "1", "role": "admin", "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)}, "dev-only-change-me", "HS256")
        real = self.create_app({"DATABASE_PATH": self.path, "SECRET_KEY": GOOD_KEY}).test_client()
        self.assertEqual(real.get("/api/auth/me", headers={"Authorization": "Bearer " + forged}).status_code, 401)

    # ---- 2. no admin with the example password on a hosted portal ----
    def seed_run(self, path, **env):
        e = {k: v for k, v in os.environ.items() if k not in ("ADMIN_EMAIL", "ADMIN_PASSWORD", "DATABASE_URL", "POSTGRES_URL", "SEED_DEMO")}
        e.update(VERCEL="1", SECRET_KEY=GOOD_KEY, DATABASE_PATH=path, **env)
        r = subprocess.run([sys.executable, os.path.join(ROOT, "seed.py")], cwd=ROOT, env=e, capture_output=True, text=True, timeout=120)
        con = sqlite3.connect(path)
        try: users = con.execute("SELECT email, must_change_password FROM users").fetchall()
        except sqlite3.OperationalError: users = []
        finally: con.close()
        return r, users

    def test_02_hosted_seed_refuses_the_example_admin_password(self):
        tmp = tempfile.mkdtemp()
        for i, env in enumerate(({}, {"ADMIN_PASSWORD": "ChangeMe-Admin1"}, {"ADMIN_PASSWORD": "short"})):
            r, users = self.seed_run(os.path.join(tmp, f"h{i}.db"), **env)
            self.assertNotEqual(r.returncode, 0, env); self.assertIn("ADMIN_PASSWORD", r.stderr); self.assertEqual(users, [], env)
        r, users = self.seed_run(os.path.join(tmp, "ok.db"), ADMIN_EMAIL="owner@s39.test", ADMIN_PASSWORD="My-Own-Password-39")
        self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(users, [("owner@s39.test", 1)])   # created, and must change it at first sign-in
        r, users = self.seed_run(os.path.join(tmp, "ok.db"), ADMIN_EMAIL="owner@s39.test")              # an admin that exists is never touched or required again
        self.assertEqual(r.returncode, 0, r.stderr); self.assertEqual(users, [("owner@s39.test", 1)])

    # ---- 3. dates after midnight ----
    def test_03_withdrawal_date_is_the_maldives_date(self):
        self.assertEqual(self.c.patch(f"/api/enrollments/{self.e1}", json={"status": "dropped", "reason": "moved"}, headers=self.H).status_code, 200)
        ev = self.c.get(f"/api/enrollment-events?student_id={self.s1}", headers=self.H).get_json()
        self.assertEqual([e["effective_date"] for e in ev], ["2027-03-10"])   # was 2027-03-09 (the UTC date)

    # ---- 4. limits ----
    def test_04_sign_in_limit_is_shared_by_every_copy_of_the_app(self):
        bad = lambda c, login="s2@s39.test", **kw: c.post("/api/auth/login", json={"login": login, "password": "wrong"}, **kw).status_code
        addr = {"environ_base": {"REMOTE_ADDR": "10.1.1.1"}}
        self.assertEqual([bad(self.c, **addr) for _ in range(8)], [401] * 8)
        self.assertEqual(bad(self.c, **addr), 429)
        other = self.create_app({"DATABASE_PATH": self.path}).test_client()   # a second copy, as on Vercel: before, it started counting from 0
        self.assertEqual(bad(other, **addr), 429)
        self.assertEqual(other.post("/api/auth/login", json={"login": "s2@s39.test", "password": PW}, environ_base={"REMOTE_ADDR": "10.1.1.2"}).status_code, 429)   # the account is limited from any address
        self.assertEqual(other.post("/api/auth/login", json={"login": "s3@s39.test", "password": PW}, environ_base={"REMOTE_ADDR": "10.1.1.2"}).status_code, 200)   # other people are not affected
        self.sql_("UPDATE rate_hits SET at=at-400")                             # five minutes later
        self.assertEqual(other.post("/api/auth/login", json={"login": "s2@s39.test", "password": PW}, **addr).status_code, 200)

    def test_05_real_address_behind_a_trusted_proxy_only(self):
        self.sql_("DELETE FROM rate_hits")
        fake = lambda n: {"X-Real-IP": f"203.0.113.{n}"}
        bad = lambda c, n: c.post("/api/auth/login", json={"login": f"nobody{n}@s39.test", "password": "x"}, headers=fake(n), environ_base={"REMOTE_ADDR": "10.2.2.2"}).status_code
        # no trusted proxy: the header is ignored (anyone could send it), all nine count for the connection's address
        self.assertEqual([bad(self.c, n) for n in range(9)], [401] * 8 + [429])
        self.assertEqual(self.sql_("SELECT DISTINCT ip FROM audit_log WHERE action='failed_login' AND login_id LIKE 'nobody%'"), [("10.2.2.2",)])
        self.sql_("DELETE FROM rate_hits")
        vercel = self.create_app({"DATABASE_PATH": self.path, "TRUST_PROXY": True}).test_client()
        # behind Vercel every request arrives from the proxy; people are told apart by the header, so one person cannot lock everyone out
        self.assertEqual([bad(vercel, 50) for _ in range(9)], [401] * 8 + [429])
        self.assertEqual(bad(vercel, 51), 401)
        self.assertIn(("203.0.113.50",), self.sql_("SELECT DISTINCT ip FROM audit_log WHERE action='failed_login' AND login_id='nobody50@s39.test'"))
        self.sql_("DELETE FROM rate_hits")

    def test_06_forgot_and_apply_limits_are_shared(self):
        self.sql_("DELETE FROM rate_hits")
        a = self.create_app({"DATABASE_PATH": self.path, "FORGOT_LIMIT": 2, "APPLY_LIMIT": 1})
        b = self.create_app({"DATABASE_PATH": self.path, "FORGOT_LIMIT": 2, "APPLY_LIMIT": 1})
        n = lambda: self.sql_("SELECT COUNT(*) FROM password_help")[0][0]
        start = n()
        for i, app in enumerate((a, b, a, b)):
            self.assertEqual(app.test_client().post("/api/auth/forgot", json={"login": f"who{i}@s39.test"}, environ_base={"REMOTE_ADDR": "10.3.3.3"}).status_code, 200)
        self.assertEqual(n() - start, 2)                                           # the third and fourth were not stored, whichever copy got them
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM rate_hits WHERE key='forgot:10.3.3.3'")[0][0], 2)
        self.sql_("INSERT INTO rate_hits(key,at) VALUES('apply:10.3.3.4', strftime('%s','now'))")
        r = b.test_client().post("/api/public/apply", data={"full_name": "X"}, content_type="multipart/form-data", environ_base={"REMOTE_ADDR": "10.3.3.4"})
        self.assertEqual(r.status_code, 429)
        self.sql_("DELETE FROM rate_hits")

    # ---- 5. old sign-ins end ----
    def test_07_sign_out_ends_every_sign_in_of_the_account(self):
        phone, laptop = self.tok("s3@s39.test", PW), self.tok("s3@s39.test", PW)
        self.assertEqual((self.me(phone), self.me(laptop)), (200, 200))
        self.assertEqual(self.c.post("/api/auth/logout", headers=phone).status_code, 200)
        self.assertEqual((self.me(phone), self.me(laptop)), (401, 401))            # before: both worked for up to 8 more hours
        self.assertEqual(self.me(self.tok("s3@s39.test", PW)), 200)                # signing in again works
        self.assertEqual(self.me(self.H), 200)                                     # other accounts are untouched

    def test_08_password_change_ends_old_sign_ins_and_gives_a_new_token(self):
        old, thief = self.tok("s2@s39.test", PW), self.tok("s2@s39.test", PW)
        r = self.c.post("/api/auth/change-password", json={"current_password": PW, "new_password": "NewPassword456"}, headers=old)
        self.assertEqual(r.status_code, 200); self.assertEqual(r.headers.get("Cache-Control"), "no-store")
        new = {"Authorization": "Bearer " + r.get_json()["token"]}
        self.assertEqual((self.me(old), self.me(thief), self.me(new)), (401, 401, 200))
        # an admin reset, and an admin typing a new password, end the person's sign-ins too
        self.assertEqual(self.c.post(f"/api/users/{self.s2}/reset-password", headers=self.H).status_code, 200)
        self.assertEqual(self.me(new), 401)
        self.assertEqual(self.c.patch(f"/api/users/{self.s2}", json={"password": PW}, headers=self.H).status_code, 200)
        self.sql_("UPDATE users SET must_change_password=0 WHERE id=?", (self.s2,))
        again = self.tok("s2@s39.test", PW)
        self.assertEqual(self.c.patch(f"/api/users/{self.s2}", json={"password": PW}, headers=self.H).status_code, 200)
        self.assertEqual(self.me(again), 401)
        self.sql_("UPDATE users SET must_change_password=0 WHERE id=?", (self.s2,))

    def test_09_tokens_from_before_the_update_keep_working_until_sign_out(self):
        import jwt
        uid = self.t1
        self.assertEqual(self.sql_("SELECT token_version FROM users WHERE id=?", (uid,)), [(0,)])
        old_style = {"Authorization": "Bearer " + jwt.encode({"sub": str(uid), "role": "teacher", "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)},
                                                             self.app.config["SECRET_KEY"], "HS256")}
        self.assertEqual(self.me(old_style), 200)                                  # nobody is signed out by the update itself
        self.assertEqual(self.c.post("/api/auth/logout", headers=old_style).status_code, 200)
        self.assertEqual(self.me(old_style), 401)

    def test_10_page_keeps_the_new_token(self):
        page = open(os.path.join(ROOT, "static/index.html"), encoding="utf-8").read()
        self.assertIn('if (r && r.token) { S.token = r.token; sessionStorage.setItem("tok", r.token); }', page)

    # ---- 7. repository ----
    def test_11_data_and_secrets_are_ignored_by_git(self):
        lines = open(os.path.join(ROOT, ".gitignore"), encoding="utf-8").read().split()
        for need in ("instance/", ".env"): self.assertIn(need, lines)
        if os.path.isdir(os.path.join(ROOT, ".git")):
            r = subprocess.run(["git", "ls-files", "instance", ".env"], cwd=ROOT, capture_output=True, text=True)
            if r.returncode == 0: self.assertEqual(r.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
