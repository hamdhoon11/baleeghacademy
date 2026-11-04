"""Phase 3 - learning tools: timetable + Join class, attendance, assignments, grades, materials.

Registered from app.create_app(). All access rules are enforced here on the server:
  admin   -> everything
  teacher -> only batches where batches.teacher_id = their user id
  student -> only batches they are actively enrolled in (or completed), and only their own submissions/grades/attendance
Times are Maldives time (UTC+5, no daylight saving).
"""
import os, re, uuid, datetime as dt
import common
from flask import jsonify, request, send_from_directory, g

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
    store = c.store

    # ---------- helpers ----------
    def join_early():
        """Minutes before class start that Join appears: the admin's Settings value, else the JOIN_EARLY_MIN env/config default."""
        r = one("SELECT value FROM settings WHERE key='join_early_min'")
        try: return int(r["value"]) if r and str(r["value"]).strip() else int(app.config.get("JOIN_EARLY_MIN", 15))
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
        return name, re.sub(r"[^\w.\- ]", "_", os.path.basename(f.filename))[:80]

    def rm(name):
        if name: store.delete("learning", name)

    def send_private(stored, shown):
        resp = store.send("learning", stored, shown or stored, as_attachment=True)
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    BQ = ("SELECT b.id,b.code,b.days,b.start_time,b.start_date,b.status,b.meet_link,b.teacher_id,b.course_id,"
          "c.name AS course_name,COALESCE(c.minutes_per_class,60) AS minutes,u.full_name AS teacher_name "
          "FROM batches b JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=b.teacher_id")

    def batch(bid):
        return one(BQ + " WHERE b.id=?", (bid,))

    def manage(bid):
        """Admin, or the batch's own teacher. Returns (batch, None) or (None, error response)."""
        b = batch(bid)
        if not b: return None, err("Batch not found", 404)
        if g.user["role"] == "admin" or (g.user["role"] == "teacher" and b["teacher_id"] == g.user["id"]):
            return b, None
        return None, err("This is not your batch", 403)

    def viewable(bid):
        """manage() rights, or a student enrolled (active/completed) in the batch."""
        b = batch(bid)
        if not b: return None, err("Batch not found", 404)
        u = g.user
        if u["role"] == "admin" or (u["role"] == "teacher" and b["teacher_id"] == u["id"]): return b, None
        if u["role"] == "student" and one("SELECT 1 x FROM enrollments WHERE student_id=? AND batch_id=? AND status IN ('active','completed')", (u["id"], bid)):
            return b, None
        return None, err("You do not have access to this batch", 403)

    def my_batches(batch_id=None):
        u, w, a = g.user, [], []
        if u["role"] == "teacher": w.append("b.teacher_id=?"); a.append(u["id"])
        if u["role"] == "student":
            w.append("b.id IN (SELECT batch_id FROM enrollments WHERE student_id=? AND status IN ('active','completed'))"); a.append(u["id"])
        if batch_id: w.append("b.id=?"); a.append(batch_id)
        return rows(BQ + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY b.id", a)

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
                        seen[(d.isoformat(), b["start_time"])] = {"status": "scheduled", "extra": False, "session_id": None, "topic": None, "note": None}
                    d += dt.timedelta(days=1)
            for (bid, sd, st), s in sess.items():
                if bid != b["id"]: continue
                seen[(sd, st)] = {"status": s["status"], "extra": (sd, st) not in seen, "session_id": s["id"], "topic": s["topic"], "note": s["note"]}
            for (sd, st), o in seen.items():
                start = dt.datetime.combine(dt.date.fromisoformat(sd), dt.time.fromisoformat(st), tzinfo=MVT)
                end = start + dt.timedelta(minutes=b["minutes"])
                n = now()
                early = dt.timedelta(minutes=join_early())
                o.update(batch_id=b["id"], batch_code=b["code"], course_name=b["course_name"], teacher_name=b["teacher_name"],
                         date=sd, weekday=DAYS[start.weekday()], start_time=st, end_time=end.strftime("%H:%M"), minutes=b["minutes"],
                         meet_link=b["meet_link"], starts_at=start.isoformat(), _start=start, _end=end,
                         can_join=bool(o["status"] != "cancelled" and b["meet_link"] and start - early <= n <= end),
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
        return jsonify([clean(o) for o in occurrences(my_batches(bid), d0, d1)])

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
        ex = one("SELECT * FROM sessions WHERE batch_id=? AND session_date=? AND start_time=?", (bid, day.isoformat(), st))
        if ex:
            if ex["status"] == "held" and status == "cancelled": return err("This class already has attendance, so it cannot be cancelled", 409)
            new_status = "held" if ex["status"] == "held" else status
            db().execute("UPDATE sessions SET status=?,topic=COALESCE(?,topic),note=COALESCE(?,note) WHERE id=?", (new_status, d.get("topic"), d.get("note"), ex["id"]))
            sid = ex["id"]
        else:
            sid = db().execute("INSERT INTO sessions(batch_id,session_date,start_time,status,topic,note,created_by) VALUES(?,?,?,?,?,?,?)",
                               (bid, day.isoformat(), st, status, d.get("topic"), d.get("note"), g.user["id"])).lastrowid
        audit("session_" + status, "session", sid, f"batch {bid} {day} {st}"); db().commit()
        return jsonify(id=sid), 201

    # ---------- attendance ----------
    def threshold():
        r = one("SELECT value FROM settings WHERE key='low_attendance_pct'")
        try: return int(r["value"]) if r else 75
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

    @app.get("/api/batches/<int:bid>/attendance")
    @auth("admin", "teacher", perm="classroom")
    def l_att_get(bid):
        b, e = manage(bid)
        if e: return e
        day = pdate(request.args.get("date")) or today()
        st = request.args.get("start_time") or b["start_time"]
        sess = one("SELECT * FROM sessions WHERE batch_id=? AND session_date=? AND start_time=?", (bid, day.isoformat(), st)) if st else None
        marks = {r["student_id"]: r for r in rows("SELECT student_id,status,note FROM attendance WHERE session_id=?", (sess["id"],))} if sess else {}
        students = [{**s, "status": marks.get(s["id"], {}).get("status"), "note": marks.get(s["id"], {}).get("note")} for s in roster(bid)]
        return jsonify(date=day.isoformat(), start_time=st, session=sess, students=students)

    @app.post("/api/batches/<int:bid>/attendance")
    @auth("admin", "teacher", perm="classroom")
    def l_att_save(bid):
        b, e = manage(bid)
        if e: return e
        d = body()
        day = pdate(d.get("date"))
        if not day: return err("Enter a valid date")
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
        for sid, status, note in clean_recs:
            db().execute("INSERT INTO attendance(session_id,student_id,status,note,marked_by) VALUES(?,?,?,?,?) "
                         "ON CONFLICT(session_id,student_id) DO UPDATE SET status=excluded.status,note=excluded.note,marked_by=excluded.marked_by,marked_at=datetime('now')",
                         (sid_, sid, status, note, g.user["id"]))
        audit("mark_attendance", "session", sid_, f"batch {bid} {day} ({len(clean_recs)} students)"); db().commit()
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

    @app.get("/api/my/attendance")
    @auth("student")
    def l_my_att():
        out = []
        for b in my_batches():
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
        audit("create_assignment", "assignment", aid, d["title"] + (" (with file)" if stored else "")); db().commit()
        return jsonify(id=aid), 201

    @app.get("/api/assignments/<int:aid>/attachment")
    @auth()
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
        audit("update_assignment", "assignment", aid, ",".join(f)); db().commit()
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
        audit("delete_assignment", "assignment", aid, a["title"]); db().commit()
        return jsonify(ok=True)

    @app.get("/api/assignments")
    @auth()
    def l_assign_list():
        u = g.user
        bid = request.args.get("batch_id", type=int)
        ids = [b["id"] for b in my_batches(bid)]
        if not ids: return jsonify([])
        q = ",".join("?" * len(ids))
        base = ("SELECT a.id,a.batch_id,a.title,a.description,a.kind,a.due_date,a.max_points,a.created_at,a.attachment_name,(a.attachment IS NOT NULL) AS has_attachment,b.code AS batch_code,c.name AS course_name "
                "FROM assignments a JOIN batches b ON b.id=a.batch_id JOIN courses c ON c.id=b.course_id")
        items = rows(f"{base} WHERE a.batch_id IN ({q}) ORDER BY COALESCE(a.due_date,'9999-12-31'),a.id DESC", ids)
        for a in items:
            if u["role"] == "student":
                s = one("SELECT id,submitted_at,is_late,grade,feedback,graded_at,text_answer,file_name,(file IS NOT NULL) AS has_file FROM submissions WHERE assignment_id=? AND student_id=?", (a["id"], u["id"]))
                a["my"] = {"submission_id": s["id"] if s else None, "submitted": bool(s and s["submitted_at"]), "is_late": bool(s and s["is_late"]), "grade": s["grade"] if s else None,
                           "feedback": s["feedback"] if s else None, "text_answer": s["text_answer"] if s else None,
                           "file_name": s["file_name"] if s else None, "has_file": bool(s and s["has_file"])}
            else:
                n = one("SELECT SUM(CASE WHEN submitted_at IS NOT NULL THEN 1 ELSE 0 END) sub,SUM(CASE WHEN grade IS NOT NULL THEN 1 ELSE 0 END) gr FROM submissions WHERE assignment_id=?", (a["id"],))
                a["submitted_count"], a["graded_count"] = n["sub"] or 0, n["gr"] or 0
                a["student_count"] = len(roster(a["batch_id"]))
        return jsonify(items)

    @app.post("/api/assignments/<int:aid>/submit")
    @auth("student")
    def l_submit(aid):
        a = aget(aid)
        if not a: return err("Assignment not found", 404)
        if not one("SELECT 1 x FROM enrollments WHERE student_id=? AND batch_id=? AND status='active'", (g.user["id"], a["batch_id"])):
            return err("You are not enrolled in this batch", 403)
        if a["kind"] == "test": return err("This is a test. Your teacher enters the marks.", 400)
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
            db().execute("UPDATE submissions SET text_answer=?,file=?,file_name=?,submitted_at=datetime('now'),is_late=? WHERE id=?",
                         (text or None, stored, shown, late, old["id"]))
            sid = old["id"]
        else:
            sid = db().execute("INSERT INTO submissions(assignment_id,student_id,text_answer,file,file_name,submitted_at,is_late) VALUES(?,?,?,?,?,datetime('now'),?)",
                               (aid, g.user["id"], text or None, stored, shown, late)).lastrowid
        audit("submit_assignment", "submission", sid, a["title"]); db().commit()
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
        return jsonify(assignment={k: a[k] for k in ("id", "title", "kind", "due_date", "max_points", "description")}, students=out)

    @app.get("/api/submissions/<int:sid>/file")
    @auth()
    def l_sub_file(sid):
        s = one("SELECT s.*,a.batch_id,b.teacher_id FROM submissions s JOIN assignments a ON a.id=s.assignment_id JOIN batches b ON b.id=a.batch_id WHERE s.id=?", (sid,))
        if not s or not s["file"]: return err("File not found", 404)
        u = g.user
        if not (u["role"] == "admin" or (u["role"] == "teacher" and s["teacher_id"] == u["id"]) or (u["role"] == "student" and s["student_id"] == u["id"])):
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
        ex = one("SELECT id FROM submissions WHERE assignment_id=? AND student_id=?", (aid, sid))
        if ex:
            db().execute("UPDATE submissions SET grade=?,feedback=?,graded_by=?,graded_at=datetime('now') WHERE id=?", (gr, fb, g.user["id"], ex["id"]))
        else:
            db().execute("INSERT INTO submissions(assignment_id,student_id,grade,feedback,graded_by,graded_at) VALUES(?,?,?,?,?,datetime('now'))", (aid, sid, gr, fb, g.user["id"]))
        audit("grade", "assignment", aid, f"student {sid}: {gr}/{a['max_points']}"); db().commit()
        return jsonify(ok=True, grade=gr)

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
        out = []
        for b in bs:
            items = rows("SELECT a.id,a.title,a.kind,a.max_points,a.due_date,s.grade,s.feedback,s.is_late,(s.submitted_at IS NOT NULL) AS submitted "
                         "FROM assignments a LEFT JOIN submissions s ON s.assignment_id=a.id AND s.student_id=? WHERE a.batch_id=? ORDER BY COALESCE(a.due_date,'9999-12-31'),a.id",
                         (uid, b["id"]))
            r = one(GRADE_SQL + "AND s.student_id=? GROUP BY s.student_id", (b["id"], uid))
            out.append({"batch_id": b["id"], "course_name": b["course_name"], "batch_code": b["code"], "avg_pct": avg(r),
                        "attendance_pct": batch_att(b["id"], uid)["pct"], "items": items})
        return out

    @app.get("/api/my/grades")
    @auth("student")
    def l_my_grades():
        return jsonify(grades_for(g.user["id"], my_batches()))

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
        audit("add_material", "material", mid, f["title"]); db().commit()
        return jsonify(id=mid), 201

    @app.get("/api/materials")
    @auth()
    def l_mat_list():
        ids = [b["id"] for b in my_batches(request.args.get("batch_id", type=int))]
        if not ids: return jsonify([])
        q = ",".join("?" * len(ids))
        return jsonify(rows(f"SELECT m.id,m.batch_id,m.title,m.description,m.kind,m.file_name,m.url,m.created_at,b.code AS batch_code,c.name AS course_name,u.full_name AS uploader "
                            f"FROM materials m JOIN batches b ON b.id=m.batch_id JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=m.uploaded_by "
                            f"WHERE m.batch_id IN ({q}) ORDER BY m.id DESC", ids))

    @app.get("/api/materials/<int:mid>/file")
    @auth()
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
        audit("delete_material", "material", mid, m["title"]); db().commit()
        return jsonify(ok=True)

    # ---------- tutorials library (Phase 5, started): everyone signed in reads and posts; admin or the poster deletes ----------
    @app.post("/api/tutorials")
    @auth()
    def l_tut_add():
        """Written text, a file, a link, or any mix (at least one). Form when a file is attached, JSON otherwise."""
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
        stored = shown = None
        if has_file:
            try: stored, shown = save_file(up, ALLOWED_MATERIAL)
            except ValueError as x: return err(str(x))
        tid = db().execute("INSERT INTO tutorials(title,body,course_id,file,file_name,url,uploaded_by) VALUES(?,?,?,?,?,?,?)",
                           (f["title"].strip(), text or None, cid, stored, shown, url or None, g.user["id"])).lastrowid
        audit("add_tutorial", "tutorial", tid, f["title"]); db().commit()
        return jsonify(id=tid), 201

    @app.get("/api/tutorials")
    @auth()
    def l_tut_list():
        cid, q = request.args.get("course_id", type=int), (request.args.get("q") or "").strip()
        w, a = [], []
        if cid: w.append("t.course_id=?"); a.append(cid)
        if q: w.append("(t.title LIKE ? OR t.body LIKE ?)"); a += [f"%{q}%"] * 2
        items = rows("SELECT t.id,t.title,t.body AS text,t.course_id,t.file_name,(t.file IS NOT NULL) AS has_file,t.url,t.created_at,t.uploaded_by,c.name AS course_name,u.full_name AS uploader,u.role AS uploader_role "
                     "FROM tutorials t LEFT JOIN courses c ON c.id=t.course_id JOIN users u ON u.id=t.uploaded_by "
                     + ("WHERE " + " AND ".join(w) + " " if w else "") + "ORDER BY t.id DESC LIMIT 300", a)
        for t in items:
            t["has_file"] = bool(t["has_file"])
            t["can_delete"] = g.user["role"] == "admin" or t.pop("uploaded_by") == g.user["id"]
            t.pop("uploaded_by", None)
        return jsonify(items)

    @app.get("/api/tutorials/<int:tid>/file")
    @auth()
    def l_tut_file(tid):
        t = one("SELECT file,file_name FROM tutorials WHERE id=?", (tid,))
        if not t or not t["file"]: return err("File not found", 404)
        return send_private(t["file"], t["file_name"])

    @app.delete("/api/tutorials/<int:tid>")
    @auth()
    def l_tut_del(tid):
        t = one("SELECT * FROM tutorials WHERE id=?", (tid,))
        if not t: return err("Tutorial not found", 404)
        if g.user["role"] != "admin" and t["uploaded_by"] != g.user["id"]: return err("You can only delete your own posts", 403)
        rm(t["file"])
        db().execute("DELETE FROM tutorials WHERE id=?", (tid,))
        audit("delete_tutorial", "tutorial", tid, t["title"]); db().commit()
        return jsonify(ok=True)

    # ---------- home (student + teacher) ----------
    @app.get("/api/my/home")
    @auth("student", "teacher")
    def l_home():
        u = g.user
        t0 = today()
        bs = my_batches()
        occ = occurrences(bs, t0, t0 + dt.timedelta(days=27))
        nxt = next_class(occ)
        out = {"today": [clean(o) for o in occ if o["date"] == t0.isoformat()],
               "week": [clean(o) for o in occ if o["date"] < (t0 + dt.timedelta(days=7)).isoformat()],
               "next_class": clean(nxt) if nxt else None,
               "batches_without_schedule": [{"id": b["id"], "course_name": b["course_name"], "code": b["code"]} for b in bs if b["status"] != "closed" and not (b["days"] and b["start_time"])]}
        if u["role"] == "student":
            gr = {x["batch_id"]: x for x in grades_for(u["id"], bs)}
            out["courses"] = [{"batch_id": b["id"], "course_name": b["course_name"], "batch_code": b["code"], "teacher_name": b["teacher_name"],
                               "attendance_pct": gr[b["id"]]["attendance_pct"], "avg_pct": gr[b["id"]]["avg_pct"]} for b in bs]
            ids = [b["id"] for b in bs]
            todo = []
            if ids:
                q = ",".join("?" * len(ids))
                todo = rows(f"SELECT a.id,a.title,a.due_date,c.name AS course_name FROM assignments a JOIN batches b ON b.id=a.batch_id JOIN courses c ON c.id=b.course_id "
                            f"WHERE a.batch_id IN ({q}) AND a.kind='assignment' AND NOT EXISTS (SELECT 1 FROM submissions s WHERE s.assignment_id=a.id AND s.student_id=? AND s.submitted_at IS NOT NULL) "
                            f"ORDER BY COALESCE(a.due_date,'9999-12-31') LIMIT 5", (*ids, u["id"]))
            out["todo"] = todo
        else:
            ids = [b["id"] for b in bs]
            n = 0
            low = []
            if ids:
                q = ",".join("?" * len(ids))
                n = one(f"SELECT COUNT(*) n FROM submissions s JOIN assignments a ON a.id=s.assignment_id WHERE a.batch_id IN ({q}) AND s.submitted_at IS NOT NULL AND s.grade IS NULL", ids)["n"]
            for b in bs:
                st = batch_att(b["id"])
                for s in roster(b["id"]):
                    if st.get(s["id"], {}).get("low"):
                        low.append({"batch_id": b["id"], "batch_code": b["code"], "course_name": b["course_name"], "student_id": s["id"], "full_name": s["full_name"], "pct": st[s["id"]]["pct"]})
            out["to_grade"], out["low_attendance"] = n, low
        return jsonify(out)
