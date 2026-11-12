"""Session 32: security and regression sweep.
1. POLICY below is written by hand and is the oracle: every route must be admin-only unless listed in OPEN, and every admin-only route must sit in the right
   permission area. A new route that is not covered fails here, so it gets a decision before it ships.
2. The matrix runs every protected route as: no token, full admin, limited admin (Admissions only), teacher, other teacher, substitute, student, other
   student and withdrawn student. Refusals are executed (they never change data); allowed GETs are executed and must never give a 5xx.
3. Object-level checks: nobody sees another person's invoice, slip, receipt, submission or batch, and nothing leaks a hash, a password or a file key."""
import datetime as dt, io, os, re, sqlite3, sys, tempfile, unittest, warnings
warnings.simplefilter("ignore", ResourceWarning)   # Flask's test client leaves file responses open
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, ROOT)
PW = "Passw0rd!x1"; PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"; MVT = dt.timezone(dt.timedelta(hours=5))
ALL = ("admin", "teacher", "student"); AT = ("admin", "teacher"); AS = ("admin", "student")
# (method, rule) -> roles allowed. Everything not listed here must be admin only.
OPEN = {
 ("GET", "/api/assignments"): ALL, ("PATCH", "/api/assignments/<int:aid>"): AT, ("DELETE", "/api/assignments/<int:aid>"): AT, ("GET", "/api/assignments/<int:aid>/attachment"): ALL,
 ("POST", "/api/assignments/<int:aid>/grades"): AT, ("GET", "/api/assignments/<int:aid>/submissions"): AT, ("POST", "/api/assignments/<int:aid>/submit"): ("student",),
 ("POST", "/api/auth/change-password"): ALL, ("POST", "/api/auth/logout"): ALL, ("GET", "/api/auth/me"): ALL, ("GET", "/api/batches"): ALL,
 ("POST", "/api/batches/<int:bid>/assignments"): AT, ("GET", "/api/batches/<int:bid>/attendance"): AT, ("POST", "/api/batches/<int:bid>/attendance"): AT,
 ("GET", "/api/batches/<int:bid>/attendance/summary"): AT, ("GET", "/api/batches/<int:bid>/gradebook"): AT, ("POST", "/api/batches/<int:bid>/materials"): AT,
 ("PUT", "/api/batches/<int:bid>/meet-link"): AT, ("POST", "/api/batches/<int:bid>/recordings"): AT, ("POST", "/api/batches/<int:bid>/sessions"): AT,
 ("GET", "/api/batches/<int:bid>/students"): AT, ("GET", "/api/courses"): ALL, ("GET", "/api/enrollments"): ALL, ("GET", "/api/invoices/<int:iid>"): AS,
 ("POST", "/api/invoices/<int:iid>/slips"): ("student",), ("GET", "/api/materials"): ALL, ("DELETE", "/api/materials/<int:mid>"): AT, ("GET", "/api/materials/<int:mid>/file"): ALL,
 ("GET", "/api/my/attendance"): ("student",), ("GET", "/api/my/batches"): ("student", "teacher"), ("GET", "/api/my/earnings"): ("teacher",), ("GET", "/api/my/fees"): ("student",),
 ("GET", "/api/my/fees/summary"): ("student",), ("GET", "/api/my/given-grades"): ("teacher",), ("GET", "/api/my/grades"): ("student",), ("GET", "/api/my/home"): ("student", "teacher"),
 ("GET", "/api/my/information"): ("student", "teacher"), ("GET", "/api/my/substitutions"): ("teacher",), ("GET", "/api/notifications"): ALL,
 ("POST", "/api/notifications/<int:nid>/read"): ALL, ("POST", "/api/notifications/read-all"): ALL, ("GET", "/api/notifications/unread-count"): ALL,
 ("GET", "/api/payments/<int:pid>/receipt.pdf"): AS, ("GET", "/api/recordings"): ALL, ("DELETE", "/api/recordings/<int:rid>"): AT, ("GET", "/api/slips/<int:sid>/file"): AS,
 ("GET", "/api/submissions/<int:sid>/file"): ALL, ("GET", "/api/teacher/dashboard"): ("teacher",), ("GET", "/api/timetable"): ALL,
 ("GET", "/api/tutorial-submissions/<int:sid>/file"): ALL, ("POST", "/api/tutorials"): AT, ("GET", "/api/tutorials"): ALL, ("GET", "/api/tutorials/<int:tid>"): ALL,
 ("DELETE", "/api/tutorials/<int:tid>"): AT, ("GET", "/api/tutorials/<int:tid>/file"): ALL, ("POST", "/api/tutorials/<int:tid>/submission"): ("student",),
 ("GET", "/api/tutorials/<int:tid>/submission"): ("student",), ("GET", "/api/tutorials/<int:tid>/submissions"): AT,
}
# admin-only routes with no permission area: each checks inside the route, and test_03 / test_04 prove it.
NO_AREA = {("GET", "/api/admin/dashboard"), ("GET", "/api/dashboard"), ("GET", "/api/users"), ("POST", "/api/whatsapp/prepare"), ("POST", "/api/whatsapp/sent")}
AREA = [("/api/applications", "admissions"), ("/api/announcements", "classroom"), ("/api/audit", "audit"), ("/api/discounts", "fees"), ("/api/families", "fees"), ("/api/fees", "fees"),
        ("/api/invoices", "fees"), ("/api/payments", "fees"), ("/api/slips", "fees"), ("/api/earnings", "finance"), ("/api/expense", "finance"), ("/api/finance", "finance"),
        ("/api/enrollments/<int:eid>/void-open-invoices", "fees"), ("/api/enrollment", "enrollments"), ("/api/import/enrolments", "enrollments"), ("/api/import", "people"),
        ("/api/settings", "settings"), ("/api/admin/storage", "settings"), ("/api/notifications", "settings"), ("/api/student-information", "student_information"), ("/api/teacher-information", "teacher_information"),
        ("/api/substitutions", "batches"), ("/api/users", "people"), ("/api/courses", "courses"), ("/api/batches", "batches")]
