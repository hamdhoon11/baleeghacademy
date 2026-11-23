"""v0.8.61: remove a person from the portal, even when they already have records.

Before this version an account could only be deleted while it had no records at all; anyone with an enrolment, grade or invoice had to be
disabled instead. Now an admin with the People area can remove them. The person's own records go with them; money records stay so the
finance totals never change:

  DELETED   the account and profile, enrolments, attendance marks, submitted work and grades, tutorial answers, transfer/withdrawal history,
            family membership, notifications, WhatsApp log, password requests, sign-in history, Teachers' room messages, the classes they
            were booked to cover as a substitute, recurring discounts on their enrolments, and their uploaded answer files.
  KEPT      invoices, payments, payment slips and one-off discounts. The invoices keep the person's name and phone ("Not in portal", like a
            walk-in customer from v0.8.45), so Fees, receipts, reports and finance show the same totals as before. Unpaid invoices stay
            owed: void them in Fees if they will not be paid.
            Applications stay in Admissions (no longer linked to an account).
            Things they made for others stay: batches they taught are left without a teacher, assignments, materials, recordings, classes,
            grades they gave, payments they recorded, and so on lose only the "by whom" (the activity log still has it). Tutorials, which
            must have an owner, move to the admin who removes the person.
  REFUSED   a teacher with pay records (earnings, payments to the teacher, salary expenses): payroll needs the teacher. Disable instead.

GET  /api/users/<id>/removal   -> the preview (counts). Changes nothing.
DELETE /api/users/<id>          -> removes. {"password": "..."} (the admin's own) is required when the person has any records.

Every (table, column) that points at users must be listed in PLAN; tests/test_v0861.py fails when a new one is added without a decision.
"""

# (table, column) -> what happens to the rows that point at the person
DELETE, DETACH, NULL, OWNER, BLOCK = "delete", "detach", "null", "owner", "block"
PLAN = {
    # the person's own records: deleted
    ("notifications", "user_id"): DELETE, ("wa_log", "user_id"): DELETE, ("password_help", "user_id"): DELETE,
    ("staff_messages", "user_id"): DELETE, ("fee_notes", "student_id"): DELETE, ("post_reads", "user_id"): DELETE, ("post_comments", "user_id"): DELETE, ("attendance", "student_id"): DELETE, ("submissions", "student_id"): DELETE,
    ("tutorial_submissions", "student_id"): DELETE, ("enrollment_events", "student_id"): DELETE, ("family_members", "student_id"): DELETE,
    ("enrollments", "student_id"): DELETE, ("substitutions", "substitute_teacher_id"): DELETE,
    ("students", "user_id"): DELETE, ("teachers", "user_id"): DELETE,
    # money and admissions: kept, no longer linked to the account
    ("invoices", "student_id"): DETACH, ("payments", "student_id"): DETACH, ("payment_slips", "student_id"): DETACH,
    ("applications", "student_user_id"): DETACH,
    # must have an owner: moved to the admin who removes the person
    ("tutorials", "uploaded_by"): OWNER, ("posts", "author_id"): OWNER,
    # payroll needs the teacher
    ("teacher_earnings", "teacher_id"): BLOCK, ("teacher_payments", "teacher_id"): BLOCK, ("expenses", "teacher_id"): BLOCK,
    # "by whom" on everything else: emptied (the activity log keeps who did it)
    ("applications", "decided_by"): NULL, ("assignments", "created_by"): NULL, ("attendance", "marked_by"): NULL, ("batches", "teacher_id"): NULL,
    ("discounts", "created_by"): NULL, ("discounts", "ended_by"): NULL, ("enrollment_events", "by_user"): NULL,
    ("expenses", "entered_by"): NULL, ("expenses", "updated_by"): NULL, ("interest_list", "created_by"): NULL, ("invoices", "created_by"): NULL,
    ("materials", "uploaded_by"): NULL, ("password_help", "handled_by"): NULL, ("payment_slips", "reviewed_by"): NULL,
    ("payments", "recorded_by"): NULL, ("payments", "reversed_by"): NULL, ("recordings", "created_by"): NULL,
    ("recurring_expenses", "created_by"): NULL, ("reminders", "sent_by"): NULL, ("sessions", "created_by"): NULL,
    ("staff_files", "uploaded_by"): NULL, ("staff_files", "updated_by"): NULL, ("staff_folders", "created_by"): NULL,
    ("staff_messages", "pinned_by"): NULL, ("posts", "pinned_by"): NULL, ("post_comments", "deleted_by"): NULL, ("staff_messages", "deleted_by"): NULL, ("submissions", "graded_by"): NULL,
    ("substitutions", "created_by"): NULL, ("substitutions", "removed_by"): NULL, ("substitutions", "original_teacher_id"): NULL,
    ("teacher_earnings", "calculated_by"): NULL, ("teacher_earnings", "approved_by"): NULL,
    ("teacher_payments", "recorded_by"): NULL, ("teacher_payments", "voided_by"): NULL, ("tutorial_submissions", "graded_by"): NULL,
    ("wa_log", "sent_by"): NULL, ("fee_notes", "updated_by"): NULL, ("users", "account_changed_by"): NULL,
}
# columns without a database reference that still hold the person's id
EXTRA_DELETE = (("login_events", "user_id"),)

