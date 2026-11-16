"""Security review 2026-11: a hosted server needs a real SECRET_KEY; a new password ends old sessions; status lookups are limited; safety headers."""
import os, sys, unittest, warnings
warnings.simplefilter("ignore", ResourceWarning)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_session32 as T


class SecurityReview(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.W = T.build()

    def test_01_hosted_server_refuses_default_key(self):
        from app import create_app
        for key in ("dev-only-change-me", "short"):
            with self.assertRaises(RuntimeError):
                create_app({"DATABASE_URL": "postgresql://fake/db", "SECRET_KEY": key})

    def test_02_own_password_change_ends_other_sessions(self):
        W, c = self.W, self.W["c"]
        r = c.post("/api/auth/login", json={"login": W["s2"][1], "password": T.PW}); second = {"Authorization": "Bearer " + r.get_json()["token"]}
        r = c.post("/api/auth/change-password", headers=W["H_s2"], json={"current_password": T.PW, "new_password": "AnotherPass123"})
        self.assertEqual(r.status_code, 200); fresh = {"Authorization": "Bearer " + r.get_json()["token"]}
        self.assertEqual(c.get("/api/auth/me", headers=second).status_code, 401)
        self.assertEqual(c.get("/api/auth/me", headers=W["H_s2"]).status_code, 401)
        self.assertEqual(c.get("/api/auth/me", headers=fresh).status_code, 200)

    def test_03_admin_reset_ends_sessions(self):
        W, c = self.W, self.W["c"]
        self.assertEqual(W["J"]("patch", f"/api/users/{W['t3'][0]}", json={"password": "ResetPass12345"}).status_code, 200)
        self.assertEqual(c.get("/api/auth/me", headers=W["H_t3"]).status_code, 401)
        self.assertEqual(W["J"]("post", f"/api/users/{W['t2'][0]}/reset-password").status_code, 200)
        self.assertEqual(c.get("/api/auth/me", headers=W["H_t2"]).status_code, 401)

    def test_04_status_lookup_limited_and_headers(self):
        c = self.W["c"]
        codes = [c.post("/api/public/apply/status", json={"ref": f"BA-{i:06X}", "phone": "7771234"}).status_code for i in range(35)]
        self.assertIn(429, codes)
        h = c.get("/").headers
        self.assertIn("frame-ancestors 'none'", h["Content-Security-Policy"])
        self.assertEqual(c.get("/", headers={"X-Forwarded-Proto": "https"}).headers.get("Strict-Transport-Security"), "max-age=31536000; includeSubDomains")


if __name__ == "__main__":
    unittest.main()
