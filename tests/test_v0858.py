"""v0.8.58: batch end time, and the Teachers' room (staff chat, teachers' guide, head teacher)."""
import datetime as dt, io, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MVT = dt.timezone(dt.timedelta(hours=5)); PW = "Password123"
PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class V0858(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@v58.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2026, 11, 16, 15, 0, tzinfo=MVT)   # a Monday
        cls.H = cls.login("admin@v58.test", "AdminPass123")
        P = lambda p, j: cls.c.post(p, json=j, headers=cls.H)
        mk = lambda e, n, role="student", **k: P("/api/users", {"email": e, "password": PW, "full_name": n, "role": role, "phone": "7771234", **k}).get_json()["id"]
        cls.t1, cls.t2, cls.t3 = mk("t1@v58.test", "Head Teacher", "teacher"), mk("t2@v58.test", "Teacher Two", "teacher"), mk("t3@v58.test", "Teacher Three", "teacher")
        cls.tlim = mk("t4@v58.test", "Limited Teacher", "teacher", permissions=["classroom"])
        cls.s1 = mk("s1@v58.test", "Student", "student")
        cls.T1, cls.T2, cls.T3, cls.TL, cls.S1 = (cls.login(f"{x}@v58.test", PW) for x in ("t1", "t2", "t3", "t4", "s1"))
        cls.co = P("/api/courses", {"name": "Arabic", "monthly_fee_mvr": 500, "status": "open", "minutes_per_class": 60}).get_json()["id"]

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

    # ---------- batch end time ----------
    def test_01_end_time_saved_and_used(self):
        r = self.J("post", "/api/batches", json={"course_id": self.co, "code": "E1", "teacher_id": self.t2, "capacity": 9, "days": "Mon,Wed", "start_time": "16:00", "end_time": "17:30"})
        self.assertEqual(r.status_code, 201, r.get_json()); bid = r.get_json()["id"]
        self.assertEqual(self.sql_("SELECT start_time, end_time FROM batches WHERE id=?", (bid,))[0], ("16:00", "17:30"))
        b = [x for x in self.J("get", "/api/batches").get_json() if x["id"] == bid][0]
        self.assertEqual(b["end_time"], "17:30")
        tl = [o for o in self.J("get", f"/api/timetable?from=2026-11-16&to=2026-11-22&batch_id=0").get_json() if o["batch_id"] == bid]
        self.assertEqual([(o["date"], o["start_time"], o["end_time"], o["minutes"]) for o in tl],
                         [("2026-11-16", "16:00", "17:30", 90), ("2026-11-18", "16:00", "17:30", 90)])
        # change the end time; clearing it falls back to the course's 60 minutes
        self.assertEqual(self.J("patch", f"/api/batches/{bid}", json={"end_time": "18:15"}).status_code, 200)
        o = [o for o in self.J("get", f"/api/timetable?from=2026-11-16&to=2026-11-16&batch_id=0").get_json() if o["batch_id"] == bid][0]
        self.assertEqual((o["end_time"], o["minutes"]), ("18:15", 135))
        self.assertEqual(self.J("patch", f"/api/batches/{bid}", json={"end_time": None}).status_code, 200)
        o = [o for o in self.J("get", f"/api/timetable?from=2026-11-16&to=2026-11-16&batch_id=0").get_json() if o["batch_id"] == bid][0]
        self.assertEqual((o["end_time"], o["minutes"]), ("17:00", 60))
        # the end time is in the activity log
        self.assertTrue(self.sql_("SELECT 1 FROM audit_log WHERE action='update_batch' AND entity_id=? AND detail LIKE '%end_time%'", (bid,)))

    def test_02_end_time_rules(self):
        base = {"course_id": self.co, "capacity": 9, "days": "Tue"}
        bad = lambda **k: self.J("post", "/api/batches", json={**base, **k})
        self.assertEqual(bad(code="X1", start_time="16:00", end_time="15:00").status_code, 400)
        self.assertEqual(bad(code="X2", start_time="16:00", end_time="16:00").status_code, 400)
        self.assertEqual(bad(code="X3", start_time="16:00", end_time="25:00").status_code, 400)
        self.assertEqual(bad(code="X4", end_time="17:00").status_code, 400)
        bid = bad(code="X5", start_time="16:00", end_time="17:00").get_json()["id"]
        # moving the start past the saved end is refused; moving both together is fine
        self.assertEqual(self.J("patch", f"/api/batches/{bid}", json={"start_time": "17:30"}).status_code, 400)
        self.assertEqual(self.J("patch", f"/api/batches/{bid}", json={"start_time": "17:30", "end_time": "19:00"}).status_code, 200)
        self.assertEqual(self.J("patch", f"/api/batches/{bid}", json={"start_time": None}).status_code, 400)   # end without start

    def test_03_end_time_in_teacher_views_and_workload(self):
        bid = self.J("post", "/api/batches", json={"course_id": self.co, "code": "W1", "teacher_id": self.t3, "capacity": 9, "days": "Mon,Tue,Wed", "start_time": "09:00", "end_time": "11:00"}).get_json()["id"]
        mine = self.J("get", "/api/my/batches", self.T3).get_json()
        self.assertEqual([(b["id"], b["start_time"], b["end_time"]) for b in mine if b["id"] == bid], [(bid, "09:00", "11:00")])
        r = self.J("get", f"/api/teacher-information/{self.t3}").get_json()
        self.assertEqual([b["end_time"] for b in r["batches"] if b["id"] == bid], ["11:00"])
        self.assertEqual((r["workload"]["weekly_classes"], r["workload"]["weekly_hours"]), (3, 6.0))   # 3 classes of 2 hours, not 3 x 60 minutes
        pub = [b for b in self.c.get("/api/public/batches").get_json() if b["id"] == bid]
        self.assertTrue(all("end_time" in b for b in pub))

    def test_04_end_time_excel_roundtrip(self):
        r = self.J("get", "/api/batches/export.csv")
        self.assertEqual(r.status_code, 200)
        head = r.data.decode("utf-8-sig").splitlines()[0]
        self.assertIn("start_time,end_time", head)

    # ---------- Teachers' room ----------
    def test_10_who_gets_in(self):
        for h in (self.H, self.T1, self.T2):
            self.assertEqual(self.J("get", "/api/staff/messages", h).status_code, 200)
        self.assertEqual(self.J("get", "/api/staff/messages", self.S1).status_code, 403)
        self.assertEqual(self.J("get", "/api/staff/messages", self.TL).status_code, 403)   # limited teacher without the area
        self.assertEqual(self.c.get("/api/staff/messages").status_code, 401)
        me = lambda h: self.c.get("/api/auth/me", headers=h).get_json()
        tabs = lambda h: (me(h).get("user") or me(h))["tabs"]
        self.assertIn("staff_room", tabs(self.T2)); self.assertIn("staff_room", tabs(self.H)); self.assertNotIn("staff_room", tabs(self.S1))
        self.assertNotIn("staff_room", tabs(self.TL))

    def test_11_chat_post_edit_delete_reply(self):
        r = self.J("post", "/api/staff/messages", self.T2, json={"body": "Assalaamu alaikum, who has the Level 1 answers?"})
        self.assertEqual(r.status_code, 201); m1 = r.get_json()["id"]
        m2 = self.J("post", "/api/staff/messages", self.T3, json={"body": "I do, uploading now", "reply_to": m1}).get_json()["id"]
        self.assertEqual(self.J("post", "/api/staff/messages", self.T3, json={"body": "  "}).status_code, 400)
        self.assertEqual(self.J("post", "/api/staff/messages", self.T3, json={"body": "x" * 4001}).status_code, 400)
        j = self.J("get", "/api/staff/messages", self.T2).get_json()
        got = {m["id"]: m for m in j["messages"]}
        self.assertEqual(got[m2]["reply_author"], "Teacher Two"); self.assertTrue(got[m2]["reply_body"].startswith("Assalaamu"))
        self.assertTrue(got[m1]["can_edit"]); self.assertFalse(got[m2]["can_edit"]); self.assertFalse(got[m2]["can_delete"])
        # others cannot edit or delete; the author can
        self.assertEqual(self.J("patch", f"/api/staff/messages/{m1}", self.T3, json={"body": "hacked"}).status_code, 403)
        self.assertEqual(self.J("delete", f"/api/staff/messages/{m1}", self.T3).status_code, 403)
        self.assertEqual(self.J("patch", f"/api/staff/messages/{m1}", self.T2, json={"body": "Who has the Level 1 answer key?"}).status_code, 200)
        e = [m for m in self.J("get", "/api/staff/messages", self.T3).get_json()["messages"] if m["id"] == m1][0]
        self.assertEqual(e["body"], "Who has the Level 1 answer key?"); self.assertTrue(e["edited_at"])
        self.assertEqual(self.J("delete", f"/api/staff/messages/{m2}", self.T3).status_code, 200)
        d = [m for m in self.J("get", "/api/staff/messages", self.T2).get_json()["messages"] if m["id"] == m2][0]
        self.assertTrue(d["deleted_at"]); self.assertIsNone(d["body"])
        # new messages since an id, and the signature changes when something changes
        s1 = self.J("get", "/api/staff/messages", self.T2).get_json()["signature"]
        m3 = self.J("post", "/api/staff/messages", self.H, json={"body": "Staff meeting on Thursday"}).get_json()["id"]
        j = self.J("get", f"/api/staff/messages?after={m2}", self.T2).get_json()
        self.assertEqual([m["id"] for m in j["messages"]], [m3]); self.assertNotEqual(j["signature"], s1)
        self.assertEqual(self.J("get", "/api/staff/messages", self.T2).get_json()["messages"][-1]["author_role"], "admin")

    def test_12_attachment(self):
        r = self.J("post", "/api/staff/messages", self.T2, data={"body": "Lesson plan", "file": (io.BytesIO(PDF), "plan.pdf")}, content_type="multipart/form-data")
        self.assertEqual(r.status_code, 201, r.get_json()); mid = r.get_json()["id"]
        f = self.J("get", f"/api/staff/messages/{mid}/file", self.T3)
        self.assertEqual(f.status_code, 200); self.assertEqual(f.data, PDF)
        self.assertEqual(self.J("get", f"/api/staff/messages/{mid}/file", self.S1).status_code, 403)
        bad = self.J("post", "/api/staff/messages", self.T2, data={"file": (io.BytesIO(b"MZ..."), "virus.exe")}, content_type="multipart/form-data")
        self.assertEqual(bad.status_code, 400)
        fake = self.J("post", "/api/staff/messages", self.T2, data={"file": (io.BytesIO(b"not a pdf"), "x.pdf")}, content_type="multipart/form-data")
        self.assertEqual(fake.status_code, 400)

    def test_20_head_teacher(self):
        # only admins choose head teachers
        self.assertEqual(self.J("post", "/api/staff/head", self.T1, json={"user_id": self.t1, "is_head": True}).status_code, 403)
        self.assertEqual(self.J("post", "/api/staff/head", json={"user_id": self.s1, "is_head": True}).status_code, 404)
        self.assertEqual(self.J("post", "/api/staff/head", json={"user_id": self.t1, "is_head": True}).status_code, 200)
        self.assertTrue(self.sql_("SELECT 1 FROM audit_log WHERE action='staff_head_set' AND entity_id=?", (self.t1,)))
        self.assertTrue(self.sql_("SELECT 1 FROM notifications WHERE user_id=? AND kind='staff_room'", (self.t1,)))
        room = self.J("get", "/api/staff/room", self.T1).get_json()
        self.assertTrue(room["me"]["can_moderate"]); self.assertTrue(room["me"]["is_head"])
        self.assertTrue([m for m in room["members"] if m["id"] == self.t1][0]["is_head"])
        self.assertEqual(room["teachers"], [])   # the list with the head-teacher switches is for admins
        self.assertTrue(self.J("get", "/api/staff/room").get_json()["teachers"])
        self.assertFalse(self.J("get", "/api/staff/room", self.T2).get_json()["me"]["can_moderate"])
        # head teacher moderates: pin (others are told), remove someone else's message
        mid = self.J("post", "/api/staff/messages", self.T2, json={"body": "Exam papers due Sunday"}).get_json()["id"]
        self.assertEqual(self.J("post", f"/api/staff/messages/{mid}/pin", self.T2, json={"pinned": True}).status_code, 403)
        self.assertEqual(self.J("post", f"/api/staff/messages/{mid}/pin", self.T1, json={"pinned": True}).status_code, 200)
        j = self.J("get", "/api/staff/messages", self.T3).get_json()
        self.assertEqual([p["id"] for p in j["pinned"]], [mid])
        self.assertTrue(self.sql_("SELECT 1 FROM notifications WHERE user_id=? AND dedupe_key=?", (self.t3, f"staffpin:{mid}")))
        self.assertFalse(self.sql_("SELECT 1 FROM notifications WHERE user_id=? AND dedupe_key=?", (self.t1, f"staffpin:{mid}")))   # not the pinner
        self.assertFalse(self.sql_("SELECT 1 FROM notifications WHERE user_id=? AND dedupe_key=?", (self.s1, f"staffpin:{mid}")))   # never students
        self.assertEqual(self.J("post", f"/api/staff/messages/{mid}/pin", self.T1, json={"pinned": False}).status_code, 200)
        self.assertEqual(self.J("get", "/api/staff/messages", self.T3).get_json()["pinned"], [])
        rude = self.J("post", "/api/staff/messages", self.T3, json={"body": "off-topic"}).get_json()["id"]
        self.assertEqual(self.J("delete", f"/api/staff/messages/{rude}", self.T1).status_code, 200)
        self.assertTrue(self.sql_("SELECT 1 FROM audit_log WHERE action='staff_message_remove' AND entity_id=? AND detail LIKE '%off-topic%'", (rude,)))
        # removing the head role takes the rights away at once
        self.assertEqual(self.J("post", "/api/staff/head", json={"user_id": self.t1, "is_head": False}).status_code, 200)
        m2 = self.J("post", "/api/staff/messages", self.T3, json={"body": "another"}).get_json()["id"]
        self.assertEqual(self.J("delete", f"/api/staff/messages/{m2}", self.T1).status_code, 403)
        self.assertEqual(self.J("delete", f"/api/staff/messages/{m2}", self.H).status_code, 200)   # admins always moderate

    def test_30_guide_folders_and_files(self):
        self.J("post", "/api/staff/head", json={"user_id": self.t1, "is_head": True})
        self.assertEqual(self.J("post", "/api/staff/folders", self.T2, json={"name": "Lesson plans"}).status_code, 403)
        open_f = self.J("post", "/api/staff/folders", self.T1, json={"name": "Lesson plans"}).get_json()["id"]
        locked = self.J("post", "/api/staff/folders", self.T1, json={"name": "Official guide", "locked": True}).get_json()["id"]
        self.assertEqual(self.J("post", "/api/staff/folders", self.T1, json={"name": "lesson PLANS"}).status_code, 409)
        up = lambda h, fid, title="Plan", name="plan.pdf": self.J("post", "/api/staff/files", h, data={"title": title, "folder_id": str(fid), "file": (io.BytesIO(PDF), name)}, content_type="multipart/form-data")
        r = up(self.T2, open_f); self.assertEqual(r.status_code, 201, r.get_json()); f2 = r.get_json()["id"]
        self.assertEqual(up(self.T2, locked).status_code, 403)          # locked: head teacher and admins only
        self.assertEqual(up(self.T1, locked, "Teaching guide").status_code, 201)
        link = self.J("post", "/api/staff/files", self.T3, json={"title": "Quran audio", "url": "https://example.org/audio"})
        self.assertEqual(link.status_code, 201)
        self.assertEqual(self.J("post", "/api/staff/files", self.T3, json={"title": "bad", "url": "javascript:alert(1)"}).status_code, 400)
        fs = self.J("get", f"/api/staff/folders", self.T3).get_json()
        cnt = {f["id"]: (f["files"], f["can_add"]) for f in fs["folders"]}
        self.assertEqual(cnt[open_f], (1, True)); self.assertEqual(cnt[locked], (1, False)); self.assertEqual(fs["unfiled"], 1)
        lst = self.J("get", f"/api/staff/files?folder_id={open_f}", self.T3).get_json()
        self.assertEqual([(x["id"], x["can_edit"]) for x in lst], [(f2, False)])
        self.assertEqual([x["title"] for x in self.J("get", "/api/staff/files?q=guide", self.T3).get_json()], ["Teaching guide"])
        self.assertEqual(self.J("get", f"/api/staff/files/{f2}/file", self.T3).data, PDF)
        self.assertEqual(self.J("get", f"/api/staff/files/{f2}/file", self.S1).status_code, 403)
        # changing: owner yes, other teacher no, head teacher yes; a plain teacher cannot move a file INTO a locked folder
        self.assertEqual(self.J("patch", f"/api/staff/files/{f2}", self.T3, json={"title": "x"}).status_code, 403)
        self.assertEqual(self.J("patch", f"/api/staff/files/{f2}", self.T2, json={"folder_id": locked}).status_code, 403)
        self.assertEqual(self.J("patch", f"/api/staff/files/{f2}", self.T2, json={"title": "Plan week 1"}).status_code, 200)
        self.assertEqual(self.J("patch", f"/api/staff/files/{f2}", self.T1, json={"folder_id": locked}).status_code, 200)
        # folders with files cannot be deleted; empty ones can, by moderators only
        self.assertEqual(self.J("delete", f"/api/staff/folders/{locked}", self.T1).status_code, 409)
        self.assertEqual(self.J("delete", f"/api/staff/folders/{open_f}", self.T2).status_code, 403)
        self.assertEqual(self.J("delete", f"/api/staff/folders/{open_f}", self.T1).status_code, 200)
        stored = self.sql_("SELECT file FROM staff_files WHERE id=?", (f2,))[0][0]
        self.assertEqual(self.J("delete", f"/api/staff/files/{f2}", self.T3).status_code, 403)
        self.assertEqual(self.J("delete", f"/api/staff/files/{f2}", self.T1).status_code, 200)
        self.assertFalse(self.app.extensions["store"].exists("learning", stored) if "store" in self.app.extensions else False)
        self.assertTrue(self.sql_("SELECT 1 FROM audit_log WHERE action='staff_file_delete' AND entity_id=?", (f2,)))
        # students can reach none of it
        for m, p in (("get", "/api/staff/folders"), ("get", "/api/staff/files"), ("get", "/api/staff/room"), ("post", "/api/staff/files"), ("post", "/api/staff/messages")):
            self.assertEqual(self.J(m, p, self.S1, json={}).status_code, 403, p)


if __name__ == "__main__":
    unittest.main()