# words for the preview
LABELS = {"enrollments": "Enrolments", "attendance": "Attendance marks", "submissions": "Submitted work and grades",
          "tutorial_submissions": "Tutorial answers", "enrollment_events": "Transfers and withdrawals", "family_members": "Family membership",
          "notifications": "Notifications", "wa_log": "WhatsApp log entries", "password_help": "Password requests",
          "staff_messages": "Teachers' room messages", "post_reads": "Notice board posts marked as read", "post_comments": "Notice board comments", "substitutions": "Classes booked to cover as a substitute",
          "discounts": "Recurring discounts on their enrolments", "login_events": "Sign-in history"}
FILES = (("submissions", "student_id", "file"), ("tutorial_submissions", "student_id", "file"), ("staff_messages", "user_id", "file"))


def _n(conn, sql, args):
    return int(conn.execute(sql, args).fetchone()[0] or 0)


def _has(conn, table, col):
    return col in conn.columns(table)


def plan(conn, uid):
    """What remove() would do to this person. Changes nothing."""
    deleted = []
    for (t, col), act in PLAN.items():
        if act != DELETE or t in ("students", "teachers") or not _has(conn, t, col): continue
        n = _n(conn, f"SELECT COUNT(*) FROM {t} WHERE {col}=?", (uid,))
        if n: deleted.append({"table": t, "label": LABELS.get(t, t), "rows": n})
    n = _n(conn, "SELECT COUNT(*) FROM discounts WHERE scope='enrollment' AND enrollment_id IN (SELECT id FROM enrollments WHERE student_id=?)", (uid,))
    if n: deleted.append({"table": "discounts", "label": LABELS["discounts"], "rows": n})
    for t, col in EXTRA_DELETE:
        if _has(conn, t, col):
            n = _n(conn, f"SELECT COUNT(*) FROM {t} WHERE {col}=?", (uid,))
            if n: deleted.append({"table": t, "label": LABELS.get(t, t), "rows": n})
    owed = conn.execute("SELECT COUNT(*) n, COALESCE(SUM(amount_due_mvr-waived_mvr-paid_mvr),0) s FROM invoices WHERE student_id=? "
                        "AND status IN ('unpaid','slip_submitted') AND amount_due_mvr-waived_mvr-paid_mvr>0", (uid,)).fetchone()
    kept = {"invoices": _n(conn, "SELECT COUNT(*) FROM invoices WHERE student_id=?", (uid,)),
            "unpaid_invoices": int(owed["n"] or 0), "unpaid_mvr": int(owed["s"] or 0),
            "payments": _n(conn, "SELECT COUNT(*) FROM payments WHERE student_id=?", (uid,)),
            "slips": _n(conn, "SELECT COUNT(*) FROM payment_slips WHERE student_id=?", (uid,)),
            "applications": _n(conn, "SELECT COUNT(*) FROM applications WHERE student_user_id=?", (uid,)),
            "batches_taught": _n(conn, "SELECT COUNT(*) FROM batches WHERE teacher_id=?", (uid,)),
            "tutorials": _n(conn, "SELECT COUNT(*) FROM tutorials WHERE uploaded_by=?", (uid,))}
    blocked = []
    for (t, col), act in PLAN.items():
        if act == BLOCK and _has(conn, t, col) and _n(conn, f"SELECT COUNT(*) FROM {t} WHERE {col}=?", (uid,)):
            blocked.append(t)
    other = sum(_n(conn, f"SELECT COUNT(*) FROM {t} WHERE {col}=?", (uid,)) for (t, col), act in PLAN.items()
                if act in (NULL,) and t != "batches" and _has(conn, t, col))
    has_records = bool(deleted and any(d["table"] not in ("notifications", "login_events") for d in deleted)) or any(
        kept[k] for k in ("invoices", "payments", "slips", "applications", "batches_taught", "tutorials")) or bool(blocked) or other > 0
    return {"deleted": deleted, "kept": kept, "blocked": blocked, "has_records": has_records,
            "blocked_message": ("This teacher has pay records (earnings or payments to the teacher), which payroll needs. "
                                "Disable the account instead (untick Account active).") if blocked else ""}


