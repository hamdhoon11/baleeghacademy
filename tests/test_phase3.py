import io, json, os, sys, tempfile, unittest, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MVT = dt.timezone(dt.timedelta(hours=5))
PDF = b"%PDF-1.4 test file"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20
PW = "Password123"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class P3(unittest.TestCase):
    """Each test builds its own course, teacher, batch and students (world()), so tests do not depend on each other."""

    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ["DATABASE_PATH"] = os.path.join(tmp, "t.db")
        os.environ["ADMIN_EMAIL"] = "admin@t.test"; os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        from app import create_app
        cls.clock = [dt.datetime(2026, 3, 2, 15, 50, tzinfo=MVT)]  # Monday
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"], "NOW": lambda: cls.clock[0]})
        cls.n = 0

    def setUp(self):
        self.c = self.app.test_client()
        self.at("2026-03-02 15:50")

    def at(self, s):
        P3.clock[0] = dt.datetime.fromisoformat(s).replace(tzinfo=MVT)

    # ----- helpers -----
    def login(self, email, pw=PW):
        r = self.c.post("/api/auth/login", json={"email": email, "password": pw})
        self.assertEqual(r.status_code, 200, r.get_data(as_text=True))
        return {"Authorization": "Bearer " + r.get_json()["token"]}

    def admin(self): return self.login("admin@t.test", "AdminPass123")

    def world(self, students=2, days="Mon,Wed,Fri"):
        P3.n += 1; k = P3.n; a = self.admin()
        cid = self.c.post("/api/courses", json={"name": f"Course{k}", "status": "open", "minutes_per_class": 60}, headers=a).get_json()["id"]
        tid = self.c.post("/api/users", json={"email": f"teach{k}@p3.test", "password": PW, "full_name": f"Teacher {k}", "role": "teacher"}, headers=a).get_json()["id"]
        bid = self.c.post("/api/batches", json={"course_id": cid, "code": "B1", "days": days, "start_time": "16:00", "teacher_id": tid,
                                                 "meet_link": "https://meet.google.com/aaa-bbbb-ccc", "capacity": 20}, headers=a).get_json()["id"]
        w = {"a": a, "cid": cid, "tid": tid, "bid": bid, "t_email": f"teach{k}@p3.test", "stu": [], "s_email": []}
        w["t"] = self.login(w["t_email"])
        for i in range(students):
            email = f"stu{k}_{i}@p3.test"
            sid = self.c.post("/api/users", json={"email": email, "password": PW, "full_name": f"Student {k}-{i}", "role": "student"}, headers=a).get_json()["id"]
            self.c.post("/api/enrollments", json={"student_id": sid, "batch_id": bid}, headers=a)
            w["stu"].append(sid); w["s_email"].append(email)
        return w

    def mark(self, w, date, statuses, hdr=None):
        recs = [{"student_id": sid, "status": st} for sid, st in zip(w["stu"], statuses)]
        return self.c.post(f"/api/batches/{w['bid']}/attendance", json={"date": date, "records": recs}, headers=hdr or w["t"])

    def submit(self, aid, hdr, text=None, file=None):
        d = {}
        if text: d["text"] = text
        if file: d["file"] = file
        return self.c.post(f"/api/assignments/{aid}/submit", data=d, headers=hdr, content_type="multipart/form-data")

    def mk_assign(self, w, **over):
        d = {"title": "Homework 1", "description": "Do it", "due_date": "2026-03-03", "max_points": 100}
        d.update(over)
        r = self.c.post(f"/api/batches/{w['bid']}/assignments", json=d, headers=w["t"])
        self.assertEqual(r.status_code, 201, r.get_data(as_text=True))
        return r.get_json()["id"]

    # ----- batch setup validation -----
    def test_01_batch_days_time_link_validation(self):
        w = self.world(0)
        p = lambda **j: self.c.patch(f"/api/batches/{w['bid']}", json=j, headers=w["a"])
        self.assertEqual(p(days="Funday").status_code, 400)
        self.assertEqual(p(start_time="25:00").status_code, 400)
        self.assertEqual(p(meet_link="http://insecure.example").status_code, 400)
        self.assertEqual(p(days="wed, mon,Mon").status_code, 200)
        b = [x for x in self.c.get("/api/batches", headers=w["a"]).get_json() if x["id"] == w["bid"]][0]
        self.assertEqual(b["days"], "Mon,Wed")  # normalised, ordered, de-duplicated

    # ----- timetable and Join class -----
    def test_02_next_class_and_join_window(self):
        w = self.world(1); s = self.login(w["s_email"][0])
        home = lambda: self.c.get("/api/my/home", headers=s).get_json()
        self.at("2026-03-02 15:50")  # Monday, class at 16:00
        n = home()["next_class"]
        self.assertEqual((n["date"], n["start_time"], n["end_time"]), ("2026-03-02", "16:00", "17:00"))
        self.assertTrue(n["can_join"]); self.assertEqual(n["meet_link"], "https://meet.google.com/aaa-bbbb-ccc")
        self.at("2026-03-02 15:30"); self.assertFalse(home()["next_class"]["can_join"])  # more than 15 min early
        self.at("2026-03-02 16:30"); n = home()["next_class"]; self.assertTrue(n["can_join"] and n["live"])  # in progress
        self.at("2026-03-02 17:05"); self.assertEqual(home()["next_class"]["date"], "2026-03-04")  # Wednesday next

    def test_03_cancel_and_extra_class(self):
        w = self.world(1); s = self.login(w["s_email"][0])
        self.at("2026-03-02 17:05")
        r = self.c.post(f"/api/batches/{w['bid']}/sessions", json={"date": "2026-03-04", "status": "cancelled"}, headers=w["t"])
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.c.get("/api/my/home", headers=s).get_json()["next_class"]["date"], "2026-03-06")  # Wed skipped -> Fri
        tl = self.c.get("/api/timetable?from=2026-03-02&to=2026-03-08", headers=s).get_json()
        self.assertEqual([o["status"] for o in tl if o["date"] == "2026-03-04"], ["cancelled"])
        self.c.post(f"/api/batches/{w['bid']}/sessions", json={"date": "2026-03-05", "start_time": "20:00", "topic": "Extra revision"}, headers=w["t"])
        tl = self.c.get("/api/timetable?from=2026-03-05&to=2026-03-05", headers=s).get_json()
        self.assertEqual([(o["start_time"], o["extra"], o["topic"]) for o in tl], [("20:00", True, "Extra revision")])
        self.assertEqual(self.c.post(f"/api/batches/{w['bid']}/sessions", json={"date": "2026-03-09"}, headers=s).status_code, 403)

    def test_04_timetable_only_shows_my_batches_and_warns_when_no_days(self):
        w1, w2 = self.world(1), self.world(1, days="")
        s1 = self.login(w1["s_email"][0])
        ids = {o["batch_id"] for o in self.c.get("/api/timetable", headers=s1).get_json()}
        self.assertEqual(ids, {w1["bid"]})
        s2 = self.login(w2["s_email"][0])
        h = self.c.get("/api/my/home", headers=s2).get_json()
        self.assertIsNone(h["next_class"]); self.assertEqual(h["batches_without_schedule"][0]["id"], w2["bid"])

    # ----- attendance -----
    def test_05_mark_attendance_and_rules(self):
        w = self.world(2)
        self.at("2026-03-02 18:00")
        self.assertEqual(self.mark(w, "2026-03-02", ["present", "late"]).status_code, 200)
        self.assertEqual(self.mark(w, "2026-03-09", ["present", "present"]).status_code, 400)  # future class
        self.assertEqual(self.mark(w, "2026-03-02", ["present", "sleeping"]).status_code, 400)  # bad status
        other = self.world(1)
        r = self.c.post(f"/api/batches/{w['bid']}/attendance", json={"date": "2026-03-02", "records": [{"student_id": other["stu"][0], "status": "present"}]}, headers=w["t"])
        self.assertEqual(r.status_code, 400)  # student from another batch
        self.assertEqual(self.mark(w, "2026-03-02", ["present", "present"], other["t"]).status_code, 403)  # another teacher
        self.assertEqual(self.mark(w, "2026-03-02", ["present", "present"], self.login(w["s_email"][0])).status_code, 403)  # a student
        self.mark(w, "2026-03-02", ["absent", "late"])  # re-marking updates, no duplicates
        roster = self.c.get(f"/api/batches/{w['bid']}/attendance?date=2026-03-02", headers=w["t"]).get_json()
        self.assertEqual([s["status"] for s in roster["students"]], ["absent", "late"])
        self.assertEqual(self.c.post(f"/api/batches/{w['bid']}/sessions", json={"date": "2026-03-02", "status": "cancelled"}, headers=w["t"]).status_code, 409)

    def test_06_percentages_low_flag_and_student_view(self):
        w = self.world(2)
        self.at("2026-03-06 18:00")
        self.mark(w, "2026-03-02", ["present", "absent"]); self.mark(w, "2026-03-04", ["late", "absent"]); self.mark(w, "2026-03-06", ["excused", "absent"])
        sm = self.c.get(f"/api/batches/{w['bid']}/attendance/summary", headers=w["t"]).get_json()
        a, b = sm["students"]
        self.assertEqual((a["pct"], a["counted"], a["excused"], a["low"]), (100.0, 2, 1, False))  # excused is not counted against the student
        self.assertEqual((b["pct"], b["low"]), (0.0, True))  # 3 counted classes, 0% < 75%
        mine = self.c.get("/api/my/attendance", headers=self.login(w["s_email"][1])).get_json()
        self.assertEqual((mine[0]["pct"], mine[0]["low"], len(mine[0]["recent"])), (0.0, True, 3))
        h = self.c.get("/api/my/home", headers=w["t"]).get_json()
        self.assertEqual([x["student_id"] for x in h["low_attendance"]], [w["stu"][1]])

    def test_07_low_flag_threshold_setting(self):
        w = self.world(1); self.at("2026-03-06 18:00")
        self.mark(w, "2026-03-02", ["present"]); self.mark(w, "2026-03-04", ["present"]); self.mark(w, "2026-03-06", ["absent"])  # 66.7%
        low = lambda: self.c.get(f"/api/batches/{w['bid']}/attendance/summary", headers=w["t"]).get_json()["students"][0]["low"]
        self.assertTrue(low())
        self.c.put("/api/settings", json={"low_attendance_pct": "50"}, headers=w["a"])
        self.assertFalse(low())
        self.c.put("/api/settings", json={"low_attendance_pct": "75"}, headers=w["a"])

    # ----- assignments and grades -----
    def test_08_submit_late_resubmit_and_grade(self):
        w = self.world(2); s0, s1 = self.login(w["s_email"][0]), self.login(w["s_email"][1])
        aid = self.mk_assign(w)
        self.assertEqual(self.submit(aid, s0).status_code, 400)  # nothing attached
        r = self.submit(aid, s0, text="my answer"); self.assertEqual((r.status_code, r.get_json()["is_late"]), (201, False))
        self.at("2026-03-05 10:00")
        r = self.submit(aid, s0, text="better answer", file=(io.BytesIO(PDF), "work.pdf")); self.assertEqual(r.get_json()["is_late"], True)
        subs = self.c.get(f"/api/assignments/{aid}/submissions", headers=w["t"]).get_json()["students"]
        self.assertEqual(len(subs), 2)
        row = [x for x in subs if x["student_id"] == w["stu"][0]][0]
        self.assertEqual((row["text_answer"], row["has_file"], row["is_late"]), ("better answer", True, True))
        self.assertFalse([x for x in subs if x["student_id"] == w["stu"][1]][0]["submitted"])
        g = lambda **j: self.c.post(f"/api/assignments/{aid}/grades", json={"student_id": w["stu"][0], **j}, headers=w["t"])
        self.assertEqual(g(grade=101).status_code, 400); self.assertEqual(g(grade="abc").status_code, 400); self.assertEqual(g(grade=-1).status_code, 400)
        self.assertEqual(g(grade=85, feedback="Well done").status_code, 200)
        self.assertEqual(self.submit(aid, s0, text="change after grading").status_code, 409)
        my = [x for x in self.c.get("/api/assignments", headers=s0).get_json() if x["id"] == aid][0]["my"]
        self.assertEqual((my["grade"], my["feedback"], my["submitted"]), (85, "Well done", True))
        other = [x for x in self.c.get("/api/assignments", headers=s1).get_json() if x["id"] == aid][0]["my"]
        self.assertEqual((other["grade"], other["submitted"], other["text_answer"]), (None, False, None))  # sees nothing of student 0

    def test_09_submission_validation_and_enrolment(self):
        w, x = self.world(1), self.world(1)
        s = self.login(w["s_email"][0]); aid = self.mk_assign(w)
        self.assertEqual(self.submit(aid, s, file=(io.BytesIO(b"MZ\x90 exe"), "evil.exe")).status_code, 400)
        self.assertEqual(self.submit(aid, s, file=(io.BytesIO(b"not really a pdf"), "a.pdf")).status_code, 400)
        self.assertEqual(self.submit(aid, s, file=(io.BytesIO(PDF + b"0" * 21_000_000), "big.pdf")).status_code, 400)
        self.assertEqual(self.submit(aid, self.login(x["s_email"][0]), text="sneaky").status_code, 403)  # not in this batch
        self.assertEqual(self.submit(aid, w["t"], text="teacher").status_code, 403)  # only students submit
        self.assertEqual(self.submit(aid, s, file=(io.BytesIO(PNG), "p.png")).status_code, 201)

    def test_10_submission_file_access(self):
        w, x = self.world(2), self.world(1)
        s0, s1 = self.login(w["s_email"][0]), self.login(w["s_email"][1]); aid = self.mk_assign(w)
        self.submit(aid, s0, file=(io.BytesIO(PDF), "mine.pdf"))
        sid = [r for r in self.c.get(f"/api/assignments/{aid}/submissions", headers=w["t"]).get_json()["students"] if r["has_file"]][0]["submission_id"]
        url = f"/api/submissions/{sid}/file"
        for hdr, code in ((s0, 200), (w["t"], 200), (w["a"], 200), (s1, 403), (x["t"], 403), (self.login(x["s_email"][0]), 403), ({}, 401)):
            self.assertEqual(self.c.get(url, headers=hdr).status_code, code, hdr)
        r = self.c.get(url, headers=s0)
        self.assertEqual(r.data[:4], b"%PDF"); self.assertIn("attachment", r.headers["Content-Disposition"])

    def test_11_test_marks_and_progress_average(self):
        w = self.world(1); s = self.login(w["s_email"][0])
        a1 = self.mk_assign(w, max_points=100)
        t1 = self.mk_assign(w, title="Quiz", kind="test", max_points=50, due_date=None)
        self.assertEqual(self.submit(t1, s, text="x").status_code, 400)  # tests have no submission
        self.c.post(f"/api/assignments/{a1}/grades", json={"student_id": w["stu"][0], "grade": 85}, headers=w["t"])
        self.c.post(f"/api/assignments/{t1}/grades", json={"student_id": w["stu"][0], "grade": 40, "feedback": "Revise unit 2"}, headers=w["t"])
        g = self.c.get("/api/my/grades", headers=s).get_json()[0]
        self.assertEqual(g["avg_pct"], 83.3)  # (85+40)/(100+50)
        self.assertEqual({i["title"]: i["grade"] for i in g["items"]}, {"Homework 1": 85, "Quiz": 40})
        gb = self.c.get(f"/api/batches/{w['bid']}/gradebook", headers=w["t"]).get_json()
        self.assertEqual((gb[0]["avg_pct"], gb[0]["graded_items"]), (83.3, 2))
        self.assertEqual(self.c.post(f"/api/assignments/{t1}/grades", json={"student_id": w["stu"][0], "grade": 51}, headers=w["t"]).status_code, 400)
        self.assertEqual(self.c.patch(f"/api/assignments/{t1}", json={"max_points": 30}, headers=w["t"]).status_code, 409)  # would orphan the grade of 40

    def test_12_assignment_edit_delete_and_todo(self):
        w = self.world(1); s = self.login(w["s_email"][0]); aid = self.mk_assign(w)
        self.assertEqual([t["id"] for t in self.c.get("/api/my/home", headers=s).get_json()["todo"]], [aid])
        self.submit(aid, s, text="done")
        self.assertEqual(self.c.get("/api/my/home", headers=s).get_json()["todo"], [])
        self.assertEqual(self.c.get("/api/my/home", headers=w["t"]).get_json()["to_grade"], 1)
        self.assertEqual(self.c.patch(f"/api/assignments/{aid}", json={"title": "Renamed"}, headers=w["t"]).status_code, 200)
        self.assertEqual(self.c.delete(f"/api/assignments/{aid}", headers=s).status_code, 403)
        self.assertEqual(self.c.delete(f"/api/assignments/{aid}", headers=w["t"]).status_code, 200)
        self.assertEqual(self.c.get("/api/assignments", headers=s).get_json(), [])

    # ----- materials -----
    def test_13_materials(self):
        w, x = self.world(1), self.world(1)
        s, xs = self.login(w["s_email"][0]), self.login(x["s_email"][0])
        add = lambda hdr, bid=None, **d: self.c.post(f"/api/batches/{bid or w['bid']}/materials", data=d, headers=hdr, content_type="multipart/form-data")
        r = add(w["t"], title="Lesson 1", file=(io.BytesIO(PDF), "lesson1.pdf")); self.assertEqual(r.status_code, 201); mid = r.get_json()["id"]
        self.assertEqual(add(w["t"], title="Video", url="https://www.youtube.com/watch?v=abc").status_code, 201)
        self.assertEqual(add(w["t"], title="Both", url="https://x.example", file=(io.BytesIO(PDF), "a.pdf")).status_code, 400)
        self.assertEqual(add(w["t"], title="Neither").status_code, 400)
        self.assertEqual(add(w["t"], title="Bad link", url="ftp://x.example/file").status_code, 400)
        self.assertEqual(add(w["t"], title="Exe", file=(io.BytesIO(b"MZ\x90"), "setup.exe")).status_code, 400)
        self.assertEqual(add(w["t"], title="Fake", file=(io.BytesIO(b"hello"), "x.pdf")).status_code, 400)
        self.assertEqual(add(s, title="Student upload", file=(io.BytesIO(PDF), "a.pdf")).status_code, 403)
        self.assertEqual(add(x["t"], bid=w["bid"], title="Intruder", file=(io.BytesIO(PDF), "a.pdf")).status_code, 403)
        self.assertEqual(sorted(m["title"] for m in self.c.get("/api/materials", headers=s).get_json()), ["Lesson 1", "Video"])
        self.assertTrue(all(m["batch_id"] == x["bid"] for m in self.c.get("/api/materials", headers=xs).get_json()))
        dl = f"/api/materials/{mid}/file"
        for hdr, code in ((s, 200), (w["t"], 200), (w["a"], 200), (xs, 403), (x["t"], 403), ({}, 401)):
            self.assertEqual(self.c.get(dl, headers=hdr).status_code, code, hdr)
        self.assertEqual(self.c.delete(f"/api/materials/{mid}", headers=s).status_code, 403)
        self.assertEqual(self.c.delete(f"/api/materials/{mid}", headers=x["t"]).status_code, 403)
        self.assertEqual(self.c.delete(f"/api/materials/{mid}", headers=w["a"]).status_code, 200)
        self.assertEqual(self.c.get(dl, headers=w["a"]).status_code, 404)

    # ----- role isolation -----
    def test_14_teacher_cannot_touch_another_teachers_batch(self):
        w, x = self.world(1), self.world(1)
        aid = self.mk_assign(w)
        t = x["t"]; b = w["bid"]
        checks = [("get", f"/api/batches/{b}/attendance"), ("get", f"/api/batches/{b}/attendance/summary"), ("get", f"/api/batches/{b}/gradebook"),
                  ("get", f"/api/assignments/{aid}/submissions"), ("delete", f"/api/assignments/{aid}")]
        for m, u in checks: self.assertEqual(getattr(self.c, m)(u, headers=t).status_code, 403, u)
        self.assertEqual(self.c.post(f"/api/batches/{b}/assignments", json={"title": "x"}, headers=t).status_code, 403)
        self.assertEqual(self.c.post(f"/api/assignments/{aid}/grades", json={"student_id": w["stu"][0], "grade": 1}, headers=t).status_code, 403)
        self.assertNotIn(aid, [a["id"] for a in self.c.get("/api/assignments", headers=t).get_json()])
        self.assertNotIn(b, {o["batch_id"] for o in self.c.get("/api/timetable", headers=t).get_json()})

    def test_15_student_cannot_see_other_students_or_teacher_tools(self):
        w = self.world(2); aid = self.mk_assign(w)
        s0, s1 = self.login(w["s_email"][0]), self.login(w["s_email"][1])
        self.submit(aid, s1, text="private answer")
        self.c.post(f"/api/assignments/{aid}/grades", json={"student_id": w["stu"][1], "grade": 77, "feedback": "secret feedback"}, headers=w["t"])
        for m, u in (("get", f"/api/batches/{w['bid']}/attendance"), ("get", f"/api/batches/{w['bid']}/gradebook"), ("get", f"/api/assignments/{aid}/submissions")):
            self.assertEqual(getattr(self.c, m)(u, headers=s0).status_code, 403, u)
        blob = json.dumps([self.c.get(u, headers=s0).get_json() for u in ("/api/assignments", "/api/my/grades", "/api/my/attendance", "/api/my/home")])
        self.assertNotIn("private answer", blob); self.assertNotIn("secret feedback", blob); self.assertNotIn(w["s_email"][1], blob)
        self.assertEqual(self.c.get("/api/my/attendance", headers=w["t"]).status_code, 403)  # student-only endpoint
        self.assertEqual(self.c.get("/api/my/home", headers=w["a"]).status_code, 403)  # admin uses the dashboard instead

    def test_16_dropped_student_loses_access(self):
        w = self.world(1); s = self.login(w["s_email"][0]); aid = self.mk_assign(w)
        self.c.post(f"/api/batches/{w['bid']}/materials", data={"title": "M", "url": "https://x.example"}, headers=w["t"], content_type="multipart/form-data")
        eid = self.c.get("/api/enrollments", headers=w["a"]).get_json()
        eid = [e for e in eid if e["student_id"] == w["stu"][0]][0]["id"]
        self.c.patch(f"/api/enrollments/{eid}", json={"status": "dropped"}, headers=w["a"])
        self.assertEqual(self.submit(aid, s, text="late").status_code, 403)
        self.assertEqual(self.c.get("/api/materials", headers=s).get_json(), [])
        self.assertEqual(self.c.get("/api/assignments", headers=s).get_json(), [])
        self.assertEqual(self.c.get("/api/my/home", headers=s).get_json()["next_class"], None)
        self.assertEqual(self.mark(w, "2026-03-02", ["present"]).status_code, 400)  # no longer on the active roster

    def test_17_admin_sees_everything(self):
        w = self.world(1); a = w["a"]; self.mk_assign(w)
        self.assertEqual(self.c.get(f"/api/batches/{w['bid']}/attendance", headers=a).status_code, 200)
        self.assertTrue(any(x["batch_id"] == w["bid"] for x in self.c.get("/api/assignments", headers=a).get_json()))
        self.assertTrue(any(o["batch_id"] == w["bid"] for o in self.c.get("/api/timetable", headers=a).get_json()))
        acts = {r["action"] for r in self.c.get("/api/audit", headers=a).get_json()}
        self.assertIn("create_assignment", acts)

    # ----- English / Dhivehi -----
    def test_18_language_files(self):
        en = json.load(open(os.path.join(ROOT, "static/i18n/en.json"), encoding="utf-8"))
        dv = json.load(open(os.path.join(ROOT, "static/i18n/dv.json"), encoding="utf-8"))
        self.assertEqual([k for k in dv if k not in en and not k.startswith("_")], [], "dv.json has keys that en.json lacks")
        need = ["home", "classroom", "attendance", "assignments", "progress", "materials", "schedule", "gradebook", "present", "late", "absent", "excused",
                "next_class", "join", "save_attendance", "submit", "grade", "feedback", "due_date"] + [f"day_{d}" for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]
        self.assertEqual([k for k in need if k not in en], [])
        for k in [f"day_{d}" for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")] + ["attendance", "assignments", "present", "absent"]:
            self.assertTrue(any("\u0780" <= ch <= "\u07bf" for ch in dv.get(k, "")), f"{k} needs a Dhivehi (Thaana) translation")
        self.assertEqual(self.c.get("/i18n/dv.json").status_code, 200)
        page = self.c.get("/").get_data(as_text=True)
        self.assertIn('dir = l === "dv" ? "rtl" : "ltr"', page); self.assertIn("learning.js", page)
        self.assertEqual(self.c.get("/learning.js").status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
