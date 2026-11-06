"""Session 7: teacher information. Admins with the 'teacher_information' area find a teacher and see profile, batches taught, students and workload.
Read-only. Students, teachers and other admins without the area never reach it."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MVT = dt.timezone(dt.timedelta(hours=5)); PW = "Password123"


class Session7(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ["DATABASE_PATH"] = os.path.join(tmp, "t.db")
        os.environ["ADMIN_EMAIL"] = "admin@s7.test"; os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        cls.clock = [dt.datetime(2026, 3, 9, 12, 0, tzinfo=MVT)]   # Monday
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"], "NOW": lambda: cls.clock[0]})
        c = cls.c = cls.app.test_client()
        cls.a = cls.login("admin@s7.test", "AdminPass123")
        c1 = c.post("/api/courses", json={"name": "Arabic", "status": "open", "minutes_per_class": 60}, headers=cls.a).get_json()["id"]
        c2 = c.post("/api/courses", json={"name": "Quran", "status": "open", "minutes_per_class": 90}, headers=cls.a).get_json()["id"]
        mk = lambda e, r, n=None: c.post("/api/users", json={"email": e + "@s7.test", "password": PW, "full_name": n or e.upper(), "role": r}, headers=cls.a).get_json()["id"]
        cls.ids = {"t1": mk("t1", "teacher", "Zainab Teacher"), "t2": mk("t2", "teacher", "Adam Idle"), "s1": mk("s1", "student", "Aisha Ali"), "s2": mk("s2", "student", "Bilal Hassan"),
                   "s3": mk("s3", "student", "Cara Dee"), "ad2": mk("ad2", "admin")}
        c.patch(f"/api/users/{cls.ids['t1']}", json={"phone": "7779999", "bio": "Ten years teaching"}, headers=cls.a)
        bt = lambda cid, code, days, t, tid, **k: c.post("/api/batches", json={"course_id": cid, "code": code, "days": days, "start_time": t, "teacher_id": tid, "capacity": 10, **k}, headers=cls.a).get_json()["id"]
        cls.b1 = bt(c1, "B1", "Mon,Wed", "10:00", cls.ids["t1"]); cls.b2 = bt(c2, "B2", "Tue", "10:00", cls.ids["t1"]); cls.b3 = bt(c1, "B3", "Fri", "10:00", cls.ids["t1"])
        for s, b in (("s1", cls.b1), ("s2", cls.b1), ("s1", cls.b2), ("s3", cls.b3)):
            r = c.post("/api/enrollments", json={"student_id": cls.ids[s], "batch_id": b}, headers=cls.a); assert r.status_code in (200, 201), r.get_json()
        r = c.patch(f"/api/batches/{cls.b3}", json={"status": "closed"}, headers=cls.a); assert r.status_code == 200, r.get_json()
        cls.t1, cls.t2, cls.s1 = (cls.login(f"{n}@s7.test") for n in ("t1", "t2", "s1"))
        r = c.post(f"/api/batches/{cls.b1}/attendance", json={"date": "2026-03-09", "records": [{"student_id": cls.ids["s1"], "status": "present"}, {"student_id": cls.ids["s2"], "status": "present"}]}, headers=cls.t1); assert r.status_code == 200, r.get_json()
        cls.aid = c.post(f"/api/batches/{cls.b1}/assignments", json={"title": "HW1", "max_points": 20}, headers=cls.t1).get_json()["id"]
        r = c.post(f"/api/assignments/{cls.aid}/submit", data={"text": "my answer"}, headers=cls.s1); assert r.status_code in (200, 201), r.get_json()
        cls.ad = cls.login("ad2@s7.test")

    @classmethod
    def login(cls, email, pw=PW):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"email": email, "password": pw}).get_json()["token"]}

    def setperms(self, name, areas):
        r = self.c.patch(f"/api/users/{self.ids[name]}", json={"permissions": areas}, headers=self.a); self.assertEqual(r.status_code, 200, r.get_json())
        return self.login(f"{name}@s7.test")
    def reset(self, name): self.c.patch(f"/api/users/{self.ids[name]}", json={"permissions": "all"}, headers=self.a)
    def lst(self, who, q=""): return self.c.get("/api/teacher-information" + q, headers=who)
    def get(self, who, k): return self.c.get(f"/api/teacher-information/{self.ids.get(k, k)}", headers=who)

    def test_full_page_for_one_teacher(self):
        r = self.get(self.a, "t1"); self.assertEqual(r.status_code, 200, r.get_json()); d = r.get_json()
        p = d["profile"]; self.assertEqual((p["full_name"], p["phone"], p["bio"]), ("Zainab Teacher", "7779999", "Ten years teaching")); self.assertNotIn("password_hash", p)
        self.assertEqual([b["code"] for b in d["batches"]], ["B1", "B2", "B3"])          # closed batches are listed too
        self.assertEqual({b["code"]: b["students"] for b in d["batches"]}, {"B1": 2, "B2": 1, "B3": 1})
        self.assertEqual([s["full_name"] for s in d["students"]], ["Aisha Ali", "Bilal Hassan"])   # distinct, closed batch's student not counted
        self.assertEqual(sorted(d["students"][0]["batches"]), ["Arabic · B1", "Quran · B2"])
        w = d["workload"]
        self.assertEqual((w["active_batches"], w["students"], w["weekly_classes"], w["weekly_hours"]), (2, 2, 3, 3.5))   # Mon+Wed 60 min, Tue 90 min; closed B3 ignored
        self.assertEqual((w["classes_held_30d"], w["to_grade"]), (1, 1))

    def test_to_grade_goes_down_after_grading(self):
        self.c.post(f"/api/assignments/{self.aid}/grades", json={"student_id": self.ids["s1"], "grade": 10}, headers=self.t1)
        try: self.assertEqual(self.get(self.a, "t1").get_json()["workload"]["to_grade"], 0)
        finally:
            con = sqlite3.connect(os.environ["DATABASE_PATH"]); con.execute("UPDATE submissions SET grade=NULL,graded_by=NULL,graded_at=NULL"); con.commit(); con.close()

    def test_teacher_without_batches(self):
        d = self.get(self.a, "t2").get_json()
        self.assertEqual((d["batches"], d["students"], d["workload"]["weekly_hours"], d["workload"]["active_batches"]), ([], [], 0, 0))

    def test_old_classes_not_in_30_day_count(self):
        self.clock[0] = dt.datetime(2026, 5, 20, 12, 0, tzinfo=MVT)
        try: self.assertEqual(self.get(self.a, "t1").get_json()["workload"]["classes_held_30d"], 0)
        finally: self.clock[0] = dt.datetime(2026, 3, 9, 12, 0, tzinfo=MVT)

    def test_list_search_filter_limit_and_summary(self):
        names = lambda r: [x["full_name"] for x in r.get_json()["teachers"] if x["full_name"] != "Demo Teacher"]
        self.assertEqual(names(self.lst(self.a)), ["Adam Idle", "Zainab Teacher"])          # teachers only, sorted
        self.assertEqual(names(self.lst(self.a, "?q=zain")), ["Zainab Teacher"])
        self.assertEqual(names(self.lst(self.a, "?q=T2@S7")), ["Adam Idle"])
        self.assertEqual(names(self.lst(self.a, "?q=777999")), ["Zainab Teacher"])
        self.assertEqual(names(self.lst(self.a, "?q=%25")), ["Adam Idle", "Zainab Teacher"])
        r = self.lst(self.a, "?limit=1").get_json(); self.assertEqual((len(r["teachers"]), r["total"]), (1, 3))   # 2 test teachers + the seeded demo teacher
        z = [x for x in self.lst(self.a).get_json()["teachers"] if x["full_name"] == "Zainab Teacher"][0]
        self.assertEqual((z["batch_count"], z["student_count"], z["weekly_hours"]), (2, 2, 3.5))

    def test_inactive_filter(self):
        self.c.patch(f"/api/users/{self.ids['t2']}", json={"is_active": False}, headers=self.a)
        try: self.assertEqual([x["full_name"] for x in self.lst(self.a, "?status=inactive").get_json()["teachers"]], ["Adam Idle"])
        finally: self.c.patch(f"/api/users/{self.ids['t2']}", json={"is_active": True}, headers=self.a)

    def test_only_admins_with_the_area(self):
        for who in (self.t1, self.t2, self.s1): self.assertEqual(self.lst(who).status_code, 403); self.assertEqual(self.get(who, "t1").status_code, 403)   # a teacher cannot read their own page either
        self.assertEqual(self.c.get("/api/teacher-information").status_code, 401)
        self.assertEqual(self.c.get(f"/api/teacher-information/{self.ids['t1']}").status_code, 401)
        try:
            ad = self.setperms("ad2", ["people", "batches", "student_information"]); self.assertEqual(self.lst(ad).status_code, 403); self.assertEqual(self.get(ad, "t1").status_code, 403)
            ad = self.setperms("ad2", ["teacher_information"]); self.assertEqual(self.lst(ad).status_code, 200); self.assertEqual(self.get(ad, "t1").status_code, 200)
            self.assertEqual(self.c.get("/api/student-information", headers=ad).status_code, 403)   # the two areas are separate
        finally: self.reset("ad2")

    def test_not_a_teacher_or_missing_is_404(self):
        for k in ("s1", "ad2", 99999): self.assertEqual(self.get(self.a, k).status_code, 404)

    def test_tab_and_area_visibility(self):
        me = lambda who: self.c.get("/api/auth/me", headers=who).get_json()["user"]
        self.assertIn("teacher_information", me(self.a)["tabs"])
        try:
            self.assertNotIn("teacher_information", me(self.setperms("ad2", ["student_information"]))["tabs"])
            self.assertIn("teacher_information", me(self.setperms("ad2", ["teacher_information"]))["tabs"])
        finally: self.reset("ad2")
        self.assertNotIn("teacher_information", me(self.t1)["tabs"]); self.assertNotIn("teacher_information", me(self.s1)["tabs"])
        r = self.c.patch(f"/api/users/{self.ids['t1']}", json={"permissions": ["classroom", "teacher_information"]}, headers=self.a); self.assertEqual(r.status_code, 400)   # admin-only area

    def test_nothing_is_changed_by_looking(self):
        con = sqlite3.connect(os.environ["DATABASE_PATH"]); tabs = ("users", "batches", "enrollments", "sessions", "submissions", "audit_log")
        n = lambda t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]; before = [n(t) for t in tabs]
        self.lst(self.a); self.get(self.a, "t1"); self.get(self.a, "t2")
        self.assertEqual(before, [n(t) for t in tabs]); con.close()


if __name__ == "__main__":
    unittest.main()
