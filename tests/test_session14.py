"""Session 14: a student with several active enrolments works in one selected batch; any other batch_id is 403."""
import io, os, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
PDF = b"%PDF-1.4\n%t\n"


class S14(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ.update(DATABASE_PATH=os.path.join(tmp, "t.db"), ADMIN_EMAIL="admin@s14.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})
        cls.c = cls.app.test_client()
        cls.H = cls.tok("admin@s14.test", "AdminPass123")
        cls.n = 0
        cls.t1, cls.t1m = cls.make("teacher", "Teacher 14")
        cls.names = ["Arabic Level 1", "Grade 8 Mathematics", "Quran Recitation"]
        cls.courses, cls.batches = [], []
        for i, nm in enumerate(cls.names):
            cid = cls.c.post("/api/courses", json={"name": nm, "kind": "tuition" if i == 1 else "course", "monthly_fee_mvr": 100, "status": "open"}, headers=cls.H).get_json()["id"]
            bid = cls.c.post("/api/batches", json={"course_id": cid, "code": f"B{i}", "teacher_id": cls.t1, "capacity": 5, "days": "Mon,Wed", "start_time": "16:00"}, headers=cls.H).get_json()["id"]
            cls.courses.append(cid); cls.batches.append(bid)
        cls.sid, cls.sm = cls.make("student", "Three Courses")
        for b in cls.batches: cls.c.post("/api/enrollments", json={"student_id": cls.sid, "batch_id": b}, headers=cls.H)
        cls.S = cls.tok(cls.sm, PW)
        cls.items = {}
        for i, b in enumerate(cls.batches):   # one assignment, one material, one tutorial per batch's course
            a = cls.c.post(f"/api/batches/{b}/assignments", json={"title": f"HW{i}"}, headers=cls.H).get_json()["id"]
            m = cls.c.post(f"/api/batches/{b}/materials", data={"title": f"Mat{i}", "file": (io.BytesIO(PDF), "m.pdf")}, headers=cls.H, content_type="multipart/form-data").get_json()["id"]
            t = cls.c.post("/api/tutorials", json={"title": f"Tut{i}", "text": "x", "course_id": cls.courses[i]}, headers=cls.H).get_json()["id"]
            cls.items[b] = (a, m, t)
        cls.other = cls.c.post("/api/batches", json={"course_id": cls.courses[0], "code": "OTHER", "capacity": 5}, headers=cls.H).get_json()["id"]   # student is NOT in this one

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def make(cls, role, name):
        cls.n += 1; email = f"p{cls.n}@s14.test"
        r = cls.c.post("/api/users", json={"email": email, "password": PW, "full_name": name, "role": role}, headers=cls.H)
        return r.get_json()["id"], email

    def get(self, path, H=None): return self.c.get(path, headers=H or self.S)

    def test_01_picker_list_has_only_active_enrolments(self):
        r = self.get("/api/my/batches"); self.assertEqual(r.status_code, 200)
        self.assertEqual([b["id"] for b in r.get_json()], self.batches)
        self.assertEqual(r.get_json()[1]["course_name"], "Grade 8 Mathematics")
        # a student with one enrolment gets one entry (the page then skips the picker); one with none gets an empty list
        s1, m1 = self.make("student", "Single"); self.c.post("/api/enrollments", json={"student_id": s1, "batch_id": self.batches[0]}, headers=self.H)
        self.assertEqual(len(self.get("/api/my/batches", self.tok(m1, PW)).get_json()), 1)
        s0, m0 = self.make("student", "None"); self.assertEqual(self.get("/api/my/batches", self.tok(m0, PW)).get_json(), [])
        self.assertEqual(self.c.get("/api/my/batches").status_code, 401)
        self.assertEqual(self.get("/api/my/batches", self.H).status_code, 403)    # staff have their own selector (Session 15)

    def test_02_every_tab_shows_only_the_selected_batch(self):
        for i, b in enumerate(self.batches):
            a, m, t = self.items[b]
            self.assertEqual([x["id"] for x in self.get(f"/api/assignments?batch_id={b}").get_json()], [a])
            self.assertEqual([x["id"] for x in self.get(f"/api/materials?batch_id={b}").get_json()], [m])
            self.assertEqual([x["batch_id"] for x in self.get(f"/api/my/grades?batch_id={b}").get_json()], [b])
            self.assertEqual([x["batch_id"] for x in self.get(f"/api/my/attendance?batch_id={b}").get_json()], [b])
            home = self.get(f"/api/my/home?batch_id={b}").get_json()
            self.assertEqual([x["batch_id"] for x in home["courses"]], [b])
            self.assertTrue(all(o["batch_id"] == b for o in home["week"]))
            self.assertEqual([x["id"] for x in home["todo"]], [a])
            self.assertTrue(all(o["batch_id"] == b for o in self.get(f"/api/timetable?batch_id={b}").get_json()))
            tut = [x["id"] for x in self.get(f"/api/tutorials?batch_id={b}").get_json()]
            self.assertEqual(tut, [self.items[b][2]])                                   # this course's tutorial only
        self.assertEqual(len(self.get("/api/assignments").get_json()), 3)               # without a selection (old callers) everything still shows

    def test_03_another_batch_id_is_403_on_every_route(self):
        for path in ("assignments", "materials", "recordings", "timetable", "my/grades", "my/attendance", "my/home", "tutorials"):
            r = self.get(f"/api/{path}?batch_id={self.other}")
            self.assertEqual(r.status_code, 403, path); self.assertIn("error", r.get_json())
            self.assertEqual(self.get(f"/api/{path}?batch_id=999999").status_code, 403, path)   # a batch that does not exist leaks nothing either
        a, m, t = self.items[self.batches[0]]
        oa = self.c.post(f"/api/batches/{self.other}/assignments", data={"title": "Not mine", "file": (io.BytesIO(PDF), "x.pdf")}, headers=self.H, content_type="multipart/form-data").get_json()["id"]
        self.assertEqual(self.get(f"/api/assignments/{oa}/attachment").status_code, 403)
        self.assertEqual(self.c.post(f"/api/assignments/{oa}/submit", data={"text": "x"}, headers=self.S, content_type="multipart/form-data").status_code, 403)

    def test_04_waitlisted_and_dropped_batches_are_not_choices(self):
        sid, em = self.make("student", "Dropper")
        full = self.c.post("/api/batches", json={"course_id": self.courses[0], "code": "FULL", "capacity": 1}, headers=self.H).get_json()["id"]
        self.c.post("/api/enrollments", json={"student_id": self.sid, "batch_id": full}, headers=self.H)         # takes the only seat
        H = self.tok(em, PW)
        r = self.c.post("/api/enrollments", json={"student_id": sid, "batch_id": full}, headers=self.H); self.assertEqual(r.get_json()["status"], "waitlist")
        self.assertEqual(self.get("/api/my/batches", H).get_json(), [])
        self.assertEqual(self.get(f"/api/assignments?batch_id={full}", H).status_code, 403)
        # drop the three-course student from one batch: it leaves the list and its batch_id becomes 403
        eid = [e["id"] for e in self.c.get("/api/enrollments", headers=self.H).get_json() if e["student_id"] == self.sid and e["batch_id"] == full][0]
        self.c.patch(f"/api/enrollments/{eid}", json={"status": "dropped"}, headers=self.H)
        self.assertNotIn(full, [b["id"] for b in self.get("/api/my/batches").get_json()])
        self.assertEqual(self.get(f"/api/my/home?batch_id={full}").status_code, 403)

    def test_05_staff_calls_are_unchanged(self):
        T = self.tok(self.t1m, PW)
        self.assertEqual(self.get("/api/my/home", T).status_code, 200)
        self.assertEqual(len(self.get(f"/api/assignments?batch_id={self.batches[0]}", T).get_json()), 1)
        self.assertEqual(self.get(f"/api/assignments?batch_id={self.other}", T).status_code, 403)   # Session 15: a batch that is not theirs is refused (it was an empty list)
        self.assertEqual(len(self.get(f"/api/assignments?batch_id={self.other}").get_json()), 1)  # admin


if __name__ == "__main__":
    unittest.main()
