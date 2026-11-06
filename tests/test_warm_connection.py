"""A warm instance reuses its database connection for the next request, and never reuses a stale or broken one.
Uses a stand-in for PostgreSQL (a SQLite file) so it runs anywhere; only the reuse rules are under test."""
import os, sys, tempfile, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeRaw:
    def __init__(self, inner): self.inner, self.closed, self.broken = inner, False, False
    def rollback(self): self.inner.rollback()
    def __getattr__(self, k): return getattr(self.inner, k)
    def close(self): self.closed = True; self.inner.close()


class WarmConnection(unittest.TestCase):
    def test_reuse_expiry_and_broken(self):
        tmp = tempfile.mkdtemp(); path = os.path.join(tmp, "w.db")
        os.environ["DATABASE_PATH"] = path; os.environ["ADMIN_EMAIL"] = "a@w.test"; os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import dbx
        import seed  # noqa: F401  creates the admin
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
            app = appmod.create_app({"DATABASE_URL": "postgresql://fake/db", "DATABASE_PATH": path})
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
