"""v0.8.63: Notice board (posts, pictures, files, video links, comments, Seen by), everyone's own to-do list, and more notifications."""
import datetime as dt, io, os, sqlite3, sys, tempfile, unittest, warnings
warnings.simplefilter("ignore", ResourceWarning)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MVT = dt.timezone(dt.timedelta(hours=5)); PW = "Password123"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class V0863(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@v63.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2026, 11, 16, 15, 0, tzinfo=MVT)   # a Monday
        cls.H = cls.login("admin@v63.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, n, role="student", **k: P("/api/users", {"email": e, "password": PW, "full_name": n, "role": role, "phone": "7771234", "guardian_phone": "7771234", **k}).get_json()["id"]
        cls.t1, cls.t2 = mk("t1@v63.test", "Teacher One", "teacher"), mk("t2@v63.test", "Teacher Two", "teacher")
        cls.tl = mk("tl@v63.test", "Limited Teacher", "teacher", permissions=["classroom"])
        cls.s1, cls.s2 = mk("s1@v63.test", "Student One"), mk("s2@v63.test", "Student Two")
        cls.sql_("UPDATE users SET must_change_password=0")
        cls.T1, cls.T2, cls.TL, cls.S1, cls.S2 = (cls.login(f"{x}@v63.test", PW) for x in ("t1", "t2", "tl", "s1", "s2"))
        cls.co = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 500, "status": "open", "minutes_per_class": 60}).get_json()["id"]
        cls.b1 = P("/api/batches", {"course_id": cls.co, "code": "A1", "teacher_id": cls.t1, "capacity": 9, "days": "Mon", "start_time": "14:00"}).get_json()["id"]
        cls.b2 = P("/api/batches", {"course_id": cls.co, "code": "A2", "teacher_id": cls.t2, "capacity": 9, "days": "Tue", "start_time": "16:00"}).get_json()["id"]
        for s, b in ((cls.s1, cls.b1), (cls.s2, cls.b2)):
            r = P("/api/enrollments", {"student_id": s, "batch_id": b}); assert r.status_code == 201, r.get_json()

    @classmethod
    def login(cls, who, pw):
        r = cls.c.post("/api/auth/login", json={"login": who, "password": pw}).get_json()
        return {"Authorization": "Bearer " + r["token"]}

    @classmethod
    def sql_(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def J(self, m, p, h=None, **k): return getattr(self.c, m)(p, headers=h or self.H, **k)
    def post(self, h=None, **k):
        r = self.J("post", "/api/posts", h, json={"title": "Hello", **k}); return r
    def ids(self, h): return {p["id"] for p in self.J("get", "/api/posts", h).get_json()["items"]}
    def notes(self, uid, kind): return self.sql_("SELECT title, body, link FROM notifications WHERE user_id=? AND kind=? ORDER BY id", (uid, kind))

    def test_01_who_sees_what(self):
        ev = self.post(audience="everyone").get_json()["id"]
        st = self.post(audience="students").get_json()["id"]
        te = self.post(audience="teachers").get_json()["id"]
        b1 = self.post(audience="batch", batch_id=self.b1).get_json()["id"]
        s1, s2, t1, t2 = self.ids(self.S1), self.ids(self.S2), self.ids(self.T1), self.ids(self.T2)
        self.assertTrue({ev, st, b1} <= s1); self.assertNotIn(te, s1)
        self.assertTrue({ev, st} <= s2); self.assertFalse({te, b1} & s2)
        self.assertTrue({ev, te, b1} <= t1); self.assertNotIn(st, t1)
        self.assertIn(te, t2); self.assertNotIn(b1, t2)
        self.assertTrue({ev, st, te, b1} <= self.ids(self.H))
        # everyone it is for is told, with a link that opens the post
        self.assertTrue(any(a.startswith("New post from") and b == "Hello" and l == f"posts:{b1}" for a, b, l in self.notes(self.s1, "post")))
        self.assertTrue(any(l == f"posts:{b1}" for _, _, l in self.notes(self.t1, "post")))
        self.assertFalse(any(l == f"posts:{b1}" for _, _, l in self.notes(self.s2, "post")))
        self.assertFalse(any(l == f"posts:{te}" for _, _, l in self.notes(self.s1, "post")))
        # a post the reader may not see is 404 for its files and comments too
        self.assertEqual(self.J("get", f"/api/posts/{b1}/comments", self.S2).status_code, 404)

    def test_02_who_may_post(self):
        self.assertEqual(self.post(self.S1, audience="everyone").status_code, 403)                                   # students never post
        self.assertEqual(self.post(self.T1, audience="batch", batch_id=self.b1).status_code, 201)                    # own batch
        self.assertEqual(self.post(self.T1, audience="batch", batch_id=self.b2).status_code, 403)                    # someone else's batch
        self.assertEqual(self.post(self.T1, audience="everyone").status_code, 403)                                   # teachers post to batches only
        self.assertEqual(self.post(self.TL, audience="batch", batch_id=self.b1).status_code, 403)                    # no write_posts area
        self.assertEqual(self.post(audience="batch").status_code, 400)                                                # no batch chosen
        self.assertEqual(self.J("post", "/api/posts", json={"title": " "}).status_code, 400)
        j = self.J("get", "/api/posts", self.T1).get_json()
        self.assertTrue(j["can_post"]); self.assertEqual([b["id"] for b in j["batches"]], [self.b1])
        self.assertFalse(self.J("get", "/api/posts", self.S1).get_json()["can_post"])
        self.assertFalse(self.J("get", "/api/posts", self.TL).get_json()["can_post"])

    def test_03_read_and_seen_by(self):
        pid = self.post(title="Read me", audience="batch", batch_id=self.b1).get_json()["id"]
        u0 = self.J("get", "/api/posts", self.S1).get_json()["unread"]
        self.assertGreaterEqual(u0, 1)
        p = [x for x in self.J("get", "/api/posts", self.S1).get_json()["items"] if x["id"] == pid][0]
        self.assertFalse(p["read"]); self.assertNotIn("seen_n", p)                                                   # readers do not see counts
        seen = self.J("get", f"/api/posts/{pid}/seen").get_json()
        self.assertEqual(({x["id"] for x in seen["seen"]}, {x["id"] for x in seen["not_seen"]}), (set(), {self.s1, self.t1}))
        r = self.J("post", "/api/posts/read", self.S1, json={"ids": [pid]}).get_json()
        self.assertEqual((r["marked"], r["unread"]), (1, u0 - 1))
        self.assertEqual(self.J("post", "/api/posts/read", self.S1, json={"ids": [pid]}).get_json()["marked"], 0)   # twice is once
        self.assertEqual(self.J("post", "/api/posts/read", self.S2, json={"ids": [pid]}).get_json()["marked"], 0)   # not theirs: ignored
        seen = self.J("get", f"/api/posts/{pid}/seen").get_json()
        self.assertEqual([x["id"] for x in seen["seen"]], [self.s1]); self.assertEqual([x["id"] for x in seen["not_seen"]], [self.t1])
        p = [x for x in self.J("get", "/api/posts").get_json()["items"] if x["id"] == pid][0]
        self.assertEqual((p["seen_n"], p["audience_n"]), (1, 2))
        self.assertEqual(self.J("get", f"/api/posts/{pid}/seen", self.S1).status_code, 403)
        self.assertEqual(self.J("get", f"/api/posts/{pid}/seen", self.T1).status_code, 403)                           # not the author

    def test_04_comments(self):
        pid = self.post(title="Talk", audience="batch", batch_id=self.b1).get_json()["id"]
        r = self.J("post", f"/api/posts/{pid}/comments", self.S1, json={"body": "Thank you!"}); self.assertEqual(r.status_code, 201)
        cid = r.get_json()["id"]
        admin = self.sql_("SELECT id FROM users WHERE email='admin@v63.test'")[0][0]
        self.assertTrue(any(l == f"posts:{pid}" for _, _, l in self.notes(admin, "post_comment")))
        self.assertEqual(self.J("post", f"/api/posts/{pid}/comments", self.S2, json={"body": "x"}).status_code, 404)
        self.assertEqual(self.J("post", f"/api/posts/{pid}/comments", self.S1, json={"body": " "}).status_code, 400)
        c2 = self.J("post", f"/api/posts/{pid}/comments", self.T1, json={"body": "Welcome"}).get_json()["id"]
        self.assertEqual(self.J("delete", f"/api/posts/{pid}/comments/{c2}", self.S1).status_code, 403)               # someone else's
        cs = self.J("get", f"/api/posts/{pid}/comments", self.S1).get_json()
        self.assertEqual([(c["body"], c["can_delete"]) for c in cs], [("Thank you!", True), ("Welcome", False)])
        self.assertEqual(self.J("delete", f"/api/posts/{pid}/comments/{c2}").status_code, 200)                         # admin moderates
        self.assertEqual(self.J("delete", f"/api/posts/{pid}/comments/{cid}", self.S1).status_code, 200)               # own
        self.assertEqual(self.J("get", f"/api/posts/{pid}/comments", self.S1).get_json(), [])
        off = self.post(title="No talk", audience="students", allow_comments=False).get_json()["id"]
        self.assertEqual(self.J("post", f"/api/posts/{off}/comments", self.S1, json={"body": "hi"}).status_code, 403)

    def test_05_video_links(self):
        from posts import video_embed
        yt = "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"
        for u in ("https://youtu.be/dQw4w9WgXcQ", "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "https://youtube.com/shorts/dQw4w9WgXcQ", "https://m.youtube.com/watch?v=dQw4w9WgXcQ"):
            self.assertEqual(video_embed(u), (yt, None), u)
        self.assertEqual(video_embed("https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/view?usp=sharing")[0], "https://drive.google.com/file/d/1AbCdEfGhIjKlMnOp/preview")
        self.assertEqual(video_embed("https://vimeo.com/123456789")[0], "https://player.vimeo.com/video/123456789")
        self.assertEqual(video_embed("https://example.com/video"), (None, None))                                       # shown as a plain link
        self.assertIsNotNone(video_embed("http://youtu.be/dQw4w9WgXcQ")[1])
        self.assertIsNotNone(video_embed("https://www.youtube.com/watch?x=1")[1])
        self.assertEqual(self.post(audience="students", video_url="https://www.youtube.com/channel").status_code, 400)
        pid = self.post(audience="students", video_url="https://youtu.be/dQw4w9WgXcQ").get_json()["id"]
        p = [x for x in self.J("get", "/api/posts", self.S1).get_json()["items"] if x["id"] == pid][0]
        self.assertEqual(p["video_embed"], yt)

    def test_06_files_pin_edit_delete(self):
        pid = self.post(title="Photos", audience="batch", batch_id=self.b1).get_json()["id"]
        up = lambda data, name, h=None: self.J("post", f"/api/posts/{pid}/files", h, data={"file": (io.BytesIO(data), name)}, content_type="multipart/form-data")
        r = up(PNG, "trip.png"); self.assertEqual(r.status_code, 201); fimg = r.get_json()["id"]
        fpdf = up(PDF, "notes.pdf").get_json()["id"]
        self.assertEqual(up(b"not a png", "fake.png").status_code, 400)
        self.assertEqual(up(PNG, "x.png", self.S1).status_code, 403)
        self.assertEqual(up(PNG, "x.png", self.T2).status_code, 404)   # not their batch: the post does not exist for them
        r = self.J("get", f"/api/posts/{pid}/files/{fimg}", self.S1); self.assertEqual(r.status_code, 200)
        self.assertTrue(r.headers["Content-Disposition"].startswith("inline")); r.close()
        r = self.J("get", f"/api/posts/{pid}/files/{fpdf}", self.S1); self.assertTrue(r.headers["Content-Disposition"].startswith("attachment")); r.close()
        self.assertEqual(self.J("get", f"/api/posts/{pid}/files/{fimg}", self.S2).status_code, 404)
        for k in range(4): up(PNG, f"p{k}.png")
        self.assertEqual(up(PNG, "seventh.png").status_code, 400)
        p = [x for x in self.J("get", "/api/posts", self.S1).get_json()["items"] if x["id"] == pid][0]
        self.assertEqual([(f["name"], f["image"]) for f in p["files"]][:2], [("trip.png", True), ("notes.pdf", False)])
        # pin, edit, delete
        self.assertEqual(self.J("post", f"/api/posts/{pid}/pin", self.T1, json={"pinned": True}).status_code, 403)
        self.J("post", f"/api/posts/{pid}/pin", json={"pinned": True})
        j = self.J("get", "/api/posts", self.S1).get_json()
        self.assertIn(pid, [x["id"] for x in j["pinned"]]); self.assertNotIn(pid, [x["id"] for x in j["items"]])
        self.assertEqual(self.J("patch", f"/api/posts/{pid}", self.S1, json={"title": "x"}).status_code, 403)
        self.assertEqual(self.J("patch", f"/api/posts/{pid}", json={"title": "Trip photos"}).get_json()["changed"], True)
        self.assertEqual(self.sql_("SELECT title, audience, batch_id FROM posts WHERE id=?", (pid,))[0], ("Trip photos", "batch", self.b1))
        stored = [r[0] for r in self.sql_("SELECT file FROM post_files WHERE post_id=?", (pid,))]
        self.J("post", f"/api/posts/{pid}/comments", self.S1, json={"body": "nice"}); self.J("post", "/api/posts/read", self.S1, json={"ids": [pid]})
        self.assertEqual(self.J("delete", f"/api/posts/{pid}").status_code, 200)
        for t in ("posts", "post_files", "post_reads", "post_comments"):
            self.assertEqual(self.sql_(f"SELECT COUNT(*) FROM {t} WHERE {'id' if t == 'posts' else 'post_id'}=?", (pid,))[0][0], 0, t)
        self.assertEqual(len(stored), 6)
        self.assertTrue(self.sql_("SELECT 1 FROM audit_log WHERE action='post_delete' AND entity_id=?", (pid,)))

    def test_07_teacher_own_post_is_theirs_to_manage(self):
        pid = self.post(self.T1, title="Homework tip", audience="batch", batch_id=self.b1).get_json()["id"]
        self.assertEqual(self.J("post", f"/api/posts/{pid}/pin", self.T1, json={"pinned": True}).status_code, 200)
        seen = self.J("get", f"/api/posts/{pid}/seen", self.T1).get_json()
        self.assertEqual([x["id"] for x in seen["not_seen"]], [self.s1])                                                # not the author
        self.assertEqual(self.J("delete", f"/api/posts/{pid}", self.T2).status_code, 404)                              # not theirs to see
        ev = self.post(title="For all", audience="everyone").get_json()["id"]
        self.assertEqual(self.J("delete", f"/api/posts/{ev}", self.T2).status_code, 403)                               # seen, but not theirs
        self.assertEqual(self.J("delete", f"/api/posts/{pid}", self.T1).status_code, 200)

    def test_08_more_notifications(self):
        T = self.T1
        self.J("post", f"/api/batches/{self.b1}/materials", T, data={"title": "Lesson 3 notes", "url": "https://example.com/l3"}, content_type="multipart/form-data")
        self.assertIn(("New material", "Lesson 3 notes", "materials"), self.notes(self.s1, "material_new"))
        self.assertEqual(self.notes(self.s2, "material_new"), [])
        r = self.J("post", f"/api/batches/{self.b1}/recordings", T, json={"title": "Class 5", "url": "https://drive.google.com/file/d/abcdefghijk/view", "recorded_on": "2026-11-16"})
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual([n[2] for n in self.notes(self.s1, "recording_new")], ["recordings"])
        r = self.J("post", "/api/tutorials", T, data={"title": "Verbs practice", "text": "Try these", "course_id": str(self.co)}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201, r.get_json())
        self.assertEqual(len(self.notes(self.s1, "tutorial_new")), 1); self.assertEqual(len(self.notes(self.s2, "tutorial_new")), 1)   # same course
        # absent: told once, even when the class is saved again
        rec = {"date": "2026-11-16", "start_time": "14:00", "records": [{"student_id": self.s1, "status": "absent"}]}
        for _ in range(2): self.assertEqual(self.J("post", f"/api/batches/{self.b1}/attendance", T, json=rec).status_code, 200)
        self.assertEqual(len(self.notes(self.s1, "absent")), 1)
        self.J("post", f"/api/batches/{self.b1}/attendance", T, json={**rec, "records": [{"student_id": self.s1, "status": "present"}]})
        self.assertEqual(len(self.notes(self.s1, "absent")), 1)
        # the enrolment in setUpClass made an invoice: the student was told
        inv = self.notes(self.s1, "invoice_new")
        self.assertTrue(inv and inv[0][2].startswith("fees:") and "500 MVR" in inv[0][1], inv)

    def test_09_my_todo(self):
        T, S = self.T1, self.S1
        aid = self.J("post", f"/api/batches/{self.b1}/assignments", T, json={"title": "Essay", "kind": "assignment", "due_date": "2026-11-20", "max_points": 10}).get_json()["id"]
        j = self.J("get", "/api/my/todo", S).get_json()
        mine = [x for x in j["items"] if x["title"] == "Essay"]
        self.assertEqual([(x["key"], x["status"], x["n"]) for x in mine], [("td_hand_in_due", "todo", "2026-11-20")])
        self.assertIn("td_fee", [x["key"] for x in j["items"] if x["status"] == "todo"])
        self.assertTrue(j["todo"] >= 2)
        self.assertEqual(j["items"][0]["status"], "todo")                                                              # to-do first, done last
        r = self.J("post", f"/api/assignments/{aid}/submit", S, data={"text": "My essay"}, content_type="multipart/form-data"); self.assertEqual(r.status_code, 201, r.get_json())
        mine = [x for x in self.J("get", "/api/my/todo", S).get_json()["items"] if x["title"] == "Essay"]
        self.assertEqual([(x["key"], x["status"]) for x in mine], [("td_handed_in", "done")])
        t = self.J("get", "/api/my/todo", T).get_json()["items"]
        self.assertIn(("td_grade", "todo", "Essay", 1), [(x["key"], x["status"], x["title"], x["n"]) for x in t])
        self.assertTrue(any(x["key"] in ("td_take_attendance", "td_attendance_taken") for x in t))                     # Monday 14:00 class, now 15:00
        self.J("post", f"/api/assignments/{aid}/grades", T, json={"student_id": self.s1, "grade": 8})
        mine = [x for x in self.J("get", "/api/my/todo", S).get_json()["items"] if x["title"] == "Essay"]
        self.assertEqual([(x["key"], x["status"], x["n"]) for x in mine], [("td_graded", "done", "8 / 10")])
        # the Notice board line
        self.post(title="Fresh news", audience="students")
        keys = {x["key"]: x for x in self.J("get", "/api/my/todo", S).get_json()["items"]}
        self.assertEqual(keys["td_posts"]["status"], "todo")
        ids = [p["id"] for p in self.J("get", "/api/posts", S).get_json()["items"]]
        self.J("post", "/api/posts/read", S, json={"ids": ids})
        keys = {x["key"]: x for x in self.J("get", "/api/my/todo", S).get_json()["items"]}
        self.assertEqual(keys["td_posts_read"]["status"], "done")
        a = self.J("get", "/api/my/todo").get_json()["items"]
        self.assertTrue(all(x["status"] in ("todo", "done") for x in a))

    def test_10_removing_people_keeps_posts(self):
        sid = self.J("post", "/api/users", json={"email": "s9@v63.test", "password": PW, "full_name": "Leaver", "role": "student", "phone": "7771234", "guardian_phone": "7771234"}).get_json()["id"]
        tid = self.J("post", "/api/users", json={"email": "t9@v63.test", "password": PW, "full_name": "Leaving Teacher", "role": "teacher", "phone": "7771234"}).get_json()["id"]
        self.sql_("UPDATE users SET must_change_password=0")
        self.J("post", "/api/enrollments", json={"student_id": sid, "batch_id": self.b1})
        S9 = self.login("s9@v63.test", PW)
        pid = self.post(title="Stay", audience="students").get_json()["id"]
        self.J("post", f"/api/posts/{pid}/comments", S9, json={"body": "bye"}); self.J("post", "/api/posts/read", S9, json={"ids": [pid]})
        bt = self.J("post", "/api/batches", json={"course_id": self.co, "code": "A9", "teacher_id": tid, "capacity": 5}).get_json()["id"]
        tp = self.post(self.login("t9@v63.test", PW), title="Teacher news", audience="batch", batch_id=bt).get_json()["id"]
        for uid in (sid, tid):
            r = self.J("delete", f"/api/users/{uid}", json={"password": "AdminPass123"}); self.assertEqual(r.status_code, 200, r.get_json())
        self.assertEqual(self.sql_("SELECT COUNT(*) FROM post_comments WHERE user_id=?", (sid,))[0][0], 0)
        admin = self.sql_("SELECT id FROM users WHERE email='admin@v63.test'")[0][0]
        self.assertEqual(self.sql_("SELECT author_id FROM posts WHERE id=?", (tp,))[0][0], admin)                     # moved to the admin, like tutorials
        self.assertEqual(self.J("delete", f"/api/batches/{bt}").status_code, 409)                                       # a batch with posts is closed, not deleted


if __name__ == "__main__":
    unittest.main()
