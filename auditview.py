"""Session 21: activity log viewer (read only).

register() adds, all for admins with the 'audit' permission:
  GET /api/audit          filtered rows, newest first, as a JSON LIST (older screens and tests rely on that);
                          paging in the query (page, per_page) and in the headers X-Total-Count / X-Page / X-Per-Page
  GET /api/audit.csv      the same filter as a CSV download (the export itself is logged)
  GET /api/audit/summary  what a user, batch or course has done: totals, counts per action, busiest people
  GET /api/audit/actions  the action names present in the log (for the filter box)
Filters: user_id (who did it), login_id, role, course_id, batch_id, action (one, or several separated by commas), entity, entity_id,
q (words in the detail), date_from / date_to (Maldives dates, inclusive).
There is deliberately NO route that changes or deletes a log row; the database triggers in auditlog.py refuse it as well."""
import csv, datetime as dt, io
from flask import Response, jsonify, request

MVT_HOURS = 5          # the log stores UTC; people think in Maldives dates
MAX_PAGE, MAX_CSV = 500, 20000
COLS = ("id", "at", "user_id", "user_name", "user_role", "login_id", "action", "entity", "entity_id", "course_id", "batch_id", "old_value", "new_value", "ip", "detail")
BASE = "FROM audit_log a LEFT JOIN users u ON u.id=a.user_id"


def utc_bounds(day, end=False):
    """'YYYY-MM-DD' (Maldives) -> UTC 'YYYY-MM-DD HH:MM:SS' for the start of that day, or of the next day when end=True."""
    d = dt.datetime.strptime(day, "%Y-%m-%d") + dt.timedelta(days=1 if end else 0) - dt.timedelta(hours=MVT_HOURS)
    return d.strftime("%Y-%m-%d %H:%M:%S")


def where_of(args):
    """Returns (sql, params, error). Every value is a bound parameter; nothing from the request is put into the SQL text."""
    w, p = [], []

    def num(name, col):
        v = args.get(name)
        if v in (None, ""): return None
        try: w.append(f"{col}=?"); p.append(int(v))
        except ValueError: return f"{name} must be a number"
    for name, col in (("user_id", "a.user_id"), ("course_id", "a.course_id"), ("batch_id", "a.batch_id"), ("entity_id", "a.entity_id")):
        e = num(name, col)
        if e: return "", [], e
    if args.get("role"): w.append("a.user_role=?"); p.append(args["role"].strip().lower())
    if args.get("login_id"): w.append("UPPER(a.login_id)=?"); p.append(args["login_id"].strip().upper())
    if args.get("entity"): w.append("a.entity=?"); p.append(args["entity"].strip())
    acts = [x.strip() for x in (args.get("action") or "").split(",") if x.strip()]
    if acts: w.append("a.action IN (" + ",".join("?" * len(acts)) + ")"); p += acts
    if args.get("q"): w.append("LOWER(COALESCE(a.detail,'')) LIKE ?"); p.append("%" + args["q"].strip().lower()[:100] + "%")
    try:
        if args.get("date_from"): w.append("a.at>=?"); p.append(utc_bounds(args["date_from"]))
        if args.get("date_to"): w.append("a.at<?"); p.append(utc_bounds(args["date_to"], end=True))
    except ValueError:
        return "", [], "Dates must look like 2027-03-31"
    return (" WHERE " + " AND ".join(w)) if w else "", p, None


def register(app, c):
    db, rows, one, err, auth, audit = c.db, c.rows, c.one, c.err, c.auth, c.audit

    def paging(default):
        try: page = max(1, int(request.args.get("page", 1))); per = int(request.args.get("per_page", default))
        except ValueError: return None, None, "page and per_page must be numbers"
        return page, max(1, min(per, MAX_PAGE)), None

    @app.get("/api/audit")
    @auth("admin", perm="audit")
    def audit_list():
        w, p, e = where_of(request.args)
        if e: return err(e)
        page, per, e = paging(100)
        if e: return err(e)
        # Session 13 (v0.8.33): ?offset= wins over page, so the screen can ask for one row more than a page and know whether a next page exists
        off = request.args.get("offset", "")
        if off and not off.isdigit(): return err("offset must be a number")
        start = int(off) if off else (page - 1) * per
        total = one(f"SELECT COUNT(*) n {BASE}{w}", p)["n"]
        out = rows(f"SELECT a.*, u.full_name AS user_name {BASE}{w} ORDER BY a.id DESC LIMIT ? OFFSET ?", (*p, per, start))
        resp = jsonify(out)
        resp.headers.update({"X-Total-Count": str(total), "X-Page": str(page), "X-Per-Page": str(per), "Access-Control-Expose-Headers": "X-Total-Count, X-Page, X-Per-Page"})
        return resp

    def audit_export(ext):
        import excelio
        w, p, e = where_of(request.args)
        if e: return err(e)
        r = rows(f"SELECT a.*, u.full_name AS user_name {BASE}{w} ORDER BY a.id DESC LIMIT ?", (*p, MAX_CSV))
        audit(f"export_audit_{ext}", "report", None, f"{len(r)} rows" + (" (cut at %d)" % MAX_CSV if len(r) == MAX_CSV else "") + (f"; filters: {dict(request.args)}" if request.args else ""))
        db().commit()
        return excelio.send_table(ext, "activity-log", COLS, [[x.get(k) for k in COLS] for x in r], "Activity log")

    @app.get("/api/audit.csv")
    @auth("admin", perm="audit")
    def audit_csv(): return audit_export("csv")

    @app.get("/api/audit.xlsx")
    @auth("admin", perm="audit")
    def audit_xlsx(): return audit_export("xlsx")   # v0.8.38

    @app.get("/api/audit/summary")
    @auth("admin", perm="audit")
    def audit_summary():
        w, p, e = where_of(request.args)
        if e: return err(e)
        tot = one(f"SELECT COUNT(*) n, MIN(a.at) first_at, MAX(a.at) last_at {BASE}{w}", p)
        return jsonify(total=tot["n"], first_at=tot["first_at"], last_at=tot["last_at"],
                       by_action=rows(f"SELECT a.action, COUNT(*) n {BASE}{w} GROUP BY a.action ORDER BY n DESC, a.action LIMIT 50", p),
                       by_user=rows(f"SELECT a.user_id, MAX(u.full_name) user_name, MAX(a.user_role) user_role, COUNT(*) n {BASE}{w} GROUP BY a.user_id ORDER BY n DESC LIMIT 10", p))

    @app.get("/api/audit/actions")
    @auth("admin", perm="audit")
    def audit_actions():
        return jsonify([r["action"] for r in rows("SELECT DISTINCT action FROM audit_log ORDER BY action")])
