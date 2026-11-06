"""Session 4: class links. A teacher sets the Meet link of their own batches only and can add a one-off link for one class;
students join as before; the 'class_links' permission is controlled by a full admin."""
import datetime as dt, os, sqlite3, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MVT = dt.timezone(dt.timedelta(hours=5)); PW = "Password123"
BATCH_LINK = "https://meet.google.com/aaa-bbbb-ccc"; NEW_LINK = "https://meet.google.com/new-link-xyz"; ONE_OFF = "https://meet.google.com/one-off-123"


class Session4(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        os.environ["DATABASE_PATH"] = os.path.join(tmp, "t.db")
        os.environ["ADMIN_EMAIL"] = "admin@s4.test"; os.environ["ADMIN_PASSWORD"] = "AdminPass123"
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        cls.clock = [dt.datetime(2026, 3, 2, 15, 50, tzinfo=MVT)]   # Monday; the class is at 16:00
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": os.environ["DATABASE_PATH"], "NOW": lambda: cls.clock[0]})
        c = cls.c = cls.app.test_client()
        cls.a = cls.login("admin@s4.test", "AdminPass123")
        cid = c.post("/api/courses", json={"name": "Arabic", "status": "open", "minutes_per_class": 60}, headers=cls.a).get_json()["id"]
        mk = lambda e, r: c.post("/api/users", json={"email": e + "@s4.test", "password": PW, "full_name": e.upper(), "role": r}, headers=cls.a).get_json()["id"]
        cls.ids = {n: mk(n, r) for n, r in (("t1", "teacher"), ("t2", "teacher"), ("s1", "student"), ("s2", "student"))}
        cls.b1 = c.post("/api/batches", json={"course_id": cid, "code": "B1", "days": "Mon,Wed,Fri", "start_time": "16:00", "teacher_id": cls.ids["t1"], "meet_link": BATCH_LINK, "capacity": 10}, headers=cls.a).get_json()["id"]
        cls.b2 = c.post("/api/batches", json={"course_id": cid, "code": "B2", "days": "Tue", "start_time": "10:00", "teacher_id": cls.ids["t2"], "capacity": 10}, headers=cls.a).get_json()["id"]
        c.post("/api/enrollments", json={"student_id": cls.ids["s1"], "batch_id": cls.b1}, headers=cls.a)
        cls.t1, cls.t2, cls.s1, cls.s2 = (cls.login(f"{n}@s4.test") for n in ("t1", "t2", "s1", "s2"))

    @classmethod
    def login(cls, email, pw=PW):
        return {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"email": email, "password": pw}).get_json()["token"]}

    def setUp(self): self.clock[0] = dt.datetime(2026, 3, 2, 15, 50, tzinfo=MVT)
    def put(self, bid, who, link): return self.c.put(f"/api/batches/{bid}/meet-link", json={"meet_link": link}, headers=who)
    def sess(self, bid, who, **kw): return self.c.post(f"/api/batches/{bid}/sessions", json=kw, headers=who)
    def tl(self, who, bid=None):
        return self.c.get("/api/timetable?from=2026-03-02&to=2026-03-09" + (f"&batch_id={bid}" if bid else ""), headers=who).get_json()
    def occ(self, who, date, time="16:00"): return [o for o in self.tl(who) if o["date"] == date and o["start_time"] == time][0]
    def setperms(self, name, areas):
        r = self.c.patch(f"/api/users/{self.ids[name]}", json={"permissions": areas}, headers=self.a); self.assertEqual(r.status_code, 200, r.get_json())
        return self.login(f"{name}@s4.test")
    def reset_perms(self, name): self.c.patch(f"/api/users/{self.ids[name]}", json={"permissions": "all"}, headers=self.a)

    # ---- the batch link ----
    def test_teacher_sets_link_students_join_with_it(self):
        self.assertEqual(self.put(self.b1, self.t1, NEW_LINK).status_code, 200)
        o = self.occ(self.s1, "2026-03-02")
        self.assertEqual((o["meet_link"], o["can_join"]), (NEW_LINK, True))        # 10 minutes before class: Join shows, with the new link
        self.put(self.b1, self.t1, BATCH_LINK)

    def test_only_own_batches_and_not_students(self):
        self.assertEqual(self.put(self.b1, self.t2, "https://meet.google.com/x").status_code, 403)   # another teacher's batch
        self.assertEqual(self.put(self.b2, self.t1, "https://meet.google.com/x").status_code, 403)
        self.assertEqual(self.put(self.b1, self.s1, "https://meet.google.com/x").status_code, 403)
        self.assertEqual(self.c.put(f"/api/batches/{self.b1}/meet-link", json={"meet_link": "https://x.y/z"}).status_code, 401)
        self.assertEqual(self.put(99999, self.a, "https://meet.google.com/x").status_code, 404)
        self.assertEqual(self.put(self.b2, self.a, "https://meet.google.com/adm").status_code, 200)   # admin: any batch
        self.assertEqual(self.put(self.b2, self.t2, "").status_code, 200)

    def test_link_validation_and_clearing(self):
        for bad in ("http://meet.google.com/x", "javascript:alert(1)", "meet.google.com/x", "https://a b", "https://" + "x" * 600):
            self.assertEqual(self.put(self.b1, self.t1, bad).status_code, 400, bad)
        self.assertEqual(self.c.put(f"/api/batches/{self.b1}/meet-link", json={"meet_link": 5}, headers=self.t1).status_code, 400)
        self.assertEqual(self.put(self.b1, self.t1, "").status_code, 200)                         # empty removes the link
        o = self.occ(self.s1, "2026-03-02"); self.assertEqual((o["meet_link"], o["can_join"]), (None, False))
        self.put(self.b1, self.t1, BATCH_LINK)

    def test_permission_is_controlled_by_full_admin(self):
        h = self.setperms("t1", ["classroom", "tutorials"])                    # Class links not ticked
        self.assertEqual(self.put(self.b1, h, NEW_LINK).status_code, 403)
        self.assertEqual(self.sess(self.b1, h, date="2026-03-04", start_time="20:00", meet_link=ONE_OFF).status_code, 403)
        self.assertEqual(self.sess(self.b1, h, date="2026-03-04", start_time="20:00", topic="No link").status_code, 201)   # extra class without a link still works
        h = self.setperms("t1", ["classroom", "class_links"])
        self.assertEqual(self.put(self.b1, h, BATCH_LINK).status_code, 200)
        self.reset_perms("t1")
        self.assertEqual(self.put(self.b1, self.login("t1@s4.test"), BATCH_LINK).status_code, 200)   # no limit = has it

    def test_new_area_listed_for_teachers_and_admins_only(self):
        self.assertIn("class_links", self.c.get(f"/api/users/{self.ids['t1']}", headers=self.a).get_json()["areas"])
        self.assertNotIn("class_links", self.c.get(f"/api/users/{self.ids['s1']}", headers=self.a).get_json()["areas"])
        self.assertEqual(self.c.patch(f"/api/users/{self.ids['s1']}", json={"permissions": ["class_links"]}, headers=self.a).status_code, 400)

    # ---- one-off link for a single class ----
    def test_one_off_link_for_an_extra_class(self):
        self.assertEqual(self.sess(self.b1, self.t1, date="2026-03-03", start_time="20:00", topic="Revision", meet_link=ONE_OFF).status_code, 201)
        extra = self.occ(self.s1, "2026-03-03", "20:00")
        self.assertEqual((extra["extra"], extra["own_link"], extra["meet_link"]), (True, True, ONE_OFF))
        regular = self.occ(self.s1, "2026-03-02"); self.assertEqual((regular["own_link"], regular["meet_link"]), (False, BATCH_LINK))   # other classes keep the batch link
        self.clock[0] = dt.datetime(2026, 3, 3, 19, 50, tzinfo=MVT)
        e = self.occ(self.s1, "2026-03-03", "20:00"); self.assertEqual((e["can_join"], e["meet_link"]), (True, ONE_OFF))
        self.assertEqual(self.c.get("/api/my/home", headers=self.s1).get_json()["next_class"]["meet_link"], ONE_OFF)
        # change it, then remove it (empty): the batch link is used again
        self.sess(self.b1, self.t1, date="2026-03-03", start_time="20:00", meet_link=NEW_LINK)
        self.assertEqual(self.occ(self.s1, "2026-03-03", "20:00")["meet_link"], NEW_LINK)
        self.assertEqual(self.sess(self.b1, self.t1, date="2026-03-03", start_time="20:00", meet_link="").status_code, 201)
        e = self.occ(self.s1, "2026-03-03", "20:00"); self.assertEqual((e["own_link"], e["meet_link"]), (False, BATCH_LINK))

    def test_extra_class_link_when_batch_has_none(self):
        self.sess(self.b2, self.t2, date="2026-03-05", start_time="09:00", meet_link=ONE_OFF)
        self.c.post("/api/enrollments", json={"student_id": self.ids["s2"], "batch_id": self.b2}, headers=self.a)
        self.clock[0] = dt.datetime(2026, 3, 5, 8, 50, tzinfo=MVT)
        o = self.occ(self.s2, "2026-03-05", "09:00"); self.assertEqual((o["meet_link"], o["can_join"]), (ONE_OFF, True))
        tuesday = [x for x in self.tl(self.s2) if x["date"] == "2026-03-03"][0]; self.assertEqual((tuesday["meet_link"], tuesday["can_join"]), (None, False))

    def test_one_off_link_rules(self):
        self.assertEqual(self.sess(self.b1, self.t2, date="2026-03-06", start_time="20:00", meet_link=ONE_OFF).status_code, 403)   # not their batch
        self.assertEqual(self.sess(self.b1, self.s1, date="2026-03-06", start_time="20:00", meet_link=ONE_OFF).status_code, 403)
        self.assertEqual(self.sess(self.b1, self.t1, date="2026-03-06", start_time="20:00", meet_link="http://insecure").status_code, 400)
        self.assertEqual(self.sess(self.b1, self.t1, date="2026-03-06", start_time="20:00", meet_link="javascript:1").status_code, 400)
        self.assertEqual(self.occ(self.s1, "2026-03-06", "16:00")["meet_link"], BATCH_LINK)   # nothing was saved by the refused calls
        self.assertEqual(len([o for o in self.tl(self.s1) if o["date"] == "2026-03-06"]), 1)

    def test_cancelled_class_cannot_be_joined_even_with_own_link(self):
        self.sess(self.b1, self.t1, date="2026-03-09", meet_link=ONE_OFF); self.sess(self.b1, self.t1, date="2026-03-09", status="cancelled")
        self.clock[0] = dt.datetime(2026, 3, 9, 15, 50, tzinfo=MVT)
        o = [x for x in self.c.get("/api/timetable?from=2026-03-09&to=2026-03-09", headers=self.s1).get_json()][0]
        self.assertEqual((o["status"], o["can_join"], o["meet_link"]), ("cancelled", False, ONE_OFF))

    def test_audit_trail(self):
        self.put(self.b1, self.t1, NEW_LINK); self.put(self.b1, self.t1, BATCH_LINK)
        acts = [x["action"] for x in self.c.get("/api/audit", headers=self.a).get_json()]
        self.assertIn("set_class_link", acts)
        self.assertNotIn(NEW_LINK, str([x["detail"] for x in self.c.get("/api/audit", headers=self.a).get_json()]))   # the link itself is not written to the log

    # ---- upgrade of an existing database ----
    def test_upgrade_adds_column_and_keeps_admin_access(self):
        from app import create_app
        p = os.path.join(tempfile.mkdtemp(), "old.db")
        create_app({"DATABASE_PATH": p})
        con = sqlite3.connect(p)
        con.execute("ALTER TABLE sessions DROP COLUMN meet_link")            # what an older database looks like
        con.execute("INSERT INTO users(email,password_hash,full_name,role,permissions) VALUES('la@x.test','x','LA','admin','batches,courses')")
        con.execute("INSERT INTO users(email,password_hash,full_name,role,permissions) VALUES('lo@x.test','x','LO','admin','courses')")
        con.execute("INSERT INTO users(email,password_hash,full_name,role,permissions) VALUES('lt@x.test','x','LT','teacher','classroom')")
        con.execute("DELETE FROM schema_meta"); con.commit(); con.close()
        create_app({"DATABASE_PATH": p})
        con = sqlite3.connect(p)
        self.assertIn("meet_link", {r[1] for r in con.execute("PRAGMA table_info(sessions)")})
        got = dict(con.execute("SELECT email,permissions FROM users WHERE email IN ('la@x.test','lo@x.test','lt@x.test')").fetchall())
        self.assertEqual(got["la@x.test"], "batches,courses,class_links")     # could edit batches, so could set links
        self.assertEqual(got["lo@x.test"], "courses"); self.assertEqual(got["lt@x.test"], "classroom")   # teachers could not, so start without it


if __name__ == "__main__":
    unittest.main()
