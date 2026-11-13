"""Per-user permissions: every role (student, teacher, admin) can be limited to some areas.
The server decides the tab list AND refuses every request outside the allowed areas."""
import os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class Permissions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ["DATABASE_PATH"] = os.path.join(tmp, "t.db")
        os.environ["ADMIN_EMAIL"] = "admin@pm.test"
        os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})

    def setUp(self): self.c = self.app.test_client()

    def login(self, email, pw="Password123"):
        r = self.c.post("/api/auth/login", json={"email": email, "password": pw})
        return r.get_json() or {}

    def H(self, email, pw="Password123"):
        return {"Authorization": "Bearer " + self.login(email, pw).get("token", "x")}

    def adm(self): return self.H("admin@pm.test", "AdminPass123")
    def J(self, m, url, h=None, **kw): return getattr(self.c, m)(url, headers=h or self.adm(), **kw)

    def mk(self, email, role):
        return self.J("post", "/api/users", json={"email": email, "password": "Password123", "full_name": email, "role": role}).get_json()["id"]

    def limit(self, uid, areas):
        r = self.J("patch", f"/api/users/{uid}", json={"permissions": areas})
        self.assertEqual(r.status_code, 200, r.get_json()); return r

    # ---- the server decides the tabs ----
    def test_01_default_tabs_per_role(self):
        self.assertEqual(self.login("admin@pm.test", "AdminPass123")["user"]["tabs"],
                         ["dashboard", "admissions", "courses", "batches", "timetable", "classroom", "tutorials", "people", "student_information", "teacher_information", "enrollments", "online", "fees", "finance", "settings", "audit"])
        self.mk("t0@pm.test", "teacher"); self.mk("s0@pm.test", "student")
        self.assertEqual(self.login("t0@pm.test")["user"]["tabs"], ["home", "timetable", "classroom", "tutorials", "my_files", "my_earnings", "my_information"])
        self.assertEqual(self.login("s0@pm.test")["user"]["tabs"], ["home", "timetable", "assignments", "progress", "materials", "recordings", "fees", "tutorials", "my_files", "my_information"])
        self.assertIsNone(self.login("s0@pm.test")["user"]["permissions"])   # None = everything the role has

    def test_02_student_limited_tabs_and_me(self):
        sid = self.mk("s1@pm.test", "student")
        self.limit(sid, ["assignments", "tutorials"])
        u = self.login("s1@pm.test")["user"]
        self.assertEqual(u["tabs"], ["home", "timetable", "assignments", "tutorials", "my_files", "my_information"]); self.assertEqual(u["permissions"], ["assignments", "tutorials"])
        me = self.J("get", "/api/auth/me", self.H("s1@pm.test")).get_json()["user"]
        self.assertEqual(me["tabs"], ["home", "timetable", "assignments", "tutorials", "my_files", "my_information"])

    # ---- the server refuses what is not allowed ----
    def test_03_student_requests_refused_outside_areas(self):
        sid = self.mk("s2@pm.test", "student"); self.limit(sid, ["assignments"])
        h = self.H("s2@pm.test")
        for url in ("/api/my/grades", "/api/my/attendance", "/api/materials", "/api/my/fees", "/api/my/fees/summary", "/api/tutorials"):
            r = self.J("get", url, h); self.assertEqual(r.status_code, 403, url); self.assertIn("permission", r.get_json()["error"])
        self.assertEqual(self.J("get", "/api/assignments", h).status_code, 200)
        self.assertEqual(self.J("get", "/api/my/home", h).status_code, 200)   # Home is always allowed
        self.assertEqual(self.J("post", "/api/tutorials", h, data={"title": "x", "text": "y"}).status_code, 403)

    def test_04_student_home_hides_what_is_not_allowed(self):
        sid = self.mk("s3@pm.test", "student")
        bid = self.J("get", "/api/batches").get_json()[0]["id"]
        self.assertEqual(self.J("post", "/api/enrollments", json={"student_id": sid, "batch_id": bid}).status_code, 201)
        full = self.J("get", "/api/my/home", self.H("s3@pm.test")).get_json()
        self.assertIn("todo", full)
        self.limit(sid, ["materials"])
        h = self.J("get", "/api/my/home", self.H("s3@pm.test")).get_json()
        self.assertEqual(h["todo"], [])
        for c in h["courses"]: self.assertEqual((c["attendance_pct"], c["avg_pct"]), (None, None))
        self.limit(sid, ["assignments", "progress"])
        self.assertEqual(self.J("get", "/api/materials", self.H("s3@pm.test")).status_code, 403)

    def test_05_teacher_limited(self):
        tid = self.mk("t1@pm.test", "teacher"); self.limit(tid, ["tutorials"])
        self.assertEqual(self.login("t1@pm.test")["user"]["tabs"], ["home", "timetable", "tutorials", "my_files", "my_earnings", "my_information"])
        h = self.H("t1@pm.test")
        bid = self.J("get", "/api/batches").get_json()[0]["id"]
        for m, url in (("get", f"/api/batches/{bid}/attendance"), ("get", "/api/assignments"), ("get", "/api/materials"), ("get", f"/api/batches/{bid}/gradebook")):
            self.assertEqual(self.J(m, url, h).status_code, 403, url)
        self.assertEqual(self.J("get", "/api/tutorials", h).status_code, 200)
        home = self.J("get", "/api/my/home", h).get_json()
        self.assertEqual((home["to_grade"], home["low_attendance"]), (0, []))

    def test_06_admin_limited_still_works_and_other_roles_cannot_enter_admin_areas(self):
        aid = self.mk("a1@pm.test", "admin"); self.limit(aid, ["people"])
        self.assertEqual(self.login("a1@pm.test")["user"]["tabs"], ["dashboard", "people"])
        h = self.H("a1@pm.test")
        self.assertEqual(self.J("get", "/api/users/1", h).status_code, 200)
        self.assertEqual(self.J("get", "/api/settings", h).status_code, 403)
        # a student can never reach an admin route, with or without a permission list
        self.mk("s4@pm.test", "student")
        self.assertEqual(self.J("get", "/api/users/1", self.H("s4@pm.test")).status_code, 403)
        self.assertEqual(self.J("get", "/api/audit", self.H("s4@pm.test")).status_code, 403)

    # ---- who may change permissions, and what is checked ----
    def test_07_validation(self):
        sid = self.mk("s5@pm.test", "student"); tid = self.mk("t2@pm.test", "teacher")
        self.assertEqual(self.J("patch", f"/api/users/{sid}", json={"permissions": ["people"]}).status_code, 400)       # admin area, not a student area
        self.assertEqual(self.J("patch", f"/api/users/{tid}", json={"permissions": ["fees"]}).status_code, 400)
        self.assertEqual(self.J("patch", f"/api/users/{sid}", json={"permissions": ["nonsense"]}).status_code, 400)
        self.assertEqual(self.J("patch", f"/api/users/{sid}", json={"permissions": "everything"}).status_code, 400)
        self.limit(sid, []); self.assertEqual(self.login("s5@pm.test")["user"]["tabs"], ["home", "timetable", "my_information"])   # nothing ticked: Home and the timetable (v0.8.37) only
        self.limit(sid, "all"); self.assertIsNone(self.login("s5@pm.test")["user"]["permissions"])
        self.assertEqual(self.J("get", f"/api/users/{sid}").get_json()["areas"], ["assignments", "progress", "materials", "recordings", "fees", "tutorials", "submit_tutorial_work"])

    def test_08_only_a_full_admin_changes_permissions(self):
        aid = self.mk("a2@pm.test", "admin"); self.limit(aid, ["people"])
        sid = self.mk("s6@pm.test", "student")
        self.assertEqual(self.J("patch", f"/api/users/{sid}", self.H("a2@pm.test"), json={"permissions": ["fees"]}).status_code, 403)
        self.assertEqual(self.J("post", "/api/users", self.H("a2@pm.test"), json={"email": "s7@pm.test", "password": "Password123", "full_name": "x", "role": "student", "permissions": ["fees"]}).status_code, 403)
        self.assertEqual(self.J("patch", "/api/users/1", json={"permissions": ["people"]}).status_code, 400)   # full admin id 1 is the only one: cannot be limited... or own account
        # nobody changes their own permissions
        self.assertEqual(self.J("patch", f"/api/users/{aid}", self.H("a2@pm.test"), json={"permissions": "all"}).status_code, 403)

    def test_09_create_with_permissions_and_role_change_resets(self):
        r = self.J("post", "/api/users", json={"email": "s8@pm.test", "password": "Password123", "full_name": "S8", "role": "student", "permissions": ["materials", "tutorials"]})
        self.assertEqual(r.status_code, 201, r.get_json()); uid = r.get_json()["id"]
        self.assertEqual(self.login("s8@pm.test")["user"]["tabs"], ["home", "timetable", "materials", "tutorials", "my_files", "my_information"])
        self.assertEqual(self.J("post", "/api/users", json={"email": "s9@pm.test", "password": "Password123", "full_name": "S9", "role": "teacher", "permissions": ["fees"]}).status_code, 400)
        # role change: permissions + role together is refused; the role change alone resets to "everything the new role has"
        self.assertEqual(self.J("patch", f"/api/users/{uid}", json={"role": "teacher", "permissions": ["classroom"]}).status_code, 400)
        self.assertEqual(self.J("patch", f"/api/users/{uid}", json={"role": "teacher"}).status_code, 200)
        self.assertEqual(self.login("s8@pm.test")["user"]["tabs"], ["home", "timetable", "classroom", "tutorials", "my_files", "my_earnings", "my_information"])

    def test_10_change_takes_effect_on_the_next_request(self):
        sid = self.mk("s10@pm.test", "student"); h = self.H("s10@pm.test")   # one token, used before and after
        self.assertEqual(self.J("get", "/api/materials", h).status_code, 200)
        self.limit(sid, ["tutorials"])
        self.assertEqual(self.J("get", "/api/materials", h).status_code, 403)
        self.limit(sid, "all")
        self.assertEqual(self.J("get", "/api/materials", h).status_code, 200)

    def test_11_audit_records_permission_change(self):
        sid = self.mk("s11@pm.test", "student"); self.limit(sid, ["fees"])
        self.assertTrue(any(r["action"] == "update_user" and "permissions" in (r["detail"] or "") for r in self.J("get", "/api/audit").get_json()))

    def test_12_every_tab_has_a_view_and_a_label(self):
        import json, re, settings_schema as SS
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        en = json.load(open(os.path.join(root, "static/i18n/en.json"), encoding="utf-8"))
        js = "".join(open(os.path.join(root, "static", f), encoding="utf-8").read() for f in ("index.html", "learning.js", "fees.js", "admin.js"))
        adm = open(os.path.join(root, "static/admin.js"), encoding="utf-8").read()
        for role, tabs in SS.ROLE_TABS.items():
            for tab in tabs:
                self.assertIn(tab, en, f"{role}: tab label {tab}")
                self.assertTrue(re.search(r"views\.%s\s*=|\b%s\(\)\s*\{|\b%s:\s*async" % (tab, tab, tab), js) or tab == "home", f"{role}: view for {tab}")
        for role, areas in SS.ROLE_AREAS.items():
            for a in areas: self.assertIn(a, re.search(r"AREA_LABELS = \{(.*?)\}", adm, re.S).group(1), f"people editor knows area {a}")
            self.assertEqual(set(areas) - set(SS.AREAS), set())
        self.assertTrue(re.search(r'ROLE_AREAS = \{admin: \[%s\]' % ", ".join('"%s"' % a for a in SS.ROLE_AREAS["admin"]), adm), "admin.js and the server list the same admin areas")
        self.assertTrue(re.search(r'student: \[%s\]' % ", ".join('"%s"' % a for a in SS.ROLE_AREAS["student"]), adm))
        self.assertTrue(re.search(r'teacher: \[%s\]' % ", ".join('"%s"' % a for a in SS.ROLE_AREAS["teacher"]), adm))


if __name__ == "__main__":
    unittest.main(verbosity=2)
