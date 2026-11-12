"""A warm instance reuses its database connection for the next request, and never reuses a stale or broken one.
Uses a stand-in for PostgreSQL (a SQLite file) so it runs anywhere; only the reuse rules are under test."""
import os, runpy, sys, tempfile, time, unittest
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class FakeRaw:
    def __init__(self, inner): self.inner, self.closed, self.broken = inner, False, False
    def rollback(self): self.inner.rollback()
    def __getattr__(self, k): return getattr(self.inner, k)
    def close(self): self.closed = True; self.inner.close()


class WarmConnection(unittest.TestCase):
    def test_reuse_expiry_and_broken(self):
        # Session 22 (v0.8.33): isolated. It used to set DATABASE_PATH/ADMIN_* for the whole run and relied on "import seed" creating the
        # admin, but in the full suite seed was already imported (so no admin in this database) and other tests changed the environment
        # (for example ALLOW_EMAIL_LOGIN). Now the environment is patched only inside this test and seed.py is executed again here.
        tmp = tempfile.mkdtemp(); path = os.path.join(tmp, "w.db")
        env = {"DATABASE_PATH": path, "ADMIN_EMAIL": "a@w.test", "ADMIN_PASSWORD": "AdminPass123", "ALLOW_EMAIL_LOGIN": "1", "SEED_DEMO": "0"}
        env_patch = mock.patch.dict(os.environ, env); env_patch.start(); self.addCleanup(env_patch.stop)
        for k in ("DATABASE_URL", "POSTGRES_URL"): os.environ.pop(k, None)
        import dbx
        runpy.run_path(os.path.join(ROOT, "seed.py"), run_name="seed_for_warm_test")   # creates the admin in THIS database
        opened = []
        real = dbx.Conn

        class FakePG(real):
            def __init__(self, url=None, path_=None, id_tables=()):
                super().__init__(None, path, id_tables)
                self.raw_real, self.pg = self.raw, False
                self.raw = FakeRaw(self.raw_real)
                opened.append(self)
            def close(self): self.raw.close()
            def rollback(self): self.raw.rollback()

        dbx.Conn = FakePG
        try:
            import app as appmod
            app = appmod.create_app({"DATABASE_URL": "postgresql://fake/db", "DATABASE_PATH": path, "SECRET_KEY": "warm-test-key-" + "k" * 30})   # v0.8.39: a hosted database needs a real key
            opened.clear()
            c = app.test_client()
            tok = c.post("/api/auth/login", json={"email": "a@w.test", "password": "AdminPass123"}).get_json()["token"]
            H = {"Authorization": "Bearer " + tok}
            n0 = len(opened)
            for _ in range(3): self.assertEqual(c.get("/api/auth/me", headers=H).status_code, 200)
            self.assertEqual(len(opened) - n0, 0, "warm connection should be reused, not reopened")
            # broken connection is replaced
            opened[-1].raw.broken = True
            self.assertEqual(c.get("/api/auth/me", headers=H).status_code, 200)
            self.assertGreater(len(opened) - n0, 0)
            # idle too long is replaced
            app.config["WARM_SECONDS"] = -1
            n1 = len(opened)
            self.assertEqual(c.get("/api/auth/me", headers=H).status_code, 200)
            self.assertEqual(len(opened) - n1, 1)
        finally:
            dbx.Conn = real


if __name__ == "__main__":
    unittest.main()
