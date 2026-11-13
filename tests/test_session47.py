"""v0.8.47: who is online; a full admin can sign a person out everywhere, pause (until a time), suspend and restore an account.
Limited admins, teachers and students can do none of it. Nobody can act on their own account. Every action is logged."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"
UA_PHONE = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Mobile Safari/537.36"


class Presence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s47.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.clock = [dt.datetime(2026, 11, 14, 10, 0, tzinfo=MVT)]
        cls.app.config["NOW"] = lambda: cls.clock[0]
        cls.H = cls.tok("admin@s47.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, role: P("/api/users", {"email": e, "password": PW, "full_name": e.split("@")[0].title(), "role": role}).get_json()["id"]
        cls.adm = cls.sql_("SELECT id FROM users WHERE email='admin@s47.test'")[0][0]
        cls.t1, cls.s1, cls.s2, cls.lim, cls.adm2 = (mk("t1@s47.test", "teacher"), mk("s1@s47.test", "student"), mk("s2@s47.test", "student"),
                                                     mk("lim@s47.test", "admin"), mk("adm2@s47.test", "admin"))
        cls.c.patch(f"/api/users/{cls.lim}", json={"permissions": ["people", "audit"]}, headers=cls.H)
        cls.sql_("UPDATE users SET must_change_password=0")

    @classmethod
    def tok(cls, login, pw, ua=None):
        r = cls.c.post("/api/auth/login", json={"login": login, "password": pw}, headers={"User-Agent": ua} if ua else {})
        assert r.status_code == 200, r.get_json()
        return {"Authorization": "Bearer " + r.get_json()["token"], **({"User-Agent": ua} if ua else {})}

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def tick(self, **kw):
        self.clock[0] = self.clock[0] + dt.timedelta(**kw)

    def person(self, uid):
        r = self.c.get("/api/admin/presence", headers=self.H); self.assertEqual(r.status_code, 200, r.get_json())
        return [p for p in r.get_json()["people"] if p["id"] == uid][0]

    def act(self, uid, what, body=None, H=None):
        return self.c.post(f"/api/admin/accounts/{uid}/{what}", json=body or {}, headers=self.H if H is None else H)

    def test_01_online_away_offline_and_signout_button(self):
        S = self.tok("s1@s47.test", PW, UA_PHONE)
        self.assertEqual(self.c.get("/api/auth/me", headers=S).status_code, 200)
        p = self.person(self.s1)
        self.assertEqual((p["status"], p["device"], p["account"]), ("online", "Phone · Chrome", "active"))
        self.assertTrue(p["last_login_at"]); self.assertIn("ip", p)
        self.tick(minutes=5); self.assertEqual(self.person(self.s1)["status"], "away")
        self.tick(minutes=20); self.assertEqual(self.person(self.s1)["status"], "offline")
        self.c.get("/api/auth/me", headers=S); self.assertEqual(self.person(self.s1)["status"], "online")   # any request = back online
        self.c.post("/api/auth/logout", headers=S); self.assertEqual(self.person(self.s1)["status"], "offline")   # Sign out = offline at once
        never = self.person(self.s2); self.assertEqual((never["status"], never["last_seen_at"]), ("offline", None))
        d = self.c.get("/api/admin/presence", headers=self.H).get_json()
        self.assertGreaterEqual(d["counts"]["online"], 1); self.assertIn("student", d["by_role"])
        self.assertTrue([p for p in d["people"] if p["id"] == self.adm][0]["is_self"])
        self.assertEqual(d["people"][0]["status"], "online")   # online people first

    def test_02_activity_written_at_most_every_30_seconds(self):
        S = self.tok("t1@s47.test", PW)
        first = self.sql_("SELECT last_seen_at FROM users WHERE id=?", (self.t1,))[0][0]
        self.tick(seconds=10); self.c.get("/api/auth/me", headers=S)
        self.assertEqual(self.sql_("SELECT last_seen_at FROM users WHERE id=?", (self.t1,))[0][0], first)
        self.tick(seconds=31); self.c.get("/api/auth/me", headers=S)
        self.assertNotEqual(self.sql_("SELECT last_seen_at FROM users WHERE id=?", (self.t1,))[0][0], first)

    def test_03_sign_out_everywhere(self):
        A, B = self.tok("s2@s47.test", PW), self.tok("s2@s47.test", PW)   # two devices
        r = self.act(self.s2, "signout", {"reason": "shared password"}); self.assertEqual(r.status_code, 200, r.get_json())
        for H in (A, B):
            r = self.c.get("/api/auth/me", headers=H)
            self.assertEqual((r.status_code, r.get_json()["code"]), (401, "signed_out_by_admin"))
        self.assertEqual(self.person(self.s2)["status"], "offline")
        N = self.tok("s2@s47.test", PW); self.assertEqual(self.c.get("/api/auth/me", headers=N).status_code, 200)   # may sign in again
        log = self.sql_("SELECT detail FROM audit_log WHERE action='account_signout' AND entity_id=?", (self.s2,))
        self.assertIn("shared password", log[-1][0])

    def test_04_pause_lifts_by_itself(self):
        S = self.tok("t1@s47.test", PW)
        r = self.act(self.t1, "pause", {"hours": 2, "reason": "Leave"}); self.assertEqual(r.status_code, 200, r.get_json())
        r = self.c.get("/api/my/home", headers=S); self.assertEqual((r.status_code, r.get_json()["code"]), (401, "account_paused"))
        r = self.c.post("/api/auth/login", json={"login": "t1@s47.test", "password": PW})
        self.assertEqual((r.status_code, r.get_json()["code"]), (403, "account_paused"))
        end = self.clock[0] + dt.timedelta(hours=2)
        self.assertIn(f"{end.day} {end.strftime('%b %Y, %H:%M')} (Maldives time)", r.get_json()["error"])   # now + 2 h, shown in Maldives time
        bad = self.c.post("/api/auth/login", json={"login": "t1@s47.test", "password": "wrong"})
        self.assertEqual(bad.status_code, 401); self.assertNotIn("paused", bad.get_json()["error"])   # wrong password learns nothing
        p = self.person(self.t1); self.assertEqual((p["account"], p["pause_reason"]), ("paused", "Leave"))
        self.tick(hours=2, minutes=1)
        self.assertEqual(self.person(self.t1)["account"], "active")
        self.tok("t1@s47.test", PW)
        self.assertTrue(self.sql_("SELECT 1 FROM audit_log WHERE action='login_blocked' AND entity_id=?", (self.t1,)))

    def test_05_pause_until_a_date_and_validation(self):
        r = self.act(self.s1, "pause", {"until": "2026-11-20T18:00"}); self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(r.get_json()["paused_until"], "2026-11-20 13:00:00")   # stored in UTC
        for body in ({"until": "2020-01-01T10:00"}, {"until": "nonsense"}, {}, {"hours": 0}, {"hours": 24 * 400}):
            self.assertEqual(self.act(self.s1, "pause", body).status_code, 400, body)
        self.assertEqual(self.act(self.s1, "restore").status_code, 200)
        self.assertEqual(self.act(self.s1, "restore").status_code, 409)   # nothing to restore
        self.tok("s1@s47.test", PW)

    def test_06_suspend_and_restore(self):
        S = self.tok("s1@s47.test", PW)
        self.assertEqual(self.act(self.s1, "suspend", {}).status_code, 400)   # a reason is required
        r = self.act(self.s1, "suspend", {"reason": "Fees unpaid for 3 months"}); self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.get("/api/my/fees", headers=S).status_code, 401)
        r = self.c.post("/api/auth/login", json={"login": "s1@s47.test", "password": PW})
        self.assertEqual((r.status_code, r.get_json()["code"]), (403, "account_suspended"))
        self.assertNotIn("Fees unpaid", r.get_json()["error"])   # the reason is for staff only
        self.tick(days=400); self.assertEqual(self.person(self.s1)["account"], "suspended")   # never lifts by itself
        self.assertEqual(self.act(self.s1, "pause", {"hours": 1}).status_code, 409)
        self.assertEqual(self.act(self.s1, "restore").status_code, 200)
        self.tok("s1@s47.test", PW)
        acts = [a for (a,) in self.sql_("SELECT action FROM audit_log WHERE entity_id=? AND action LIKE 'account_%' ORDER BY id", (self.s1,))]
        self.assertEqual(acts[-2:], ["account_suspend", "account_restore"])

    def test_07_only_full_admins(self):
        L = self.tok("lim@s47.test", PW); T = self.tok("t1@s47.test", PW); S = self.tok("s2@s47.test", PW)
        for H, code in ((L, 403), (T, 403), (S, 403), ({}, 401)):
            self.assertEqual(self.c.get("/api/admin/presence", headers=H).status_code, code)
            for what in ("signout", "pause", "suspend", "restore"):
                self.assertEqual(self.act(self.s1, what, {"reason": "x", "hours": 1}, H=H).status_code, code, what)
        self.assertNotIn("online", self.c.get("/api/auth/me", headers=L).get_json()["user"]["tabs"])
        self.assertIn("online", self.c.get("/api/auth/me", headers=self.H).get_json()["user"]["tabs"])
        self.assertNotIn("online", self.c.get("/api/auth/me", headers=T).get_json()["user"]["tabs"])

    def test_08_not_on_yourself_but_on_another_admin(self):
        for what in ("signout", "pause", "suspend", "restore"):
            self.assertEqual(self.act(self.adm, what, {"reason": "x", "hours": 1}).status_code, 409, what)
        self.assertEqual(self.act(99999, "signout").status_code, 404)
        A2 = self.tok("adm2@s47.test", PW)
        self.assertEqual(self.act(self.adm2, "pause", {"hours": 1}).status_code, 200)
        self.assertEqual(self.c.get("/api/admin/presence", headers=A2).status_code, 401)
        self.assertEqual(self.act(self.adm2, "restore").status_code, 200)

    def test_09_old_tokens_without_version_still_work(self):
        import jwt
        tok = jwt.encode({"sub": str(self.s2), "role": "student", "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)},
                         self.app.config["SECRET_KEY"], "HS256")
        self.sql_("UPDATE users SET token_version=0 WHERE id=?", (self.s2,))
        self.assertEqual(self.c.get("/api/auth/me", headers={"Authorization": "Bearer " + tok}).status_code, 200)

    def test_10_bulk_actions(self):
        ids = [self.s1, self.s2, self.adm]   # yourself is skipped, the others are done
        r = self.c.post("/api/admin/accounts/bulk", json={"ids": ids, "action": "pause", "hours": 3, "reason": "Holiday", "_until": ["2099-01-01 00:00:00", None]}, headers=self.H).get_json()
        self.assertEqual((r["done"], [x["id"] for x in r["skipped"]]), (2, [self.adm]))
        until = self.sql_("SELECT paused_until FROM users WHERE id=?", (self.s1,))[0][0]
        self.assertFalse(until.startswith("2099"))   # the end time comes from hours, never from the request body
        self.assertEqual(self.sql_("SELECT paused_until FROM users WHERE id=?", (self.s2,))[0][0], until)   # one end time for everyone
        r = self.c.post("/api/admin/accounts/bulk", json={"ids": [self.s1, self.s2], "action": "suspend"}, headers=self.H)
        self.assertEqual(r.status_code, 400)   # a reason is required
        r = self.c.post("/api/admin/accounts/bulk", json={"ids": [self.s1, self.s2, self.t1], "action": "restore"}, headers=self.H).get_json()
        self.assertEqual(r["done"], 2); self.assertEqual(r["skipped"][0]["id"], self.t1)   # t1 was not paused
        for body in ({"ids": [], "action": "signout"}, {"ids": [self.s1], "action": "explode"}):
            self.assertEqual(self.c.post("/api/admin/accounts/bulk", json=body, headers=self.H).status_code, 400)
        L = self.tok("lim@s47.test", PW)
        self.assertEqual(self.c.post("/api/admin/accounts/bulk", json={"ids": [self.s1], "action": "signout"}, headers=L).status_code, 403)

    def test_11_sign_out_everyone(self):
        S, T = self.tok("s1@s47.test", PW), self.tok("t1@s47.test", PW)
        r = self.c.post("/api/admin/accounts/signout-all", json={"role": "student", "reason": "Exam"}, headers=self.H).get_json()
        self.assertEqual(r["count"], 2)
        self.assertEqual(self.c.get("/api/auth/me", headers=S).status_code, 401)
        self.assertEqual(self.c.get("/api/auth/me", headers=T).status_code, 200)   # teachers untouched
        self.c.post("/api/admin/accounts/signout-all", json={}, headers=self.H)
        self.assertEqual(self.c.get("/api/auth/me", headers=T).status_code, 401)
        self.assertEqual(self.c.get("/api/auth/me", headers=self.H).status_code, 200)   # never yourself
        self.assertTrue(self.sql_("SELECT 1 FROM audit_log WHERE action='account_signout_all'"))

    def test_12_history_failed_and_new_device(self):
        for _ in range(3): self.c.post("/api/auth/login", json={"login": "s2@s47.test", "password": "nope"})
        self.tok("s2@s47.test", PW, "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/130.0 Safari/537.36")
        self.tok("s2@s47.test", PW, "Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/130.0 Safari/537.36")
        self.tok("s2@s47.test", PW, UA_PHONE)
        p = self.person(self.s2)
        self.assertGreaterEqual(p["failed_24h"], 3); self.assertEqual(p["new_device"], "Phone · Chrome")
        h = self.c.get(f"/api/admin/accounts/{self.s2}/history", headers=self.H).get_json()
        self.assertEqual(h["person"]["id"], self.s2); self.assertGreaterEqual(h["failed_24h"], 3)
        self.assertEqual(h["events"][0]["ok"], 1); self.assertEqual(h["events"][0]["device"], "Phone · Chrome")
        self.assertIn("wrong password", [e["reason"] for e in h["events"]])
        self.assertIn("Phone · Chrome", [d["device"] for d in h["devices"]])
        self.assertTrue(any(a["action"].startswith("account_") for a in h["actions"]))
        self.assertNotIn("password", " ".join(str(e) for e in h["events"]).replace("wrong password", ""))   # never a password
        s = self.c.get("/api/admin/presence/summary", headers=self.H).get_json()
        self.assertGreaterEqual(s["failed_24h"], 3); self.assertIn("online", s["counts"]); self.assertGreaterEqual(s["counts"]["warnings"], 1)
        self.assertEqual(self.c.get(f"/api/admin/accounts/{self.s2}/history", headers=self.tok("lim@s47.test", PW)).status_code, 403)

    def test_13_pause_end_notice_and_message_to_person(self):
        self.assertEqual(self.act(self.t1, "pause", {"hours": 1, "message": "Back after the exam board meeting"}).status_code, 200)
        r = self.c.post("/api/auth/login", json={"login": "t1@s47.test", "password": PW}).get_json()
        self.assertIn("Message from the academy: Back after the exam board meeting", r["error"])
        self.tick(hours=1, minutes=1)
        self.c.get("/api/auth/me", headers=self.H)   # any request by a full admin clears ended pauses
        self.assertEqual(self.sql_("SELECT paused_until, account_message FROM users WHERE id=?", (self.t1,))[0], (None, None))
        n = self.sql_("SELECT user_id, title, link FROM notifications WHERE kind='account' AND title='Pause ended' AND link=?", (f"online:{self.t1}",))
        self.assertIn(self.adm, [x[0] for x in n]); self.assertNotIn(self.lim, [x[0] for x in n])   # full admins only
        before = len(self.sql_("SELECT 1 FROM notifications WHERE link=? AND user_id=?", (f"online:{self.t1}", self.adm)))
        self.tick(minutes=1); self.c.get("/api/admin/presence", headers=self.H); self.c.get("/api/auth/me", headers=self.H)
        self.assertEqual(len(self.sql_("SELECT 1 FROM notifications WHERE link=? AND user_id=?", (f"online:{self.t1}", self.adm))), before)   # told once per pause
        self.assertTrue(self.sql_("SELECT 1 FROM audit_log WHERE action='account_pause_ended' AND entity_id=?", (self.t1,)))


class Upgrade(unittest.TestCase):
    def test_old_database_gets_the_columns(self):
        """A database made by the v0.8.8 schema gains the new columns on start; existing accounts are unchanged and can sign in."""
        import dbx
        tmp = tempfile.mkdtemp(); path = os.path.join(tmp, "old.db")
        fixture = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "schema_v0_8_8.sql")
        con = sqlite3.connect(path); con.executescript(open(fixture).read())
        from werkzeug.security import generate_password_hash
        con.execute("INSERT INTO users(email,password_hash,full_name,role) VALUES('old@s47.test',?,'Old','admin')", (generate_password_hash("OldPass123"),))
        con.commit(); con.close()
        from app import create_app
        old = os.environ.get("SEED_DEMO"); os.environ["SEED_DEMO"] = "0"
        try: app = create_app({"DATABASE_PATH": path})
        finally: os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        cols = {r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(users)")}
        self.assertTrue({c for c, _ in dbx.V0847_USER_COLUMNS} <= cols)
        r = app.test_client().post("/api/auth/login", json={"login": "old@s47.test", "password": "OldPass123"})
        self.assertEqual(r.status_code, 200, r.get_json())


if __name__ == "__main__":
    unittest.main()
