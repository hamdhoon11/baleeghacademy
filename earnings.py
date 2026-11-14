"""Session 30: teacher earnings calculation (admin, area "finance").

v0.8.51: by FEE month. For one month and one batch:
  collected = payments (not reversed) on that month's fee invoices (invoices.period = month), whenever they were paid or entered.
Payments on void invoices and on one-time registration fee invoices are left out (registration goes wholly to the academy); hand-made invoices
count only with the "monthly" revenue type; a partial payment counts only what was paid. teacher share = collected x revenue_share_percent / 100
(whole MVR, rounded down towards zero); the academy keeps the rest. The teacher is the batch's permanent teacher (batches.teacher_id).
An approved month is locked and never changes. Fees for it collected (or reversed) after approval are found by Calculate on that month and
saved as LATE rows (seq 1, 2, ..., booked_month = when found): accrued earnings, approved with the same Approve button, then payable.
(Before v0.8.51 it counted payments by the date they were paid.)

  POST /api/earnings/calculate   month=YYYY-MM, dry_run=1 to preview only (default is to save) -> rows and per-teacher totals
  GET  /api/earnings             ?month=YYYY-MM&teacher_id=&batch_id=  -> saved rows, per-teacher roll-up, totals

Session 31 (same area, all admin "finance"):
  POST /api/earnings/approve     month (a finished month), expected_teacher_total? -> recalculates, then locks every row of the month
  GET  /api/earnings/teachers    per teacher: approved earned, paid, outstanding (all approved months)
  POST /api/earnings/payments    teacher_id, amount_mvr, paid_on?, method, reference?, note?  (not more than outstanding)
  GET  /api/earnings/payments    ?teacher_id=
  POST /api/earnings/payments/<id>/void   reason
  GET  /api/earnings/report(.csv|.xlsx)   ?from=YYYY-MM&to=YYYY-MM&teacher_id=  one line per teacher, batch and month
Teacher (own data only, approved months only, and only while setting teachers_see_earnings is on):
  GET  /api/my/earnings"""
import datetime as dt
import re
from flask import Response, g, jsonify, request
import settings_schema as SS
import dbx

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
SALARY_CATEGORY = "Teacher salaries"   # v0.8.51


