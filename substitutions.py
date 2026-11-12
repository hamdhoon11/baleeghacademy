"""Session 22: substitute teachers.

A substitution gives another teacher temporary access to ONE batch's class information for a date or a date range. batches.teacher_id is
never touched. Access exists only while today (Maldives date) is inside [class_date, ends_on] and the row is not removed; nothing has to run
to end it, the date check does. What a substitute may do (decision recorded in HANDOFF.md): see the batch in their picker and timetable
(only the substituted dates), see the class students and the join link, and take/see attendance for the substituted dates. Not: assignments,
grades, materials, tutorials, class cancellation, link editing, people information, or the batch's earlier attendance history.

windows()  - pure helper used by learning.py: {batch_id: [(first_day, last_day)]} active on a day
register() - admin routes (area 'batches') and the teacher's own list:
  POST   /api/substitutions        batch_id, substitute_teacher_id, class_date (or session_id), ends_on?, reason?
  GET    /api/substitutions        ?batch_id=&when=active|upcoming|past|all (default all, newest first)
  DELETE /api/substitutions/<id>   ends it now (the row stays as history; removed_at is set)
  GET    /api/my/substitutions     teacher: my current and upcoming substitutions (no student data)"""
import datetime as dt
from flask import g, jsonify, request

MAX_DAYS = 92


def windows(rows, uid, day):
    """day is 'YYYY-MM-DD'. Returns {batch_id: [(first_day, last_day), ...]} of this teacher's live substitutions on that day."""
    out = {}
    for r in rows("SELECT batch_id,class_date,COALESCE(ends_on,class_date) AS last_day FROM substitutions "
                  "WHERE substitute_teacher_id=? AND removed_at IS NULL AND class_date<=? AND COALESCE(ends_on,class_date)>=?", (uid, day, day)):
        out.setdefault(r["batch_id"], []).append((r["class_date"], r["last_day"]))
    return out