PUBLIC = {"/", "/<path:filename>", "/api/auth/login", "/api/cron/generate-invoices", "/api/cron/reminders", "/api/health", "/api/public/apply",
          "/api/public/apply/status", "/api/public/batches", "/api/public/courses", "/api/public/info"}
PARAM = {}


def build():
    tmp = tempfile.mkdtemp(); path = os.path.join(tmp, "t.db")
    os.environ.update(DATABASE_PATH=path, ADMIN_EMAIL="admin@m.test", ADMIN_PASSWORD="AdminPass123")
    import importlib; importlib.reload(sys.modules["seed"]) if "seed" in sys.modules else importlib.import_module("seed")
    from app import create_app
    app = create_app({"DATABASE_PATH": path}); c = app.test_client(); W = {"app": app, "c": c, "path": path}
    app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 12, 0, tzinfo=MVT)
    def tok(login, pw):
        r = c.post("/api/auth/login", json={"login": login, "password": pw}); return {"Authorization": "Bearer " + r.get_json()["token"]}
    A = tok("admin@m.test", "AdminPass123"); W["A"] = A
    def J(m, u, h=A, **kw):
        r = getattr(c, m)(u, headers=h, **kw); return r
    def mk(role, name, **kw):
        r = J("post", "/api/users", json={"email": f"{name.lower().replace(' ','')}@m.test", "password": PW, "full_name": name, "role": role, **kw})
        assert r.status_code == 201, r.get_json(); return r.get_json()["id"], f"{name.lower().replace(' ','')}@m.test"
    W["J"] = J
    t1, t2, t3 = mk("teacher", "Teach One"), mk("teacher", "Teach Two"), mk("teacher", "Teach Three")
    s1, s2, sw = mk("student", "Stud One"), mk("student", "Stud Two"), mk("student", "Stud Wd")
    lim = mk("admin", "Lim Admin"); J("patch", f"/api/users/{lim[0]}", json={"permissions": ["admissions"]})
    course = J("post", "/api/courses", json={"name": "Arabic", "monthly_fee_mvr": 100, "status": "open"}).get_json()["id"]
    b1 = J("post", "/api/batches", json={"course_id": course, "code": "B1", "teacher_id": t1[0], "capacity": 9, "days": "Mon,Wed", "start_time": "16:00"}).get_json()["id"]
    b2 = J("post", "/api/batches", json={"course_id": course, "code": "B2", "teacher_id": t2[0], "capacity": 9, "days": "Tue", "start_time": "16:00"}).get_json()["id"]
    for s, b in ((s1, b1), (sw, b1), (s2, b2)):
        r = J("post", "/api/enrollments", json={"student_id": s[0], "batch_id": b}); assert r.status_code == 201, r.get_json()
    W.update(t1=t1, t2=t2, t3=t3, s1=s1, s2=s2, sw=sw, lim=lim, course=course, b1=b1, b2=b2)
    for k in ("t1", "t2", "t3", "s1", "s2", "sw", "lim"): W["H_" + k] = tok(W[k][1], PW)
    return fill(W)


