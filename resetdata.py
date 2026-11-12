"""v0.8.41: "Clear portal data". Removes everything that was entered into the portal and keeps the admins.

  POST /api/admin/reset-data    full admins only (Settings area, permissions = all).
       {}                                  -> a preview: what would be deleted, per table. Nothing is changed.
       {"apply": true, "password": "...",  -> deletes. Needs the admin's own password and the exact words DELETE ALL DATA.
        "confirm": "DELETE ALL DATA",
        "reset_numbers": false}

KEPT:    every admin account (login ID, password, permissions), the settings, the activity log (it cannot be deleted by design, and it
         records who cleared the data and when), the ID and receipt number counters (so a number is never given out twice) unless
         reset_numbers is true (then student, teacher, enrolment and receipt numbers start again from 1; admin IDs never restart).
DELETED: teacher and student accounts, courses, batches, enrolments, applications, classes, attendance, assignments, answers, grades,
         materials, recordings, tutorials, invoices, payments, slips, discounts, families, expenses and categories, monthly expenses,
         teacher earnings and payments, notifications, reminders, password requests, and every uploaded file.

Everything is deleted in one transaction: if any step fails, nothing is deleted. It cannot be undone afterwards; take the database
provider's backup first. Files in a bucket or a local folder are removed after the database commit (in the database they go with it).

Also usable from the command line (dry run by default, like the migrate scripts):
    python resetdata.py                              shows what would be deleted
    python resetdata.py --apply --i-have-a-backup    deletes
"""
import re

PHRASE = "DELETE ALL DATA"
KEEP = ("users", "settings", "audit_log", "audit_unlock", "schema_meta", "counters")   # users: admins stay, see wipe()
_TABLE = re.compile(r"CREATE TABLE IF NOT EXISTS (\w+)", re.I)

# words for the preview; a table not listed here is shown by its own name
LABELS = {"users": "Teacher and student accounts", "students": "Student profiles", "teachers": "Teacher profiles", "courses": "Courses", "batches": "Batches",
          "enrollments": "Enrolments", "enrollment_events": "Transfers and withdrawals", "applications": "Applications", "sessions": "Classes",
          "attendance": "Attendance marks", "assignments": "Assignments and tests", "submissions": "Submitted work and grades", "materials": "Class materials",
          "recordings": "Recordings", "tutorials": "Tutorials", "tutorial_submissions": "Tutorial answers", "substitutions": "Substitute teachers",
          "families": "Families", "family_members": "Family members", "invoices": "Invoices", "discounts": "Discounts", "payment_slips": "Payment slips",
          "payments": "Payments", "reminders": "Fee reminders", "expense_categories": "Expense categories", "expenses": "Expenses",
          "recurring_expenses": "Monthly expenses", "recurring_done": "Monthly expenses already entered", "notifications": "Notifications", "wa_log": "WhatsApp log",
          "teacher_earnings": "Teacher earnings", "teacher_payments": "Payments to teachers", "stored_files": "Files stored in the database",
          "password_help": "Password requests", "rate_hits": "Attempt counters"}


def table_refs(script):
    """{table: the tables it points to}, read from schema.sql (tests compare this with what the database itself reports)."""
    text = re.sub(r"--[^\n]*", "", script)                       # comments may mention other tables
    parts = _TABLE.split(text)                                    # [before, name1, body1, name2, body2, ...]
    return {name.lower(): {r.lower() for r in re.findall(r"\bREFERENCES\s+(\w+)", body, re.I)} - {name.lower()}
            for name, body in zip(parts[1::2], parts[2::2])}


def delete_order(script):
    """Tables of schema.sql in an order that never breaks a reference: a table comes before every table it points to."""
    refs = table_refs(script)
    order, left = [], dict(refs)
    while left:
        free = sorted(t for t in left if not any(t in r for o, r in left.items() if o != t))
        if not free: free = sorted(left)   # a circle of references (none today): take them as they come; the transaction undoes a failure
        for t in free: order.append(t); del left[t]
    return order


def _tables(conn, script):
    return [t for t in delete_order(script) if t not in KEEP and conn.columns(t)]


def _count(conn, sql):
    return int(conn.execute(sql).fetchone()[0])


def plan(conn, script):
    """What wipe() would delete: [{table, label, rows}] (only tables with rows) and what stays. Changes nothing."""
    items = [{"table": "users", "label": LABELS["users"], "rows": _count(conn, "SELECT COUNT(*) FROM users WHERE role<>'admin'")}]
    for t in _tables(conn, script):
        items.append({"table": t, "label": LABELS.get(t, t), "rows": _count(conn, f"SELECT COUNT(*) FROM {t}")})
    items = [i for i in items if i["rows"]]
    return {"items": items, "total": sum(i["rows"] for i in items),
            "kept": {"admins": _count(conn, "SELECT COUNT(*) FROM users WHERE role='admin'"), "settings": _count(conn, "SELECT COUNT(*) FROM settings"),
                     "log_rows": _count(conn, "SELECT COUNT(*) FROM audit_log")}}


