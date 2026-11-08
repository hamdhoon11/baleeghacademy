"""Session 15: a teacher works in one selected batch; unassigned batches are 403; one function decides which batches a teacher may use."""
import io, os, sys, tempfile, unittest
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"
PDF = b"%PDF-1.4\n%t\n"


class S15(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ.update(DATABASE_PATH=os.path.join(tmp, "t.db"), ADMIN_EMAIL="admin@s15.test", ADMIN_PASSWORD="AdminPass123")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"]})
        cls.c = cls.app.test_client()
        cls.H = cls.tok("admin@s15.test", "AdminPass123")
        cls.n = 0
        cls.ta, cls.tam = cls.make("teacher", "Teacher A")
        cls.tb, cls.tbm = cls.make("teacher", "Teacher B")
        cls.tz, cls.tzm = cls.make("teacher", "Teacher Without Batches")
        cid = cls.c.post("/api/courses", json={"name": "Arabic Level 1", "monthly_fee_mvr": 100, "status": "open"}, headers=cls.H).get_json()["id"]
        cid2 = cls.c.post("/api/courses", json={"name": "Grade 8 Mathematics", "kind": "tuition", "monthly_fee_mvr": 100, "status": "open"}, headers=cls.H).get_json()["id"]
        mk = lambda c, code, t: cls.c.post("/api/batches", json={"course_id": c, "code": code, "teacher_id": t, "capacity": 5, "days": "Mon,Wed", "start_time": "16:00"}, headers=cls.H).get_json()["id"]
        cls.a1, cls.a2, cls.b1 = mk(cid, "A1", cls.ta), mk(cid2, "A2", cls.ta), mk(cid, "B1", cls.tb)
        cls.nobody = cls.c.post("/api/batches", json={"course_id": cid, "code": "NOBODY", "capacity": 5}, headers=cls.H).get_json()["id"]   # no teacher
        cls.asg = {}
        for b in (cls.a1, cls.a2, cls.b1):
            cls.asg[b] = cls.c.post(f"/api/batches/{b}/assignments", data={"title": f"HW{b}", "file": (io.BytesIO(PDF), "h.pdf")}, headers=cls.H, content_type="multipart/form-data").get_json()["id"]
        cls.TA, cls.TB, cls.TZ = cls.tok(cls.tam, PW), cls.tok(cls.tbm, PW), cls.tok(cls.tzm, PW)

    @classmethod
    def tok(cls, login, pw):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": login, "password": pw}).get_json()["token"]}

    @classmethod
    def make(cls, role, name):
        cls.n += 1; email = f"p{cls.n}@s15.test"
        r = cls.c.post("/api/users", json={"email": email, "password": PW, "full_name": name, "role": role}, headers=cls.H)
        return r.get_json()["id"], email

    def get(self, path, H): return self.c.get(path, headers=H)

    def test_01_picker_lists_only_own_batches(self):
        self.assertEqual([b["id"] for b in self.get("/api/my/batches", self.TA).get_json()], [self.a1, self.a2])
        self.assertEqual([b["id"] for b in self.get("/api/my/batches", self.TB).get_json()], [self.b1])
        self.assertEqual(self.get("/api/my/batches", self.TZ).get_json(), [])
        self.assertEqual([b["id"] for b in self.get("/api/batches", self.TA).get_json()], [self.a1, self.a2])
        self.assertEqual(self.c.get("/api/my/batches").status_code, 401)
        self.assertEqual(self.get("/api/my/batches", self.H).status_code, 403)       # admins pick any batch in the Classroom, not here

    def test_02_selected_batch_limits_every_read(self):
        for b in (self.a1, self.a2):
            self.assertEqual([x["id"] for x in self.get(f"/api/assignments?batch_id={b}", self.TA).get_json()], [self.asg[b]])
            home = self.get(f"/api/my/home?batch_id={b}", self.TA); self.assertEqual(home.status_code, 200)
            self.assertTrue(all(o["batch_id"] == b for o in home.get_json()["week"]))
            self.assertTrue(all(o["batch_id"] == b for o in self.get(f"/api/timetable?batch_id={b}", self.TA).get_json()))
            self.assertEqual(self.get(f"/api/materials?batch_id={b}", self.TA).status_code, 200)
            self.assertEqual(self.get(f"/api/recordings?batch_id={b}", self.TA).status_code, 200)
        self.assertEqual(len(self.get("/api/assignments", self.TA).get_json()), 2)    # no selection: all of their own, never B's

    def test_03_unassigned_batch_is_403_everywhere(self):
        for other in (self.b1, self.nobody, 999999):
            for path in ("assignments", "materials", "recordings", "timetable", "my/home"):
                r = self.get(f"/api/{path}?batch_id={other}", self.TA)
                self.assertEqual(r.status_code, 403, (path, other)); self.assertIn("error", r.get_json())
        self.assertEqual(self.get(f"/api/assignments?batch_id={self.a1}", self.TZ).status_code, 403)     # a teacher with no batches owns none
        for path in (f"/api/batches/{self.b1}/attendance", f"/api/batches/{self.b1}/gradebook", f"/api/batches/{self.b1}/attendance/summary",
                     f"/api/assignments/{self.asg[self.b1]}/submissions"):
            self.assertEqual(self.get(path, self.TA).status_code, 403, path)
        self.assertEqual(self.c.post(f"/api/batches/{self.b1}/assignments", json={"title": "x"}, headers=self.TA).status_code, 403)
        self.assertEqual(self.get(f"/api/assignments/{self.asg[self.b1]}/attachment", self.TA).status_code, 403)
        self.assertEqual(self.c.post(f"/api/assignments/{self.asg[self.b1]}/grades", json={"student_id": 1, "grade": 1}, headers=self.TA).status_code, 403)
        self.assertEqual(self.get("/api/batches", self.TZ).get_json(), [])

    def test_04_one_function_decides(self):
        def fn(uid):
            with self.app.app_context(): return self.app.extensions["teacher_batches"](uid)
        self.assertEqual(fn(self.ta), {self.a1, self.a2}); self.assertEqual(fn(self.tz), set())
        # moving a batch to another teacher changes access at once, in lists and in direct routes (all through the one function)
        self.c.patch(f"/api/batches/{self.a2}", json={"teacher_id": self.tb}, headers=self.H)
        self.assertEqual(fn(self.ta), {self.a1}); self.assertEqual(fn(self.tb), {self.a2, self.b1})
        self.assertEqual(self.get(f"/api/assignments?batch_id={self.a2}", self.TA).status_code, 403)
        self.assertEqual(self.get(f"/api/batches/{self.a2}/attendance", self.TA).status_code, 403)
        self.assertEqual(self.get(f"/api/assignments/{self.asg[self.a2]}/attachment", self.TA).status_code, 403)
        self.assertEqual(self.get(f"/api/assignments?batch_id={self.a2}", self.TB).status_code, 200)
        self.assertEqual([b["id"] for b in self.get("/api/my/batches", self.TA).get_json()], [self.a1])
        self.c.patch(f"/api/batches/{self.a2}", json={"teacher_id": self.ta}, headers=self.H)       # put it back for the other tests

    def test_05_admin_and_student_unchanged(self):
        self.assertEqual(len(self.get(f"/api/assignments?batch_id={self.b1}", self.H).get_json()), 1)
        self.assertTrue({self.a1, self.a2, self.b1, self.nobody} <= {b["id"] for b in self.get("/api/batches", self.H).get_json()})
        sid, sm = self.make("student", "Kid"); self.c.post("/api/enrollments", json={"student_id": sid, "batch_id": self.a1}, headers=self.H)
        S = self.tok(sm, PW)
        self.assertEqual([b["id"] for b in self.get("/api/my/batches", S).get_json()], [self.a1])
        self.assertEqual(self.get(f"/api/assignments?batch_id={self.b1}", S).status_code, 403)


if __name__ == "__main__":
    unittest.main()
