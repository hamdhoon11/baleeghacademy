"""v0.8.57: attempt counters in the database. A stranger cannot lock the real owner out; guessing is still stopped; two server instances share
the counts; on Vercel the visitor's address comes from Vercel's header, elsewhere a sent X-Forwarded-For is ignored."""
import os, sys, tempfile, unittest, warnings
warnings.simplefilter("ignore", ResourceWarning)
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)


class RateLimits(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "r.db")
        os.environ.update(DATABASE_PATH=self.path, ADMIN_EMAIL="admin@r.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        self.clock = [1_900_000_000]
        self.mk = lambda **cfg: create_app({"DATABASE_PATH": self.path, "RATE_NOW": lambda: self.clock[0], **cfg})
        self.app = self.mk(); self.c = self.app.test_client()

    def login(self, pw, ip, c=None, who="admin@r.test"):
        return (c or self.c).post("/api/auth/login", json={"login": who, "password": pw}, environ_base={"REMOTE_ADDR": ip}).status_code

    def test_01_stranger_cannot_lock_owner_out(self):
        codes = [self.login("wrong", "6.6.6.6") for _ in range(10)]
        self.assertEqual(codes[:8], [401] * 8); self.assertEqual(codes[8:], [429, 429])
        self.assertEqual(self.login("AdminPass123", "6.6.6.6"), 429)          # the guesser stays blocked, even with the right password
        self.assertEqual(self.login("AdminPass123", "10.0.0.5"), 200)         # the owner, elsewhere, signs in
        self.clock[0] += 301
        self.assertEqual(self.login("wrong", "6.6.6.6"), 401)                 # 5 minutes later the guesser may try again

    def test_02_success_clears_own_count(self):
        for _ in range(7): self.login("wrong", "10.0.0.5")
        self.assertEqual(self.login("AdminPass123", "10.0.0.5"), 200)
        self.assertEqual([self.login("wrong", "10.0.0.5") for _ in range(8)], [401] * 8)

    def test_03_spraying_many_accounts_from_one_connection(self):
        codes = [self.login("wrong", "7.7.7.7", who=f"nobody{i}@r.test") for i in range(32)]
        self.assertEqual(codes.count(401), 30); self.assertEqual(codes[-1], 429)

    def test_04_many_connections_on_one_account(self):
        for i in range(50): self.login("wrong", f"9.9.{i // 200}.{i % 200}")
        self.assertEqual(self.login("AdminPass123", "9.9.0.3"), 429)          # a connection that already failed here waits
        self.assertEqual(self.login("AdminPass123", "10.0.0.5"), 200)         # a clean one still gets in

    def test_05_shared_by_instances(self):
        other = self.mk().test_client()
        for _ in range(4): self.login("wrong", "6.6.6.6")
        for _ in range(4): self.login("wrong", "6.6.6.6", c=other)
        self.assertEqual(self.login("wrong", "6.6.6.6"), 429)

    def test_06_client_address(self):
        local = self.c   # not on Vercel: a sent header is ignored
        for i in range(8): local.post("/api/auth/login", json={"login": "admin@r.test", "password": "x"}, headers={"X-Forwarded-For": f"1.1.1.{i}"})
        self.assertEqual(local.post("/api/auth/login", json={"login": "admin@r.test", "password": "x"}, headers={"X-Forwarded-For": "1.1.1.99"}).status_code, 429)
        vc = self.mk(ON_VERCEL=True).test_client()
        r = vc.post("/api/auth/login", json={"login": "admin@r.test", "password": "AdminPass123"}, headers={"X-Vercel-Forwarded-For": "203.0.113.9"})
        self.assertEqual(r.status_code, 200)
        import sqlite3; k = sqlite3.connect(self.path)
        self.assertEqual(k.execute("SELECT ip FROM login_events ORDER BY id DESC LIMIT 1").fetchone()[0], "203.0.113.9"); k.close()


if __name__ == "__main__":
    unittest.main()