def file_refs(conn, uid):
    out = []
    for t, col, fcol in FILES:
        if not _has(conn, t, fcol): continue
        for r in conn.execute(f"SELECT {fcol} AS f FROM {t} WHERE {col}=? AND {fcol} IS NOT NULL AND {fcol}<>''", (uid,)).fetchall():
            out.append(("learning", r["f"]))
    return out


def remove(conn, uid, actor_id):
    """Inside the caller's transaction (the caller commits or rolls back). Returns {table: rows deleted}."""
    u = conn.execute("SELECT full_name, phone FROM users WHERE id=?", (uid,)).fetchone()
    done = {}

    def run(key, sql, args):
        n = conn.execute(sql, args).rowcount
        if n and key: done[key] = done.get(key, 0) + n

    # money: kept under the person's name, no longer linked to the account or the enrolment
    run(None, "UPDATE invoices SET customer_name=COALESCE(customer_name, ?), customer_phone=COALESCE(customer_phone, ?), student_id=NULL, "
              "enrollment_id=NULL WHERE student_id=?", (u["full_name"], u["phone"], uid))
    run(None, "UPDATE invoices SET enrollment_id=NULL WHERE enrollment_id IN (SELECT id FROM enrollments WHERE student_id=?)", (uid,))
    run("discounts", "DELETE FROM discounts WHERE scope='enrollment' AND enrollment_id IN (SELECT id FROM enrollments WHERE student_id=?)", (uid,))
    run(None, "UPDATE discounts SET enrollment_id=NULL WHERE enrollment_id IN (SELECT id FROM enrollments WHERE student_id=?)", (uid,))
    for (t, col), act in PLAN.items():
        if not _has(conn, t, col): continue
        if act == DETACH and t != "invoices": run(None, f"UPDATE {t} SET {col}=NULL WHERE {col}=?", (uid,))
        elif act == NULL: run(None, f"UPDATE {t} SET {col}=NULL WHERE {col}=?", (uid,))
        elif act == OWNER: run(None, f"UPDATE {t} SET {col}=? WHERE {col}=?", (actor_id, uid))
    # the person's own records; children before parents (attendance/submissions before enrolments, enrolments last)
    order = ("notifications", "wa_log", "password_help", "staff_messages", "post_reads", "post_comments", "attendance", "submissions", "tutorial_submissions",
             "enrollment_events", "family_members", "substitutions", "enrollments", "students", "teachers")
    cols = {t: c for (t, c), a in PLAN.items() if a == DELETE}
    for t in order:
        if _has(conn, t, cols[t]): run(t if t not in ("students", "teachers") else None, f"DELETE FROM {t} WHERE {cols[t]}=?", (uid,))
    for t, col in EXTRA_DELETE:
        if _has(conn, t, col): run(t, f"DELETE FROM {t} WHERE {col}=?", (uid,))
    conn.execute("DELETE FROM users WHERE id=?", (uid,))
    return done


def remove_files(store, refs):
    """After the commit for a bucket or folder (in the database the files are deleted inside the same transaction, see app.py)."""
    ok = bad = 0
    for area, name in refs:
        try: store.delete(area, name); ok += 1
        except Exception: bad += 1   # the record is gone either way; a left-over file is unreachable
    return ok, bad
