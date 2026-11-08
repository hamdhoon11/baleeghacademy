"""Teacher file + written text on assignments, and the tutorials library (text, file, link, or any mix)."""
import io, os, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PDF = b"%PDF-1.4 worksheet"
PW = "Password123"


class P5(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ["DATABASE_PATH"] = os.path.join(tmp, "t5.db")
        os.environ["ADMIN_EMAIL"] = "admin@t5.test"; os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})
        c = cls.app.test_client(); cls.c = c
        cls.a = cls.login("admin@t5.test", "AdminPass123")
        cid = c.post("/api/courses", json={"name": "Arabic5", "status": "open"}, headers=cls.a).get_json()["id"]
        cls.cid = cid
        mk = lambda email, role, name: c.post("/api/users", json={"email": email, "password": PW, "full_name": name, "role": role}, headers=cls.a).get_json()["id"]
        t1, t2, s1, s2 = mk("t1@t5.test", "teacher", "Teacher One"), mk("t2@t5.test", "teacher", "Teacher Two"), mk("s1@t5.test", "student", "Student One"), mk("s2@t5.test", "student", "Student Two")
        cls.bid = c.post("/api/batches", json={"course_id": cid, "code": "X1", "teacher_id": t1, "capacity": 10}, headers=cls.a).get_json()["id"]
        c.post("/api/enrollments", json={"student_id": s1, "batch_id": cls.bid}, headers=cls.a)
        cls.t1, cls.t2, cls.s1, cls.s2 = (cls.login(e) for e in ("t1@t5.test", "t2@t5.test", "s1@t5.test", "s2@t5.test"))

    @classmethod
    def login(cls, email, pw=PW):
        r = cls.c.post("/api/auth/login", json={"email": email, "password": pw})
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    def f(self, data=PDF, name="sheet.pdf"): return (io.BytesIO(data), name)

    # ---- assignments: text, file, or both ----
    def test_assignment_text_and_file(self):
        r = self.c.post(f"/api/batches/{self.bid}/assignments", data={"title": "Both", "description": "Do page 3", "file": self.f()}, headers=self.t1, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True)); aid = r.get_json()["id"]
        a = [x for x in self.c.get("/api/assignments", headers=self.s1).get_json() if x["id"] == aid][0]
        self.assertEqual((a["description"], a["has_attachment"], a["attachment_name"]), ("Do page 3", True, "sheet.pdf"))
        d = self.c.get(f"/api/assignments/{aid}/attachment", headers=self.s1)
        self.assertEqual((d.status_code, d.data), (200, PDF))

    def test_assignment_text_only_and_json_still_work(self):
        r = self.c.post(f"/api/batches/{self.bid}/assignments", json={"title": "Text", "description": "Write 5 lines"}, headers=self.t1)
        self.assertEqual(r.status_code, 201)
        a = [x for x in self.c.get("/api/assignments", headers=self.t1).get_json() if x["id"] == r.get_json()["id"]][0]
        self.assertFalse(a["has_attachment"])
        self.assertEqual(self.c.get(f"/api/assignments/{a['id']}/attachment", headers=self.s1).status_code, 404)

    def test_assignment_file_only(self):
        r = self.c.post(f"/api/batches/{self.bid}/assignments", data={"title": "File only", "file": self.f()}, headers=self.t1, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201)

    def test_attachment_access_and_bad_files(self):
        aid = self.c.post(f"/api/batches/{self.bid}/assignments", data={"title": "Private", "file": self.f()}, headers=self.t1, content_type="multipart/form-data").get_json()["id"]
        self.assertEqual(self.c.get(f"/api/assignments/{aid}/attachment", headers=self.s2).status_code, 403)  # not enrolled
        self.assertEqual(self.c.get(f"/api/assignments/{aid}/attachment", headers=self.t2).status_code, 403)  # another teacher
        self.assertEqual(self.c.get(f"/api/assignments/{aid}/attachment").status_code, 401)
        r = self.c.post(f"/api/batches/{self.bid}/assignments", data={"title": "Bad", "file": self.f(b"MZ not a pdf", "x.pdf")}, headers=self.t1, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        r = self.c.post(f"/api/batches/{self.bid}/assignments", data={"title": "Bad", "file": self.f(b"x", "x.exe")}, headers=self.t1, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.c.post(f"/api/batches/{self.bid}/assignments", data={"title": "No", "file": self.f()}, headers=self.t2, content_type="multipart/form-data").status_code, 403)

    def test_delete_assignment_removes_file(self):
        aid = self.c.post(f"/api/batches/{self.bid}/assignments", data={"title": "Del", "file": self.f()}, headers=self.t1, content_type="multipart/form-data").get_json()["id"]
        self.assertEqual(self.c.delete(f"/api/assignments/{aid}", headers=self.t1).status_code, 200)
        self.assertEqual(self.c.get(f"/api/assignments/{aid}/attachment", headers=self.t1).status_code, 404)

    # ---- tutorials ----
    def post(self, who, **kw):
        data = {k: v for k, v in kw.items()}
        return self.c.post("/api/tutorials", data=data, headers=who, content_type="multipart/form-data")

    def test_tutorial_text_file_link_and_mix(self):
        for who in (self.t1, self.a):
            self.assertEqual(self.post(who, title="Text only", text="Read this").status_code, 201)
        self.assertEqual(self.post(self.s1, title="Student text", text="Read this").status_code, 403)   # students no longer post
        self.assertEqual(self.post(self.t1, title="File only", file=self.f()).status_code, 201)
        self.assertEqual(self.post(self.t1, title="Link only", url="https://example.com/x").status_code, 201)
        r = self.post(self.t1, title="All three", text="Notes", url="https://example.com/y", file=self.f(), course_id=str(self.cid))
        self.assertEqual(r.status_code, 201)
        tid = r.get_json()["id"]
        self.assertEqual(self.c.get(f"/api/tutorials/{tid}", headers=self.s2).status_code, 403)   # Session 13: course tutorials need an ACTIVE enrolment in that course
        item = [x for x in self.c.get("/api/tutorials", headers=self.s1).get_json() if x["id"] == tid][0]
        self.assertEqual((item["text"], item["has_file"], item["url"], item["course_name"], item["uploader"], item["uploader_role"]), ("Notes", True, "https://example.com/y", "Arabic5", "Teacher One", "teacher"))
        self.assertEqual(self.c.get(f"/api/tutorials/{tid}/file", headers=self.s1).data, PDF)  # an enrolled student can download

    def test_tutorial_validation(self):
        self.assertEqual(self.post(self.t1, title="Empty").status_code, 400)
        self.assertEqual(self.post(self.t1, text="No title").status_code, 400)
        self.assertEqual(self.post(self.t1, title="Bad link", url="javascript:alert(1)").status_code, 400)
        self.assertEqual(self.post(self.t1, title="Bad type", file=self.f(b"x", "a.exe")).status_code, 400)
        self.assertEqual(self.post(self.t1, title="Bad course", text="x", course_id="9999").status_code, 404)
        self.assertEqual(self.c.post("/api/tutorials", data={"title": "x", "text": "y"}).status_code, 401)

    def test_tutorial_delete_rules_and_audit(self):
        tid = self.post(self.t1, title="Teacher post", text="hi", file=self.f()).get_json()["id"]
        self.assertEqual(self.c.delete(f"/api/tutorials/{tid}", headers=self.s2).status_code, 403)   # students cannot delete
        self.assertEqual(self.c.delete(f"/api/tutorials/{tid}", headers=self.t2).status_code, 403)   # another teacher
        mine = [x for x in self.c.get("/api/tutorials", headers=self.t1).get_json() if x["id"] == tid][0]
        other = [x for x in self.c.get("/api/tutorials", headers=self.s2).get_json() if x["id"] == tid][0]
        adm = [x for x in self.c.get("/api/tutorials", headers=self.a).get_json() if x["id"] == tid][0]
        self.assertEqual((mine["can_delete"], other["can_delete"], adm["can_delete"]), (True, False, True))
        self.assertEqual(self.c.delete(f"/api/tutorials/{tid}", headers=self.a).status_code, 200)  # admin can remove anything
        self.assertEqual(self.c.get(f"/api/tutorials/{tid}/file", headers=self.s1).status_code, 404)
        acts = [x["action"] for x in self.c.get("/api/audit", headers=self.a).get_json()]
        self.assertIn("add_tutorial", acts); self.assertIn("delete_tutorial", acts)

    def test_tutorial_search_and_filter(self):
        self.post(self.t1, title="Verb tables", text="past tense", course_id=str(self.cid))
        self.post(self.t1, title="Other", text="unrelated")
        self.assertTrue(all("verb" in (x["title"] + (x["text"] or "")).lower() for x in self.c.get("/api/tutorials?q=verb", headers=self.s1).get_json()))
        self.assertTrue(all(x["course_name"] == "Arabic5" for x in self.c.get(f"/api/tutorials?course_id={self.cid}", headers=self.s1).get_json()))

    def test_old_database_gets_new_columns(self):
        import sqlite3
        p = os.path.join(tempfile.mkdtemp(), "old.db"); db = sqlite3.connect(p)
        db.executescript("CREATE TABLE assignments (id INTEGER PRIMARY KEY, batch_id INTEGER, title TEXT, description TEXT, kind TEXT, due_date TEXT, max_points INTEGER, created_by INTEGER, created_at TEXT);"); db.commit(); db.close()
        from app import create_app
        os.environ["DATABASE_PATH"] = p
        try:
            create_app({"DATABASE_PATH": p})
        except sqlite3.Error:
            pass  # a stub table cannot satisfy later foreign keys; the migration step is what is under test
        cols = {r[1] for r in sqlite3.connect(p).execute("PRAGMA table_info(assignments)")}
        self.assertTrue({"attachment", "attachment_name"} <= cols, cols)


if __name__ == "__main__":
    unittest.main()
