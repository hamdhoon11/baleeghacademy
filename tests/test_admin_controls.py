"""Admin editing, corrections, permissions and detailed settings."""
import os, sys, tempfile, unittest, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class AdminControls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ["DATABASE_PATH"] = os.path.join(tmp, "t.db")
        os.environ["ADMIN_EMAIL"] = "admin@ac.test"
        os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})

    def setUp(self): self.c = self.app.test_client()

    def login(self, email, pw):
        r = self.c.post("/api/auth/login", json={"email": email, "password": pw})
        return {"Authorization": "Bearer " + (r.get_json() or {}).get("token", "x")}

    def adm(self): return self.login("admin@ac.test", "AdminPass123")
    def J(self, m, url, h=None, **kw): return getattr(self.c, m)(url, headers=h or self.adm(), **kw)

    def mk(self, email, role="student", pw="Password123"):
        return self.J("post", "/api/users", json={"email": email, "password": pw, "full_name": email, "role": role}).get_json()["id"]

    # ---- users ----
    def test_01_edit_user_email_role_profile(self):
        uid = self.mk("edit1@t.test")
        r = self.J("patch", f"/api/users/{uid}", json={"email": "Fixed1@T.test", "full_name": "Fixed One", "grade": "9", "island": "Male", "guardian_name": "G"})
        self.assertEqual(r.status_code, 200, r.get_json())
        u = self.J("get", f"/api/users/{uid}").get_json()
        self.assertEqual((u["email"], u["full_name"], u["grade"], u["island"]), ("fixed1@t.test", "Fixed One", "9", "Male"))
        self.assertEqual(self.login("fixed1@t.test", "Password123")["Authorization"].startswith("Bearer x"), False)
        self.mk("dup@t.test")
        self.assertEqual(self.J("patch", f"/api/users/{uid}", json={"email": "dup@t.test"}).status_code, 409)
        self.assertEqual(self.J("patch", f"/api/users/{uid}", json={"email": "nope"}).status_code, 400)
        # role change allowed when no records; becomes a teacher with a bio
        self.assertEqual(self.J("patch", f"/api/users/{uid}", json={"role": "teacher", "bio": "Hi"}).status_code, 200)
        u = self.J("get", f"/api/users/{uid}").get_json()
        self.assertEqual((u["role"], u["bio"]), ("teacher", "Hi"))

    def test_02_role_change_blocked_with_records(self):
        sid = self.mk("withenr@t.test")
        bid = self.J("get", "/api/batches").get_json()[0]["id"]
        self.assertEqual(self.J("post", "/api/enrollments", json={"student_id": sid, "batch_id": bid}).status_code, 201)
        self.assertEqual(self.J("patch", f"/api/users/{sid}", json={"role": "teacher"}).status_code, 409)
        self.assertEqual(self.J("delete", f"/api/users/{sid}").status_code, 409)   # has records -> disable instead

    def test_03_delete_clean_user_and_self_protection(self):
        uid = self.mk("gone@t.test")
        self.assertEqual(self.J("delete", f"/api/users/{uid}").status_code, 200)
        self.assertEqual(self.J("get", f"/api/users/{uid}").status_code, 404)
        me = self.c.get("/api/auth/me", headers=self.adm()).get_json()["user"]
        self.assertIsNone(me["permissions"])
        self.assertEqual(self.J("delete", f"/api/users/{me['id']}").status_code, 400)
        self.assertEqual(self.J("patch", f"/api/users/{me['id']}", json={"role": "teacher"}).status_code, 400)
        self.assertEqual(self.J("patch", f"/api/users/{me['id']}", json={"is_active": False}).status_code, 400)

    def test_04_password_reset_and_min_length_setting(self):
        uid = self.mk("pw@t.test")
        self.assertEqual(self.J("patch", f"/api/users/{uid}", json={"password": "short"}).status_code, 400)
        self.assertEqual(self.J("put", "/api/settings", json={"min_password_length": "12"}).status_code, 200)
        self.assertEqual(self.J("patch", f"/api/users/{uid}", json={"password": "Password123"}).status_code, 400)
        self.assertEqual(self.J("patch", f"/api/users/{uid}", json={"password": "Password12345"}).status_code, 200)
        self.assertEqual(self.J("post", "/api/users", json={"email": "x9@t.test", "password": "Password123", "full_name": "x", "role": "student"}).status_code, 400)
        self.J("put", "/api/settings", json={"min_password_length": ""})   # back to default

    # ---- permissions ----
    def test_05_restricted_admin(self):
        a2 = self.mk("sub@t.test", "admin")
        self.assertEqual(self.J("patch", f"/api/users/{a2}", json={"permissions": ["courses", "batches"]}).status_code, 200)
        h = self.login("sub@t.test", "Password123")
        me = self.c.get("/api/auth/me", headers=h).get_json()["user"]
        self.assertEqual(me["permissions"], ["courses", "batches"])
        self.assertEqual(self.J("post", "/api/courses", h, json={"name": "SubCourse"}).status_code, 201)
        for method, url in (("get", "/api/settings"), ("get", "/api/audit"), ("get", "/api/applications"), ("get", "/api/invoices")):
            self.assertEqual(self.J(method, url, h).status_code, 403, url)
        self.assertEqual(self.J("post", "/api/users", h, json={"email": "z@t.test", "password": "Password123", "full_name": "z", "role": "student"}).status_code, 403)
        # cannot grant itself more, nor create admins
        self.assertEqual(self.J("patch", f"/api/users/{a2}", h, json={"permissions": None}).status_code, 403)
        # dashboard / lists stay readable so the screens still load
        self.assertEqual(self.J("get", "/api/dashboard", h).status_code, 200)
        self.assertEqual(self.J("patch", f"/api/users/{a2}", json={"permissions": ["bogus"]}).status_code, 400)
        self.assertEqual(self.J("patch", f"/api/users/{a2}", json={"permissions": "all"}).status_code, 200)
        self.assertEqual(self.J("get", "/api/settings", self.login("sub@t.test", "Password123")).status_code, 200)

    def test_06_last_full_admin_protected(self):
        users = self.J("get", "/api/users?role=admin").get_json()
        full = [u for u in users if u["permissions"] is None and u["is_active"]]
        # make every other full admin restricted/disabled, then the remaining one cannot be demoted
        keep = full[0]["id"]
        for u in full[1:]:
            self.J("patch", f"/api/users/{u['id']}", json={"is_active": False})
        other = self.mk("other-admin@t.test", "admin")
        self.J("patch", f"/api/users/{other}", json={"is_active": False})
        h = self.adm()
        self.assertEqual(self.J("patch", f"/api/users/{keep}", h, json={"permissions": ["courses"]}).status_code, 400)  # own account
        for u in full[1:]:
            self.J("patch", f"/api/users/{u['id']}", json={"is_active": True})

    # ---- courses and batches ----
    def test_07_course_validation_edit_delete(self):
        cid = self.J("post", "/api/courses", json={"name": "Temp", "status": "open"}).get_json()["id"]
        self.assertEqual(self.J("patch", f"/api/courses/{cid}", json={"monthly_fee_mvr": -5}).status_code, 400)
        self.assertEqual(self.J("patch", f"/api/courses/{cid}", json={"monthly_fee_mvr": "abc"}).status_code, 400)
        self.assertEqual(self.J("patch", f"/api/courses/{cid}", json={"name": "  "}).status_code, 400)
        self.assertEqual(self.J("patch", f"/api/courses/{cid}", json={"name": "Renamed", "monthly_fee_mvr": "400", "description": "d", "days_per_week": 3}).status_code, 200)
        c = [x for x in self.J("get", "/api/courses").get_json() if x["id"] == cid][0]
        self.assertEqual((c["name"], c["monthly_fee_mvr"]), ("Renamed", 400))
        b = self.J("post", "/api/batches", json={"course_id": cid, "code": "X1"}).get_json()["id"]
        self.assertEqual(self.J("delete", f"/api/courses/{cid}").status_code, 409)
        self.assertEqual(self.J("delete", f"/api/batches/{b}").status_code, 200)
        self.assertEqual(self.J("delete", f"/api/courses/{cid}").status_code, 200)
        self.assertEqual(self.J("delete", f"/api/courses/{cid}").status_code, 404)

    def test_08_batch_edit_code_course_capacity(self):
        c1 = self.J("post", "/api/courses", json={"name": "BC1"}).get_json()["id"]
        c2 = self.J("post", "/api/courses", json={"name": "BC2"}).get_json()["id"]
        b = self.J("post", "/api/batches", json={"course_id": c1, "code": "A"}).get_json()["id"]
        self.assertEqual(self.J("get", "/api/batches").get_json()[-1]["capacity"], 20)   # default_capacity setting
        self.assertEqual(self.J("patch", f"/api/batches/{b}", json={"code": "Evening 7", "course_id": c2, "capacity": 5}).status_code, 200)
        row = [x for x in self.J("get", "/api/batches").get_json() if x["id"] == b][0]
        self.assertEqual((row["code"], row["course_id"], row["capacity"]), ("Evening 7", c2, 5))
        self.assertEqual(self.J("patch", f"/api/batches/{b}", json={"capacity": 0}).status_code, 400)
        self.assertEqual(self.J("patch", f"/api/batches/{b}", json={"teacher_id": 999999}).status_code, 400)
        self.assertEqual(self.J("patch", f"/api/batches/{b}", json={"code": " "}).status_code, 400)
        b2 = self.J("post", "/api/batches", json={"course_id": c2, "code": "B"}).get_json()["id"]
        self.assertEqual(self.J("patch", f"/api/batches/{b2}", json={"code": "Evening 7"}).status_code, 409)
        # capacity cannot drop below enrolled students; course cannot change once students exist
        s = self.mk("cap@t.test")
        self.J("post", "/api/enrollments", json={"student_id": s, "batch_id": b})
        self.assertEqual(self.J("patch", f"/api/batches/{b}", json={"capacity": 1}).status_code, 200)
        s2 = self.mk("cap2@t.test")
        self.assertEqual(self.J("patch", f"/api/batches/{b}", json={"course_id": c1}).status_code, 409)
        self.assertEqual(self.J("delete", f"/api/batches/{b}").status_code, 409)

    def test_09_delete_enrollment_mistake(self):
        s = self.mk("enrdel@t.test")
        bid = self.J("post", "/api/batches", json={"course_id": self.J("post", "/api/courses", json={"name": "ED"}).get_json()["id"], "code": "E"}).get_json()["id"]
        eid = self.J("post", "/api/enrollments", json={"student_id": s, "batch_id": bid}).get_json()["id"]
        self.assertEqual(self.J("delete", f"/api/enrollments/{eid}").status_code, 200)
        self.assertEqual(self.J("delete", f"/api/enrollments/{eid}").status_code, 404)

    # ---- applications ----
    def apply(self, course_id, **over):
        f = {"full_name": "Appl Icant", "date_of_birth": "2000-01-01", "phone": "7771234", "email": "appl@t.test", "course_id": str(course_id)}
        f.update(over)
        pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
        f["id_card"] = (io.BytesIO(pdf), "id.pdf")
        return self.c.post("/api/public/apply", data=f, content_type="multipart/form-data")

    def test_10_edit_application_and_settings_wiring(self):
        cid = self.J("post", "/api/courses", json={"name": "AppC", "status": "open"}).get_json()["id"]
        r = self.apply(cid)
        self.assertEqual(r.status_code, 201, r.get_json())
        aid = [a for a in self.J("get", "/api/applications?status=pending").get_json() if a["email"] == "appl@t.test"][0]["id"]
        self.assertEqual(self.J("patch", f"/api/applications/{aid}", json={"full_name": "Corrected Name", "phone": "7779999", "email": "right@t.test"}).status_code, 200)
        a = self.J("get", f"/api/applications/{aid}").get_json()
        self.assertEqual((a["full_name"], a["email"]), ("Corrected Name", "right@t.test"))
        self.assertEqual(self.J("patch", f"/api/applications/{aid}", json={"email": "bad"}).status_code, 400)
        # welcome template
        self.J("put", "/api/settings", json={"welcome_message_template": "Hello {name}, login {email} / {password}"})
        bid = self.J("post", "/api/batches", json={"course_id": cid, "code": "W"}).get_json()["id"]
        res = self.J("post", f"/api/applications/{aid}/approve", json={"batch_id": bid}).get_json()
        self.assertTrue(res["message"].startswith("Hello Corrected Name, login right@t.test / "))
        self.assertEqual(self.J("patch", f"/api/applications/{aid}", json={"full_name": "x"}).status_code, 409)   # decided
        self.J("put", "/api/settings", json={"welcome_message_template": ""})
        # applications closed
        self.J("put", "/api/settings", json={"applications_open": "0", "applications_closed_message": "Closed until January"})
        r = self.apply(cid, email="late@t.test")
        self.assertEqual((r.status_code, r.get_json()["error"]), (403, "Closed until January"))
        self.assertFalse(self.c.get("/api/public/info").get_json()["applications_open"])
        self.J("put", "/api/settings", json={"applications_open": "1"})
        # minor age setting: a 19-year-old now needs a guardian
        self.J("put", "/api/settings", json={"minor_age": "21"})
        self.assertEqual(self.apply(cid, email="young@t.test", date_of_birth="2007-01-01").status_code, 400)
        self.J("put", "/api/settings", json={"minor_age": ""})

    def test_11_settings_schema_and_validation(self):
        sc = self.J("get", "/api/settings/schema").get_json()
        keys = [i["key"] for g in sc["groups"] for i in g["items"]]
        self.assertGreaterEqual(len(keys), 25)
        self.assertIn("applications_open", keys)
        for bad in ({"minor_age": "5"}, {"minor_age": "x"}, {"website_url": "http://x"}, {"contact_email": "nope"}, {"session_hours": "500"},
                    {"applications_open": "yes"}, {"first_invoice_mode": "maybe"}):
            self.assertEqual(self.J("put", "/api/settings", json=bad).status_code, 400, bad)
        self.assertEqual(self.J("put", "/api/settings", json={"tagline": "Learn well", "address": "Male'", "website_url": "https://baleeghacademy.netlify.app"}).status_code, 200)
        info = self.c.get("/api/public/info").get_json()
        self.assertEqual((info["tagline"], info["website_url"]), ("Learn well", "https://baleeghacademy.netlify.app"))
        self.assertEqual(info["academy_name"], "Baleegh Academy")

    def test_12_audit_records_what_changed(self):
        uid = self.mk("aud@t.test")
        self.J("patch", f"/api/users/{uid}", json={"full_name": "Audit Person"})
        log = self.J("get", "/api/audit").get_json()
        self.assertTrue(any(r["action"] == "update_user" and "Audit Person" in (r["detail"] or "") for r in log))
        self.assertFalse(any("Password123" in (r["detail"] or "") for r in log))


if __name__ == "__main__":
    unittest.main()
