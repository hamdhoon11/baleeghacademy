"""Phase 3 - learning tools: timetable + Join class, attendance, assignments, grades, materials.

Registered from app.create_app(). All access rules are enforced here on the server:
  admin   -> everything
  teacher -> only batches where batches.teacher_id = their user id
  student -> only batches they are actively enrolled in (or completed), and only their own submissions/grades/attendance
Times are Maldives time (UTC+5, no daylight saving).
"""
import os, re, uuid, datetime as dt
from urllib.parse import urlparse
import common, substitutions
import settings_schema as SS
from flask import abort, jsonify, request, send_from_directory, g

MVT = dt.timezone(dt.timedelta(hours=5))
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]  # index = python weekday()
ATT = ("present", "late", "absent", "excused")
TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")

ALLOWED_SUBMISSION = (".pdf", ".jpg", ".jpeg", ".png", ".docx", ".mp3", ".m4a", ".mp4")
ALLOWED_MATERIAL = ALLOWED_SUBMISSION + (".pptx", ".xlsx")


def magic_ok(ext, head):
    if ext == ".pdf": return head.startswith(b"%PDF")
    if ext in (".jpg", ".jpeg"): return head.startswith(b"\xff\xd8\xff")
    if ext == ".png": return head.startswith(b"\x89PNG")
    if ext in (".docx", ".pptx", ".xlsx"): return head.startswith(b"PK\x03\x04")
    if ext == ".mp3": return head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)
    if ext in (".m4a", ".mp4"): return head[4:8] == b"ftyp"
    return False


