"""Session 5: class recordings. A teacher adds a Google Drive link (title + class date) to their own batches only; students of that batch
open it; the 'add_recordings' and 'recordings' permissions are controlled by a full admin."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MVT = dt.timezone(dt.timedelta(hours=5)); PW = "Password123"
FILE = "https://drive.google.com/file/d/1AbC_dEf-123/view?usp=sharing"
FOLDER = "https://drive.google.com/drive/folders/1FolderId"


class Session5(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ["DATABASE_PATH"] = os.path.join(tmp, "t.db")
        os.environ["ADMIN_EMAIL"] = "admin@s5.test"; os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        cls.clock = [dt.datetime(2026, 3, 2, 15, 50, tzinfo=MVT)]
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"], "NOW": lambda: cls.clock[0]})
        c = cls.c = cls.app.test_client()
        cls.a = cls.login("admin@s5.test", "AdminPass123")
        cid = c.post("/api/courses", json={"name": "Arabic", "status": "open", "minutes_per_class": 60}, headers=cls.a).get_json()["id"]
        mk = lambda e, r: c.post("/api/users", json={"email": e + "@s5.test", "password": PW, "full_name": e.upper(), "role": r}, headers=cls.a).get_json()["id"]
        cls.ids = {n: mk(n, r) for n, r in (("t1", "teacher"), ("t2", "teacher"), ("s1", "student"), ("s2", "student"))}
        cls.b1 = c.post("/api/batches", json={"course_id": cid, "code": "B1", "days": "Mon", "start_time": "16:00", "teacher_id": cls.ids["t1"], "capacity": 10}, headers=cls.a).get_json()["id"]
        cls.b2 = c.post("/api/batches", json={"course_id": cid, "code": "B2", "days": "Tue", "start_time": "10:00", "teacher_id": cls.ids["t2"], "capacity": 10}, headers=cls.a).get_json()["id"]
        c.post("/api/enrollments", json={"student_id": cls.ids["s1"], "batch_id": cls.b1}, headers=cls.a)
        cls.t1, cls.t2, cls.s1, cls.s2 = (cls.login(f"{n}@s5.test") for n in ("t1", "t2", "s1", "s2"))

    @classmethod
    def login(cls, email, pw=PW):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"email": email, "password": pw}).get_json()["token"]}

    def setUp(self):
        self.clock[0] = dt.datetime(2026, 3, 2, 15, 50, tzinfo=MVT)
        con = sqlite3.connect(os.environ["DATABASE_PATH"]); con.execute("DELETE FROM recordings"); con.commit(); con.close()
    def add(self, bid, who, **kw):
        d = {"title": "Lesson 1", "recorded_on": "2026-03-01", "url": FILE}; d.update(kw)
        return self.c.post(f"/api/batches/{bid}/recordings", json=d, headers=who)
    def lst(self, who, q=""): return self.c.get("/api/recordings" + q, headers=who)
    def setperms(self, name, areas):
        r = self.c.patch(f"/api/users/{self.ids[name]}", json={"permissions": areas}, headers=self.a); self.assertEqual(r.status_code, 200, r.get_json())
        return self.login(f"{name}@s5.test")
    def reset(self, name): self.c.patch(f"/api/users/{self.ids[name]}", json={"permissions": "all"}, headers=self.a)

    def test_teacher_adds_student_of_batch_sees_and_opens(self):
        r = self.add(self.b1, self.t1); self.assertEqual(r.status_code, 201, r.get_json())
        l = self.lst(self.s1).get_json()
        self.assertEqual(len(l), 1); self.assertEqual((l[0]["title"], l[0]["url"], l[0]["recorded_on"], l[0]["batch_code"]), ("Lesson 1", FILE, "2026-03-01", "B1"))
        self.assertEqual(l[0]["download_url"], "https://drive.google.com/uc?export=download&id=1AbC_dEf-123")
        self.assertEqual(len(self.lst(self.t1).get_json()), 1)
        self.assertEqual(len(self.lst(self.a).get_json()), 1)

    def test_folder_link_has_open_but_no_download(self):
        self.add(self.b1, self.t1, url=FOLDER)
        l = self.lst(self.s1).get_json(); self.assertEqual((l[0]["url"], l[0]["download_url"]), (FOLDER, None))

    def test_newest_class_first(self):
        self.add(self.b1, self.t1, title="Old", recorded_on="2026-02-20"); self.add(self.b1, self.t1, title="New", recorded_on="2026-03-02")
        self.assertEqual([x["title"] for x in self.lst(self.s1).get_json()], ["New", "Old"])

    def test_students_only_see_their_own_batch(self):
        self.add(self.b2, self.t2, title="Other batch")
        self.assertEqual(self.lst(self.s1).get_json(), [])               # s1 is in B1 only
        self.assertEqual(self.lst(self.s2).get_json(), [])               # s2 is in no batch
        self.assertEqual(self.lst(self.t1).get_json(), [])               # t1 does not teach B2
        self.assertEqual(len(self.lst(self.t2).get_json()), 1)
        self.assertEqual(self.lst(self.s1, f"?batch_id={self.b2}").get_json(), [])   # asking for another batch by id gives nothing

    def test_only_own_batches_and_not_students(self):
        self.assertEqual(self.add(self.b1, self.t2).status_code, 403)    # another teacher's batch
        self.assertEqual(self.add(self.b2, self.t1).status_code, 403)
        self.assertEqual(self.add(self.b1, self.s1).status_code, 403)    # student
        self.assertEqual(self.c.post(f"/api/batches/{self.b1}/recordings", json={}).status_code, 401)
        self.assertEqual(self.add(99999, self.a).status_code, 404)
        self.assertEqual(self.add(self.b2, self.a).status_code, 201)     # admin: any batch

    def test_validation(self):
        for kw in ({"title": ""}, {"title": "x" * 201}, {"recorded_on": ""}, {"recorded_on": "not-a-date"}, {"recorded_on": "2026-03-03"},   # future
                   {"url": ""}, {"url": "http://drive.google.com/file/d/abc/view"}, {"url": "https://evil.example/file/d/abc"},
                   {"url": "https://drive.google.com.evil.example/x"}, {"url": "javascript:alert(1)"}, {"url": "https://drive.google.com/a b"}, {"url": 5}):
            r = self.add(self.b1, self.t1, **kw); self.assertEqual(r.status_code, 400, (kw, r.get_json()))
        self.assertEqual(self.add(self.b1, self.t1, recorded_on="2026-03-02").status_code, 201)   # today is fine
        self.assertEqual(self.add(self.b1, self.t1, url="https://docs.google.com/document/d/abc/edit").status_code, 201)
        self.assertEqual(self.lst(self.a).get_json().__len__(), 2)

    def test_delete_own_batch_only(self):
        rid = self.add(self.b1, self.t1).get_json()["id"]
        d = lambda who, i=rid: self.c.delete(f"/api/recordings/{i}", headers=who).status_code
        self.assertEqual(d(self.t2), 403); self.assertEqual(d(self.s1), 403); self.assertEqual(self.c.delete(f"/api/recordings/{rid}").status_code, 401)
        self.assertEqual(len(self.lst(self.s1).get_json()), 1)
        self.assertEqual(d(self.t1), 200); self.assertEqual(self.lst(self.s1).get_json(), []); self.assertEqual(d(self.t1), 404)
        rid = self.add(self.b2, self.t2).get_json()["id"]; self.assertEqual(d(self.a, rid), 200)

    def test_permissions_add_recordings(self):
        try:
            t = self.setperms("t1", ["classroom"])                       # Add class recordings not ticked
            self.assertEqual(self.add(self.b1, t).status_code, 403)
            self.assertEqual(self.lst(t).status_code, 200)               # can still see them in Classroom
            t = self.setperms("t1", ["add_recordings"])                  # no Classroom
            self.assertEqual(self.add(self.b1, t).status_code, 403)
            t = self.setperms("t1", ["classroom", "add_recordings"])
            rid = self.add(self.b1, t).get_json()["id"]
            self.assertEqual(self.c.delete(f"/api/recordings/{rid}", headers=t).status_code, 200)
            self.assertEqual(self.c.get("/api/auth/me", headers=t).get_json()["user"]["permissions"], ["classroom", "add_recordings"])
        finally: self.reset("t1")

    def test_permissions_student_recordings_tab(self):
        self.add(self.b1, self.t1)
        me = self.c.get("/api/auth/me", headers=self.s1).get_json()["user"]; self.assertIn("recordings", me["tabs"])
        try:
            s = self.setperms("s1", ["assignments"])
            self.assertEqual(self.lst(s).status_code, 403)
            self.assertNotIn("recordings", self.c.get("/api/auth/me", headers=s).get_json()["user"]["tabs"])
            s = self.setperms("s1", ["recordings"]); self.assertEqual(len(self.lst(s).get_json()), 1)
        finally: self.reset("s1")

    def test_teacher_cannot_get_area_students_use_and_vice_versa(self):
        r = self.c.patch(f"/api/users/{self.ids['t1']}", json={"permissions": ["classroom", "recordings"]}, headers=self.a)
        self.assertEqual(r.status_code, 400)                              # 'recordings' is a student area
        r = self.c.patch(f"/api/users/{self.ids['s1']}", json={"permissions": ["add_recordings"]}, headers=self.a)
        self.assertEqual(r.status_code, 400)

    def test_only_full_admin_changes_the_permission_and_it_is_audited(self):
        r = self.c.patch(f"/api/users/{self.ids['t1']}", json={"permissions": ["classroom", "add_recordings"]}, headers=self.t1); self.assertEqual(r.status_code, 403)
        rid = self.add(self.b1, self.t1).get_json()["id"]; self.c.delete(f"/api/recordings/{rid}", headers=self.t1)
        con = sqlite3.connect(os.environ["DATABASE_PATH"])
        acts = [x[0] for x in con.execute("SELECT action FROM audit_log WHERE action IN ('add_recording','delete_recording')")]; con.close()
        self.assertIn("add_recording", acts); self.assertIn("delete_recording", acts)

    def test_migration_keeps_older_limits_working(self):
        """A limited admin with Classroom and a limited student with Materials gain the new area; other limits stay as they were."""
        import dbx
        con = sqlite3.connect(os.environ["DATABASE_PATH"])
        ids = {n: self.ids[n] for n in ("s1", "t1")}
        con.execute("UPDATE users SET permissions='materials,fees' WHERE id=?", (ids["s1"],))
        con.execute("UPDATE users SET permissions='classroom,class_links' WHERE id=?", (ids["t1"],))
        con.execute("DELETE FROM schema_meta"); con.commit(); con.close()
        from app import create_app
        create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})
        con = sqlite3.connect(os.environ["DATABASE_PATH"])
        p = lambda i: con.execute("SELECT permissions FROM users WHERE id=?", (i,)).fetchone()[0]
        self.assertEqual(p(ids["s1"]), "materials,fees,recordings")
        self.assertEqual(p(ids["t1"]), "classroom,class_links")           # limited teachers do not gain it
        con.close(); self.reset("s1"); self.reset("t1")


if __name__ == "__main__":
    unittest.main()
