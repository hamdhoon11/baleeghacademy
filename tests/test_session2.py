"""Session 2: only teachers and admins post tutorials; students send answers (text, file, or both); permissions are superadmin controls."""
import io, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PDF = b"%PDF-1.4 answer"
PW = "Password123"


class Session2(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ["DATABASE_PATH"] = os.path.join(tmp, "t.db")
        os.environ["ADMIN_EMAIL"] = "admin@s2.test"; os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})
        cls.c = cls.app.test_client()
        cls.a = cls.login("admin@s2.test", "AdminPass123")
        cls.ids = {}
        for email, role in (("t1", "teacher"), ("t2", "teacher"), ("s1", "student"), ("s2", "student")):
            cls.ids[email] = cls.c.post("/api/users", json={"email": f"{email}@s2.test", "password": PW, "full_name": email.upper(), "role": role}, headers=cls.a).get_json()["id"]
        cls.t1, cls.t2, cls.s1, cls.s2 = (cls.login(f"{e}@s2.test") for e in ("t1", "t2", "s1", "s2"))

    @classmethod
    def login(cls, email, pw=PW):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"email": email, "password": pw}).get_json()["token"]}

    def tut(self, who, **kw):
        return self.c.post("/api/tutorials", data=kw, headers=who, content_type="multipart/form-data")

    def answer(self, who, tid, **kw):
        return self.c.post(f"/api/tutorials/{tid}/submission", data=kw, headers=who, content_type="multipart/form-data")

    def item(self, who, tid):
        return [x for x in self.c.get("/api/tutorials", headers=who).get_json() if x["id"] == tid][0]

    def setperms(self, name, areas):
        r = self.c.patch(f"/api/users/{self.ids[name]}", json={"permissions": areas}, headers=self.a); self.assertEqual(r.status_code, 200, r.get_json())
        return self.login(f"{name}@s2.test")

    # ---- who can post ----
    def test_students_cannot_create(self):
        r = self.tut(self.s1, title="x", text="y")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.c.get("/api/tutorials", headers=self.s1).status_code, 200)   # but they can read
        self.assertEqual(self.tut(self.t1, title="ok", text="y").status_code, 201)
        self.assertEqual(self.tut(self.a, title="ok", text="y").status_code, 201)

    def test_superadmin_controls_create_permission(self):
        h = self.setperms("t2", ["classroom", "tutorials"])            # create_tutorials not ticked
        self.assertEqual(self.tut(h, title="x", text="y").status_code, 403)
        h = self.setperms("t2", ["classroom", "tutorials", "create_tutorials"])
        self.assertEqual(self.tut(h, title="x", text="y").status_code, 201)
        h = self.setperms("t2", ["classroom", "create_tutorials"])     # cannot open Tutorials at all
        self.assertEqual(self.tut(h, title="x", text="y").status_code, 403)
        self.c.patch(f"/api/users/{self.ids['t2']}", json={"permissions": "all"}, headers=self.a)

    # ---- answers ----
    def test_answer_text_file_both_and_resubmit(self):
        tid = self.tut(self.t1, title="Verbs", text="Do it").get_json()["id"]
        self.assertEqual(self.answer(self.s1, tid).status_code, 400)                                    # nothing sent
        r = self.answer(self.s1, tid, text="my answer"); self.assertEqual(r.status_code, 201)
        self.assertEqual(self.answer(self.s2, tid, file=(io.BytesIO(PDF), "a.pdf")).status_code, 201)   # file only
        r = self.answer(self.s1, tid, file=(io.BytesIO(PDF), "b.pdf")); self.assertEqual(r.status_code, 200)   # replace: file added, text kept? (text empty -> cleared)
        mine = self.c.get(f"/api/tutorials/{tid}/submission", headers=self.s1).get_json()["submission"]
        self.assertEqual((mine["has_file"], mine["file_name"]), (True, "b.pdf"))
        self.answer(self.s1, tid, text="new words", file=(io.BytesIO(PDF), "c.pdf"))
        self.answer(self.s1, tid, text="only text again")                                                # keeps the earlier file
        mine = self.c.get(f"/api/tutorials/{tid}/submission", headers=self.s1).get_json()["submission"]
        self.assertEqual((mine["text_answer"], mine["file_name"]), ("only text again", "c.pdf"))
        self.assertEqual(len(self.c.get(f"/api/tutorials/{tid}/submissions", headers=self.t1).get_json()["submissions"]), 2)   # one per student

    def test_answer_validation(self):
        tid = self.tut(self.t1, title="V", text="x").get_json()["id"]
        self.assertEqual(self.answer(self.s1, tid, file=(io.BytesIO(b"MZ nope"), "x.pdf")).status_code, 400)
        self.assertEqual(self.answer(self.s1, tid, file=(io.BytesIO(b"x"), "x.exe")).status_code, 400)
        self.assertEqual(self.answer(self.s1, tid, text="x" * 10001).status_code, 400)
        self.assertEqual(self.answer(self.s1, 99999, text="x").status_code, 404)
        self.assertEqual(self.c.post(f"/api/tutorials/{tid}/submission", data={"text": "x"}).status_code, 401)
        self.assertEqual(self.answer(self.t1, tid, text="x").status_code, 403)                            # teachers do not submit
        self.assertEqual(self.answer(self.a, tid, text="x").status_code, 403)

    def test_submit_permission_is_superadmin_controlled(self):
        tid = self.tut(self.t1, title="Perm", text="x").get_json()["id"]
        h = self.setperms("s2", ["assignments", "tutorials"])         # submit_tutorial_work not ticked
        self.assertEqual(self.answer(h, tid, text="x").status_code, 403)
        self.assertFalse(self.item(h, tid)["can_submit"])
        h = self.setperms("s2", ["assignments", "tutorials", "submit_tutorial_work"])
        self.assertEqual(self.answer(h, tid, text="x").status_code, 201)
        self.assertTrue(self.item(h, tid)["can_submit"])
        h = self.setperms("s2", ["submit_tutorial_work"])             # no Tutorials tab
        self.assertEqual(self.answer(h, tid, text="y").status_code, 403)
        self.c.patch(f"/api/users/{self.ids['s2']}", json={"permissions": "all"}, headers=self.a)

    # ---- who sees answers ----
    def test_who_sees_answers_and_files(self):
        tid = self.tut(self.t1, title="Private", text="x").get_json()["id"]
        self.answer(self.s1, tid, text="secret", file=(io.BytesIO(PDF), "mine.pdf"))
        sub = self.c.get(f"/api/tutorials/{tid}/submissions", headers=self.t1).get_json()["submissions"][0]
        self.assertEqual((sub["full_name"], sub["text_answer"], sub["has_file"]), ("S1", "secret", True))
        self.assertEqual(self.c.get(f"/api/tutorials/{tid}/submissions", headers=self.a).status_code, 200)           # admin sees all
        self.assertEqual(self.c.get(f"/api/tutorials/{tid}/submissions", headers=self.t2).status_code, 403)          # another teacher
        self.assertEqual(self.c.get(f"/api/tutorials/{tid}/submissions", headers=self.s1).status_code, 403)          # students never list answers
        url = f"/api/tutorial-submissions/{sub['id']}/file"
        for who, code in ((self.s1, 200), (self.t1, 200), (self.a, 200), (self.s2, 403), (self.t2, 403)):
            self.assertEqual(self.c.get(url, headers=who).status_code, code, url)
        self.assertEqual(self.c.get(url).status_code, 401)
        self.assertEqual(self.c.get(url, headers=self.t1).data, PDF)
        self.assertEqual(self.c.get(f"/api/tutorials/{tid}/submission", headers=self.s2).get_json()["submission"], None)   # others' answers are not mine
        t = self.item(self.t1, tid); self.assertEqual((t["can_view_answers"], t["answer_count"]), (True, 1))
        self.assertEqual([x for x in self.c.get("/api/tutorials", headers=self.t2).get_json() if x["id"] == tid], [])   # Session 18: a teacher sees only tutorials of their own batches
        self.assertNotIn("can_view_answers", self.item(self.s1, tid))
        self.assertTrue(self.item(self.s1, tid)["my_submission"]["has_file"]); self.assertIsNone(self.item(self.s2, tid)["my_submission"])

    # ---- old student posts ----
    def test_old_student_posts_stay_visible_read_only(self):
        # simulate a post made before this change
        with self.app.app_context():
            from flask import g
            import dbx
            conn = dbx.Conn(self.app.config["DATABASE_URL"], self.app.config["DATABASE_PATH"], ())
            tid = conn.execute("INSERT INTO tutorials(title,body,uploaded_by) VALUES(?,?,?)", ("Old student post", "from before", self.ids["s1"])).lastrowid
            conn.commit(); conn.close()
        for who in (self.s1, self.s2, self.a):
            it = self.item(who, tid); self.assertEqual(it["text"], "from before")
            self.assertFalse(it["can_submit"]); self.assertFalse(it["accepts_answers"])
        self.assertFalse(self.item(self.s1, tid)["can_delete"])                                    # even the author cannot delete now
        self.assertEqual(self.c.delete(f"/api/tutorials/{tid}", headers=self.s1).status_code, 403)
        self.assertEqual(self.answer(self.s2, tid, text="x").status_code, 409)                      # no answers to old student posts
        self.assertEqual(self.c.delete(f"/api/tutorials/{tid}", headers=self.a).status_code, 200)  # admin can still clean up

    def test_deleting_a_tutorial_removes_answers_and_files(self):
        tid = self.tut(self.t1, title="Gone", text="x").get_json()["id"]
        self.answer(self.s1, tid, file=(io.BytesIO(PDF), "g.pdf"))
        sid = self.c.get(f"/api/tutorials/{tid}/submissions", headers=self.t1).get_json()["submissions"][0]["id"]
        self.assertEqual(self.c.delete(f"/api/tutorials/{tid}", headers=self.t2).status_code, 403)
        self.assertEqual(self.c.delete(f"/api/tutorials/{tid}", headers=self.t1).status_code, 200)
        self.assertEqual(self.c.get(f"/api/tutorial-submissions/{sid}/file", headers=self.a).status_code, 404)
        self.assertEqual(self.c.get(f"/api/tutorials/{tid}/submissions", headers=self.a).status_code, 404)

    # ---- permissions list and upgrade of limited accounts ----
    def test_new_areas_listed_per_role(self):
        for name, role, area in (("t1", "teacher", "create_tutorials"), ("s1", "student", "submit_tutorial_work")):
            self.assertIn(area, self.c.get(f"/api/users/{self.ids[name]}", headers=self.a).get_json()["areas"])
        self.assertEqual(self.c.patch(f"/api/users/{self.ids['s1']}", json={"permissions": ["create_tutorials"]}, headers=self.a).status_code, 400)   # wrong role
        self.assertEqual(self.c.patch(f"/api/users/{self.ids['t1']}", json={"permissions": ["submit_tutorial_work"]}, headers=self.a).status_code, 400)

    def test_limited_accounts_keep_what_they_could_do(self):
        import sqlite3, dbx
        p = os.path.join(tempfile.mkdtemp(), "up.db")
        from app import create_app
        app = create_app({"DATABASE_PATH": p}); c = app.test_client()
        con = sqlite3.connect(p)
        con.execute("INSERT INTO users(email,password_hash,full_name,role,permissions) VALUES('lt@x.test','x','LT','teacher','classroom,tutorials')")
        con.execute("INSERT INTO users(email,password_hash,full_name,role,permissions) VALUES('ls@x.test','x','LS','student','assignments,tutorials')")
        con.execute("INSERT INTO users(email,password_hash,full_name,role,permissions) VALUES('lc@x.test','x','LC','teacher','classroom')")
        con.execute("DELETE FROM schema_meta"); con.commit(); con.close()
        create_app({"DATABASE_PATH": p})   # starting again runs the upgrade
        got = dict(sqlite3.connect(p).execute("SELECT email,permissions FROM users WHERE email LIKE 'l_@x.test'").fetchall())
        self.assertEqual(got["lt@x.test"], "classroom,tutorials,create_tutorials")
        self.assertEqual(got["ls@x.test"], "assignments,tutorials,submit_tutorial_work")
        self.assertEqual(got["lc@x.test"], "classroom")     # no Tutorials access before, none now


if __name__ == "__main__":
    unittest.main()