def split(collected, pct):
    """(teacher, academy) in whole MVR; the teacher part is rounded towards zero."""
    t = (abs(collected) * pct // 100) * (1 if collected >= 0 else -1)
    return t, collected - t


FEE_RULE = ("i.status<>'void' AND i.kind<>'registration' AND i.batch_id IS NOT NULL "
            "AND (i.kind<>'manual' OR i.revenue_type_id=(SELECT rt.id FROM revenue_types rt WHERE rt.code='monthly'))")


def compute(q, month, pct):
    """v0.8.51: by FEE month. For each batch: payments not reversed on that month's fee invoices (invoices.period = month), whenever they
    were paid or entered. Returns [{batch_id, teacher_id, collected, pct}] for batches with any such payment."""
    got = {r[0]: int(r[1]) for r in q("SELECT i.batch_id, SUM(p.amount_mvr) FROM payments p JOIN invoices i ON i.id=p.invoice_id "
                                      f"WHERE p.reversed_at IS NULL AND {FEE_RULE} AND i.period=? GROUP BY i.batch_id", (month,))}
    teachers = {r[0]: r[1] for r in q("SELECT id, teacher_id FROM batches")}
    return [{"batch_id": b, "teacher_id": teachers.get(b), "collected": got[b], "pct": pct} for b in sorted(got)]


def is_approved(conn_q, month):
    return bool(conn_q("SELECT 1 FROM teacher_earnings WHERE period=? AND seq=0 AND status='approved' LIMIT 1", (month,)))


def run_month(conn_q, conn_x, month, pct, user_id, now, apply=True, booked=None):
    """Works out one fee month. Returns (rows, mode): mode "month" = the month's own draft rows (seq 0);
    mode "late" = the month is already approved, so only what was collected for it since then (draft rows seq >= 1, accrued earnings).
    Approved rows are never changed."""
    rows_ = compute(conn_q, month, pct)
    for r in rows_:
        r["teacher_share"], r["academy_share"] = split(r["collected"], pct) if r["teacher_id"] else (0, r["collected"])
    if not is_approved(conn_q, month):
        if apply:
            for r in rows_:
                conn_x("INSERT INTO teacher_earnings (teacher_id,batch_id,period,collected_mvr,share_percent,teacher_share_mvr,academy_share_mvr,status,calculated_at,calculated_by,seq) "
                       "VALUES (?,?,?,?,?,?,?, 'draft',?,?,0) ON CONFLICT(batch_id,period,seq) DO UPDATE SET teacher_id=excluded.teacher_id, collected_mvr=excluded.collected_mvr, "
                       "share_percent=excluded.share_percent, teacher_share_mvr=excluded.teacher_share_mvr, academy_share_mvr=excluded.academy_share_mvr, "
                       "calculated_at=excluded.calculated_at, calculated_by=excluded.calculated_by WHERE teacher_earnings.status<>'approved'",
                       (r["teacher_id"], r["batch_id"], month, r["collected"], pct, r["teacher_share"], r["academy_share"], now, user_id))
            seen = {r["batch_id"] for r in rows_}   # a batch that had a row but has nothing now is set to 0, never left stale
            for old in conn_q("SELECT batch_id FROM teacher_earnings WHERE period=? AND seq=0 AND status<>'approved'", (month,)):
                if old[0] not in seen:
                    conn_x("UPDATE teacher_earnings SET collected_mvr=0, teacher_share_mvr=0, academy_share_mvr=0, share_percent=?, calculated_at=? WHERE batch_id=? AND period=? AND seq=0", (pct, now, old[0], month))
        return rows_, "month"
    # the month is approved: what was collected for it after that = now minus everything approved for it (late rows included)
    done = {r[0]: int(r[1]) for r in conn_q("SELECT batch_id, SUM(collected_mvr) FROM teacher_earnings WHERE period=? AND status='approved' GROUP BY batch_id", (month,))}
    now_ = {r["batch_id"]: r for r in rows_}
    late = []
    for b in sorted(set(now_) | set(done)):
        diff = (now_[b]["collected"] if b in now_ else 0) - done.get(b, 0)
        if diff:
            t = now_[b]["teacher_id"] if b in now_ else (conn_q("SELECT teacher_id FROM batches WHERE id=?", (b,)) or [[None]])[0][0]
            ts, ac = split(diff, pct) if t else (0, diff)
            late.append({"batch_id": b, "teacher_id": t, "collected": diff, "pct": pct, "teacher_share": ts, "academy_share": ac, "late": True})
    if apply:
        conn_x("DELETE FROM teacher_earnings WHERE period=? AND seq>0 AND status='draft'", (month,))
        for r in late:
            nxt = (conn_q("SELECT COALESCE(MAX(seq),0)+1 FROM teacher_earnings WHERE batch_id=? AND period=?", (r["batch_id"], month)) or [[1]])[0][0]
            conn_x("INSERT INTO teacher_earnings (teacher_id,batch_id,period,collected_mvr,share_percent,teacher_share_mvr,academy_share_mvr,status,calculated_at,calculated_by,seq,booked_month) "
                   "VALUES (?,?,?,?,?,?,?, 'draft',?,?,?,?)", (r["teacher_id"], r["batch_id"], month, r["collected"], pct, r["teacher_share"], r["academy_share"], now, user_id, nxt, booked or month))
    return late, "late"


def register(app, c, today):
    db, rows, one, err, auth, audit = c.db, c.rows, c.one, c.err, c.auth, c.audit

    def pct():
        try: v = int(c.raw_setting("revenue_share_percent") or "")
        except ValueError: v = None
        if v is None or not 0 <= v <= 100: v = int(SS.default_of("revenue_share_percent"))
        return v

    def month_arg(v):
        v = (v or "").strip()
        if not MONTH.match(v): raise ValueError("Month must look like 2027-03")
        if v > today().isoformat()[:7]: raise ValueError("That month has not started yet")
        return v

    def now_s(): return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def q_(s_, a=()): return [dbx.values(r) for r in db().execute(s_, a).fetchall()]

    @app.post("/api/earnings/calculate")
    @auth("admin", perm="finance")
    def earn_calc():
        d = request.get_json(silent=True) or {}
        try: m = month_arg(d.get("month", request.args.get("month")))
        except ValueError as x: return err(str(x))
        dry = str(d.get("dry_run", request.args.get("dry_run", "0"))).lower() in ("1", "true", "yes")
        p = pct()
        q = lambda s, a=(): [dbx.values(r) for r in db().execute(s, a).fetchall()]   # v0.8.40: was tuple(r), which is the column names on PostgreSQL
        x = lambda s, a=(): db().execute(s, a)
        res, mode = run_month(q, x, m, p, g.user["id"], now_s(), apply=not dry, booked=today().isoformat()[:7])
        if not dry:
            audit("earnings_calculated", "teacher_earnings", None, f"{m}: {len(res)} batch(es) at {p}%" + (" (collected after approval)" if mode == "late" else ""),
                  new=str(sum(r["collected"] for r in res)))
            db().commit()
        return jsonify(month=m, dry_run=dry, mode=mode, share_percent=p, count=len(res), why=explain(m, res, mode), **summary(m, res if dry else None))

    def explain(m, res, mode="month"):
        """v0.8.51: what Calculate found, in words (fees are counted by the month they are FOR)."""
        n = lambda r: int((r or {}).get("s") or 0)
        got = n(one("SELECT COALESCE(SUM(p.amount_mvr),0) s FROM payments p JOIN invoices i ON i.id=p.invoice_id WHERE p.reversed_at IS NULL AND i.status<>'void' AND i.period=?", (m,)))
        counted = n(one(f"SELECT COALESCE(SUM(p.amount_mvr),0) s FROM payments p JOIN invoices i ON i.id=p.invoice_id WHERE p.reversed_at IS NULL AND {FEE_RULE} AND i.period=?", (m,)))
        owed = n(one("SELECT COALESCE(SUM(amount_due_mvr-waived_mvr-paid_mvr),0) s FROM invoices i WHERE i.status IN ('unpaid','slip_submitted') AND i.kind<>'registration' AND i.period=?", (m,)))
        nt = {r["batch_id"] for r in res if r["teacher_id"] is None and r["collected"]}
        no_teacher = [f"{x['course_name']} {x['code']}" for x in rows("SELECT b.id, b.code, c.name AS course_name FROM batches b JOIN courses c ON c.id=b.course_id") if x["id"] in nt]
        msg = []
        if mode == "late":
            add = sum(r["teacher_share"] for r in res)
            msg.append(f"{m} is approved. " + (f"MVR {sum(r['collected'] for r in res):,} for {m} fees was collected after approval: teachers' share MVR {add:,} is added as "
                                               "accrued (late) earnings. Press Approve to make it payable." if res else "Nothing new was collected for it since it was approved."))
        elif not counted:
            msg.append(f"No fees for {m} have been collected yet (teacher earnings count the fees FOR {m}, whenever they are paid).")
        else:
            msg.append(f"Fees for {m} collected so far: MVR {counted:,} on batches, counted for teachers.")
        if got - counted > 0: msg.append(f"MVR {got - counted:,} for {m} is registration fees or on invoices with no batch: not shared with teachers.")
        if owed: msg.append(f"MVR {owed:,} of {m} fees is still unpaid. When it is collected after you approve {m}, press Calculate on {m} again: it is added as accrued earnings.")
        if no_teacher: msg.append("These batches have no teacher, so their share goes to the academy: " + ", ".join(no_teacher) + ". Choose a teacher in Batches, then press Calculate again.")
        return msg

    def summary(m, live=None):
        if live is None:
            items = rows("SELECT e.*, b.code AS batch_code, c.name AS course_name, u.full_name AS teacher_name FROM teacher_earnings e JOIN batches b ON b.id=e.batch_id "
                         "JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=e.teacher_id WHERE e.period=? ORDER BY e.seq, c.name, b.code", (m,))
            items = [dict(r) | {"late": bool(r["seq"])} for r in items]
        else:
            names = {r["id"]: r for r in rows("SELECT b.id, b.code AS batch_code, c.name AS course_name, u.full_name AS teacher_name FROM batches b JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=b.teacher_id")}
            items = [{"batch_id": r["batch_id"], "teacher_id": r["teacher_id"], "collected_mvr": r["collected"], "teacher_share_mvr": r["teacher_share"],
                      "academy_share_mvr": r["academy_share"], "share_percent": r["pct"], "status": "preview", "late": bool(r.get("late")), **{k: names[r["batch_id"]][k] for k in ("batch_code", "course_name", "teacher_name")}} for r in live]
        by_t = {}
        for r in items:
            t = by_t.setdefault(r["teacher_id"], {"teacher_id": r["teacher_id"], "teacher_name": r["teacher_name"], "collected_mvr": 0, "teacher_share_mvr": 0, "academy_share_mvr": 0, "batches": 0})
            t["collected_mvr"] += r["collected_mvr"]; t["teacher_share_mvr"] += r["teacher_share_mvr"]; t["academy_share_mvr"] += r["academy_share_mvr"]; t["batches"] += 1
        tot = {k: sum(r[k] for r in items) for k in ("collected_mvr", "teacher_share_mvr", "academy_share_mvr")}
        return {"items": items, "by_teacher": list(by_t.values()), "totals": tot}

    @app.get("/api/earnings")
    @auth("admin", perm="finance")
    def earn_list():
        a = request.args
        try: m = month_arg(a.get("month") or today().isoformat()[:7])
        except ValueError as x: return err(str(x))
        out = summary(m)
        for key in ("teacher_id", "batch_id"):
            if a.get(key):
                try: v = int(a[key])
                except ValueError: return err("Bad " + key)
                out["items"] = [r for r in out["items"] if r[key] == v]
        if a.get("teacher_id") or a.get("batch_id"):
            out["by_teacher"] = [t for t in out["by_teacher"] if any(r["teacher_id"] == t["teacher_id"] for r in out["items"])]
            out["totals"] = {k: sum(r[k] for r in out["items"]) for k in ("collected_mvr", "teacher_share_mvr", "academy_share_mvr")}
        # v0.8.51: an approved month with fees collected for it since (not calculated yet): say so
        pending = 0
        if is_approved(q_, m):
            done = int(one("SELECT COALESCE(SUM(collected_mvr),0) s FROM teacher_earnings WHERE period=? AND (status='approved' OR seq>0)", (m,))["s"])
            pending = sum(r["collected"] for r in compute(q_, m, pct())) - done
        return jsonify(month=m, share_percent_now=pct(), approved=is_approved(q_, m), late_not_calculated=pending, **out)

    # ---------------- Session 31 ----------------
    def pay_totals(tid=None):
        """{teacher_id: (earned, paid)} over all approved months and all payments not voided."""
        w, a = ("AND teacher_id=?", (tid,)) if tid else ("", ())
        out = {}
        for r in rows("SELECT teacher_id, SUM(teacher_share_mvr) s FROM teacher_earnings WHERE status='approved' AND teacher_id IS NOT NULL " + w + " GROUP BY teacher_id", a): out[r["teacher_id"]] = [int(r["s"]), 0]
        for r in rows("SELECT teacher_id, SUM(amount_mvr) s FROM teacher_payments WHERE voided_at IS NULL " + w + " GROUP BY teacher_id", a): out.setdefault(r["teacher_id"], [0, 0])[1] = int(r["s"])
        return out

    @app.post("/api/earnings/approve")
    @auth("admin", perm="finance")
    def earn_approve():
        d = request.get_json(silent=True) or {}
        try: m = month_arg(d.get("month"))
        except ValueError as x: return err(str(x))
        # v0.8.51: the current month can be approved too (teachers are paid around the 15th); its fees collected later become late rows
        if m > today().isoformat()[:7]: return err("That month has not started yet")
        late = is_approved(q_, m)   # v0.8.51: an approved month: approve what was collected for it since (accrued), if anything
        if late and not one("SELECT 1 x FROM teacher_earnings WHERE period=? AND status='draft' LIMIT 1", (m,)):
            return err(f"{m} is already approved. Press Calculate first to add fees collected for it since then.", 409)
        if not late: run_month(q_, lambda s, a=(): db().execute(s, a), m, pct(), g.user["id"], now_s(), apply=True)
        tot = int(one("SELECT COALESCE(SUM(teacher_share_mvr),0) s FROM teacher_earnings WHERE period=?", (m,))["s"])
        n = int(one("SELECT COUNT(*) n FROM teacher_earnings WHERE period=? AND status='draft'", (m,))["n"])
        if not n: db().rollback(); return err(f"Nothing to approve for {m}: no fees for {m} were collected")
        if d.get("expected_teacher_total") not in (None, "") and str(d["expected_teacher_total"]) != str(tot):
            db().rollback(); return err(f"The figures changed since you looked: teacher total is now {tot} MVR. Review {m} again.", 409)
        db().execute("UPDATE teacher_earnings SET status='approved', approved_at=?, approved_by=? WHERE period=? AND status<>'approved'", (now_s(), g.user["id"], m))
        audit("earnings_approved", "teacher_earnings", None, f"{m}: {n} row(s)" + (" collected after approval (accrued)" if late else ""), new=str(tot)); db().commit()
        return jsonify(month=m, approved=n, teacher_total=tot, **summary(m))

    @app.get("/api/earnings/teachers")
    @auth("admin", perm="finance")
    def earn_teachers():
        tp = pay_totals(); names = {r["id"]: r["full_name"] for r in rows("SELECT id, full_name FROM users WHERE role='teacher'")}
        items = [{"teacher_id": t, "teacher_name": names.get(t), "earned_mvr": e, "paid_mvr": p, "outstanding_mvr": e - p} for t, (e, p) in tp.items()]
        items.sort(key=lambda r: (r["teacher_name"] or ""))
        everyone = [{"id": r["id"], "full_name": r["full_name"]} for r in rows("SELECT id, full_name FROM users WHERE role='teacher' AND is_active=1 ORDER BY full_name")]   # v0.8.51: for the salary expense form
        return jsonify(items=items, teachers=everyone, totals={k: sum(r[k] for r in items) for k in ("earned_mvr", "paid_mvr", "outstanding_mvr")}, note="Earned counts approved months only.")

    PAY_SQL = "SELECT p.*, u.full_name AS teacher_name FROM teacher_payments p JOIN users u ON u.id=p.teacher_id"

    @app.post("/api/earnings/payments")
    @auth("admin", perm="finance")
    def earn_pay_create():
        d = request.get_json(silent=True) or {}
        try: tid = int(d.get("teacher_id")); amt = int(d.get("amount_mvr"))
        except (TypeError, ValueError): return err("Choose a teacher and a whole-number amount")
        if amt <= 0: return err("Amount must be more than 0")
        if not one("SELECT 1 x FROM users WHERE id=? AND role='teacher'", (tid,)): return err("Teacher not found", 404)
        try: day = dt.date.fromisoformat(str(d.get("paid_on") or today().isoformat())).isoformat()
        except ValueError: return err("Date must look like 2027-03-31")
        method = (d.get("method") or "").strip().lower()
        if method not in ("cash", "bank_transfer", "cheque", "other"): return err("Method must be cash, bank_transfer, cheque or other")
        e, p = pay_totals(tid).get(tid, [0, 0])
        if amt > e - p: return err(f"That is more than the outstanding {e - p} MVR for this teacher (approved months only)", 409)
        note = (d.get("note") or "").strip()[:300] or None
        # v0.8.51: a payment to a teacher is also a salary EXPENSE (category "Teacher salaries"), so it is entered once and shows in both places
        kid = one("SELECT id FROM expense_categories WHERE LOWER(name)=LOWER(?)", (SALARY_CATEGORY,))
        kid = kid["id"] if kid else db().execute("INSERT INTO expense_categories(name,is_active) VALUES(?,1)", (SALARY_CATEGORY,)).lastrowid
        tname = one("SELECT full_name FROM users WHERE id=?", (tid,))["full_name"]
        exp = db().execute("INSERT INTO expenses(expense_date,amount_mvr,category_id,description,entered_by,teacher_id) VALUES(?,?,?,?,?,?)",
                           (day, amt, kid, (f"Salary: {tname}" + (f" ({note})" if note else ""))[:500], g.user["id"], tid)).lastrowid
        cur = db().execute("INSERT INTO teacher_payments(teacher_id,amount_mvr,paid_on,method,reference,note,recorded_by,created_at,expense_id) VALUES(?,?,?,?,?,?,?,?,?)",
                           (tid, amt, day, method, (d.get("reference") or "").strip()[:80] or None, note, g.user["id"], now_s(), exp))
        audit("teacher_payment", "teacher_payment", cur.lastrowid, f"teacher {tid}, {method}, {day}", new=str(amt)); db().commit()
        return jsonify(id=cur.lastrowid, outstanding_mvr=e - p - amt), 201

    @app.get("/api/earnings/payments")
    @auth("admin", perm="finance")
    def earn_pay_list():
        tid = request.args.get("teacher_id")
        try: a = (int(tid),) if tid else ()
        except ValueError: return err("Bad teacher id")
        return jsonify(rows(PAY_SQL + (" WHERE p.teacher_id=?" if a else "") + " ORDER BY p.paid_on DESC, p.id DESC LIMIT 500", a))

    @app.post("/api/earnings/payments/<int:pid>/void")
    @auth("admin", perm="finance")
    def earn_pay_void(pid):
        r = one("SELECT * FROM teacher_payments WHERE id=?", (pid,)); why = ((request.get_json(silent=True) or {}).get("reason") or "").strip()
        if not r: return err("Payment not found", 404)
        if r["voided_at"]: return err("Already voided", 409)
        if not why: return err("Give a reason")
        db().execute("UPDATE teacher_payments SET voided_at=?, voided_by=?, void_reason=? WHERE id=?", (now_s(), g.user["id"], why[:300], pid))
        if r.get("expense_id"):   # v0.8.51: the matching salary expense goes too
            db().execute("DELETE FROM expenses WHERE id=?", (r["expense_id"],))
            audit("expense_delete", "expense", r["expense_id"], f"salary payment voided: {why[:150]}", old=str(r["amount_mvr"]))
        audit("teacher_payment_void", "teacher_payment", pid, why[:200], old=str(r["amount_mvr"])); db().commit()
        return jsonify(ok=True)

    def report_rows(a):
        f, t = (a.get("from") or "0000-00"), (a.get("to") or today().isoformat()[:7])
        for v in (f, t):
            if not MONTH.match(v) and v != "0000-00": raise ValueError("from and to must look like 2027-03")
        w, args = ["e.period>=?", "e.period<=?"], [f, t]
        if a.get("teacher_id"):
            try: args.append(int(a["teacher_id"]))
            except ValueError: raise ValueError("Bad teacher id")
            w.append("e.teacher_id=?")
        return rows("SELECT e.period, COALESCE(u.full_name,'(no teacher)') AS teacher, c.name AS course, b.code AS batch, e.collected_mvr, e.share_percent, e.teacher_share_mvr, e.academy_share_mvr, "
                    "CASE WHEN e.seq>0 THEN e.status || ' (collected late, ' || COALESCE(e.booked_month,'') || ')' ELSE e.status END AS status "
                    "FROM teacher_earnings e JOIN batches b ON b.id=e.batch_id JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=e.teacher_id WHERE " + " AND ".join(w) +
                    " ORDER BY e.period DESC, teacher, course, batch, e.seq", tuple(args))

    REPORT_COLS = ["period", "teacher", "course", "batch", "collected_mvr", "share_percent", "teacher_share_mvr", "academy_share_mvr", "status"]

    @app.get("/api/earnings/report")
    @auth("admin", perm="finance")
    def earn_report():
        try: r = report_rows(request.args)
        except ValueError as x: return err(str(x))
        return jsonify(items=r, totals={k: sum(x[k] for x in r) for k in ("collected_mvr", "teacher_share_mvr", "academy_share_mvr")}, teachers=earn_teachers().get_json()["items"])

    def export(kind):
        import payreports as pr
        try: r = report_rows(request.args)
        except ValueError as x: return err(str(x))
        audit("export_teacher_earnings", "teacher_earnings", None, f"{kind}, {len(r)} row(s)"); db().commit()
        if kind == "xlsx":
            return Response(pr.to_xlsx([[x[k] for k in REPORT_COLS] for x in r], REPORT_COLS, "Teacher earnings"), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": "attachment; filename=teacher-earnings.xlsx"})
        import csv, io
        buf = io.StringIO(); w = csv.writer(buf); w.writerow(REPORT_COLS)
        for x in r: w.writerow([pr.csv_safe(x[k]) for k in REPORT_COLS])
        return Response("\ufeff" + buf.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=teacher-earnings.csv"})

    @app.get("/api/earnings/report.csv")
    @auth("admin", perm="finance")
    def earn_csv(): return export("csv")

    @app.get("/api/earnings/report.xlsx")
    @auth("admin", perm="finance")
    def earn_xlsx(): return export("xlsx")

    @app.get("/api/earnings/report.pdf")
    @auth("admin", perm="finance")
    def earn_pdf():   # v0.8.48
        import reportpdf as R
        try: r = report_rows(request.args)
        except ValueError as x: return err(str(x))
        audit("export_teacher_earnings", "teacher_earnings", None, f"pdf, {len(r)} row(s)"); db().commit()
        tot = {k: sum(x[k] for x in r) for k in ("collected_mvr", "teacher_share_mvr", "academy_share_mvr")}
        per = {}
        for x in r: per[x["teacher"]] = per.get(x["teacher"], 0) + x["teacher_share_mvr"]
        a = request.args
        sub = " · ".join(f"{k.replace('_', ' ')}: {a[k]}" for k in a if a.get(k)) or "All months"
        blocks = [("stats", [("Collected (MVR)", tot["collected_mvr"]), ("Teachers' share (MVR)", tot["teacher_share_mvr"]), ("Academy's share (MVR)", tot["academy_share_mvr"]), ("Rows", len(r))])]
        if len(per) > 1: blocks.append(("bars", "Teachers' share by teacher (MVR)", list(per), [("Teacher's share", list(per.values()), R.BLUE)]))
        blocks.append(("table", ["Month", "Teacher", "Course", "Batch", "Collected", "Share %", "Teacher's share", "Academy's share", "Status"],
                       [[x["period"], x["teacher"], x["course"], x["batch"], x["collected_mvr"], x["share_percent"], x["teacher_share_mvr"], x["academy_share_mvr"], x["status"]] for x in r],
                       {"widths": [1.2, 2.4, 2.6, 1.2, 1.3, 1, 1.4, 1.4, 1.2], "right": {4, 5, 6, 7},
                        "total": ["Total", "", "", "", tot["collected_mvr"], "", tot["teacher_share_mvr"], tot["academy_share_mvr"], ""]}))
        return app.extensions["pdf"]("Teacher earnings report", blocks, "teacher-earnings", subtitle=sub + " · amounts in MVR")

    @app.get("/api/my/earnings")
    @auth("teacher")
    def earn_mine():
        if (c.raw_setting("teachers_see_earnings") or SS.default_of("teachers_see_earnings")).strip() not in ("1", "true", "yes", "on"):
            return err("Earnings are not shown to teachers", 403)
        me = g.user["id"]; e, p = pay_totals(me).get(me, [0, 0])
        items = rows("SELECT e.period, c.name AS course_name, b.code AS batch_code, e.collected_mvr, e.share_percent, e.teacher_share_mvr, e.seq>0 AS late, e.booked_month FROM teacher_earnings e JOIN batches b ON b.id=e.batch_id "
                     "JOIN courses c ON c.id=b.course_id WHERE e.teacher_id=? AND e.status='approved' ORDER BY e.period DESC, c.name, b.code", (me,))
        pays = rows("SELECT id, amount_mvr, paid_on, method, reference FROM teacher_payments WHERE teacher_id=? AND voided_at IS NULL ORDER BY paid_on DESC, id DESC", (me,))
        return jsonify(earned_mvr=e, paid_mvr=p, outstanding_mvr=e - p, items=items, payments=pays, note="Approved months only; registration fees are not part of teacher earnings.")

    app.extensions["earnings"] = {"approved_in": lambda m1, m2: one("SELECT COALESCE(SUM(teacher_share_mvr),0) t, COALESCE(SUM(academy_share_mvr),0) a FROM teacher_earnings WHERE status='approved' AND period>=? AND period<=?", (m1, m2)),
                                  "paid_in": lambda d1, d2: int(one("SELECT COALESCE(SUM(amount_mvr),0) s FROM teacher_payments WHERE voided_at IS NULL AND paid_on>=? AND paid_on<=?", (d1 or "0000-00-00", d2 or "9999-12-31"))["s"])}
