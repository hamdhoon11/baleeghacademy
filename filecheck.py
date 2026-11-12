"""v0.8.34: storage health for admins.

  GET /api/admin/storage           where uploaded files are kept, whether that survives (Vercel's disk does not), and what to do about it
  GET /api/admin/storage/missing   records whose file can no longer be found (for example uploads lost on Vercel before v0.8.34),
                                   so the admin knows which ID copies, slips, materials, assignments, answers and receipts to ask for again

Admins with the Settings area only. Read only: nothing is changed or deleted here.
"""
import os

from flask import jsonify, request

# (area, what it is, table, file column, label SQL, date column). The label tells the admin which record it is.
REFS = (
    ("ids", "ID copy (application)", "applications", "id_file", "full_name || ' (' || ref || ')'", "created_at"),
    ("ids", "Guardian ID copy (application)", "applications", "guardian_id_file", "full_name || ' (' || ref || ')'", "created_at"),
    ("slips", "Payment slip", "payment_slips", "file", "COALESCE(file_name, file)", "created_at"),
    ("learning", "Assignment file", "assignments", "attachment", "title", "created_at"),
    ("learning", "Student submission", "submissions", "file", "COALESCE(file_name, file)", "submitted_at"),
    ("learning", "Class material", "materials", "file", "title", "created_at"),
    ("learning", "Tutorial file", "tutorials", "file", "title", "created_at"),
    ("learning", "Tutorial answer", "tutorial_submissions", "file", "COALESCE(file_name, file)", "submitted_at"),
    ("receipts", "Expense receipt", "expenses", "receipt_file", "COALESCE(receipt_name, receipt_file)", "created_at"),
)
CHECK_LIMIT = 400   # bucket checks are one request each; keep a scan inside a serverless time limit


def health(app, store):
    """Where files live and whether they last. persistent=False means uploads will (or already did) disappear."""
    pg, vercel = app.config.get("USE_POSTGRES"), bool(app.config.get("ON_VERCEL"))
    kind = store.kind
    if kind == "s3":
        persistent, advice = True, ""
    elif kind == "db":
        persistent = bool(pg) or not vercel
        advice = "" if persistent else "Files are kept in the database, but the database is a temporary SQLite file on Vercel. Set DATABASE_URL (PostgreSQL) so data and files are kept."
    else:
        persistent = not vercel
        advice = "" if persistent else "Files are on Vercel's temporary disk and disappear within minutes. Leave FILE_STORAGE empty (files then go into the database) or set S3_BUCKET."
    return {"storage": kind, "where": store.describe(), "database": "postgresql" if pg else "sqlite", "on_vercel": vercel,
            "persistent": persistent, "advice": advice}


def register(app, c):
    store = c.store

    @app.get("/api/admin/storage")
    @c.auth("admin", perm="settings")
    def storage_info():
        h = health(app, store)
        if store.kind == "db":
            r = c.one("SELECT COUNT(*) AS n, COALESCE(SUM(size),0) AS bytes FROM stored_files")
            h["files"], h["mb"] = r["n"], round((r["bytes"] or 0) / 1048576, 1)
        return jsonify(h)

    @app.get("/api/admin/storage/missing")
    @c.auth("admin", perm="settings")
    def storage_missing():
        have = None
        if store.kind == "db":   # one query instead of one per file
            have = {(r["area"], r["name"]) for r in c.rows("SELECT area, name FROM stored_files")}
        out, checked, total, cut = [], 0, 0, False
        for area, what, table, col, label, when in REFS:
            for r in c.rows(f"SELECT id, {col} AS f, {label} AS label, {when} AS at FROM {table} WHERE {col} IS NOT NULL AND {col} <> '' ORDER BY id DESC"):
                total += 1
                if have is None and checked >= CHECK_LIMIT: cut = True; continue
                checked += 1
                ok = (area, os.path.basename(r["f"])) in have if have is not None else store.exists(area, r["f"])
                if not ok:
                    out.append({"kind": what, "table": table, "id": r["id"], "label": r["label"], "at": r["at"]})
        by_kind = {}
        for x in out: by_kind[x["kind"]] = by_kind.get(x["kind"], 0) + 1
        limit = min(int(request.args.get("limit", 200) or 200), 1000)
        return jsonify(total=total, checked=checked, complete=not cut, missing=len(out), by_kind=by_kind, items=out[:limit])
