"""v0.8.42: imports. (1) Importing N students no longer costs about N*N/2 queries, (2) temporary passwords of imported accounts are
hashed quickly, (3) a file can be sent in parts and gives the same result, (4) routes called from inside an import share the outer
request's connection on every Flask version, so a check never saves."""
import datetime as dt, io, os, sqlite3, sys, tempfile, unittest
from unittest import mock
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
MVT = dt.timezone(dt.timedelta(hours=5))
PW = "Password123"


class Imports42(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp(); cls.path = os.path.join(tmp, "t.db")
        old = os.environ.get("SEED_DEMO")
        os.environ.update(DATABASE_PATH=cls.path, ADMIN_EMAIL="admin@s42.test", ADMIN_PASSWORD="AdminPass123", SEED_DEMO="0")
        import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
        os.environ.pop("SEED_DEMO") if old is None else os.environ.update(SEED_DEMO=old)
        from app import create_app
        cls.app = create_app({"DATABASE_PATH": cls.path}); cls.c = cls.app.test_client()
        cls.app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 17, 0, tzinfo=MVT)
        cls.sql("UPDATE users SET must_change_password=0")
        cls.sql("DELETE FROM batches"); cls.sql("DELETE FROM courses")
        cls.H = {"Authorization": "Bearer " + cls.c.post("/api/auth/login", json={"login": "admin@s42.test", "password": "AdminPass123"}).get_json()["token"]}

    @classmethod
    def sql(cls, q, a=()):
        con = sqlite3.connect(cls.path)
        try: r = con.execute(q, a).fetchall(); con.commit(); return r
        finally: con.close()

    def up(self, kind, text, **q):
        qs = "&".join(f"{k}={v}" for k, v in q.items())
        r = self.c.post(f"/api/import/{kind}?{qs}", data={"file": (io.BytesIO(text.encode()), "f.csv")}, headers=self.H, content_type="multipart/form-data")
        return r.status_code, r.get_json()

    def in_parts(self, kind, text, dry, limit):
        """What the page does: the same file again and again with offset and limit; the results put together."""
        off, rows, ok, bad = 0, [], 0, 0
        while off is not None:
            code, j = self.up(kind, text, dry_run=dry, offset=off, limit=limit); self.assertEqual(code, 200, j)
            rows += j["rows"]; ok += j["ok"]; bad += j["rejected"]; total = j["file_total"]; off = j["next_offset"]
        return {"rows": rows, "ok": ok, "rejected": bad, "total": total}

    # ---- 1. speed ----
    def test_01_student_import_does_not_slow_down_with_every_student(self):
        import dbx
        n = {"q": 0}; real = dbx.Conn.execute
        def counting(conn, *a, **k): n["q"] += 1; return real(conn, *a, **k)
        text = "full_name,email\n" + "".join(f"Fast {i},fast{i}@s42.test\n" for i in range(60))
        with mock.patch.object(dbx.Conn, "execute", counting):
            code, j = self.up("students", text, dry_run=0)
        self.assertEqual((code, j["ok"], j["rejected"]), (200, 60, 0))
        self.assertLess(n["q"] / 60, 20)            # was 40 a row for 60 students and rising with every student still waiting for a course
        self.assertEqual(self.sql("SELECT COUNT(*) FROM users WHERE email LIKE 'fast%' AND login_id LIKE 'BAL/STU/%'")[0][0], 60)
        self.assertEqual(len(set(self.sql("SELECT login_id FROM users WHERE email LIKE 'fast%'"))), 60)

    def test_02_ids_are_still_given_as_before(self):
        import dbx, idcodes
        P = lambda p, jn: self.c.post(p, json=jn, headers=self.H)
        course = P("/api/courses", {"name": "Quran", "code": "QR", "monthly_fee_mvr": 0, "status": "open"}).get_json()["id"]
        b = P("/api/batches", {"course_id": course, "code": "Q1", "capacity": 50, "days": "Mon", "start_time": "16:00"}).get_json()["id"]
        sid = self.sql("SELECT id FROM users WHERE email='fast0@s42.test'")[0][0]
        self.assertEqual(self.sql("SELECT student_code FROM students WHERE user_id=?", (sid,)), [(None,)])    # waits for the first course
        self.assertEqual(P("/api/enrollments", {"student_id": sid, "batch_id": b}).status_code, 201)
        self.assertEqual(self.sql("SELECT student_code FROM students WHERE user_id=?", (sid,))[0][0], "BAL/QR/001")   # the first course decides it
        self.sql("UPDATE students SET student_code=NULL WHERE user_id=?", (sid,))                              # as an older database would be
        conn = dbx.connect({"DATABASE_URL": "", "DATABASE_PATH": self.path}, ROOT, dbx.read_schema(ROOT))
        try:
            rep = idcodes.fill_missing(conn, unenrolled_students=False)
            self.assertEqual([u for u, _c in rep["students"]], [sid])                                         # only the enrolled one, others keep waiting
            self.assertTrue(rep["students"][0][1].startswith("BAL/QR/"))
            waiting = conn.execute("SELECT COUNT(*) FROM students WHERE student_code IS NULL").fetchone()[0]
            self.assertGreaterEqual(waiting, 59)
            rep = idcodes.fill_missing(conn, unenrolled_students=True)                                         # the migration gives everyone a code
            self.assertEqual(len(rep["students"]), waiting)
            self.assertTrue(all(c.startswith("BAL/STU/") for _u, c in rep["students"]))
            self.assertEqual(idcodes.duplicates(conn), [])
            conn.rollback()
        finally: conn.close()

    # ---- 2. temporary passwords ----
    def test_03_temporary_password_is_quick_and_the_chosen_one_is_not(self):
        code, j = self.up("teachers", "full_name,email\nTemp Teacher,temp-t@s42.test\n", dry_run=0)
        self.assertEqual((code, j["ok"]), (200, 1)); row = j["rows"][0]
        h = self.sql("SELECT password_hash FROM users WHERE email='temp-t@s42.test'")[0][0]
        self.assertTrue(h.startswith("pbkdf2:sha256:1000$"), h[:30])
        self.assertEqual(len(row["temporary_password"]), 12)
        r = self.c.post("/api/auth/login", json={"login": row["login_id"], "password": row["temporary_password"]})
        self.assertEqual(r.status_code, 200); self.assertTrue(r.get_json()["user"]["must_change_password"])    # it only opens the "choose a password" page
        tok = {"Authorization": "Bearer " + r.get_json()["token"]}
        self.assertEqual(self.c.post("/api/auth/change-password", json={"current_password": row["temporary_password"], "new_password": "MyOwnPassword9"}, headers=tok).status_code, 200)
        h = self.sql("SELECT password_hash FROM users WHERE email='temp-t@s42.test'")[0][0]
        self.assertFalse(h.startswith("pbkdf2:sha256:1000$"))                                                   # their own password gets the usual slow hash
        u = self.c.post("/api/users", json={"email": "typed@s42.test", "password": PW, "full_name": "Typed", "role": "student"}, headers=self.H)
        self.assertEqual(u.status_code, 201)
        self.assertFalse(self.sql("SELECT password_hash FROM users WHERE email='typed@s42.test'")[0][0].startswith("pbkdf2:sha256:1000$"))

    # ---- 3. a file in parts ----
    PEOPLE = ("full_name,email,student_code\n" + "".join(f"Part {i},part{i}@s42.test,\n" for i in range(11))
              + "Twice,part3@s42.test,\n" + "No Email,,\n" + "Code A,code-a@s42.test,BAL/ZZ/900\n" + "Code B,code-b@s42.test,bal/zz/900\n")

    def test_04_check_in_parts_gives_the_same_as_the_whole_file(self):
        code, whole = self.up("students", self.PEOPLE, dry_run=1); self.assertEqual(code, 200)
        self.assertEqual((whole["total"], whole["ok"], whole["rejected"], whole["next_offset"], whole["file_total"]), (15, 12, 3, None, 15))
        for limit in (4, 7, 15, 200):
            parts = self.in_parts("students", self.PEOPLE, 1, limit)
            self.assertEqual([(r["row"], r["status"], r.get("message")) for r in parts["rows"]], [(r["row"], r["status"], r.get("message")) for r in whole["rows"]], limit)
            self.assertEqual((parts["ok"], parts["rejected"], parts["total"]), (12, 3, 15))
        msgs = {r["row"]: r["message"] for r in whole["rows"] if r["status"] == "rejected"}
        self.assertIn("appears twice in this file", msgs[13]); self.assertIn("email is missing", msgs[14]); self.assertIn("appears twice in this file", msgs[16])
        self.assertEqual(self.sql("SELECT COUNT(*) FROM users WHERE email LIKE 'part%' OR email LIKE 'code-%'")[0][0], 0)   # a check saves nothing
        code, j = self.up("students", self.PEOPLE, dry_run=1, offset=4, limit=4)
        self.assertEqual((j["total"], j["offset"], j["next_offset"], j["file_total"], [r["row"] for r in j["rows"]]), (4, 4, 8, 15, [6, 7, 8, 9]))
        self.assertEqual(self.up("students", self.PEOPLE, dry_run=1, offset="x")[0], 400)
        code, j = self.up("students", self.PEOPLE, dry_run=1, offset=99, limit=5); self.assertEqual((code, j["rows"], j["next_offset"]), (200, [], None))

    def test_05_import_in_parts_saves_every_good_row_once(self):
        got = self.in_parts("students", self.PEOPLE, 0, 4)
        self.assertEqual((got["ok"], got["rejected"], got["total"]), (12, 3, 15))
        self.assertEqual(self.sql("SELECT COUNT(*) FROM users WHERE email LIKE 'part%' OR email LIKE 'code-%'")[0][0], 12)
        msgs = {r["row"]: r["message"] for r in got["rows"] if r["status"] == "rejected"}
        self.assertIn("already used", msgs[13])                                                # the earlier part is saved by then
        self.assertIn("appears twice in this file", msgs[16])                                    # rows 15 and 16 travel in the same part
        self.assertEqual(len([r for r in got["rows"] if r.get("temporary_password")]), 12)       # every new account's password comes back, from every part
        self.assertEqual(self.sql("SELECT COUNT(*) FROM audit_log WHERE action='import_students' AND detail LIKE '%of 4' OR action='import_students' AND detail LIKE '%of 3'")[0][0], 4)
        again = self.in_parts("students", self.PEOPLE, 0, 4)                                     # the same file again: nothing is added twice
        self.assertEqual((again["ok"], again["rejected"]), (0, 15))

    COURSES = "code,name,monthly_fee_mvr\nP1,Part One,100\nP2,Part Two,100\nP3,Part Three,100\np1,Part One again,100\nP5,Part Five,x\n"

    def test_06_courses_in_parts(self):
        n = lambda: self.sql("SELECT COUNT(*) FROM courses WHERE code LIKE 'P_'")[0][0]
        code, whole = self.up("courses", self.COURSES, dry_run=1); self.assertEqual(code, 200)
        parts = self.in_parts("courses", self.COURSES, 1, 2)
        self.assertEqual([(r["row"], r["status"]) for r in parts["rows"]], [(r["row"], r["status"]) for r in whole["rows"]])
        self.assertEqual([(r["row"], r["status"]) for r in parts["rows"]], [(2, "would_create"), (3, "would_create"), (4, "would_create"), (5, "rejected"), (6, "rejected")])
        self.assertIn("already in row 2 of this file", parts["rows"][3]["message"])              # found in the file: the first part was not saved
        self.assertEqual(n(), 0)
        got = self.in_parts("courses", self.COURSES, 0, 2)
        self.assertEqual((got["ok"], got["rejected"], n()), (3, 2, 3))
        batches = "course_code,code,capacity\nP1,B1,10\nP2,B1,10\nP1,b1,10\nP9,B1,10\n"
        parts = self.in_parts("batches", batches, 1, 2)
        self.assertEqual([r["status"] for r in parts["rows"]], ["would_create", "would_create", "rejected", "rejected"])
        self.assertIn("already in row 2 of this file", parts["rows"][2]["message"]); self.assertIn("No course with code P9", parts["rows"][3]["message"])
        self.assertEqual(self.sql("SELECT COUNT(*) FROM batches WHERE code LIKE 'B1' OR code LIKE 'b1'")[0][0], 0)

    def test_06b_enrolment_import_fills_every_seat(self):
        P = lambda p, jn: self.c.post(p, json=jn, headers=self.H)
        course = P("/api/courses", {"name": "Seats", "code": "SE", "monthly_fee_mvr": 0, "status": "open"}).get_json()["id"]
        self.assertEqual(P("/api/batches", {"course_id": course, "code": "S1", "capacity": 6, "days": "Mon", "start_time": "16:00"}).status_code, 201)
        text = "student_email,course_code,batch_code\n" + "".join(f"fast{i}@s42.test,SE,S1\n" for i in range(10, 17)) + "fast10@s42.test,se,s1\n"
        code, whole = self.up("enrolments", text, dry_run=1); self.assertEqual(code, 200)
        want = ["would_create"] * 6 + ["rejected", "rejected"]
        self.assertEqual([r["status"] for r in whole["rows"]], want)
        self.assertIn("full (capacity 6)", whole["rows"][6]["message"]); self.assertIn("appear twice", whole["rows"][7]["message"])
        for limit in (3, 5):                                                                    # the same answer when the check travels in parts
            parts = self.in_parts("enrolments", text, 1, limit)
            self.assertEqual([(r["status"], r.get("message")) for r in parts["rows"]], [(r["status"], r.get("message")) for r in whole["rows"]], limit)
        code, j = self.up("enrolments", text, dry_run=0)
        self.assertEqual([r["status"] for r in j["rows"]], ["created"] * 6 + ["rejected", "rejected"], j["rows"])   # was: "full" after 3 of the 6 seats
        self.assertEqual(self.sql("SELECT COUNT(*) FROM enrollments e JOIN batches b ON b.id=e.batch_id WHERE b.code='S1' AND e.status='active'")[0][0], 6)
        self.assertIn("full (capacity 6)", j["rows"][6]["message"]); self.assertIn("appear twice", j["rows"][7]["message"])

    # ---- 4. routes called from inside an import ----
    def as_flask_32(self):
        """Flask 3.2: an app context that is already pushed is not reused for a new request, so the inner request has its own `g`."""
        import flask
        orig = flask.Flask.test_request_context
        class Both:
            def __init__(s, app, rc): s.app, s.rc = app, rc
            def __enter__(s): s.ac = s.app.app_context(); s.ac.push(); s.rc.push(); return s.rc
            def __exit__(s, *a): s.rc.pop(); s.ac.pop(); return False
        p = mock.patch.object(flask.Flask, "test_request_context", lambda app, *a, **k: Both(app, orig(app, *a, **k))); p.start(); self.addCleanup(p.stop)

    def test_07_a_check_saves_nothing_whatever_flask_does_with_contexts(self):
        for newer in (False, True):
            if newer: self.as_flask_32()
            text = f"code,name,monthly_fee_mvr\nC{int(newer)}A,Ctx A,100\nC{int(newer)}B,Ctx B,100\nC{int(newer)}A,Ctx A twice,100\n"
            before, log = self.sql("SELECT COUNT(*) FROM courses")[0][0], self.sql("SELECT COUNT(*) FROM audit_log")[0][0]
            code, j = self.up("courses", text, dry_run=1)
            self.assertEqual((code, j["ok"], j["rejected"]), (200, 2, 1), j)                     # the third row sees the first one inside the check
            self.assertEqual(self.sql("SELECT COUNT(*) FROM courses")[0][0], before, f"newer={newer}")   # was: the check really saved them
            self.assertEqual(self.sql("SELECT COUNT(*) FROM audit_log")[0][0], log)
            code, j = self.up("courses", text, dry_run=0)
            self.assertEqual((code, j["ok"], j["rejected"]), (200, 2, 1), j)                     # and the import that follows is not refused
            self.assertEqual(self.sql("SELECT COUNT(*) FROM courses")[0][0], before + 2)
            self.assertEqual(self.sql("SELECT COUNT(*) FROM audit_log WHERE action='import_courses'")[0][0], 1 + int(newer) + 3)   # test_06 made three (one per part)
            r = self.c.get("/api/courses/export.csv", headers=self.H)                            # exports read a route the same way
            self.assertEqual(r.status_code, 200); self.assertIn(f"C{int(newer)}B", r.get_data(as_text=True))
            self.assertEqual(self.c.get("/api/invoices/export.csv", headers=self.H).status_code, 200)

    def test_08_requirements_and_page(self):
        req = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read().splitlines()
        self.assertTrue(any(l.replace(" ", "").startswith("Flask>=3.0,<3.2") for l in req), req)
        lj, aj = (open(os.path.join(ROOT, "static", f), encoding="utf-8").read() for f in ("learning.js", "admin.js"))
        self.assertIn("async function importInParts(path, file, dry, onPart)", lj)
        self.assertIn('importInParts(`/import/${k}${q ? "?" + q : ""}`, f, dry', lj); self.assertIn("importInParts(`/import/${S.impkind}`, f, dry", aj)
        import json
        en = json.load(open(os.path.join(ROOT, "static/i18n/en.json"), encoding="utf-8"))
        for k in ("server_too_slow", "xl_part_maybe", "xl_progress", "xl_stopped"): self.assertIn(k, en)


if __name__ == "__main__":
    unittest.main()