def file_refs(conn):
    """(area, stored name) of every uploaded file the records point to. Read before the rows are deleted."""
    import filecheck
    out = []
    for area, _what, table, col, _label, _when in filecheck.REFS:
        if col not in conn.columns(table): continue
        for r in conn.execute(f"SELECT {col} AS f FROM {table} WHERE {col} IS NOT NULL AND {col} <> ''").fetchall():
            out.append((area, r["f"]))
    return out


def wipe(conn, script, reset_numbers=False):
    """Deletes inside the caller's transaction (the caller commits or rolls back). Returns {table: rows deleted}."""
    done = {}
    for t in _tables(conn, script):
        n = conn.execute(f"DELETE FROM {t}").rowcount
        if n: done[t] = n
    n = conn.execute("DELETE FROM users WHERE role<>'admin'").rowcount
    if n: done["users"] = n
    if reset_numbers:
        conn.execute("DELETE FROM counters WHERE name<>'admin'")   # admin login IDs never restart: the admins are still there
        conn.execute("INSERT INTO counters(name,value) VALUES('receipt',0) ON CONFLICT (name) DO NOTHING")
    return done


def remove_files(store, refs):
    """After the commit. Files kept in the database went with the stored_files table; a bucket or folder is emptied file by file."""
    if getattr(store, "kind", "") == "db": return 0, 0
    ok = bad = 0
    for area, name in refs:
        try: store.delete(area, name); ok += 1
        except Exception: bad += 1   # the record is gone either way; a left-over file is unreachable (downloads go through the records)
    return ok, bad


def register(app, c, script, check_password):
    from flask import g, jsonify, request

    @app.post("/api/admin/reset-data")
    @c.auth("admin", perm="settings")
    def reset_data():
        if g.user["permissions"] is not None: return c.err("Only a full admin can clear the portal's data", 403)
        d = request.get_json(silent=True) or {}
        db = c.db()
        if not d.get("apply"):
            return jsonify(apply=False, phrase=PHRASE, **plan(db, script))
        if str(d.get("confirm") or "").strip() != PHRASE: return c.err(f"Type {PHRASE} exactly to confirm")
        if not check_password(g.user["id"], str(d.get("password") or "")):
            c.audit("reset_data_refused", "portal", None, "wrong password"); db.commit()
            return c.err("Your password is wrong", 403)
        before = plan(db, script)
        refs = file_refs(db)
        try:
            done = wipe(db, script, bool(d.get("reset_numbers")))
            c.audit("reset_data", "portal", None, ("numbers restarted; " if d.get("reset_numbers") else "") +
                    ", ".join(f"{t} {n}" for t, n in sorted(done.items()))[:280], old=str(before["total"]), new="0")
            db.commit()
        except Exception:
            db.rollback(); raise
        files_ok, files_bad = remove_files(c.store, refs)
        return jsonify(apply=True, deleted=done, total=sum(done.values()), files_removed=files_ok, files_left=files_bad, kept=plan(db, script)["kept"])


if __name__ == "__main__":
    import argparse, os, sys
    import dbx
    ap = argparse.ArgumentParser(description="Clear the portal's data and keep the admins. Dry run unless --apply.")
    ap.add_argument("--apply", action="store_true"); ap.add_argument("--i-have-a-backup", action="store_true"); ap.add_argument("--reset-numbers", action="store_true")
    a = ap.parse_args()
    base = os.path.dirname(os.path.abspath(__file__))
    cfg = {"DATABASE_URL": os.environ.get("DATABASE_URL", ""), "DATABASE_PATH": os.environ.get("DATABASE_PATH", os.path.join(base, "instance", "portal.db"))}
    script = dbx.read_schema(base); conn = dbx.connect(cfg, base, script)
    try:
        p = plan(conn, script)
        for i in p["items"]: print(f"  {i['rows']:>7}  {i['label']} ({i['table']})")
        print(f"Would delete {p['total']} row(s). Kept: {p['kept']['admins']} admin(s), {p['kept']['settings']} setting(s), {p['kept']['log_rows']} log row(s).")
        if not a.apply: print("Dry run: nothing was changed. Add --apply --i-have-a-backup to delete."); sys.exit(0)
        if not a.i_have_a_backup: print("Refused: take a backup first, then add --i-have-a-backup."); sys.exit(2)
        refs = file_refs(conn)
        done = wipe(conn, script, a.reset_numbers)
        conn.execute("INSERT INTO audit_log(action,entity,detail,user_role,old_value,new_value) VALUES('reset_data','portal',?,'system',?,'0')",
                     (", ".join(f"{t} {n}" for t, n in sorted(done.items()))[:280], str(p["total"])))
        conn.commit()
        print(f"Deleted {sum(done.values())} row(s). Uploaded files in a bucket or folder are not removed by the command line: {len(refs)} file(s) are now unreachable.")
    finally:
        conn.close()
