"""Session 11: sign in by ID, generated temporary passwords, forced first-login change (enforced by the server), reset, ID edit, no secrets in replies."""
import os, sqlite3, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import dbx, idcodes
from tests.test_session10 import old_database, conn_for, ROOT as _R
ADMIN_PW = "AdminPass123"


class S11(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ["DATABASE_PATH"] = os.path.join(tmp, "t.db")
        os.environ["ADMIN_EMAIL"] = "admin@s11.test"; os.environ["ADMIN_PASSWORD"] = ADMIN_PW
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        # the rule under test is ON here (the older suites switch it off with PORTAL_SKIP_FORCED_CHANGE)
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"], "SKIP_FORCED_CHANGE": False, "ALLOW_EMAIL_LOGIN": True})
        cls.c = cls.app.test_client()

    def login(self, who, pw, key="login"):
        return self.c.post("/api/auth/login", json={key: who, "password": pw})

    def H(self, r):
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    def mk(self, role="student", name="Some One", **extra):
        h = self.token("admin")
        body = {"full_name": name, "email": f"{name.split()[0].lower()}{os.urandom(3).hex()}@s11.test", "role": role, **extra}
        r = self.c.post("/api/users", json=body, headers=h)
        self.assertEqual(r.status_code, 201, r.get_json())
        return r

    _tok = {}
    def token(self, who):
        if who == "admin":
            r = self.login("admin@s11.test", ADMIN_PW_NOW[0], "email")
            if r.status_code == 200 and r.get_json()["user"]["must_change_password"]:
                h = self.H(r)
                self.assertEqual(self.c.post("/api/auth/change-password", headers=h, json={"current_password": ADMIN_PW_NOW[0], "new_password": "NewAdminPass1!"}).status_code, 200)
                ADMIN_PW_NOW[0] = "NewAdminPass1!"
                r = self.login("admin@s11.test", ADMIN_PW_NOW[0], "email")
            return self.H(r)

    # ---- tests ----
    def test_01_admin_teacher_student_get_login_ids_and_sign_in_by_id(self):
        h = self.token("admin")
        me = self.c.get("/api/auth/me", headers=h).get_json()["user"]
        self.assertRegex(me["login_id"], r"^BAL/A/\d{3}$")                      # seeded admin was backfilled
        t = self.mk("teacher", "Tea Cher").get_json()
        self.assertRegex(t["login_id"], r"^BAL/T/\d{3}$")
        s = self.mk("student", "Stu Dent").get_json()
        self.assertRegex(s["login_id"], r"^BAL/STU/\d{3}$")                     # no course yet: sign-in ID only
        # typed any way: lower case, spaces
        r = self.login(" " + s["login_id"].lower() + " ", s["temporary_password"])
        self.assertEqual(r.status_code, 200); self.assertEqual(r.get_json()["user"]["login_id"], s["login_id"])
        # student's permanent code is still empty (Session 10 decision)
        con = sqlite3.connect(os.environ["DATABASE_PATH"])
        self.assertIsNone(con.execute("SELECT student_code FROM students WHERE user_id=?", (s["id"],)).fetchone()[0]); con.close()

    def test_02_student_created_with_a_course_signs_in_with_the_course_id(self):
        h = self.token("admin")
        cid = self.c.post("/api/courses", json={"name": "Grade 8 Mathematics", "kind": "tuition", "monthly_fee_mvr": 300}, headers=h).get_json()["id"]
        s = self.mk("student", "Math Kid", course_id=cid).get_json()
        self.assertRegex(s["login_id"], r"^BAL/G8M/\d{3}$")
        self.assertEqual(self.login(s["login_id"], s["temporary_password"]).status_code, 200)

    def test_03_server_blocks_everything_until_the_password_is_changed(self):
        s = self.mk("student", "Forced Change").get_json()
        r = self.login(s["login_id"], s["temporary_password"]); h = self.H(r)
        self.assertEqual(r.get_json()["user"]["must_change_password"], 1)
        for path in ("/api/users", "/api/courses", "/api/my/grades", "/api/my/attendance"):
            x = self.c.get(path, headers=h)
            self.assertEqual(x.status_code, 403, path); self.assertEqual(x.get_json()["code"], "password_change_required", path)
        self.assertEqual(self.c.get("/api/auth/me", headers=h).status_code, 200)       # the page may ask who it is
        bad = self.c.post("/api/auth/change-password", headers=h, json={"current_password": "wrong", "new_password": "BrandNewPass9!"})
        self.assertEqual(bad.status_code, 400)
        short = self.c.post("/api/auth/change-password", headers=h, json={"current_password": s["temporary_password"], "new_password": "x"})
        self.assertEqual(short.status_code, 400)
        ok = self.c.post("/api/auth/change-password", headers=h, json={"current_password": s["temporary_password"], "new_password": "BrandNewPass9!"})
        self.assertEqual(ok.status_code, 200)
        self.assertNotEqual(self.c.get("/api/courses", headers=h).status_code, 403)    # no longer blocked
        self.assertEqual(self.login(s["login_id"], s["temporary_password"]).status_code, 401)   # the temporary password is dead
        r2 = self.login(s["login_id"], "BrandNewPass9!")
        self.assertEqual(r2.status_code, 200); self.assertEqual(r2.get_json()["user"]["must_change_password"], 0)

    def test_04_email_sign_in_can_be_switched_off(self):
        s = self.mk("teacher", "Mail Only").get_json()
        con = sqlite3.connect(os.environ["DATABASE_PATH"])
        email = con.execute("SELECT email FROM users WHERE id=?", (s["id"],)).fetchone()[0]; con.close()
        self.assertEqual(self.login(email, s["temporary_password"]).status_code, 200)          # still works by default
        self.app.config["ALLOW_EMAIL_LOGIN"] = False
        try: self.assertEqual(self.login(email, s["temporary_password"]).status_code, 401)
        finally: self.app.config["ALLOW_EMAIL_LOGIN"] = True

    def test_11_wrong_id_and_wrong_password_look_the_same_and_one_account_is_limited(self):
        s = self.mk("student", "Lock Me").get_json()
        a = self.login(s["login_id"], "nope"); b = self.login("BAL/NO/999", "nope")
        self.assertEqual((a.status_code, b.status_code), (401, 401)); self.assertEqual(a.get_json(), b.get_json())
        for _ in range(8): self.login(s["login_id"], "nope")   # (runs last: these failures also fill this address's own limit)
        self.assertEqual(self.login(s["login_id"], s["temporary_password"]).status_code, 429)   # even the right password waits

    def test_06_admin_reset_gives_new_temporary_password_once(self):
        h = self.token("admin")
        s = self.mk("student", "Reset Me").get_json()
        tok = self.H(self.login(s["login_id"], s["temporary_password"]))
        self.c.post("/api/auth/change-password", headers=tok, json={"current_password": s["temporary_password"], "new_password": "MyOwnPass123!"})
        r = self.c.post(f"/api/users/{s['id']}/reset-password", headers=h)
        self.assertEqual(r.status_code, 200); new = r.get_json()
        self.assertEqual(new["login_id"], s["login_id"]); self.assertIn("no-store", r.headers["Cache-Control"])
        self.assertEqual(self.login(s["login_id"], "MyOwnPass123!").status_code, 401)           # old password stopped
        again = self.login(s["login_id"], new["temporary_password"])
        self.assertEqual(again.status_code, 200); self.assertEqual(again.get_json()["user"]["must_change_password"], 1)
        # a student cannot reset anyone; an admin cannot reset their own password this way
        self.assertEqual(self.c.post(f"/api/users/{s['id']}/reset-password", headers=self.H(again)).status_code, 403)
        me = self.c.get("/api/auth/me", headers=h).get_json()["user"]["id"]
        self.assertEqual(self.c.post(f"/api/users/{me}/reset-password", headers=h).status_code, 400)
        self.assertEqual(self.c.post("/api/users/99999/reset-password", headers=h).status_code, 404)
        self.assertEqual(self.c.post(f"/api/users/{s['id']}/reset-password").status_code, 401)

    def test_07_deactivate_and_activate(self):
        h = self.token("admin")
        s = self.mk("student", "Switch Off").get_json()
        self.assertEqual(self.c.patch(f"/api/users/{s['id']}", json={"is_active": False}, headers=h).status_code, 200)
        self.assertEqual(self.login(s["login_id"], s["temporary_password"]).status_code, 401)
        self.assertEqual(self.c.patch(f"/api/users/{s['id']}", json={"is_active": True}, headers=h).status_code, 200)
        self.assertEqual(self.login(s["login_id"], s["temporary_password"]).status_code, 200)

    def test_08_edit_login_id_checks_format_and_uniqueness_and_is_logged(self):
        h = self.token("admin")
        a = self.mk("student", "Edit One").get_json(); b = self.mk("student", "Edit Two").get_json()
        p = lambda uid, v: self.c.patch(f"/api/users/{uid}", json={"login_id": v}, headers=h)
        self.assertEqual(p(a["id"], b["login_id"].lower()).status_code, 409)                    # taken (case does not matter)
        self.assertEqual(p(a["id"], "x").status_code, 400); self.assertEqual(p(a["id"], "bad id!").status_code, 400)
        self.assertEqual(p(a["id"], "bal/new/777").status_code, 200)
        self.assertEqual(self.login("BAL/NEW/777", a["temporary_password"]).status_code, 200)
        self.assertEqual(self.login(a["login_id"], a["temporary_password"]).status_code, 401)   # the old ID no longer works
        log = self.c.get("/api/audit", headers=h).get_json()
        acts = [x["action"] for x in log]
        self.assertIn("create_user", acts); self.assertIn("update_user", acts)
        self.assertTrue(any("BAL/NEW/777" in (x.get("detail") or "") for x in log if x["action"] == "update_user"))

    def test_09_no_reply_or_log_contains_a_password_or_hash(self):
        h = self.token("admin")
        s = self.mk("teacher", "Secret Keeper").get_json(); temp = s["temporary_password"]
        self.c.post(f"/api/users/{s['id']}/reset-password", headers=h)
        seen = []
        for path in ("/api/users", f"/api/users/{s['id']}", "/api/auth/me", "/api/audit", "/api/users?role=teacher"):
            seen.append(self.c.get(path, headers=h).get_data(as_text=True))
        seen.append(self.login(s["login_id"], temp).get_data(as_text=True))                      # (401 after the reset)
        for text in seen:
            self.assertNotIn("password_hash", text); self.assertNotIn("pbkdf2:", text); self.assertNotIn("scrypt:", text); self.assertNotIn(temp, text)

    def test_10_backfill_on_an_upgraded_v0_8_8_database_is_complete_and_repeatable(self):
        path = os.path.join(tempfile.mkdtemp(), "old.db"); old_database(path)
        c = conn_for(path); dbx.init_schema(c, ROOT)
        self.assertIn("login_id", c.columns("users"))
        rep = idcodes.fill_missing(c, unenrolled_students=True); c.commit()
        ids = {r["id"]: r["login_id"] for r in c.execute("SELECT id,login_id FROM users").fetchall()}
        self.assertTrue(all(ids.values()), ids)                                                   # everybody can sign in by ID
        self.assertEqual(len(set(ids.values())), len(ids)); self.assertEqual(ids[1], "BAL/A/001")
        self.assertEqual(ids[2], "BAL/T/001")
        self.assertEqual(len(rep["login_ids"]), 7)
        again = idcodes.fill_missing(c, unenrolled_students=True)
        self.assertEqual(again["login_ids"], [])                                                  # second run has nothing to do
        self.assertEqual(idcodes.duplicates(c), []); c.close()


ADMIN_PW_NOW = [ADMIN_PW]

if __name__ == "__main__":
    unittest.main()