def fill(W):
    J, b1, b2 = W["J"], W["b1"], W["b2"]; ids = {}
    def mp(m, u, h, **kw): return J(m, u, h, content_type="multipart/form-data", **kw)
    r = J("post", f"/api/batches/{b1}/sessions", json={"date": "2027-03-10"}); assert r.status_code in (200, 201), r.get_json()
    ids["assignment"] = J("post", f"/api/batches/{b1}/assignments", json={"title": "HW1", "due_date": "2027-03-20", "max_points": 10}).get_json()["id"]
    r = mp("post", f"/api/batches/{b1}/materials", W["A"], data={"title": "Notes", "file": (io.BytesIO(PDF), "n.pdf")}); assert r.status_code == 201, r.get_json(); ids["material"] = r.get_json()["id"]
    r = J("post", f"/api/batches/{b1}/recordings", json={"title": "Rec", "url": "https://drive.google.com/file/d/abc/view", "recorded_on": "2027-03-09"}); assert r.status_code == 201, r.get_json(); ids["recording"] = r.get_json()["id"]
    r = mp("post", "/api/tutorials", W["A"], data={"title": "Tut", "text": "hello", "course_id": str(W["course"]), "file": (io.BytesIO(PDF), "t.pdf")}); assert r.status_code == 201, r.get_json(); ids["tutorial"] = r.get_json()["id"]
    r = mp("post", f"/api/assignments/{ids['assignment']}/submit", W["H_s1"], data={"text": "my answer", "file": (io.BytesIO(PDF), "a.pdf")}); assert r.status_code in (200, 201), r.get_json()
    ids["submission"] = J("get", f"/api/assignments/{ids['assignment']}/submissions").get_json()["students"][0]["submission_id"]
    r = mp("post", f"/api/tutorials/{ids['tutorial']}/submission", W["H_s1"], data={"text": "tut answer", "file": (io.BytesIO(PDF), "ta.pdf")}); assert r.status_code in (200, 201), r.get_json()
    ids["tut_sub"] = J("get", f"/api/tutorials/{ids['tutorial']}/submissions").get_json()["submissions"][0]["submission_id"] if "submission_id" in J("get", f"/api/tutorials/{ids['tutorial']}/submissions").get_json()["submissions"][0] else J("get", f"/api/tutorials/{ids['tutorial']}/submissions").get_json()["submissions"][0]["id"]
    inv = [i for i in J("get", "/api/invoices").get_json() if i["student_id"] == W["s1"][0]][0]; ids["invoice"] = inv["id"]
    r = mp("post", f"/api/invoices/{inv['id']}/slips", W["H_s1"], data={"amount_mvr": "100", "transfer_date": "2027-03-10", "reference": "R1", "file": (io.BytesIO(PDF), "s.pdf")}); assert r.status_code == 201, r.get_json()
    ids["slip"] = J("get", "/api/slips").get_json()[0]["id"]
    r = J("post", "/api/payments", json={"invoice_id": inv["id"], "amount_mvr": 40, "method": "cash", "paid_on": "2027-03-10"}); assert r.status_code == 201, r.get_json(); ids["payment"] = r.get_json()["payment"]["id"]
    r = J("post", "/api/expense-categories", json={"name": "Rent"}); ids["exp_cat"] = r.get_json()["id"]
    r = mp("post", "/api/expenses", W["A"], data={"expense_date": "2027-03-05", "amount_mvr": "500", "category_id": str(ids["exp_cat"]), "description": "rent", "receipt": (io.BytesIO(PDF), "r.pdf")}); assert r.status_code == 201, r.get_json(); ids["expense"] = r.get_json()["id"]
    ids["family"] = J("post", "/api/families", json={"name": "Fam"}).get_json()["id"]
    ids["discount"] = (J("get", "/api/discounts").get_json() or [{"id": 1}])[0]["id"] if J("get", "/api/discounts").get_json() else 1
    d = {"full_name": "Aisha Ali", "date_of_birth": "1990-01-01", "phone": "7771234", "email": "ap@m.test", "island": "Naifaru", "course_id": str(W["course"]), "batch_id": str(b1), "id_card": (io.BytesIO(PDF), "id.pdf")}
    r = W["c"].post("/api/public/apply", data=d, content_type="multipart/form-data"); assert r.status_code == 201, r.get_data(as_text=True)
    ids["application"] = max(a["id"] for a in J("get", "/api/applications").get_json())
    ids["enrollment"] = [e for e in J("get", "/api/enrollments").get_json() if e["student_id"] == W["s1"][0]][0]["id"]
    ids["substitution"] = 1; ids["earn_payment"] = 1
    ids["wd_enrollment"] = [e for e in J("get", "/api/enrollments").get_json() if e["student_id"] == W["sw"][0]][0]["id"]
    ids["wd_enrollment"] = [e for e in J("get", "/api/enrollments").get_json() if e["student_id"] == W["sw"][0]][0]["id"]
    W["ids"] = ids; return W


