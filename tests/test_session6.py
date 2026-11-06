"""Session 6: student information. Admins with the 'student_information' area find a student and see profile, batches, attendance, grades
and fees together. Read-only. Fees show only to an admin who also has 'fees'. Teachers and students never reach it."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MVT = dt.timezone(dt.timedelta(hours=5)); PW = "Password123"


class Session6(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ["DATABASE_PATH"] = os.path.join(tmp, "t.db")
        os.environ["ADMIN_EMAIL"] = "admin@s6.test"; os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        cls.clock = [dt.datetime(2026, 3, 9, 12, 0, tzinfo=MVT)]   # Monday
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"], "NOW": lambda: cls.clock[0]})
        c = cls.c = cls.app.test_client()
        cls.a = cls.login("admin@s6.test", "AdminPass123")
        cid = c.post("/api/courses", json={"name": "Arabic", "status": "open", "minutes_per_class": 60, "monthly_fee_mvr": 500}, headers=cls.a).get_json()["id"]
        mk = lambda e, r, n=None: c.post("/api/users", json={"email": e + "@s6.test", "password": PW, "full_name": n or e.upper(), "role": r}, headers=cls.a).get_json()["id"]
        cls.ids = {"t1": mk("t1", "teacher"), "s1": mk("s1", "student", "Aisha Ali"), "s2": mk("s2", "student", "Bilal Hassan"), "s3": mk("s3", "student", "Cara Dee"),
                   "ad2": mk("ad2", "admin")}
        cls.b1 = c.post("/api/batches", json={"course_id": cid, "code": "B1", "days": "Mon", "start_time": "10:00", "teacher_id": cls.ids["t1"], "capacity": 10}, headers=cls.a).get_json()["id"]
        cls.b2 = c.post("/api/batches", json={"course_id": cid, "code": "B2", "days": "Tue", "start_time": "10:00", "teacher_id": cls.ids["t1"], "capacity": 10}, headers=cls.a).get_json()["id"]
        for s, b in (("s1", cls.b1), ("s2", cls.b1), ("s1", cls.b2)):
            r = c.post("/api/enrollments", json={"student_id": cls.ids[s], "batch_id": b}, headers=cls.a); assert r.status_code in (200, 201), r.get_json()
        c.patch(f"/api/users/{cls.ids['s1']}", json={"phone": "7771234", "island": "Male", "guardian_name": "Mr Ali"}, headers=cls.a)
        cls.t1, cls.s1, cls.s2 = (cls.login(f"{n}@s6.test") for n in ("t1", "s1", "s2"))
        # one held class with attendance, one graded assignment
        cls.clock[0] = dt.datetime(2026, 3, 9, 12, 0, tzinfo=MVT)
        r = c.post(f"/api/batches/{cls.b1}/attendance", json={"date": "2026-03-09", "records": [{"student_id": cls.ids["s1"], "status": "present"}, {"student_id": cls.ids["s2"], "status": "absent"}]}, headers=cls.t1); assert r.status_code == 200, r.get_json()
        aid = c.post(f"/api/batches/{cls.b1}/assignments", json={"title": "HW1", "max_points": 20}, headers=cls.t1).get_json()["id"]
        c.post(f"/api/assignments/{aid}/grades", json={"student_id": cls.ids["s1"], "grade": 15, "feedback": "Good"}, headers=cls.t1)
        cls.ad = cls.login("ad2@s6.test")

    @classmethod
    def login(cls, email, pw=PW):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"email": email, "password": pw}).get_json()["token"]}

    def setperms(self, name, areas):
        r = self.c.patch(f"/api/users/{self.ids[name]}", json={"permissions": areas}, headers=self.a); self.assertEqual(r.status_code, 200, r.get_json())
        return self.login(f"{name}@s6.test")
    def reset(self, name): self.c.patch(f"/api/users/{self.ids[name]}", json={"permissions": "all"}, headers=self.a)
    def lst(self, who, q=""): return self.c.get("/api/student-information" + q, headers=who)
    def get(self, who, sid): return self.c.get(f"/api/student-information/{self.ids.get(sid, sid)}", headers=who)

    def test_full_admin_sees_everything_for_one_student(self):
        r = self.get(self.a, "s1"); self.assertEqual(r.status_code, 200, r.get_json()); d = r.get_json()
        p = d["profile"]; self.assertEqual((p["full_name"], p["phone"], p["island"], p["guardian_name"]), ("Aisha Ali", "7771234", "Male", "Mr Ali"))
        self.assertNotIn("password_hash", p)
        self.assertEqual(sorted(e["code"] for e in d["enrollments"]), ["B1", "B2"])
        b1 = [x for x in d["progress"] if x["batch_code"] == "B1"][0]
        self.assertEqual((b1["attendance"]["present"], b1["attendance"]["pct"]), (1, 100.0)); self.assertEqual(b1["recent"][0]["status"], "present")
        self.assertEqual(b1["avg_pct"], 75.0); self.assertEqual([i["grade"] for i in b1["items"]], [15])
        self.assertTrue(d["fees_visible"]); self.assertIn("invoices", d["fees"]); self.assertGreaterEqual(len(d["fees"]["invoices"]), 1)
        self.assertEqual(d["fees"]["balance_due"], sum(i["balance"] for i in d["fees"]["invoices"]))

    def test_other_students_data_does_not_leak_into_a_student(self):
        d = self.get(self.a, "s2").get_json()
        self.assertEqual([e["code"] for e in d["enrollments"]], ["B1"])
        b1 = d["progress"][0]; self.assertEqual((b1["attendance"]["absent"], b1["avg_pct"]), (1, None))
        self.assertEqual(b1["items"][0]["grade"], None)

    def test_student_without_batches(self):
        d = self.get(self.a, "s3").get_json(); self.assertEqual((d["enrollments"], d["progress"], d["fees"]["invoices"]), ([], [], []))

    def test_list_search_filter_and_limit(self):
        names = lambda r: [s["full_name"] for s in r.get_json()["students"] if s["full_name"] != "Demo Student"]
        self.assertEqual(names(self.lst(self.a)), ["Aisha Ali", "Bilal Hassan", "Cara Dee"])   # students only, sorted
        self.assertEqual(names(self.lst(self.a, "?q=bil")), ["Bilal Hassan"])
        self.assertEqual(names(self.lst(self.a, "?q=S3@S6")), ["Cara Dee"])                    # email, any case
        self.assertEqual(names(self.lst(self.a, "?q=777123")), ["Aisha Ali"])                  # phone
        self.assertEqual(names(self.lst(self.a, f"?batch_id={self.b2}")), ["Aisha Ali"])
        self.assertEqual(names(self.lst(self.a, "?q=%25")), ["Aisha Ali", "Bilal Hassan", "Cara Dee"])   # % is not a wildcard
        r = self.lst(self.a, "?limit=2").get_json(); self.assertEqual((len(r["students"]), r["total"]), (2, 4))   # 3 test students + the seeded demo student
        s1 = [s for s in self.lst(self.a).get_json()["students"] if s["full_name"] == "Aisha Ali"][0]
        self.assertEqual(sorted(s1["batches"]), ["Arabic · B1", "Arabic · B2"]); self.assertGreater(s1["balance_due"], 0)

    def test_inactive_filter(self):
        self.c.patch(f"/api/users/{self.ids['s3']}", json={"is_active": False}, headers=self.a)
        try:
            self.assertEqual([s["full_name"] for s in self.lst(self.a, "?status=inactive").get_json()["students"]], ["Cara Dee"])
            self.assertNotIn("Cara Dee", [s["full_name"] for s in self.lst(self.a, "?status=active").get_json()["students"]])
        finally: self.c.patch(f"/api/users/{self.ids['s3']}", json={"is_active": True}, headers=self.a)

    def test_only_admins_with_the_area(self):
        for who in (self.t1, self.s1, self.s2): self.assertEqual(self.lst(who).status_code, 403); self.assertEqual(self.get(who, "s1").status_code, 403)
        self.assertEqual(self.c.get("/api/student-information").status_code, 401)
        self.assertEqual(self.c.get(f"/api/student-information/{self.ids['s1']}").status_code, 401)
        try:
            ad = self.setperms("ad2", ["people", "classroom", "fees"]); self.assertEqual(self.lst(ad).status_code, 403); self.assertEqual(self.get(ad, "s1").status_code, 403)
            ad = self.setperms("ad2", ["student_information"]); self.assertEqual(self.lst(ad).status_code, 200); self.assertEqual(self.get(ad, "s1").status_code, 200)
        finally: self.reset("ad2")

    def test_fees_hidden_without_fees_area(self):
        try:
            ad = self.setperms("ad2", ["student_information"])
            d = self.get(ad, "s1").get_json(); self.assertEqual((d["fees"], d["fees_visible"]), (None, False)); self.assertIn("progress", d)
            self.assertNotIn("invoices", str(d["fees"]))
            r = self.lst(ad).get_json(); self.assertFalse(r["fees_visible"]); self.assertTrue(all(s["balance_due"] is None for s in r["students"]))
            ad = self.setperms("ad2", ["student_information", "fees"]); self.assertTrue(self.get(ad, "s1").get_json()["fees_visible"])
        finally: self.reset("ad2")

    def test_not_a_student_or_missing_is_404(self):
        self.assertEqual(self.get(self.a, "t1").status_code, 404); self.assertEqual(self.get(self.a, "ad2").status_code, 404); self.assertEqual(self.get(self.a, 99999).status_code, 404)

    def test_tab_and_area_visibility(self):
        me = lambda who: self.c.get("/api/auth/me", headers=who).get_json()["user"]
        self.assertIn("student_information", me(self.a)["tabs"])
        try:
            self.assertNotIn("student_information", me(self.setperms("ad2", ["people"]))["tabs"])
            self.assertIn("student_information", me(self.setperms("ad2", ["student_information"]))["tabs"])
        finally: self.reset("ad2")
        self.assertNotIn("student_information", me(self.t1)["tabs"]); self.assertNotIn("student_information", me(self.s1)["tabs"])
        r = self.c.patch(f"/api/users/{self.ids['t1']}", json={"permissions": ["classroom", "student_information"]}, headers=self.a); self.assertEqual(r.status_code, 400)   # admin-only area

    def test_nothing_is_changed_by_looking(self):
        con = sqlite3.connect(os.environ["DATABASE_PATH"]); n = lambda t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        before = [n(t) for t in ("users", "enrollments", "invoices", "payments", "attendance", "submissions")]
        self.lst(self.a); self.get(self.a, "s1"); self.get(self.a, "s2")
        self.assertEqual(before, [n(t) for t in ("users", "enrollments", "invoices", "payments", "attendance", "submissions")]); con.close()


if __name__ == "__main__":
    unittest.main()