def register(app, c):
    db, rows, one, audit, err, auth, need = c.db, c.rows, c.one, c.audit, c.err, c.auth, c.need
    # these calls serve several roles; each role is checked against its own area (students: their tab, teachers and admins: Classroom)
    A_PERM = {"student": "assignments", "teacher": "classroom", "admin": "classroom"}
    M_PERM = {"student": "materials", "teacher": "classroom", "admin": "classroom"}
    store = c.store

    # ---------- helpers ----------
    def join_early():
        """Minutes before class start that Join appears: the admin's Settings value, else the JOIN_EARLY_MIN env/config default."""
        v = c.raw_setting("join_early_min")
        try: return int(v) if v is not None and str(v).strip() else int(app.config.get("JOIN_EARLY_MIN", 15))
        except ValueError: return 15

    def now():
        fn = app.config.get("NOW")  # tests inject a fixed clock
        return fn() if fn else dt.datetime.now(MVT)

    def today():
        return now().date()

    def body():
        return request.get_json(silent=True) or {}

    def pdate(s):
        try: return dt.date.fromisoformat(str(s))
        except ValueError: return None

    def save_file(f, allowed):
        if not f or not f.filename: raise ValueError("A file is required")
        ext = os.path.splitext(f.filename.lower())[1]
        if ext not in allowed:
            raise ValueError("This file type is not allowed. Allowed: " + ", ".join(allowed))
        mb = common.cap_mb(int(app.config.get("LEARNING_MAX_MB", 20)))
        data = f.read(mb * 1024 * 1024 + 1)
        if len(data) > mb * 1024 * 1024: raise ValueError(f"File is too large ({mb} MB max)")
        if not magic_ok(ext, data[:16]): raise ValueError("File content does not match its type")
        name = uuid.uuid4().hex + ext
        store.put("learning", name, data)
        return name, common.shown_name(f.filename)

    def rm(name):
        if name: store.delete("learning", name)

    def send_private(stored, shown):
        return common.file_headers(store.send("learning", stored, shown or stored, as_attachment=True), shown or stored, attachment=True)

    BQ = ("SELECT b.id,b.code,b.days,b.start_time,b.start_date,b.status,b.meet_link,b.teacher_id,b.course_id,"
          "c.name AS course_name,COALESCE(c.minutes_per_class,60) AS minutes,u.full_name AS teacher_name "
          "FROM batches b JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=b.teacher_id")

    def teacher_batches(uid):
        """THE one rule for which batches a teacher may use: a set of batch ids. Today: the batches where they are the teacher.
        Every teacher check below and the batch list in app.py go through this, so substitutes (Session 22) plug in here only."""
        return {r["id"] for r in rows("SELECT id FROM batches WHERE teacher_id=?", (uid,))}
    app.extensions["teacher_batches"] = teacher_batches

    # ---------- substitute teachers (Session 22) ----------
    # teacher_batches() stays "my own batches": grades, assignments, materials, tutorials, information and cancelling use it, so a substitute gets none of that.
    # Only the class-information routes (picker, timetable, class students and join link, attendance) use class_batches(), which adds the
    # batches where the teacher is a substitute TODAY. Access ends by itself: it is a date comparison, not a stored flag.
    def sub_windows(uid, day=None):
        return substitutions.windows(rows, uid, (day or today()).isoformat())

    def class_batches(uid):
        return teacher_batches(uid) | set(sub_windows(uid))

    def sub_day_error(bid, day):
        """None for admins, the batch's own teacher, or a substitute inside their dates; else a 403 (a substitute may not read other dates)."""
        if g.user["role"] != "teacher" or bid in teacher_batches(g.user["id"]): return None
        if any(a <= day.isoformat() <= z for a, z in sub_windows(g.user["id"], day).get(bid, [])): return None
        return err("You are a substitute for this batch only on the dates the admin set", 403)

    def batch(bid):
        return one(BQ + " WHERE b.id=?", (bid,))

    def manage(bid, cls=False):
        """Admin, or the batch's own teacher (cls=True: or today's substitute, for class-information routes only). Returns (batch, None) or (None, error response)."""
        b = batch(bid)
        if not b: return None, err("Batch not found", 404)
        if g.user["role"] == "admin" or (g.user["role"] == "teacher" and bid in (class_batches(g.user["id"]) if cls else teacher_batches(g.user["id"]))):
            return b, None
        return None, err("This is not your batch", 403)

    def viewable(bid):
        """manage() rights, or a student with an ACTIVE enrolment in the batch (dropped, transferred, waitlisted and completed students get 403)."""
        b = batch(bid)
        if not b: return None, err("Batch not found", 404)
        u = g.user
        if u["role"] == "admin" or (u["role"] == "teacher" and bid in teacher_batches(u["id"])): return b, None
        if u["role"] == "student" and one("SELECT 1 x FROM enrollments WHERE student_id=? AND batch_id=? AND status='active'", (u["id"], bid)):
            return b, None
        return None, err("You do not have access to this batch", 403)

    def my_batches(batch_id=None, scope="own"):
        """scope="class" also includes the batches where a teacher substitutes today (picker, timetable only); everything else stays "own"."""
        u, w, a = g.user, [], []
        if u["role"] == "teacher":
            mine = sorted(class_batches(u["id"]) if scope == "class" else teacher_batches(u["id"]))
            if batch_id and batch_id not in mine: abort(403, "This is not your batch")   # an unassigned batch: 403, not an empty list (Session 15)
            if not mine: return []
            w.append(f"b.id IN ({','.join('?' * len(mine))})"); a += mine
        if u["role"] == "student":
            w.append("b.id IN (SELECT batch_id FROM enrollments WHERE student_id=? AND status='active')"); a.append(u["id"])
        if batch_id:
            w.append("b.id=?"); a.append(batch_id)
            if u["role"] == "student" and not one("SELECT 1 x FROM enrollments WHERE student_id=? AND batch_id=? AND status='active'", (u["id"], batch_id)):
                abort(403, "You do not have access to this batch")   # a batch the student is not actively in: 403, not an empty list (Session 14)
        return rows(BQ + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY b.id", a)

    # ---------- class links (Session 4) ----------
    def can(area):
        pl = g.user.get("permissions")
        if pl is None: return area not in SS.OPT_IN.get(g.user["role"], ())   # opt-in areas (edit_grades) are not part of "everything"
        return area in [x for x in pl.split(",") if x]

    def gate(*areas):
        """Error response unless the signed-in person has every one of these areas (permissions NULL = everything their role has)."""
        if not all(can(a) for a in areas): return err("Your account does not have permission for this area", 403)

    def clean_link(v):
        """(link or None, error). Empty removes the link; otherwise it must be a plain https address."""
        v = (v or "").strip() if isinstance(v, str) or v is None else None
        if v is None: return None, err("The link must be text")
        if not v: return None, None
        if len(v) > 500 or not re.match(r"^https://\S+$", v): return None, err("The class link must start with https://")
        return v, None

    @app.put("/api/batches/<int:bid>/meet-link")
    @auth("admin", "teacher", perm="class_links")
    def l_batch_link(bid):
        """Set (or clear) the Meet link of a batch: a teacher only for their own batches, an admin for any."""
        b, e = manage(bid)
        if e: return e
        link, e = clean_link(body().get("meet_link"))
        if e: return e
        db().execute("UPDATE batches SET meet_link=? WHERE id=?", (link, bid))
        audit("set_class_link", "batch", bid, f"{b['code']}: " + ("link set" if link else "link removed"), batch_id=bid); db().commit()
        return jsonify(ok=True, meet_link=link)

    # ---------- timetable ----------
    def occurrences(batches, d0, d1):
        """Weekly pattern from batches.days + start_time, overridden/extended by rows in `sessions` (cancelled, extra, held)."""
        out = []
        ids = [b["id"] for b in batches if b["status"] != "closed"]
        sess = {}
        if ids:
            q = ",".join("?" * len(ids))
            for s in rows(f"SELECT * FROM sessions WHERE batch_id IN ({q}) AND session_date BETWEEN ? AND ?", (*ids, d0.isoformat(), d1.isoformat())):
                sess[(s["batch_id"], s["session_date"], s["start_time"])] = s
        for b in batches:
            if b["status"] == "closed": continue
            seen = {}
            wanted = {DAYS.index(x) for x in (b["days"] or "").split(",") if x in DAYS}
            if wanted and b["start_time"]:
                d = d0
                while d <= d1:
                    if d.weekday() in wanted and (not b["start_date"] or d.isoformat() >= b["start_date"]):
                        seen[(d.isoformat(), b["start_time"])] = {"status": "scheduled", "extra": False, "session_id": None, "topic": None, "note": None, "own_link": None}
                    d += dt.timedelta(days=1)
            for (bid, sd, st), s in sess.items():
                if bid != b["id"]: continue
                seen[(sd, st)] = {"status": s["status"], "extra": (sd, st) not in seen, "session_id": s["id"], "topic": s["topic"], "note": s["note"], "own_link": s.get("meet_link")}
            for (sd, st), o in seen.items():
                start = dt.datetime.combine(dt.date.fromisoformat(sd), dt.time.fromisoformat(st), tzinfo=MVT)
                end = start + dt.timedelta(minutes=b["minutes"])
                n = now()
                early = dt.timedelta(minutes=join_early())
                link = o["own_link"] or b["meet_link"]   # a one-off link for this class wins over the batch's link
                o["own_link"] = bool(o["own_link"])
                o.update(batch_id=b["id"], batch_code=b["code"], course_name=b["course_name"], teacher_name=b["teacher_name"],
                         date=sd, weekday=DAYS[start.weekday()], start_time=st, end_time=end.strftime("%H:%M"), minutes=b["minutes"],
                         meet_link=link, starts_at=start.isoformat(), _start=start, _end=end,
                         can_join=bool(o["status"] != "cancelled" and link and start - early <= n <= end),
                         live=bool(o["status"] != "cancelled" and start <= n <= end))
                out.append(o)
        out.sort(key=lambda o: (o["date"], o["start_time"], o["batch_id"]))
        return out

    def clean(o):
        return {k: v for k, v in o.items() if not k.startswith("_")}

    def next_class(occ):
        n = now()
        for o in occ:
            if o["status"] != "cancelled" and o["_end"] >= n: return o
        return None

    @app.get("/api/timetable")
    @auth()
    def l_timetable():
        d0 = pdate(request.args.get("from")) or today()
        d1 = pdate(request.args.get("to")) or d0 + dt.timedelta(days=13)
        if d1 < d0 or (d1 - d0).days > 62: return err("Choose a date range of up to 62 days")
        bid = request.args.get("batch_id", type=int)
        out = [clean(o) for o in occurrences(my_batches(bid, "class"), d0, d1)]
        if g.user["role"] == "teacher":   # as a substitute: only the substituted dates of that batch
            own = teacher_batches(g.user["id"]); win = sub_windows(g.user["id"])
            out = [o for o in out if o["batch_id"] in own or any(a <= o["date"] <= z for a, z in win.get(o["batch_id"], []))]
        return jsonify(out)

    @app.post("/api/batches/<int:bid>/sessions")
    @auth("admin", "teacher", perm="classroom")
    def l_session_set(bid):
        b, e = manage(bid)
        if e: return e
        d = body()
        day = pdate(d.get("date"))
        if not day: return err("Enter a valid date")
        st = d.get("start_time") or b["start_time"]
        if not st or not TIME.match(str(st)): return err("Enter a start time (HH:MM)")
        status = d.get("status", "scheduled")
        if status not in ("scheduled", "cancelled"): return err("Status must be scheduled or cancelled")
        if status == "cancelled" and g.user["role"] != "admin" and not can("cancel_class"):   # opt-in for teachers (Session 18)
            return err("Your account does not have permission to cancel classes", 403)
        # a one-off link for this class only: needs the Class links permission; an empty value removes it
        has_link = "meet_link" in d
        link = None
        if has_link:
            e = gate("class_links")
            if e: return e
            link, e = clean_link(d.get("meet_link"))
            if e: return e
        ex = one("SELECT * FROM sessions WHERE batch_id=? AND session_date=? AND start_time=?", (bid, day.isoformat(), st))
        if ex:
            if ex["status"] == "held" and status == "cancelled": return err("This class already has attendance, so it cannot be cancelled", 409)
            new_status = "held" if ex["status"] == "held" else status
            db().execute("UPDATE sessions SET status=?,topic=COALESCE(?,topic),note=COALESCE(?,note) WHERE id=?", (new_status, d.get("topic"), d.get("note"), ex["id"]))
            if has_link: db().execute("UPDATE sessions SET meet_link=? WHERE id=?", (link, ex["id"]))
            sid = ex["id"]
        else:
            sid = db().execute("INSERT INTO sessions(batch_id,session_date,start_time,status,topic,note,meet_link,created_by) VALUES(?,?,?,?,?,?,?,?)",
                               (bid, day.isoformat(), st, status, d.get("topic"), d.get("note"), link, g.user["id"])).lastrowid
        audit("session_" + status, "session", sid, f"batch {bid} {day} {st}", batch_id=bid, old=ex["status"] if ex else None, new=new_status if ex else status)
        if has_link: audit("set_class_link", "session", sid, f"batch {bid} {day} {st}: " + ("one-off link set" if link else "one-off link removed"), batch_id=bid)
        was = ex["status"] if ex else "scheduled"   # Session 28: tell students (and the teacher, when someone else changed it) only when the state really changes
        now_st = new_status if ex else status
        if (was == "cancelled") != (now_st == "cancelled"):
            kind_, title_ = ("class_cancelled", "Class cancelled") if now_st == "cancelled" else ("class_reinstated", "Class is back on")
            text_ = f"{day.strftime('%a %d %b')} at {st}" + (f": {d.get('note')}" if now_st == "cancelled" and d.get("note") else "")
            c.notify(c.notify_students_of(bid), kind_, title_, text_, "home")   # students have no Classroom tab
            if b["teacher_id"] != g.user["id"]: c.notify([b["teacher_id"]], kind_, title_, text_, f"classroom:{bid}")   # Session 16: opens that batch's schedule
        db().commit()
        return jsonify(id=sid), 201

    # ---------- attendance ----------
    def threshold():
        v = c.raw_setting("low_attendance_pct")
        try: return int(v) if v is not None else 75
        except ValueError: return 75

    def stat(p, l, ab, ex):
        p, l, ab, ex = p or 0, l or 0, ab or 0, ex or 0
        counted = p + l + ab  # excused classes are not counted for or against the student
        pct = round((p + l) * 100 / counted, 1) if counted else None
        return dict(present=p, late=l, absent=ab, excused=ex, counted=counted, pct=pct,
                    low=bool(pct is not None and counted >= 3 and pct < threshold()))

    ATT_SQL = ("SELECT a.student_id,SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) p,SUM(CASE WHEN a.status='late' THEN 1 ELSE 0 END) l,"
               "SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) ab,SUM(CASE WHEN a.status='excused' THEN 1 ELSE 0 END) ex "
               "FROM attendance a JOIN sessions s ON s.id=a.session_id WHERE s.batch_id=? ")

    def batch_att(bid, student_id=None):
        if student_id:
            r = one(ATT_SQL + "AND a.student_id=? GROUP BY a.student_id", (bid, student_id))
            return stat(*(r[k] for k in ("p", "l", "ab", "ex"))) if r else stat(0, 0, 0, 0)
        return {r["student_id"]: stat(r["p"], r["l"], r["ab"], r["ex"]) for r in rows(ATT_SQL + "GROUP BY a.student_id", (bid,))}

    def roster(bid, status="active"):
        return rows("SELECT u.id,u.full_name,u.phone FROM enrollments e JOIN users u ON u.id=e.student_id WHERE e.batch_id=? AND e.status=? ORDER BY u.full_name", (bid, status))

    def marks(n):
        return ",".join("?" * n)

    def att_multi(bids, student_id=None):
        """{batch_id: {student_id: stat}} for several batches in ONE query (or just that student's stats when student_id is given)."""
        out = {b: {} for b in bids}
        if not bids: return out
        sql = ("SELECT s.batch_id,a.student_id,SUM(CASE WHEN a.status='present' THEN 1 ELSE 0 END) p,SUM(CASE WHEN a.status='late' THEN 1 ELSE 0 END) l,"
               "SUM(CASE WHEN a.status='absent' THEN 1 ELSE 0 END) ab,SUM(CASE WHEN a.status='excused' THEN 1 ELSE 0 END) ex "
               f"FROM attendance a JOIN sessions s ON s.id=a.session_id WHERE s.batch_id IN ({marks(len(bids))}) ")
        args = list(bids)
        if student_id: sql += "AND a.student_id=? "; args.append(student_id)
        for r in rows(sql + "GROUP BY s.batch_id,a.student_id", args):
            out[r["batch_id"]][r["student_id"]] = stat(r["p"], r["l"], r["ab"], r["ex"])
        return out

    def roster_multi(bids):
        """{batch_id: [active students]} for several batches in ONE query."""
        out = {b: [] for b in bids}
        if not bids: return out
        for r in rows(f"SELECT e.batch_id,u.id,u.full_name,u.phone FROM enrollments e JOIN users u ON u.id=e.student_id WHERE e.batch_id IN ({marks(len(bids))}) AND e.status='active' ORDER BY u.full_name", list(bids)):
            out[r.pop("batch_id")].append(r)
        return out

    @app.get("/api/batches/<int:bid>/attendance")
    @auth("admin", "teacher", perm="classroom")
    def l_att_get(bid):
        b, e = manage(bid, cls=True)
        if e: return e
        day = pdate(request.args.get("date")) or today()
        e = sub_day_error(bid, day)
        if e: return e
        st = request.args.get("start_time") or b["start_time"]
        sess = one("SELECT * FROM sessions WHERE batch_id=? AND session_date=? AND start_time=?", (bid, day.isoformat(), st)) if st else None
        marks = {r["student_id"]: r for r in rows("SELECT student_id,status,note FROM attendance WHERE session_id=?", (sess["id"],))} if sess else {}
        students = [{**s, "status": marks.get(s["id"], {}).get("status"), "note": marks.get(s["id"], {}).get("note")} for s in roster(bid)]
        return jsonify(date=day.isoformat(), start_time=st, session=sess, students=students)

    @app.post("/api/batches/<int:bid>/attendance")
    @auth("admin", "teacher", perm="classroom")
    def l_att_save(bid):
        b, e = manage(bid, cls=True)
        if e: return e
        d = body()
        day = pdate(d.get("date"))
        if not day: return err("Enter a valid date")
        e = sub_day_error(bid, day)
        if e: return e
        as_sub = g.user["role"] == "teacher" and bid not in teacher_batches(g.user["id"])
        if day > today(): return err("You cannot mark attendance for a class that has not happened yet")
        st = d.get("start_time") or b["start_time"]
        if not st or not TIME.match(str(st)): return err("Enter a start time (HH:MM)")
        recs = d.get("records")
        if not isinstance(recs, list) or not recs: return err("No attendance records sent")
        active = {r["id"] for r in roster(bid)}
        clean_recs = []
        for r in recs:
            try: sid = int(r.get("student_id"))
            except (TypeError, ValueError, AttributeError): return err("Each record needs a student_id")
            if r.get("status") not in ATT: return err("Status must be one of: " + ", ".join(ATT))
            if sid not in active: return err(f"Student {sid} is not actively enrolled in this batch")
            clean_recs.append((sid, r["status"], (r.get("note") or None)))
        sess = one("SELECT * FROM sessions WHERE batch_id=? AND session_date=? AND start_time=?", (bid, day.isoformat(), st))
        if sess and sess["status"] == "cancelled": return err("This class is marked cancelled. Reinstate it first.", 409)
        if sess:
            sid_ = sess["id"]
            db().execute("UPDATE sessions SET status='held',topic=COALESCE(?,topic) WHERE id=?", (d.get("topic"), sid_))
        else:
            sid_ = db().execute("INSERT INTO sessions(batch_id,session_date,start_time,status,topic,created_by) VALUES(?,?,?,'held',?,?)",
                                (bid, day.isoformat(), st, d.get("topic"), g.user["id"])).lastrowid
        prev = {r["student_id"]: r["status"] for r in rows("SELECT student_id,status FROM attendance WHERE session_id=?", (sid_,))}
        was = [f"{s}:{prev[s]}" for s, st_, _ in clean_recs if s in prev and prev[s] != st_]
        now = [f"{s}:{st_}" for s, st_, _ in clean_recs if prev.get(s) != st_]   # new marks and changed marks
        for sid, status, note in clean_recs:
            db().execute("INSERT INTO attendance(session_id,student_id,status,note,marked_by) VALUES(?,?,?,?,?) "
                         "ON CONFLICT(session_id,student_id) DO UPDATE SET status=excluded.status,note=excluded.note,marked_by=excluded.marked_by,marked_at=datetime('now')",
                         (sid_, sid, status, note, g.user["id"]))
        audit("mark_attendance", "session", sid_, f"batch {bid} {day} ({len(clean_recs)} students)" + (" as substitute" if as_sub else ""), batch_id=bid, old=",".join(was) or None, new=",".join(now) or "no change"); db().commit()
        return jsonify(session_id=sid_, saved=len(clean_recs))

    @app.get("/api/batches/<int:bid>/attendance/summary")
    @auth("admin", "teacher", perm="classroom")
    def l_att_summary(bid):
        b, e = manage(bid)
        if e: return e
        st = batch_att(bid)
        held = one("SELECT COUNT(*) n FROM sessions WHERE batch_id=? AND status='held'", (bid,))["n"]
        return jsonify(threshold=threshold(), classes_held=held,
                       students=[{**s, **st.get(s["id"], stat(0, 0, 0, 0))} for s in roster(bid)])

    @app.get("/api/my/batches")
    @auth("student", "teacher")
    def l_my_batches():
        """The batches this person works in: a student's ACTIVE enrolments, or the teacher's own batches (teacher_batches). The choices of the picker."""
        return jsonify([{"id": b["id"], "code": b["code"], "course_id": b["course_id"], "course_name": b["course_name"], "teacher_name": b["teacher_name"],
                         "days": b["days"], "start_time": b["start_time"]} for b in my_batches(scope="class")] if g.user["role"] != "teacher" else
                       [{"id": b["id"], "code": b["code"], "course_id": b["course_id"], "course_name": b["course_name"], "teacher_name": b["teacher_name"],
                         "days": b["days"], "start_time": b["start_time"],
                         **({"substitute_until": max(z for a, z in sub_windows(g.user["id"]).get(b["id"], [(0, "")]))} if b["id"] not in teacher_batches(g.user["id"]) else {})}
                        for b in my_batches(scope="class")])

    @app.get("/api/my/attendance")
    @auth("student", perm="progress")
    def l_my_att():
        out = []
        for b in my_batches(request.args.get("batch_id", type=int)):
            recent = rows("SELECT s.session_date AS date,a.status FROM attendance a JOIN sessions s ON s.id=a.session_id "
                          "WHERE s.batch_id=? AND a.student_id=? ORDER BY s.session_date DESC LIMIT 20", (b["id"], g.user["id"]))
            out.append({"batch_id": b["id"], "course_name": b["course_name"], "batch_code": b["code"], **batch_att(b["id"], g.user["id"]), "recent": recent})
        return jsonify(out)

    # ---------- assignments, tests and grades ----------
    def aget(aid):
        return one("SELECT a.*,b.teacher_id FROM assignments a JOIN batches b ON b.id=a.batch_id WHERE a.id=?", (aid,))

    def a_manage(aid):
        a = aget(aid)
        if not a: return None, err("Assignment not found", 404)
        b, e = manage(a["batch_id"])
        return (a, None) if not e else (None, e)

    def points(v, mx):
        try: n = round(float(v), 2)
        except (TypeError, ValueError): return None
        return n if 0 <= n <= mx else None

    @app.post("/api/batches/<int:bid>/assignments")
    @auth("admin", "teacher", perm="classroom")
    def l_assign_create(bid):
        """Written instructions (description), an attached file, or both. Sent as a form when a file is attached, JSON otherwise."""
        b, e = manage(bid)
        if e: return e
        d = request.form if request.form else body()
        m = need(d, "title")
        if m: return err(m)
        kind = d.get("kind", "assignment")
        if kind not in ("assignment", "test"): return err("Kind must be assignment or test")
        try: mx = int(d.get("max_points") or 100)
        except (TypeError, ValueError): return err("Maximum points must be a number")
        if mx <= 0 or mx > 1000: return err("Maximum points must be between 1 and 1000")
        due = d.get("due_date") or None
        if due and not pdate(due): return err("Enter a valid due date")
        up, stored, shown = request.files.get("file"), None, None
        if up and up.filename:
            try: stored, shown = save_file(up, ALLOWED_MATERIAL)
            except ValueError as x: return err(str(x))
        aid = db().execute("INSERT INTO assignments(batch_id,title,description,kind,due_date,max_points,attachment,attachment_name,created_by) VALUES(?,?,?,?,?,?,?,?,?)",
                           (bid, d["title"].strip(), (d.get("description") or "").strip() or None, kind, due, mx, stored, shown, g.user["id"])).lastrowid
        audit("create_assignment", "assignment", aid, d["title"] + (" (with file)" if stored else ""), batch_id=bid)
        c.notify(c.notify_students_of(bid), "assignment_new", "New " + ("test" if kind == "test" else "assignment"), d["title"].strip() + (f" (due {due[:10]})" if due else ""), f"assignments:{aid}")   # Session 28; link opens it (Session 16)
        db().commit()
        return jsonify(id=aid), 201

    @app.get("/api/assignments/<int:aid>/attachment")
    @auth(perm=A_PERM)
    def l_assign_attachment(aid):
        a = aget(aid)
        if not a or not a["attachment"]: return err("File not found", 404)
        b, e = viewable(a["batch_id"])
        if e: return e
        return send_private(a["attachment"], a["attachment_name"])

    @app.patch("/api/assignments/<int:aid>")
    @auth("admin", "teacher", perm="classroom")
    def l_assign_update(aid):
        a, e = a_manage(aid)
        if e: return e
        d = body()
        f = [k for k in ("title", "description", "due_date", "max_points") if k in d]
        if not f: return err("Nothing to update")
        if "due_date" in d and d["due_date"] and not pdate(d["due_date"]): return err("Enter a valid due date")
        if "max_points" in d:
            try: mp = int(d["max_points"])
            except (TypeError, ValueError): return err("Maximum points must be a number")
            if mp <= 0 or mp > 1000: return err("Maximum points must be between 1 and 1000")
            if one("SELECT 1 x FROM submissions WHERE assignment_id=? AND grade > ?", (aid, mp)): return err("Some grades are higher than that. Change those first.", 409)
            d["max_points"] = mp
        db().execute(f"UPDATE assignments SET {','.join(k + '=?' for k in f)} WHERE id=?", (*[d[k] for k in f], aid))
        audit("update_assignment", "assignment", aid, ",".join(f), batch_id=a["batch_id"]); db().commit()
        return jsonify(ok=True)

    @app.delete("/api/assignments/<int:aid>")
    @auth("admin", "teacher", perm="classroom")
    def l_assign_delete(aid):
        a, e = a_manage(aid)
        if e: return e
        for s in rows("SELECT file FROM submissions WHERE assignment_id=?", (aid,)): rm(s["file"])
        rm(a["attachment"])
        db().execute("DELETE FROM submissions WHERE assignment_id=?", (aid,))
        db().execute("DELETE FROM assignments WHERE id=?", (aid,))
        audit("delete_assignment", "assignment", aid, a["title"], batch_id=a["batch_id"]); db().commit()
        return jsonify(ok=True)

    # ONE definition of the assignment counts (Session 18). Only students who are ACTIVE in the batch count, each student once per assignment
    # (COUNT DISTINCT), whatever the number of rows or resubmissions. "Pending grading" = handed in, no grade yet, kind 'assignment' (a test has no hand-in).
    def assign_counts(aids):
        """{assignment_id: {students, submitted, graded, pending}} for these assignments."""
        if not aids: return {}
        out = {r["id"]: {"students": r["n"], "submitted": r["sub"], "graded": r["gr"], "pending": r["pend"]} for r in rows(
            "SELECT a.id,COUNT(DISTINCT e.student_id) n,"
            "COUNT(DISTINCT CASE WHEN s.submitted_at IS NOT NULL THEN s.student_id END) sub,"
            "COUNT(DISTINCT CASE WHEN s.grade IS NOT NULL THEN s.student_id END) gr,"
            "COUNT(DISTINCT CASE WHEN s.submitted_at IS NOT NULL AND s.grade IS NULL AND a.kind='assignment' THEN s.student_id END) pend "
            "FROM assignments a JOIN enrollments e ON e.batch_id=a.batch_id AND e.status='active' "
            f"LEFT JOIN submissions s ON s.assignment_id=a.id AND s.student_id=e.student_id WHERE a.id IN ({marks(len(aids))}) GROUP BY a.id", list(aids))}
        return {i: out.get(i, {"students": 0, "submitted": 0, "graded": 0, "pending": 0}) for i in aids}

    def pending_grading(bids):
        """Number of hand-ins waiting for a grade in these batches (sum of assign_counts' pending). Used by the teacher Home and Teacher information."""
        if not bids: return 0
        aids = [r["id"] for r in rows(f"SELECT id FROM assignments WHERE kind='assignment' AND batch_id IN ({marks(len(bids))})", list(bids))]
        return sum(c["pending"] for c in assign_counts(aids).values())

    def scope_counts(bids, d1=None, d2=None):
        """Session 25: class and assignment numbers for a set of batches, used by the admin dashboard. d1/d2 are Maldives dates ('YYYY-MM-DD') or None.
        Classes use the sessions table (held / cancelled by session_date) and occurrences() (upcoming); assignments, tests, hand-ins, graded and pending
        all come from assign_counts() (Session 18), limited to assignments given (created) in the date range. Nothing is counted a second way."""
        out = {"classes_held": 0, "classes_cancelled": 0, "classes_upcoming": 0, "assignments": 0, "tests": 0, "submissions": 0, "graded": 0, "pending_grading": 0}
        if not bids: return out
        m, t0 = marks(len(bids)), today()
        w, a = "", []
        if d1: w += " AND session_date>=?"; a.append(d1)
        if d2: w += " AND session_date<=?"; a.append(d2)
        for r in rows(f"SELECT status,COUNT(*) n FROM sessions WHERE batch_id IN ({m}){w} GROUP BY status", [*bids, *a]):
            if r["status"] == "held": out["classes_held"] = r["n"]
            elif r["status"] == "cancelled": out["classes_cancelled"] = r["n"]
        start = max(t0, dt.date.fromisoformat(d1)) if d1 else t0
        end = min(dt.date.fromisoformat(d2) if d2 else t0 + dt.timedelta(days=27), t0 + dt.timedelta(days=92))   # upcoming looks ahead 28 days unless a range ends sooner, never beyond 92
        if end >= start:
            bs = rows(BQ + f" WHERE b.id IN ({m}) ORDER BY b.id", list(bids))
            out["classes_upcoming"] = sum(1 for o in occurrences(bs, start, end) if o["date"] >= t0.isoformat() and o["status"] not in ("cancelled", "held"))
        import auditview
        w2, a2 = "", []
        if d1: w2 += " AND created_at>=?"; a2.append(auditview.utc_bounds(d1))
        if d2: w2 += " AND created_at<?"; a2.append(auditview.utc_bounds(d2, end=True))
        asg = rows(f"SELECT id,kind FROM assignments WHERE batch_id IN ({m}){w2}", [*bids, *a2])
        cnt = assign_counts([x["id"] for x in asg])
        out.update(assignments=sum(1 for x in asg if x["kind"] == "assignment"), tests=sum(1 for x in asg if x["kind"] == "test"),
                   submissions=sum(c["submitted"] for c in cnt.values()), graded=sum(c["graded"] for c in cnt.values()), pending_grading=sum(c["pending"] for c in cnt.values()))
        return out
    app.extensions["scope_counts"] = scope_counts

    @app.get("/api/assignments")
    @auth(perm=A_PERM)
    def l_assign_list():
        u = g.user
        bid = request.args.get("batch_id", type=int)
        ids = [b["id"] for b in my_batches(bid)]
        if not ids: return jsonify([])
        q = ",".join("?" * len(ids))
        base = ("SELECT a.id,a.batch_id,a.title,a.description,a.kind,a.due_date,a.max_points,a.created_at,a.attachment_name,(a.attachment IS NOT NULL) AS has_attachment,b.code AS batch_code,c.name AS course_name "
                "FROM assignments a JOIN batches b ON b.id=a.batch_id JOIN courses c ON c.id=b.course_id")
        items = rows(f"{base} WHERE a.batch_id IN ({q}) ORDER BY COALESCE(a.due_date,'9999-12-31'),a.id DESC", ids)
        aids = [a["id"] for a in items]
        if aids and u["role"] == "student":
            subs = {r["assignment_id"]: r for r in rows(f"SELECT assignment_id,id,submitted_at,is_late,grade,feedback,graded_at,text_answer,file_name,(file IS NOT NULL) AS has_file FROM submissions WHERE student_id=? AND assignment_id IN ({marks(len(aids))})", [u["id"], *aids])}
        elif aids:
            cnt = assign_counts(aids)
        for a in items:
            if u["role"] == "student":
                s = subs.get(a["id"])
                a["my"] = {"submission_id": s["id"] if s else None, "submitted": bool(s and s["submitted_at"]), "is_late": bool(s and s["is_late"]), "grade": s["grade"] if s else None,
                           "feedback": s["feedback"] if s else None, "text_answer": s["text_answer"] if s else None,
                           "file_name": s["file_name"] if s else None, "has_file": bool(s and s["has_file"])}
            else:
                n = cnt[a["id"]]
                a["submitted_count"], a["graded_count"], a["student_count"], a["pending_count"] = n["submitted"], n["graded"], n["students"], n["pending"]
        return jsonify(items)

    @app.post("/api/assignments/<int:aid>/submit")
    @auth("student", perm="assignments")
    def l_submit(aid):
        a = aget(aid)
        if not a: return err("Assignment not found", 404)
        if not one("SELECT 1 x FROM enrollments WHERE student_id=? AND batch_id=? AND status='active'", (g.user["id"], a["batch_id"])):
            return err("You are not enrolled in this batch", 403)
        text = (request.form.get("text") or "").strip()[:10000]
        f = request.files.get("file")
        if not text and not (f and f.filename): return err("Write an answer or attach a file")
        old = one("SELECT * FROM submissions WHERE assignment_id=? AND student_id=?", (aid, g.user["id"]))
        if old and old["grade"] is not None: return err("This work is already graded and can no longer be changed", 409)
        stored = shown = None
        if f and f.filename:
            try: stored, shown = save_file(f, ALLOWED_SUBMISSION)
            except ValueError as x: return err(str(x))
        late = int(bool(a["due_date"] and today().isoformat() > a["due_date"]))
        if old:
            if stored: rm(old["file"])
            # sending only new text keeps the file from the earlier submission (it used to be wiped)
            db().execute("UPDATE submissions SET text_answer=?,file=?,file_name=?,submitted_at=datetime('now'),is_late=? WHERE id=?",
                         (text or None, stored or old["file"], shown or old["file_name"], late, old["id"]))
            sid = old["id"]
        else:
            sid = db().execute("INSERT INTO submissions(assignment_id,student_id,text_answer,file,file_name,submitted_at,is_late) VALUES(?,?,?,?,?,datetime('now'),?)",
                               (aid, g.user["id"], text or None, stored, shown, late)).lastrowid
        audit("submit_assignment", "submission", sid, a["title"], batch_id=a["batch_id"], old="resubmitted" if old else None, new="submitted"); db().commit()
        return jsonify(id=sid, is_late=bool(late)), 201

    @app.get("/api/assignments/<int:aid>/submissions")
    @auth("admin", "teacher", perm="classroom")
    def l_subs(aid):
        a, e = a_manage(aid)
        if e: return e
        subs = {s["student_id"]: s for s in rows("SELECT id,student_id,text_answer,file_name,(file IS NOT NULL) AS has_file,submitted_at,is_late,grade,feedback,graded_at FROM submissions WHERE assignment_id=?", (aid,))}
        out = []
        for st in roster(a["batch_id"]):
            s = subs.get(st["id"])
            out.append({"student_id": st["id"], "full_name": st["full_name"], "submission_id": s["id"] if s else None,
                        "submitted": bool(s and s["submitted_at"]), "is_late": bool(s and s["is_late"]), "text_answer": s["text_answer"] if s else None,
                        "file_name": s["file_name"] if s else None, "has_file": bool(s and s["has_file"]), "submitted_at": s["submitted_at"] if s else None,
                        "grade": s["grade"] if s else None, "feedback": s["feedback"] if s else None})
        return jsonify(can_edit_grades=g.user["role"] == "admin" or can("edit_grades"), assignment={k: a[k] for k in ("id", "title", "kind", "due_date", "max_points", "description")}, students=out)

    @app.get("/api/submissions/<int:sid>/file")
    @auth(perm=A_PERM)
    def l_sub_file(sid):
        s = one("SELECT s.*,a.batch_id,b.teacher_id FROM submissions s JOIN assignments a ON a.id=s.assignment_id JOIN batches b ON b.id=a.batch_id WHERE s.id=?", (sid,))
        if not s or not s["file"]: return err("File not found", 404)
        u = g.user
        if not (u["role"] == "admin" or (u["role"] == "teacher" and s["batch_id"] in teacher_batches(u["id"])) or (u["role"] == "student" and s["student_id"] == u["id"] and one("SELECT 1 x FROM enrollments WHERE student_id=? AND batch_id=? AND status='active'", (u["id"], s["batch_id"])))):
            return err("You do not have access to this file", 403)
        return send_private(s["file"], s["file_name"])

    @app.post("/api/assignments/<int:aid>/grades")
    @auth("admin", "teacher", perm="classroom")
    def l_grade(aid):
        a, e = a_manage(aid)
        if e: return e
        d = body()
        try: sid = int(d.get("student_id"))
        except (TypeError, ValueError): return err("Missing: student_id")
        if not one("SELECT 1 x FROM enrollments WHERE student_id=? AND batch_id=? AND status IN ('active','completed')", (sid, a["batch_id"])):
            return err("That student is not in this batch", 400)
        gr = points(d.get("grade"), a["max_points"])
        if gr is None: return err(f"Grade must be a number from 0 to {a['max_points']}")
        fb = (d.get("feedback") or "").strip()[:2000] or None
        ex = one("SELECT id,grade,feedback FROM submissions WHERE assignment_id=? AND student_id=?", (aid, sid))
        if ex and ex["grade"] is not None:
            # A saved grade: only an admin, or a teacher who was given "edit_grades", may change it (Session 17). The same value again is a no-op.
            if gr == ex["grade"] and fb == ex["feedback"]: return jsonify(ok=True, grade=gr, changed=False)
            if g.user["role"] != "admin" and not can("edit_grades"):
                return err("This grade is already saved. Only an admin, or a teacher with permission to change grades, can edit it.", 403)
            db().execute("UPDATE submissions SET grade=?,feedback=?,graded_at=datetime('now') WHERE id=?", (gr, fb, ex["id"]))   # graded_by stays the first grader; the log has every change
            c.notify([sid], "grade", "Grade updated", f"{a['title']}: {gr} / {a['max_points']}", f"assignments:{aid}")   # Session 28
            audit("grade_change", "assignment", aid, f"student {sid}: grade {ex['grade']} -> {gr} (max {a['max_points']}); feedback {'changed' if fb != ex['feedback'] else 'unchanged'}"
                  + (f": {ex['feedback'] or ''} -> {fb or ''}" if fb != ex["feedback"] else ""), batch_id=a["batch_id"], old=ex["grade"], new=gr)
        else:
            if ex: db().execute("UPDATE submissions SET grade=?,feedback=?,graded_by=?,graded_at=datetime('now') WHERE id=?", (gr, fb, g.user["id"], ex["id"]))
            else: db().execute("INSERT INTO submissions(assignment_id,student_id,grade,feedback,graded_by,graded_at) VALUES(?,?,?,?,?,datetime('now'))", (aid, sid, gr, fb, g.user["id"]))
            c.notify([sid], "grade", "Assignment graded", f"{a['title']}: {gr} / {a['max_points']}", f"assignments:{aid}")   # Session 28
            audit("grade", "assignment", aid, f"student {sid}: grade none -> {gr} (max {a['max_points']})" + (f"; feedback: {fb}" if fb else ""), batch_id=a["batch_id"], new=gr)
        db().commit()
        return jsonify(ok=True, grade=gr, changed=True)

    @app.get("/api/my/given-grades")
    @auth("teacher", perm="classroom")
    def l_given_grades():
        """Grades this teacher gave, in the batches they may use now (newest first)."""
        ids = sorted(teacher_batches(g.user["id"]))
        bid = request.args.get("batch_id", type=int)
        if bid and bid not in ids: return err("This is not your batch", 403)
        if bid: ids = [bid]
        out = rows("SELECT s.id AS submission_id,a.id AS assignment_id,a.title,a.max_points,a.batch_id,b.code AS batch_code,u.id AS student_id,u.full_name,s.grade,s.feedback,s.graded_at "
                   "FROM submissions s JOIN assignments a ON a.id=s.assignment_id JOIN batches b ON b.id=a.batch_id JOIN users u ON u.id=s.student_id "
                   f"WHERE s.graded_by=? AND s.grade IS NOT NULL AND a.batch_id IN ({marks(len(ids))}) ORDER BY s.graded_at DESC,s.id DESC LIMIT 200", [g.user["id"], *ids]) if ids else []
        return jsonify(can_edit_grades=can("edit_grades"), grades=out)

    GRADE_SQL = ("SELECT s.student_id,SUM(s.grade) g,SUM(a.max_points) m,COUNT(*) n FROM submissions s JOIN assignments a ON a.id=s.assignment_id "
                 "WHERE a.batch_id=? AND s.grade IS NOT NULL ")

    def avg(r):
        return round(r["g"] * 100 / r["m"], 1) if r and r["m"] else None

    @app.get("/api/batches/<int:bid>/gradebook")
    @auth("admin", "teacher", perm="classroom")
    def l_gradebook(bid):
        b, e = manage(bid)
        if e: return e
        gr = {r["student_id"]: r for r in rows(GRADE_SQL + "GROUP BY s.student_id", (bid,))}
        at = batch_att(bid)
        return jsonify([{"student_id": s["id"], "full_name": s["full_name"], "graded_items": gr[s["id"]]["n"] if s["id"] in gr else 0,
                         "avg_pct": avg(gr.get(s["id"])), "attendance_pct": at.get(s["id"], stat(0, 0, 0, 0))["pct"],
                         "low_attendance": at.get(s["id"], stat(0, 0, 0, 0))["low"]} for s in roster(bid)])

    def grades_for(uid, bs):
        """A student's items, average and attendance per batch: 3 queries in total, however many batches."""
        bids = [b["id"] for b in bs]
        if not bids: return []
        items = {b: [] for b in bids}
        for r in rows("SELECT a.batch_id,a.id,a.title,a.kind,a.max_points,a.due_date,s.grade,s.feedback,s.is_late,(s.submitted_at IS NOT NULL) AS submitted "
                      f"FROM assignments a LEFT JOIN submissions s ON s.assignment_id=a.id AND s.student_id=? WHERE a.batch_id IN ({marks(len(bids))}) "
                      "ORDER BY COALESCE(a.due_date,'9999-12-31'),a.id", [uid, *bids]):
            r["status"] = "graded" if r["grade"] is not None else "submitted" if r["submitted"] else "pending"   # one definition of the student-facing status
            items[r.pop("batch_id")].append(r)
        tot = {r["batch_id"]: r for r in rows("SELECT a.batch_id,SUM(s.grade) g,SUM(a.max_points) m,COUNT(*) n FROM submissions s JOIN assignments a ON a.id=s.assignment_id "
                                              f"WHERE a.batch_id IN ({marks(len(bids))}) AND s.grade IS NOT NULL AND s.student_id=? GROUP BY a.batch_id", [*bids, uid])}
        att = att_multi(bids, uid)
        return [{"batch_id": b["id"], "course_name": b["course_name"], "batch_code": b["code"], "avg_pct": avg(tot.get(b["id"])),
                 "attendance_pct": att[b["id"]].get(uid, stat(0, 0, 0, 0))["pct"], "items": items[b["id"]]} for b in bs]

    @app.get("/api/my/grades")
    @auth("student", perm="progress")
    def l_my_grades():
        return jsonify(grades_for(g.user["id"], my_batches(request.args.get("batch_id", type=int))))

    # ---------- student information (Session 6) ----------
    # A directory for admins with the "student_information" area: find a student, then see profile, batches, attendance, grades and fees together.
    # The fees part is included only when the admin also has the "fees" area. Read-only: nothing here changes data.
    def like(v):
        return "%" + v.lower().replace("\\", "").replace("%", "").replace("_", "") + "%"

    @app.get("/api/student-information")
    @auth("admin", perm="student_information")
    def l_si_list():
        qs = (request.args.get("q") or "").strip()[:100]
        bid = request.args.get("batch_id", type=int)
        try: limit = max(1, min(100, int(request.args.get("limit", 30))))
        except ValueError: limit = 30
        status = request.args.get("status")
        w, a = ["u.role='student'"], []
        if qs: w.append("(LOWER(u.full_name) LIKE ? OR LOWER(u.email) LIKE ? OR LOWER(COALESCE(u.phone,'')) LIKE ?)"); a += [like(qs)] * 3
        if bid: w.append("u.id IN (SELECT student_id FROM enrollments WHERE batch_id=? AND status IN ('active','completed'))"); a.append(bid)
        if status in ("active", "inactive"): w.append("u.is_active=?"); a.append(1 if status == "active" else 0)
        where = " WHERE " + " AND ".join(w)
        total = one("SELECT COUNT(*) n FROM users u" + where, a)["n"]
        sts = rows("SELECT u.id,u.full_name,u.email,u.phone,u.is_active FROM users u" + where + " ORDER BY LOWER(u.full_name),u.id LIMIT ?", [*a, limit])
        ids = [s["id"] for s in sts]
        bt, bal = {i: [] for i in ids}, {}
        if ids:
            for r in rows(f"SELECT e.student_id,b.code,c.name AS course_name FROM enrollments e JOIN batches b ON b.id=e.batch_id JOIN courses c ON c.id=b.course_id "
                          f"WHERE e.status='active' AND e.student_id IN ({marks(len(ids))}) ORDER BY b.id", ids):
                bt[r["student_id"]].append(f"{r['course_name']} · {r['code']}")
            if can("fees"):
                bal = {r["student_id"]: r["bal"] for r in rows("SELECT student_id,SUM(amount_due_mvr-waived_mvr-paid_mvr) bal FROM invoices WHERE status IN ('unpaid','slip_submitted') "
                                                                f"AND amount_due_mvr-waived_mvr-paid_mvr>0 AND student_id IN ({marks(len(ids))}) GROUP BY student_id", ids)}
        for s_ in sts:
            s_["is_active"] = bool(s_["is_active"]); s_["batches"] = bt[s_["id"]]
            s_["balance_due"] = bal.get(s_["id"], 0) if can("fees") else None
        return jsonify(total=total, fees_visible=can("fees"), students=sts)

    @app.get("/api/student-information/<int:uid>")
    @auth("admin", perm="student_information")
    def l_si_get(uid):
        p = one("SELECT id,email,full_name,phone,is_active,created_at FROM users WHERE id=? AND role='student'", (uid,))
        if not p: return err("Student not found", 404)
        p["is_active"] = bool(p["is_active"])
        p.update(one("SELECT date_of_birth,grade,island,guardian_name,guardian_relationship,guardian_phone FROM students WHERE user_id=?", (uid,)) or {})
        enr = rows("SELECT e.id,e.status,e.enrolled_at,b.id AS batch_id,b.code,c.name AS course_name,u.full_name AS teacher_name FROM enrollments e JOIN batches b ON b.id=e.batch_id "
                   "JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=b.teacher_id WHERE e.student_id=? ORDER BY e.id", (uid,))
        live = [e["batch_id"] for e in enr if e["status"] in ("active", "completed", "dropped")]   # dropped = transferred or withdrawn: admin keeps the history (Session 13)
        est = {e["batch_id"]: e["status"] for e in enr}
        progress = []
        if live:
            bs = rows(BQ + f" WHERE b.id IN ({marks(len(live))}) ORDER BY b.id", live)
            att = att_multi(live, uid)
            recent = {b: [] for b in live}
            for r in rows(f"SELECT s.batch_id,s.session_date AS date,a.status FROM attendance a JOIN sessions s ON s.id=a.session_id WHERE a.student_id=? AND s.batch_id IN ({marks(len(live))}) "
                          "ORDER BY s.session_date DESC LIMIT 200", [uid, *live]):
                if len(recent[r["batch_id"]]) < 10: recent[r["batch_id"]].append({"date": r["date"], "status": r["status"]})
            for gr in grades_for(uid, bs):
                progress.append({**gr, "enrollment_status": est[gr["batch_id"]], "attendance": att[gr["batch_id"]].get(uid, stat(0, 0, 0, 0)), "recent": recent[gr["batch_id"]]})
        fees = None
        if can("fees"):
            t = today().isoformat()
            invs = rows("SELECT i.id,i.period,i.description,i.amount_due_mvr,i.paid_mvr,i.waived_mvr,i.due_date,i.status FROM invoices i WHERE i.student_id=? AND i.status!='void' "
                        "ORDER BY i.period DESC,i.id DESC LIMIT 36", (uid,))
            for i in invs:
                i["balance"] = max(0, i["amount_due_mvr"] - i["paid_mvr"] - i["waived_mvr"]) if i["status"] in ("unpaid", "slip_submitted") else 0
                i["overdue"] = bool(i["balance"] > 0 and i["due_date"] < t)
            pays = rows("SELECT p.receipt_no,p.amount_mvr,p.method,p.paid_on,p.reversed_at,i.period FROM payments p JOIN invoices i ON i.id=p.invoice_id WHERE p.student_id=? ORDER BY p.id DESC LIMIT 12", (uid,))
            fees = {"balance_due": sum(i["balance"] for i in invs), "overdue_count": sum(1 for i in invs if i["overdue"]), "invoices": invs, "payments": pays}
        return jsonify(profile=p, enrollments=enr, progress=progress, fees=fees, fees_visible=fees is not None)

    # ---------- teacher information (Session 7) ----------
    # A directory for admins with the "teacher_information" area: profile, batches taught, students and workload of one teacher. Read-only.
    def workload_of(bs):
        """Weekly classes and hours from the class days of batches that are not closed (extra and cancelled classes are not counted)."""
        n = sum(len([x for x in (b["days"] or "").split(",") if x in DAYS]) for b in bs if b["status"] != "closed" and b["start_time"])
        mins = sum(len([x for x in (b["days"] or "").split(",") if x in DAYS]) * b["minutes"] for b in bs if b["status"] != "closed" and b["start_time"])
        return n, round(mins / 60, 1)

    TBQ = ("SELECT b.id,b.code,b.days,b.start_time,b.status,b.capacity,b.teacher_id,c.name AS course_name,COALESCE(c.minutes_per_class,60) AS minutes "
           "FROM batches b JOIN courses c ON c.id=b.course_id")

    @app.get("/api/teacher-information")
    @auth("admin", perm="teacher_information")
    def l_ti_list():
        qs = (request.args.get("q") or "").strip()[:100]
        try: limit = max(1, min(100, int(request.args.get("limit", 30))))
        except ValueError: limit = 30
        status = request.args.get("status")
        w, a = ["u.role='teacher'"], []
        if qs: w.append("(LOWER(u.full_name) LIKE ? OR LOWER(u.email) LIKE ? OR LOWER(COALESCE(u.phone,'')) LIKE ?)"); a += [like(qs)] * 3
        if status in ("active", "inactive"): w.append("u.is_active=?"); a.append(1 if status == "active" else 0)
        where = " WHERE " + " AND ".join(w)
        total = one("SELECT COUNT(*) n FROM users u" + where, a)["n"]
        ts = rows("SELECT u.id,u.full_name,u.email,u.phone,u.is_active FROM users u" + where + " ORDER BY LOWER(u.full_name),u.id LIMIT ?", [*a, limit])
        ids = [t_["id"] for t_ in ts]
        by, stu = {i: [] for i in ids}, {i: 0 for i in ids}
        if ids:
            for b in rows(TBQ + f" WHERE b.teacher_id IN ({marks(len(ids))})", ids): by[b["teacher_id"]].append(b)
            for r in rows(f"SELECT b.teacher_id,COUNT(DISTINCT e.student_id) n FROM enrollments e JOIN batches b ON b.id=e.batch_id WHERE e.status='active' AND b.status!='closed' "
                          f"AND b.teacher_id IN ({marks(len(ids))}) GROUP BY b.teacher_id", ids): stu[r["teacher_id"]] = r["n"]
        for t_ in ts:
            bs = by[t_["id"]]
            t_["is_active"] = bool(t_["is_active"]); t_["batch_count"] = sum(1 for b in bs if b["status"] != "closed")
            t_["student_count"] = stu[t_["id"]]; t_["weekly_hours"] = workload_of(bs)[1]
        return jsonify(total=total, teachers=ts)

    @app.get("/api/teacher-information/<int:uid>")
    @auth("admin", perm="teacher_information")
    def l_ti_get(uid):
        p = one("SELECT id,email,full_name,phone,is_active,created_at FROM users WHERE id=? AND role='teacher'", (uid,))
        if not p: return err("Teacher not found", 404)
        p["is_active"] = bool(p["is_active"]); p["bio"] = (one("SELECT bio FROM teachers WHERE user_id=?", (uid,)) or {}).get("bio")
        bs = rows(TBQ + " WHERE b.teacher_id=? ORDER BY b.id", (uid,))
        bids = [b["id"] for b in bs]
        counts, studs, held, to_grade = {}, {}, 0, 0
        if bids:
            q = marks(len(bids))
            for r in rows(f"SELECT e.batch_id,u.id AS sid,u.full_name FROM enrollments e JOIN users u ON u.id=e.student_id WHERE e.status='active' AND e.batch_id IN ({q}) ORDER BY LOWER(u.full_name),u.id", bids):
                counts[r["batch_id"]] = counts.get(r["batch_id"], 0) + 1
                b = next(x for x in bs if x["id"] == r["batch_id"])
                if b["status"] != "closed": studs.setdefault(r["sid"], {"id": r["sid"], "full_name": r["full_name"], "batches": []})["batches"].append(f"{b['course_name']} · {b['code']}")
            since = (today() - dt.timedelta(days=30)).isoformat()
            held = one(f"SELECT COUNT(*) n FROM sessions WHERE status='held' AND session_date>=? AND batch_id IN ({q})", [since, *bids])["n"]
            to_grade = pending_grading(bids)
        wk, hrs = workload_of(bs)
        out_b = [{**{k: b[k] for k in ("id", "code", "course_name", "days", "start_time", "status", "capacity", "minutes")}, "students": counts.get(b["id"], 0)} for b in bs]
        return jsonify(profile=p, batches=out_b, students=list(studs.values()),
                       workload={"active_batches": sum(1 for b in bs if b["status"] != "closed"), "students": len(studs), "weekly_classes": wk, "weekly_hours": hrs,
                                 "classes_held_30d": held, "to_grade": to_grade})

    # ---------- my information (Session 16) ----------
    # Read-only page for the signed-in student or teacher. The person is always g.user: there is no id in the URL, so nobody can ask for someone else.
    # No fees, no internal notes, no password data. Academy-managed details are changed only by an admin (PATCH /api/users/<id> needs the "people" area).
    @app.get("/api/my/information")
    @auth("student", "teacher")
    def l_my_info():
        uid, role = g.user["id"], g.user["role"]
        p = one("SELECT id,login_id,email,full_name,phone,created_at FROM users WHERE id=?", (uid,))
        if role == "student":
            p.update(one("SELECT student_code,date_of_birth,grade,island,guardian_name,guardian_relationship,guardian_phone FROM students WHERE user_id=?", (uid,)) or {})
            bs = rows("SELECT e.enrol_code,e.enrolled_at,b.id,b.code,b.days,b.start_time,c.name AS course_name,c.kind AS course_kind,u.full_name AS teacher_name FROM enrollments e "
                      "JOIN batches b ON b.id=e.batch_id JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=b.teacher_id WHERE e.student_id=? AND e.status='active' ORDER BY e.id", (uid,))
        else:
            p["teacher_code"] = (one("SELECT teacher_code FROM teachers WHERE user_id=?", (uid,)) or {}).get("teacher_code")
            p["bio"] = (one("SELECT bio FROM teachers WHERE user_id=?", (uid,)) or {}).get("bio")
            ids = sorted(teacher_batches(uid))
            bs = rows("SELECT b.id,b.code,b.days,b.start_time,b.status,c.name AS course_name,c.kind AS course_kind FROM batches b JOIN courses c ON c.id=b.course_id "
                      f"WHERE b.id IN ({marks(len(ids))}) ORDER BY b.id", ids) if ids else []
        return jsonify(role=role, profile=p, batches=bs,
                       locked=["login_id", "student_code", "teacher_code", "full_name", "email", "phone", "date_of_birth", "grade", "island", "guardian_name", "guardian_relationship", "guardian_phone", "bio"])

    # ---------- materials ----------
    @app.post("/api/batches/<int:bid>/materials")
    @auth("admin", "teacher", perm="classroom")
    def l_mat_add(bid):
        b, e = manage(bid)
        if e: return e
        f = request.form if request.form else body()
        m = need(f, "title")
        if m: return err(m)
        url, up = (f.get("url") or "").strip(), request.files.get("file")
        if bool(url) == bool(up and up.filename): return err("Add either a file or a link")
        stored = shown = None
        if url:
            if not re.match(r"^https?://\S+$", url): return err("The link must start with http:// or https://")
            kind = "link"
        else:
            kind = "file"
            try: stored, shown = save_file(up, ALLOWED_MATERIAL)
            except ValueError as x: return err(str(x))
        mid = db().execute("INSERT INTO materials(batch_id,title,description,kind,file,file_name,url,uploaded_by) VALUES(?,?,?,?,?,?,?,?)",
                           (bid, f["title"].strip(), f.get("description"), kind, stored, shown, url or None, g.user["id"])).lastrowid
        audit("add_material", "material", mid, f["title"], batch_id=bid); db().commit()
        return jsonify(id=mid), 201

    @app.get("/api/materials")
    @auth(perm=M_PERM)
    def l_mat_list():
        ids = [b["id"] for b in my_batches(request.args.get("batch_id", type=int))]
        if not ids: return jsonify([])
        q = ",".join("?" * len(ids))
        return jsonify(rows(f"SELECT m.id,m.batch_id,m.title,m.description,m.kind,m.file_name,m.url,m.created_at,b.code AS batch_code,c.name AS course_name,u.full_name AS uploader "
                            f"FROM materials m JOIN batches b ON b.id=m.batch_id JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=m.uploaded_by "
                            f"WHERE m.batch_id IN ({q}) ORDER BY m.id DESC", ids))

    @app.get("/api/materials/<int:mid>/file")
    @auth(perm=M_PERM)
    def l_mat_file(mid):
        m = one("SELECT * FROM materials WHERE id=?", (mid,))
        if not m or not m["file"]: return err("File not found", 404)
        b, e = viewable(m["batch_id"])
        if e: return e
        return send_private(m["file"], m["file_name"])

    @app.delete("/api/materials/<int:mid>")
    @auth("admin", "teacher", perm="classroom")
    def l_mat_del(mid):
        m = one("SELECT * FROM materials WHERE id=?", (mid,))
        if not m: return err("Material not found", 404)
        b, e = manage(m["batch_id"])
        if e: return e
        rm(m["file"])
        db().execute("DELETE FROM materials WHERE id=?", (mid,))
        audit("delete_material", "material", mid, m["title"], batch_id=m["batch_id"]); db().commit()
        return jsonify(ok=True)

    # ---------- class recordings (Session 5) ----------
    # A teacher (own batches) or admin adds a Google Drive link with a title and the class date. Students of that batch open it.
    # Whether it can be downloaded depends on the Drive sharing setting; the portal only holds the link.
    DRIVE_HOSTS = ("drive.google.com", "docs.google.com")

    def clean_drive(v):
        """(link, error). Must be a plain https Google Drive / Docs address."""
        v = v.strip() if isinstance(v, str) else ""
        if not v: return None, err("Add the Google Drive link")
        try: p = urlparse(v)
        except ValueError: return None, err("That is not a valid link")
        if len(v) > 500 or p.scheme != "https" or (p.hostname or "").lower() not in DRIVE_HOSTS or any(ch.isspace() for ch in v):
            return None, err("The link must be a Google Drive link starting with https://drive.google.com/")
        return v, None

    def drive_download(url):
        """Direct-download address for a single Drive file link, or None (folders and other links cannot be turned into one)."""
        p = urlparse(url)
        m = re.search(r"/file/d/([A-Za-z0-9_-]+)", p.path) or re.search(r"(?:^|&)id=([A-Za-z0-9_-]+)", p.query)
        if not m or "/folders/" in p.path: return None
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"

    @app.post("/api/batches/<int:bid>/recordings")
    @auth("admin", "teacher", perm="add_recordings")
    def l_rec_add(bid):
        b, e = manage(bid)
        if e: return e
        e = gate("classroom")
        if e: return e
        d = body()
        title = (d.get("title") or "").strip() if isinstance(d.get("title"), str) else ""
        if not title: return err("Missing: title")
        if len(title) > 200: return err("The title is too long (200 characters at most)")
        day = pdate(d.get("recorded_on"))
        if not day: return err("Enter the date of the class")
        if day > today(): return err("The class date cannot be in the future")
        url, e = clean_drive(d.get("url"))
        if e: return e
        rid = db().execute("INSERT INTO recordings(batch_id,title,url,recorded_on,created_by) VALUES(?,?,?,?,?)",
                           (bid, title, url, day.isoformat(), g.user["id"])).lastrowid
        audit("add_recording", "recording", rid, f"{b['code']}: {title}", batch_id=bid); db().commit()
        return jsonify(id=rid), 201

    @app.get("/api/recordings")
    @auth(perm={"student": "recordings", "teacher": "classroom", "admin": "classroom"})
    def l_rec_list():
        """Recordings of the batches this person manages or belongs to, newest class first."""
        ids = [b["id"] for b in my_batches(request.args.get("batch_id", type=int))]
        if not ids: return jsonify([])
        q = ",".join("?" * len(ids))
        out = rows(f"SELECT r.id,r.batch_id,r.title,r.url,r.recorded_on,r.created_at,b.code AS batch_code,c.name AS course_name,u.full_name AS added_by "
                   f"FROM recordings r JOIN batches b ON b.id=r.batch_id JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=r.created_by "
                   f"WHERE r.batch_id IN ({q}) ORDER BY r.recorded_on DESC, r.id DESC", ids)
        for r in out: r["download_url"] = drive_download(r["url"])
        return jsonify(out)

    @app.delete("/api/recordings/<int:rid>")
    @auth("admin", "teacher", perm="add_recordings")
    def l_rec_del(rid):
        r = one("SELECT * FROM recordings WHERE id=?", (rid,))
        if not r: return err("Recording not found", 404)
        b, e = manage(r["batch_id"])
        if e: return e
        e = gate("classroom")
        if e: return e
        db().execute("DELETE FROM recordings WHERE id=?", (rid,))
        audit("delete_recording", "recording", rid, f"{b['code']}: {r['title']}", batch_id=r["batch_id"]); db().commit()
        return jsonify(ok=True)

    # ---------- tutorials library ----------
    # Everyone with the "tutorials" area can read. Only teachers and admins with "create_tutorials" post and see the answers.
    # Students with "submit_tutorial_work" send one answer per tutorial (text, a file, or both). Older posts by students stay visible, read-only.
    def staff_of(t):
        """Admin, or the teacher/admin who posted this tutorial: the people who may see its answers."""
        return g.user["role"] == "admin" or (g.user["role"] == "teacher" and t["uploaded_by"] == g.user["id"])

    STU_TUT = "(t.course_id IS NULL OR t.course_id IN (SELECT b2.course_id FROM enrollments e2 JOIN batches b2 ON b2.id=e2.batch_id WHERE e2.student_id=? AND e2.status='active'))"

    def teacher_tut_sql():
        """Teacher scope (Session 18): tutorials they posted, or of a course one of THEIR batches belongs to. (sql, args)"""
        ids = sorted(teacher_batches(g.user["id"]))
        sub = f" OR t.course_id IN (SELECT course_id FROM batches WHERE id IN ({marks(len(ids))}))" if ids else ""
        return f"(t.uploaded_by=?{sub})", [g.user["id"], *ids]

    def tut_blocked(tid):
        """A student may open a tutorial only if it is general (no course) or belongs to a course they are ACTIVELY enrolled in. Returns an error response or None."""
        if g.user["role"] == "teacher" and one("SELECT 1 x FROM tutorials WHERE id=?", (tid,)):
            sql, a = teacher_tut_sql()
            if not one(f"SELECT 1 x FROM tutorials t WHERE t.id=? AND {sql}", (tid, *a)): return err("You do not have access to this tutorial", 403)
            return None
        if g.user["role"] != "student" or not one("SELECT 1 x FROM tutorials WHERE id=?", (tid,)): return None   # missing tutorial: the route answers 404
        if not one(f"SELECT 1 x FROM tutorials t WHERE t.id=? AND {STU_TUT}", (tid, g.user["id"])):
            return err("You do not have access to this tutorial", 403)

    @app.post("/api/tutorials")
    @auth("admin", "teacher", perm="create_tutorials")
    def l_tut_add():
        """Written text, a file, a link, or any mix (at least one). Form when a file is attached, JSON otherwise."""
        e = gate("tutorials")
        if e: return e
        f = request.form if request.form else body()
        m = need(f, "title")
        if m: return err(m)
        text, url, up = (f.get("text") or "").strip(), (f.get("url") or "").strip(), request.files.get("file")
        has_file = bool(up and up.filename)
        if not (text or url or has_file): return err("Write something, attach a file, or add a link")
        if len(text) > 8000: return err("The text can be up to 8000 characters")
        if url and not re.match(r"^https?://\S+$", url): return err("The link must start with http:// or https://")
        cid = f.get("course_id") or None
        if cid:
            try: cid = int(cid)
            except ValueError: return err("Choose a course from the list")
            if not one("SELECT 1 x FROM courses WHERE id=?", (cid,)): return err("Course not found", 404)
            if g.user["role"] == "teacher" and not one(f"SELECT 1 x FROM batches WHERE course_id=? AND id IN ({marks(len(teacher_batches(g.user['id'])) or 1)})", [cid, *(sorted(teacher_batches(g.user["id"])) or [0])]):
                return err("You can only post tutorials for courses you teach", 403)
        stored = shown = None
        if has_file:
            try: stored, shown = save_file(up, ALLOWED_MATERIAL)
            except ValueError as x: return err(str(x))
        tid = db().execute("INSERT INTO tutorials(title,body,course_id,file,file_name,url,uploaded_by) VALUES(?,?,?,?,?,?,?)",
                           (f["title"].strip(), text or None, cid, stored, shown, url or None, g.user["id"])).lastrowid
        audit("add_tutorial", "tutorial", tid, f["title"], course_id=cid); db().commit()
        return jsonify(id=tid), 201

    PREVIEW = 300   # characters of a tutorial's text sent in the list; the full text is fetched when the reader opens the post

    @app.get("/api/tutorials")
    @auth(perm="tutorials")
    def l_tut_list():
        cid, q = request.args.get("course_id", type=int), (request.args.get("q") or "").strip()
        limit = min(max(request.args.get("limit", 30, type=int), 1), 100)
        w, a = [], []
        if cid: w.append("t.course_id=?"); a.append(cid)
        if q: w.append("(t.title LIKE ? OR t.body LIKE ?)"); a += [f"%{q}%"] * 2
        if g.user["role"] == "teacher":
            sql, ta = teacher_tut_sql(); w.append(sql); a += ta
            tb = request.args.get("batch_id", type=int)
            if tb:   # the picker's batch: tutorials of its course, plus the teacher's own general posts (403 if not their batch)
                if tb not in teacher_batches(g.user["id"]): return err("This is not your batch", 403)
                w.append("(t.course_id=(SELECT course_id FROM batches WHERE id=?) OR (t.course_id IS NULL AND t.uploaded_by=?))"); a += [tb, g.user["id"]]
        if g.user["role"] == "student":
            w.append(STU_TUT); a.append(g.user["id"])
            sb = request.args.get("batch_id", type=int)
            if sb:   # the picker's batch: its course's tutorials plus general ones (403 if the student is not actively in it)
                w.append("(t.course_id IS NULL OR t.course_id=?)"); a.append(my_batches(sb)[0]["course_id"])
        items = rows(f"SELECT t.id,t.title,SUBSTR(t.body,1,{PREVIEW + 1}) AS text,t.course_id,t.file_name,(t.file IS NOT NULL) AS has_file,t.url,t.created_at,t.uploaded_by,c.name AS course_name,u.full_name AS uploader,u.role AS uploader_role "
                     "FROM tutorials t LEFT JOIN courses c ON c.id=t.course_id JOIN users u ON u.id=t.uploaded_by "
                     + ("WHERE " + " AND ".join(w) + " " if w else "") + "ORDER BY t.id DESC LIMIT ?", [*a, limit])
        u = g.user
        staff = u["role"] in ("admin", "teacher") and can("create_tutorials")
        student = u["role"] == "student" and can("submit_tutorial_work")
        ids = [t["id"] for t in items]
        mine, counts = {}, {}
        if ids and student:
            mine = {r["tutorial_id"]: r for r in rows(f"SELECT tutorial_id,submitted_at,(file IS NOT NULL) AS has_file,(text_answer IS NOT NULL) AS has_text FROM tutorial_submissions WHERE student_id=? AND tutorial_id IN ({','.join('?' * len(ids))})", [u["id"], *ids])}
        if ids and staff:
            counts = {r["tutorial_id"]: r["n"] for r in rows(f"SELECT tutorial_id,COUNT(*) n FROM tutorial_submissions WHERE tutorial_id IN ({','.join('?' * len(ids))}) GROUP BY tutorial_id", ids)}
        for t in items:
            t["has_file"] = bool(t["has_file"])
            by_staff = t["uploader_role"] in ("admin", "teacher")
            # deleting: an admin removes anything; a teacher removes their own post; students can no longer delete (old student posts are read-only)
            t["can_delete"] = u["role"] == "admin" or (u["role"] == "teacher" and t["uploaded_by"] == u["id"] and can("create_tutorials"))
            t["accepts_answers"] = by_staff   # older posts by students are read-only: no answers
            t["can_submit"] = bool(student and by_staff)
            if student and by_staff:
                s = mine.get(t["id"])
                t["my_submission"] = {"submitted_at": s["submitted_at"], "has_file": bool(s["has_file"]), "has_text": bool(s["has_text"])} if s else None
            if staff and staff_of(t):
                t["can_view_answers"] = True
                t["answer_count"] = counts.get(t["id"], 0)
            t.pop("uploaded_by", None)
            t["text_truncated"] = bool(t["text"]) and len(t["text"]) > PREVIEW
            if t["text_truncated"]: t["text"] = t["text"][:PREVIEW]
        return jsonify(items)

    @app.get("/api/tutorials/<int:tid>")
    @auth(perm="tutorials")
    def l_tut_one(tid):
        e = tut_blocked(tid)
        if e: return e
        t = one("SELECT id,body AS text FROM tutorials WHERE id=?", (tid,))
        return jsonify(t) if t else err("Tutorial not found", 404)

    @app.get("/api/tutorials/<int:tid>/file")
    @auth(perm="tutorials")
    def l_tut_file(tid):
        e = tut_blocked(tid)
        if e: return e
        t = one("SELECT file,file_name FROM tutorials WHERE id=?", (tid,))
        if not t or not t["file"]: return err("File not found", 404)
        return send_private(t["file"], t["file_name"])

    @app.delete("/api/tutorials/<int:tid>")
    @auth("admin", "teacher", perm="tutorials")
    def l_tut_del(tid):
        t = one("SELECT * FROM tutorials WHERE id=?", (tid,))
        if not t: return err("Tutorial not found", 404)
        if g.user["role"] != "admin":
            e = gate("create_tutorials")
            if e: return e
            if t["uploaded_by"] != g.user["id"]: return err("You can only delete your own posts", 403)
        for s in rows("SELECT file FROM tutorial_submissions WHERE tutorial_id=?", (tid,)): rm(s["file"])
        db().execute("DELETE FROM tutorial_submissions WHERE tutorial_id=?", (tid,))
        rm(t["file"])
        db().execute("DELETE FROM tutorials WHERE id=?", (tid,))
        audit("delete_tutorial", "tutorial", tid, t["title"], course_id=t["course_id"]); db().commit()
        return jsonify(ok=True)

    # ---- student answers to a tutorial ----
    def tut_for_answer(tid):
        """The tutorial a student may answer: it must exist and have been posted by a teacher or admin."""
        t = one("SELECT t.id,t.title,t.course_id,t.uploaded_by,u.role AS uploader_role FROM tutorials t JOIN users u ON u.id=t.uploaded_by WHERE t.id=?", (tid,))
        if not t: return None, err("Tutorial not found", 404)
        if t["uploader_role"] not in ("admin", "teacher"): return None, err("This older post is read-only and does not take answers", 409)
        return t, None

    @app.post("/api/tutorials/<int:tid>/submission")
    @auth("student", perm="submit_tutorial_work")
    def l_tut_submit(tid):
        """Send or replace my answer: written text, a file, or both. Sending only new text keeps the earlier file."""
        e = gate("tutorials")
        if e: return e
        e = tut_blocked(tid)
        if e: return e
        t, e = tut_for_answer(tid)
        if e: return e
        text = (request.form.get("text") or "").strip()
        if len(text) > 10000: return err("The written answer can be up to 10000 characters")
        f = request.files.get("file")
        has_file = bool(f and f.filename)
        old = one("SELECT * FROM tutorial_submissions WHERE tutorial_id=? AND student_id=?", (tid, g.user["id"]))
        if not text and not has_file: return err("Write an answer or attach a file")
        stored = shown = None
        if has_file:
            try: stored, shown = save_file(f, ALLOWED_SUBMISSION)
            except ValueError as x: return err(str(x))
        if old:
            if stored: rm(old["file"])
            db().execute("UPDATE tutorial_submissions SET text_answer=?,file=?,file_name=?,submitted_at=datetime('now') WHERE id=?",
                         (text or None, stored or old["file"], shown or old["file_name"], old["id"]))
            sid, code = old["id"], 200
        else:
            sid = db().execute("INSERT INTO tutorial_submissions(tutorial_id,student_id,text_answer,file,file_name) VALUES(?,?,?,?,?)",
                               (tid, g.user["id"], text or None, stored, shown)).lastrowid
            code = 201
        audit("submit_tutorial_work", "tutorial_submission", sid, t["title"], course_id=t["course_id"]); db().commit()
        return jsonify(id=sid), code

    @app.get("/api/tutorials/<int:tid>/submission")
    @auth("student", perm="submit_tutorial_work")
    def l_tut_my_answer(tid):
        e = gate("tutorials")
        if e: return e
        if not one("SELECT 1 x FROM tutorials WHERE id=?", (tid,)): return err("Tutorial not found", 404)
        e = tut_blocked(tid)
        if e: return e
        s = one("SELECT id,text_answer,file_name,(file IS NOT NULL) AS has_file,submitted_at FROM tutorial_submissions WHERE tutorial_id=? AND student_id=?", (tid, g.user["id"]))
        if s: s["has_file"] = bool(s["has_file"])
        return jsonify(submission=s)

    @app.get("/api/tutorials/<int:tid>/submissions")
    @auth("admin", "teacher", perm="create_tutorials")
    def l_tut_answers(tid):
        """Every student answer to one tutorial: the admin sees all, a teacher only for tutorials they posted."""
        e = gate("tutorials")
        if e: return e
        t = one("SELECT id,title,uploaded_by FROM tutorials WHERE id=?", (tid,))
        if not t: return err("Tutorial not found", 404)
        if not staff_of(t): return err("You can only see answers to your own tutorials", 403)
        subs = rows("SELECT s.id,s.student_id,u.full_name,s.text_answer,s.file_name,(s.file IS NOT NULL) AS has_file,s.submitted_at FROM tutorial_submissions s JOIN users u ON u.id=s.student_id WHERE s.tutorial_id=? ORDER BY s.submitted_at DESC,s.id DESC", (tid,))
        for s in subs: s["has_file"] = bool(s["has_file"])
        return jsonify(tutorial={"id": t["id"], "title": t["title"]}, submissions=subs)

    @app.get("/api/tutorial-submissions/<int:sid>/file")
    @auth(perm={"student": "submit_tutorial_work", "teacher": "create_tutorials", "admin": "create_tutorials"})
    def l_tut_answer_file(sid):
        e = gate("tutorials")
        if e: return e
        s = one("SELECT s.file,s.file_name,s.student_id,t.uploaded_by FROM tutorial_submissions s JOIN tutorials t ON t.id=s.tutorial_id WHERE s.id=?", (sid,))
        if not s or not s["file"]: return err("File not found", 404)
        u = g.user
        if not ((u["role"] == "student" and s["student_id"] == u["id"]) or staff_of(s)): return err("You do not have access to this file", 403)
        return send_private(s["file"], s["file_name"])

    # ---------- home (student + teacher) ----------
    # ---------- teacher dashboard (Session 19) ----------
    # One endpoint for the selected batch (?batch_id=) or all of the teacher's batches. Every assignment number comes from assign_counts() /
    # pending_grading() (Session 18); attendance from att_multi() over the ACTIVE roster; nothing is counted a second way here.
    @app.get("/api/teacher/dashboard")
    @auth("teacher", perm="classroom")
    def l_teacher_dash():
        u, t0 = g.user, today()
        bs = my_batches(request.args.get("batch_id", type=int))     # 403 for a batch that is not theirs
        ids = [b["id"] for b in bs]
        ros, att = roster_multi(ids), att_multi(ids)
        batches = [{"id": b["id"], "code": b["code"], "course_name": b["course_name"], "status": b["status"], "days": b["days"], "start_time": b["start_time"],
                    "students": len(ros[b["id"]])} for b in bs]
        out = {"scope": "batch" if request.args.get("batch_id", type=int) else "all", "batches": batches,
               "courses": sorted({b["course_name"] for b in bs}), "students": len({s["id"] for b in bs for s in ros[b["id"]]})}
        # classes: held (attendance taken), upcoming (next 28 days, not cancelled, not yet held), cancelled
        cl = {"held": 0, "held_30d": 0, "cancelled": 0}
        if ids:
            since = (t0 - dt.timedelta(days=30)).isoformat()
            for r in rows(f"SELECT status,COUNT(*) n,SUM(CASE WHEN session_date>=? THEN 1 ELSE 0 END) recent FROM sessions WHERE batch_id IN ({marks(len(ids))}) GROUP BY status", [since, *ids]):
                if r["status"] == "held": cl["held"], cl["held_30d"] = r["n"], r["recent"] or 0
                elif r["status"] == "cancelled": cl["cancelled"] = r["n"]
        occ = [o for o in occurrences(bs, t0, t0 + dt.timedelta(days=27)) if o["date"] >= t0.isoformat() and o["status"] not in ("cancelled", "held")]
        cl["upcoming"] = len(occ); cl["next"] = [clean(o) for o in occ[:5]]
        out["classes"] = cl
        # assignments, tests, hand-ins, grading: the Session 18 definitions
        asg = rows(f"SELECT id,kind FROM assignments WHERE batch_id IN ({marks(len(ids))})", ids) if ids else []
        cnt = assign_counts([a["id"] for a in asg])
        out["assignments"] = {"given": sum(1 for a in asg if a["kind"] == "assignment"), "tests": sum(1 for a in asg if a["kind"] == "test"),
                              "submissions": sum(c["submitted"] for c in cnt.values()), "graded": sum(c["graded"] for c in cnt.values()), "pending_grading": pending_grading(ids)}
        # tutorials the teacher posted for these batches' courses (or general), and the answers of students who are active here
        tut = {"given": 0, "answers": 0}
        if ids:
            cids = sorted({b["course_id"] for b in bs})
            w = f"t.uploaded_by=? AND (t.course_id IS NULL OR t.course_id IN ({marks(len(cids))}))"
            tut["given"] = one(f"SELECT COUNT(*) n FROM tutorials t WHERE {w}", [u["id"], *cids])["n"]
            tut["answers"] = one(f"SELECT COUNT(*) n FROM tutorial_submissions ts JOIN tutorials t ON t.id=ts.tutorial_id WHERE {w} AND EXISTS (SELECT 1 FROM enrollments e JOIN batches b ON b.id=e.batch_id "
                                 f"WHERE e.student_id=ts.student_id AND e.status='active' AND b.id IN ({marks(len(ids))}) AND (t.course_id IS NULL OR b.course_id=t.course_id))", [u["id"], *cids, *ids])["n"]
        out["tutorials"] = tut
        # attendance of the active students (excused not counted, as everywhere else)
        P = L = AB = EX = low = 0
        for b in ids:
            for s in ros[b]:
                x = att[b].get(s["id"])
                if x: P += x["present"]; L += x["late"]; AB += x["absent"]; EX += x["excused"]; low += 1 if x["low"] else 0
        out["attendance"] = {**stat(P, L, AB, EX), "low_students": low}
        out["recent_activity"] = rows("SELECT action,entity,entity_id,detail,at FROM audit_log WHERE user_id=? AND action NOT IN ('login','logout') ORDER BY id DESC LIMIT 10", (u["id"],))   # the teacher's own latest work (sign-ins left out)
        return jsonify(out)

    @app.get("/api/my/home")
    @auth("student", "teacher")
    def l_home():
        u = g.user
        t0 = today()
        bs = my_batches(request.args.get("batch_id", type=int))
        occ = occurrences(bs, t0, t0 + dt.timedelta(days=27))
        nxt = next_class(occ)
        out = {"today": [clean(o) for o in occ if o["date"] == t0.isoformat()],
               "week": [clean(o) for o in occ if o["date"] < (t0 + dt.timedelta(days=7)).isoformat()],
               "next_class": clean(nxt) if nxt else None,
               "batches_without_schedule": [{"id": b["id"], "course_name": b["course_name"], "code": b["code"]} for b in bs if b["status"] != "closed" and not (b["days"] and b["start_time"])]}
        pl = None if u.get("permissions") is None else [x for x in u["permissions"].split(",") if x]
        allow = lambda area: pl is None or area in pl
        if u["role"] == "student":
            gr = {x["batch_id"]: x for x in grades_for(u["id"], bs)} if allow("progress") else {}
            out["courses"] = [{"batch_id": b["id"], "course_name": b["course_name"], "batch_code": b["code"], "teacher_name": b["teacher_name"],
                               "attendance_pct": gr[b["id"]]["attendance_pct"] if gr else None, "avg_pct": gr[b["id"]]["avg_pct"] if gr else None} for b in bs]
            ids = [b["id"] for b in bs]
            todo = []
            if ids and allow("assignments"):
                q = ",".join("?" * len(ids))
                todo = rows(f"SELECT a.id,a.title,a.due_date,c.name AS course_name FROM assignments a JOIN batches b ON b.id=a.batch_id JOIN courses c ON c.id=b.course_id "
                            f"WHERE a.batch_id IN ({q}) AND a.kind='assignment' AND NOT EXISTS (SELECT 1 FROM submissions s WHERE s.assignment_id=a.id AND s.student_id=? AND s.submitted_at IS NOT NULL) "
                            f"ORDER BY COALESCE(a.due_date,'9999-12-31') LIMIT 5", (*ids, u["id"]))
            out["todo"] = todo
        else:
            ids = [b["id"] for b in bs] if allow("classroom") else []
            n = 0
            low = []
            if ids:
                q = ",".join("?" * len(ids))
                n = pending_grading(ids)
            att, ros = att_multi(ids), roster_multi(ids)
            for b in (bs if ids else []):
                st = att[b["id"]]
                for s in ros[b["id"]]:
                    if st.get(s["id"], {}).get("low"):
                        low.append({"batch_id": b["id"], "batch_code": b["code"], "course_name": b["course_name"], "student_id": s["id"], "full_name": s["full_name"], "pct": st[s["id"]]["pct"]})
            out["to_grade"], out["low_attendance"] = n, low
        return jsonify(out)