def routes(app):
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        f = app.view_functions[rule.endpoint]
        for m in sorted(rule.methods - {"HEAD", "OPTIONS"}): yield m, rule.rule, f


class S32(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["PORTAL_SKIP_FORCED_CHANGE"] = "1"
        W = build(); cls.W = W; cls.app, cls.c, cls.ids = W["app"], W["c"], W["ids"]
        W["J"]("post", "/api/substitutions", json={"batch_id": W["b1"], "substitute_teacher_id": W["t3"][0], "class_date": "2027-03-10", "ends_on": "2027-03-12", "reason": "x"})
        assert W["J"]("patch", f"/api/enrollments/{cls.ids['wd_enrollment']}", json={"status": "dropped"}).status_code == 200
        i = cls.ids
        PARAM.update({"applications": i["application"], "assignments": i["assignment"], "batches": W["b1"], "courses": W["course"], "discounts": i["discount"], "enrollments": i["enrollment"],
            "expense-categories": i["exp_cat"], "expenses": i["expense"], "families": i["family"], "invoices": i["invoice"], "materials": i["material"], "notifications": 1, "payments": i["payment"],
            "recordings": i["recording"], "slips": i["slip"], "student-information": W["s1"][0], "submissions": i["submission"], "substitutions": 1, "teacher-information": W["t1"][0],
            "tutorial-submissions": i["tut_sub"], "tutorials": i["tutorial"], "users": W["s1"][0], "student-history": W["s1"][0], "members": W["s1"][0]})
        cls.P = {"none": {}, "admin": W["A"], "lim": W["H_lim"], "t1": W["H_t1"], "t2": W["H_t2"], "t3": W["H_t3"], "s1": W["H_s1"], "s2": W["H_s2"], "sw": W["H_sw"]}
        cls.ROLE = {"admin": "admin", "lim": "admin", "t1": "teacher", "t2": "teacher", "t3": "teacher", "s1": "student", "s2": "student", "sw": "student"}

    @staticmethod
    def url(rule):
        parts, out = rule.split("/"), []
        for k, p in enumerate(parts):
            m = re.fullmatch(r"<(?:int:)?(\w+)>", p)
            out.append(p if not m else ("id" if m.group(1) == "which" else str(PARAM[parts[k - 1]])))
        return "/".join(out)

    def call(self, m, rule, who):
        r = getattr(self.c, m.lower())(self.url(rule), headers=self.P[who], **({"json": {}} if m != "GET" else {}))
        r.get_data(); r.close(); return r

    # ---- 1. the hand-written policy ----
    def test_01_every_route_is_either_public_by_decision_or_has_the_policy_roles(self):
        seen_public = set()
        for m, rule, f in routes(self.app):
            if not hasattr(f, "auth_roles"): seen_public.add(rule); continue
            want = set(OPEN.get((m, rule), ("admin",))); got = set(f.auth_roles or ALL)
            self.assertEqual(got, want, f"{m} {rule}: decorator allows {sorted(got)}, policy says {sorted(want)}")
        self.assertEqual(seen_public, PUBLIC, "a route without @auth appeared or disappeared: decide whether it may be public")

    def test_02_admin_only_routes_sit_in_the_right_permission_area(self):
        for m, rule, f in routes(self.app):
            if not hasattr(f, "auth_roles") or (m, rule) in OPEN: continue
            area = f.auth_perm.get("admin") if isinstance(f.auth_perm, dict) else f.auth_perm
            if (m, rule) in NO_AREA: self.assertIsNone(area, f"{m} {rule} now has an area: remove it from NO_AREA"); continue
            want = next((a for p, a in AREA if rule.startswith(p)), None)
            self.assertIsNotNone(want, f"{m} {rule}: add it to AREA or NO_AREA")
            self.assertEqual(area, want, f"{m} {rule}")

    # ---- 2. the matrix ----
    def test_03_no_token_is_401_everywhere(self):
        for m, rule, f in routes(self.app):
            if hasattr(f, "auth_roles"):
                r = self.call(m, rule, "none"); self.assertEqual(r.status_code, 401, f"{m} {rule}")
                self.assertIn("error", r.get_json())

    def test_04_matrix(self):
        for m, rule, f in routes(self.app):
            if not hasattr(f, "auth_roles"): continue
            area = f.auth_perm.get("admin") if isinstance(f.auth_perm, dict) else f.auth_perm
            for who in ("admin", "lim", "t1", "t2", "t3", "s1", "s2", "sw"):
                role = self.ROLE[who]; roles = f.auth_roles or ALL
                denied = role not in roles or (who == "lim" and isinstance(area, str) and area != "admissions")
                if who == "lim" and role in roles and area is None and (m, rule) in NO_AREA and m == "GET": denied = None   # checked in test_05
                if m != "GET" and not denied: continue                                                                    # allowed writes belong to the feature tests
                if denied is None: continue
                r = self.call(m, rule, who)
                if denied: self.assertEqual(r.status_code, 403, f"{who} {m} {rule} got {r.status_code}"); self.assertIn("error", r.get_json())
                else: self.assertLess(r.status_code, 500, f"{who} {m} {rule}")

    # ---- 3. the holes this session closed ----
    def test_05_limited_admin_gets_no_money_no_contacts_no_rosters(self):
        H, A = self.P["lim"], self.P["admin"]
        for u in ("/api/users", "/api/users?role=student", "/api/enrollments", f"/api/batches/{self.W['b1']}/students"):
            self.assertEqual(self.c.get(u, headers=H).status_code, 403, u)
        d = self.c.get("/api/dashboard", headers=H).get_json()
        for k in ("month_collection_mvr", "unpaid_invoices", "overdue_invoices", "slips_pending"): self.assertNotIn(k, d)
        self.assertIn("students", d)
        self.assertIn("month_collection_mvr", self.c.get("/api/dashboard", headers=A).get_json())
        self.assertNotIn("revenue", " ".join(self.c.get("/api/admin/dashboard", headers=H).get_json().keys()))

    def test_06_pickers_get_names_only_people_area_gets_contacts(self):
        J = self.W["J"]; uid = self.W["lim"][0]
        J("patch", f"/api/users/{uid}", json={"permissions": ["batches"]})
        r = self.c.get("/api/users?role=teacher", headers=self.P["lim"]); self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.get_json()[0]), {"id", "full_name", "role", "is_active"})
        J("patch", f"/api/users/{uid}", json={"permissions": ["people"]})
        self.assertIn("email", self.c.get("/api/users", headers=self.P["lim"]).get_json()[0])
        J("patch", f"/api/users/{uid}", json={"permissions": ["admissions"]})

    # ---- 4. other people's things ----
    def test_07_students_cannot_open_each_others_money_or_work(self):
        i = self.ids
        for u in (f"/api/invoices/{i['invoice']}", f"/api/slips/{i['slip']}/file", f"/api/payments/{i['payment']}/receipt.pdf"):
            self.assertEqual(self.c.get(u, headers=self.P["s1"]).status_code, 200, u)
            for who in ("s2", "sw"): self.assertIn(self.c.get(u, headers=self.P[who]).status_code, (403, 404), u)
        for u in (f"/api/submissions/{i['submission']}/file", f"/api/tutorial-submissions/{i['tut_sub']}/file"):
            self.assertEqual(self.c.get(u, headers=self.P["s2"]).status_code, 403, u)
        self.assertEqual(self.c.get("/api/my/fees", headers=self.P["s2"]).get_json()["invoices"][0]["student_id"], self.W["s2"][0])

    def test_08_withdrawn_student_sees_nothing_of_the_old_batch(self):
        H, i = self.P["sw"], self.ids
        for u in ("/api/assignments", "/api/materials", "/api/recordings", "/api/tutorials", "/api/my/grades", "/api/my/attendance", "/api/my/batches", "/api/timetable?from=2027-03-01&to=2027-03-31"):
            r = self.c.get(u, headers=H); self.assertEqual((r.status_code, r.get_json()), (200, []), u)
        for u in (f"/api/materials/{i['material']}/file", f"/api/tutorials/{i['tutorial']}", f"/api/tutorials/{i['tutorial']}/file", f"/api/tutorials/{i['tutorial']}/submission"):
            self.assertEqual(self.c.get(u, headers=H).status_code, 403, u)
        self.assertEqual(self.c.get(f"/api/submissions/{i['submission']}/file", headers=H).status_code, 403)

    def test_09_other_teacher_and_substitute_dates(self):
        b1, i = self.W["b1"], self.ids
        for u in (f"/api/batches/{b1}/attendance", f"/api/batches/{b1}/gradebook", f"/api/batches/{b1}/students", f"/api/assignments/{i['assignment']}/submissions", f"/api/submissions/{i['submission']}/file"):
            self.assertEqual(self.c.get(u, headers=self.P["t2"]).status_code, 403, u)
        for u in ("/api/assignments", "/api/materials", "/api/recordings"): self.assertEqual(self.c.get(u, headers=self.P["t2"]).get_json(), [], u)
        self.assertEqual(self.c.post(f"/api/batches/{b1}/sessions", json={"date": "2027-03-11"}, headers=self.P["t2"]).status_code, 403)
        a = f"/api/batches/{b1}/attendance"
        try:
            self.assertEqual(self.c.get(a, headers=self.P["t3"]).status_code, 200)                                              # inside the dates
            self.app.config["NOW"] = lambda: dt.datetime(2027, 3, 13, 12, 0, tzinfo=MVT)
            self.assertEqual(self.c.get(a, headers=self.P["t3"]).status_code, 403)                                              # the day after: access gone by itself
            self.assertEqual(self.c.get("/api/my/batches", headers=self.P["t3"]).get_json(), [])
        finally: self.app.config["NOW"] = lambda: dt.datetime(2027, 3, 10, 12, 0, tzinfo=MVT)

    # ---- 5. secrets ----
    def test_10_no_response_carries_a_hash_a_password_or_a_stored_file_key(self):
        con = sqlite3.connect(self.W["path"])
        needles = [r[0] for r in con.execute("SELECT password_hash FROM users")] + [PW, "scrypt:", "pbkdf2:"]
        needles += [r[0] for r in con.execute("SELECT id_file FROM applications WHERE id_file IS NOT NULL")] + [r[0] for r in con.execute("SELECT file FROM payment_slips")]
        for m, rule, f in routes(self.app):
            if m != "GET" or not hasattr(f, "auth_roles"): continue
            for who in ("admin", "t1", "s1"):
                r = self.call(m, rule, who)
                if r.status_code == 200 and r.mimetype in ("application/json", "text/csv", "text/plain"):
                    body = r.get_data(as_text=True)
                    for n in needles: self.assertNotIn(n, body, f"{who} {rule}")
        self.assertEqual([x for x in con.execute("SELECT action FROM audit_log") if "password" in str(x).lower() and "reset" not in str(x).lower() and "change" not in str(x).lower() and "login" not in str(x).lower()], [])

    def test_11_cron_endpoints_refuse_wrong_or_missing_secrets(self):
        self.app.config["CRON_SECRET"] = "right-secret"
        try:
            for u in ("/api/cron/generate-invoices", "/api/cron/reminders"):
                self.assertEqual(self.c.get(u).status_code, 401); self.assertEqual(self.c.get(u, headers={"Authorization": "Bearer wrong"}).status_code, 401)
                self.assertEqual(self.c.post(u + "?secret=right-secret").status_code, 401)                                      # never accepted in the URL
                self.assertEqual(self.c.get(u, headers={"Authorization": "Bearer right-secret"}).status_code, 200, u)
            self.app.config["CRON_SECRET"] = ""; os.environ.pop("CRON_SECRET", None)
            self.assertEqual(self.c.get("/api/cron/reminders", headers={"Authorization": "Bearer "}).status_code, 401)           # no secret set: closed
        finally: self.app.config["CRON_SECRET"] = ""

    def test_12_a_disabled_account_loses_its_token_at_once(self):
        J = self.W["J"]; r = J("post", "/api/users", json={"email": "gone@m.test", "password": PW, "full_name": "Gone", "role": "student"}); uid = r.get_json()["id"]
        h = {"Authorization": "Bearer " + self.c.post("/api/auth/login", json={"login": "gone@m.test", "password": PW}).get_json()["token"]}
        self.assertEqual(self.c.get("/api/my/home", headers=h).status_code, 200)
        J("patch", f"/api/users/{uid}", json={"is_active": False})
        self.assertEqual(self.c.get("/api/my/home", headers=h).status_code, 403)
        self.assertEqual(self.c.post("/api/auth/login", json={"login": "gone@m.test", "password": PW}).status_code in (401, 403), True)

    def test_13_errors_are_json_and_forged_tokens_fail(self):
        for h in ({"Authorization": "Bearer abc.def.ghi"}, {"Authorization": "Basic xyz"}, {"Authorization": "Bearer "}):
            r = self.c.get("/api/my/home", headers=h); self.assertEqual(r.status_code, 401); self.assertTrue(r.is_json)
        self.assertTrue(self.c.get("/api/nothing-here").is_json)
        self.assertEqual(self.c.get(f"/api/invoices/99999", headers=self.P["admin"]).status_code, 404)


if __name__ == "__main__": unittest.main()