def register(app, c, today, utc_stamp):
    db, rows, one, err, auth, audit = c.db, c.rows, c.one, c.err, c.auth, c.audit

    def pday(v):
        try: return dt.date.fromisoformat(str(v))
        except ValueError: return None

    SQL = ("SELECT s.id,s.batch_id,b.code AS batch_code,c.name AS course_name,s.class_date,COALESCE(s.ends_on,s.class_date) AS last_day,s.ends_on,s.session_id,s.reason,"
           "s.original_teacher_id,ou.full_name AS original_teacher,s.substitute_teacher_id,su.full_name AS substitute_teacher,s.created_by,s.created_at,s.removed_at "
           "FROM substitutions s JOIN batches b ON b.id=s.batch_id JOIN courses c ON c.id=b.course_id "
           "LEFT JOIN users ou ON ou.id=s.original_teacher_id JOIN users su ON su.id=s.substitute_teacher_id")

    def tag(r):
        t = today().isoformat()
        r["state"] = "removed" if r["removed_at"] else "active" if r["class_date"] <= t <= r["last_day"] else "upcoming" if r["class_date"] > t else "past"
        return r

    @app.post("/api/substitutions")
    @auth("admin", perm="batches")
    def sub_create():
        d = request.get_json(silent=True) or {}
        try: bid, tid = int(d.get("batch_id")), int(d.get("substitute_teacher_id"))
        except (TypeError, ValueError): return err("Choose a batch and a substitute teacher")
        b = one("SELECT id,code,teacher_id FROM batches WHERE id=?", (bid,))
        if not b: return err("Batch not found", 404)
        if not one("SELECT id FROM users WHERE id=? AND role='teacher' AND is_active=1", (tid,)): return err("The substitute must be an active teacher", 400)
        if tid == b["teacher_id"]: return err("That teacher already teaches this batch", 400)
        sess = None
        if d.get("session_id"):
            sess = one("SELECT id,session_date FROM sessions WHERE id=? AND batch_id=?", (d["session_id"], bid))
            if not sess: return err("That class does not belong to this batch", 400)
        first = pday(sess["session_date"] if sess else d.get("class_date"))
        if not first: return err("Enter the class date (YYYY-MM-DD)")
        last = pday(d.get("ends_on")) if d.get("ends_on") else None
        if d.get("ends_on") and not last: return err("Enter a valid end date (YYYY-MM-DD)")
        if sess: last = None                                     # one class
        if last and last < first: return err("The end date cannot be before the start date")
        if (last or first) < today(): return err("These dates are already in the past")
        if last and (last - first).days > MAX_DAYS: return err(f"A substitution can cover at most {MAX_DAYS} days; add another one after it")
        lo, hi = first.isoformat(), (last or first).isoformat()
        if one("SELECT 1 x FROM substitutions WHERE batch_id=? AND removed_at IS NULL AND class_date<=? AND COALESCE(ends_on,class_date)>=?", (bid, hi, lo)):
            return err("This batch already has a substitute on some of those dates. Remove that one first.", 409)
        reason = (d.get("reason") or "").strip()[:300] or None
        sid = db().execute("INSERT INTO substitutions(batch_id,class_date,session_id,original_teacher_id,substitute_teacher_id,reason,created_by,ends_on) VALUES(?,?,?,?,?,?,?,?)",
                           (bid, lo, sess["id"] if sess else None, b["teacher_id"], tid, reason, g.user["id"], last.isoformat() if last else None)).lastrowid
        audit("substitute_assign", "substitution", sid, f"batch {b['code']}: teacher {tid} on {lo}" + (f" to {hi}" if hi != lo else "") + (f" ({reason})" if reason else ""),
              batch_id=bid, old=b["teacher_id"], new=tid)
        span = lo + (f" to {hi}" if hi != lo else "")     # Session 28: tell the substitute, the teacher being replaced and the students
        c.notify([tid], "substitute_assigned", "You are a substitute teacher", f"Batch {b['code']}, {span}" + (f": {reason}" if reason else ""), f"classroom:{bid}")
        c.notify([b["teacher_id"]], "substitute_for_you", "A substitute will teach your batch", f"Batch {b['code']}, {span}", f"classroom:{bid}")
        c.notify(c.notify_students_of(bid), "substitute_class", "Substitute teacher", f"Batch {b['code']}, {span}: another teacher will take the class.", "home")
        db().commit()
        return jsonify(id=sid), 201

    @app.get("/api/substitutions")
    @auth("admin", perm="batches")
    def sub_list():
        w, a = [], []
        if request.args.get("batch_id"):
            try: a.append(int(request.args["batch_id"])); w.append("s.batch_id=?")
            except ValueError: return err("batch_id must be a number")
        out = [tag(r) for r in rows(SQL + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY s.class_date DESC, s.id DESC", a)]
        when = request.args.get("when", "all")
        if when != "all": out = [r for r in out if r["state"] == when]
        return jsonify(out)

    @app.delete("/api/substitutions/<int:sid>")
    @auth("admin", perm="batches")
    def sub_remove(sid):
        r = one("SELECT * FROM substitutions WHERE id=?", (sid,))
        if not r: return err("Substitution not found", 404)
        if r["removed_at"]: return err("Already removed", 409)
        db().execute("UPDATE substitutions SET removed_at=?, removed_by=? WHERE id=?", (utc_stamp(), g.user["id"], sid))
        audit("substitute_remove", "substitution", sid, f"batch {r['batch_id']}: teacher {r['substitute_teacher_id']}", batch_id=r["batch_id"], old=r["substitute_teacher_id"])
        bc = one("SELECT code FROM batches WHERE id=?", (r["batch_id"],))["code"]     # Session 28
        c.notify([r["substitute_teacher_id"]], "substitute_removed", "Substitute cancelled", f"Batch {bc}, {r['class_date']}: the substitution was removed.", "home")   # no longer their class
        c.notify([r["original_teacher_id"]], "substitute_removed", "Substitute cancelled", f"Batch {bc}, {r['class_date']}: the substitution was removed.", f"classroom:{r['batch_id']}")   # Session 16
        c.notify(c.notify_students_of(r["batch_id"]), "substitute_removed", "Teacher unchanged", f"Batch {bc}, {r['class_date']}: the usual teacher will take the class.", "home")
        db().commit()
        return jsonify(ok=True)

    @app.get("/api/my/substitutions")
    @auth("teacher")
    def sub_mine():
        uid = g.user["id"]
        t = today().isoformat()
        out = [tag(r) for r in rows(SQL + " WHERE s.substitute_teacher_id=? AND s.removed_at IS NULL AND COALESCE(s.ends_on,s.class_date)>=? ORDER BY s.class_date", (uid, t))]
        return jsonify([{k: r[k] for k in ("id", "batch_id", "batch_code", "course_name", "class_date", "last_day", "reason", "original_teacher", "state")} for r in out])
