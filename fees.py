"""Phase 4 - fees and payments (all amounts are whole MVR integers; "today" is the Maldives date from app.config["NOW"] when injected).

Registered from app.create_app() like learning.py. Access rules, all enforced here on the server:
  admin   -> everything
  student -> only their own invoices, slips, payments and receipts (someone else's id answers 404, never data)
  teacher -> nothing at all (every route below uses @auth("admin", perm="fees") or @auth("admin","student"))

Pieces: invoices (one per active enrollment per month), discounts and family concessions, bank-transfer slips with admin
verification, manual payments, PDF receipts, overdue reminders (WhatsApp/Viber links, optional SMTP email), monthly report.
Every money-changing action is written to the audit log. The payment layer itself lives in payments.py.
"""
import csv, datetime as dt, io, os, re, smtplib, time
from email.message import EmailMessage
from urllib.parse import quote
from flask import Response, g, jsonify, request, send_from_directory

import common, payments as pay, receipts

MVT = dt.timezone(dt.timedelta(hours=5))
PERIOD = re.compile(r"^(20\d\d)-(0[1-9]|1[0-2])$")
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
OPEN = ("unpaid", "slip_submitted")

DEFAULT_REMINDER_EN = ("Assalaamu alaikum. A reminder from {academy}: the fee for {name} ({course}), invoice {invoice}, "
                       "MVR {amount}, was due on {due_date}. Please pay by bank transfer and upload the slip in the portal. Thank you.")

# setting key -> (default shown/used when empty). Validation is in validate_setting().
SETTING_DEFAULTS = {"invoice_due_day": "10", "first_invoice_mode": "full", "first_invoice_grace_days": "7", "receipt_prefix": "BA-R-"}


def validate_setting(k, v):
    """Returns an error message, or None when the value is fine (empty means 'use the default')."""
    v = str(v).strip()
    if k == "invoice_due_day" and v:
        if not (v.isdigit() and 1 <= int(v) <= 28): return "Invoice due day must be a number from 1 to 28"
    if k == "first_invoice_mode" and v and v not in ("full", "skip"):
        return "First invoice mode must be 'full' or 'skip'"
    if k == "first_invoice_grace_days" and v:
        if not (v.isdigit() and 0 <= int(v) <= 60): return "Grace days must be a number from 0 to 60"
    if k == "receipt_prefix" and v:
        if len(v) > 12 or not re.match(r"^[A-Za-z0-9_\-/]+$", v): return "Receipt prefix: up to 12 letters, digits, - _ or /"
    if k.startswith("reminder_template") and len(v) > 1000: return "Message templates can be up to 1000 characters"
    return None


def fill(template, vals):
    """Replace {placeholders} using a plain lookup (no str.format, so nothing in the template can reach into objects)."""
    return re.sub(r"\{(\w+)\}", lambda m: str(vals.get(m.group(1), m.group(0))), template)


def csv_safe(v):
    """Stop spreadsheet formula injection: a text cell starting with = + - @ gets a leading apostrophe."""
    s = "" if v is None else str(v)
    return "'" + s if isinstance(v, str) and s[:1] in ("=", "+", "-", "@", "\t", "\r") else v if v is not None else ""


def inv_no(i):
    return f"INV-{i['period'].replace('-', '')}-{i['id']:04d}"


def register(app, c):
    db, rows, one, audit, err, auth, need = c.db, c.rows, c.one, c.audit, c.err, c.auth, c.need
    store = c.store
    app.config.setdefault("SLIP_LIMIT", int(os.environ.get("SLIP_LIMIT", "10")))          # slip uploads per student per hour
    app.config.setdefault("EMAIL_ENABLED", os.environ.get("EMAIL_ENABLED", "0").lower() in ("1", "true", "yes"))
    for k, d in (("SMTP_HOST", ""), ("SMTP_PORT", "587"), ("SMTP_USER", ""), ("SMTP_PASSWORD", ""), ("SMTP_FROM", ""), ("SMTP_STARTTLS", "1")):
        app.config.setdefault(k, os.environ.get(k, d))
    slip_hits = {}

    # ---------- small helpers ----------
    def now():
        fn = app.config.get("NOW")
        return fn() if fn else dt.datetime.now(MVT)

    def today():
        return now().date()

    def stamp():
        return now().isoformat(timespec="seconds")

    def body():
        return request.get_json(silent=True) or {}

    def setting(key, default=""):
        v = (c.raw_setting(key) or "").strip()
        return v or SETTING_DEFAULTS.get(key, default) or default

    P = pay.Payments(c, now, setting)

    def month_of(d):
        return f"{d.year:04d}-{d.month:02d}"

    def parse_period(p, allow_future=1):
        """'YYYY-MM' -> normalised string, or None. Allows up to `allow_future` months after the current one."""
        p = str(p or "").strip()
        m = PERIOD.match(p)
        if not m: return None
        t = today()
        if (int(m.group(1)), int(m.group(2))) > (t.year + (t.month + allow_future - 1) // 12, (t.month + allow_future - 1) % 12 + 1): return None
        return p

    def next_month_start(period):
        y, m = int(period[:4]), int(period[5:])
        return dt.date(y + (m == 12), m % 12 + 1, 1)

    def due_day():
        v = setting("invoice_due_day", "10")
        return int(v) if v.isdigit() and 1 <= int(v) <= 28 else 10

    def due_date_for(period, first):
        d = dt.date(int(period[:4]), int(period[5:]), due_day())
        if first:  # a student who joins after the due day should not be overdue on day one
            g_ = setting("first_invoice_grace_days", "7")
            d = max(d, today() + dt.timedelta(days=int(g_) if g_.isdigit() else 7))
        return d.isoformat()

    def describe(course_name, level, code, period):
        return f"{course_name}{' ' + level if level else ''} · Batch {code} · {MONTHS[int(period[5:]) - 1]} {period[:4]}"

    def audit_c(action, entity, entity_id, detail=None, **kw):
        audit(action, entity, entity_id, detail, **kw)

    def money_err(e):
        return jsonify(error=e.msg, **e.extra), e.code

    # ---------- invoice shapes ----------
    # v0.8.45: LEFT JOINs. A manual invoice may have no enrolment/course/batch, and no portal account at all (customer_name instead).
    RT_JOIN = " LEFT JOIN revenue_types rt ON rt.id=COALESCE(i.revenue_type_id, (SELECT r2.id FROM revenue_types r2 WHERE r2.code=i.kind))"
    INV_SQL = ("SELECT i.*, COALESCE(u.full_name, i.customer_name) AS student_name, COALESCE(u.phone, i.customer_phone) AS student_phone, u.email AS student_email, "
               "c.name AS course_name, b.code AS batch_code, e.status AS enrollment_status, rt.id AS revenue_type, rt.name AS revenue_type_name "
               "FROM invoices i LEFT JOIN users u ON u.id=i.student_id LEFT JOIN courses c ON c.id=i.course_id "
               "LEFT JOIN batches b ON b.id=i.batch_id LEFT JOIN enrollments e ON e.id=i.enrollment_id" + RT_JOIN)

    def shape(i, t=None):
        t = t or today()
        d = dict(i)
        d["number"] = inv_no(i)
        d["balance"] = P.balance(i)
        is_open = i["status"] in OPEN and d["balance"] > 0
        d["overdue"] = bool(is_open and i["due_date"] < t.isoformat())
        d["days_overdue"] = (t - dt.date.fromisoformat(i["due_date"])).days if d["overdue"] else 0
        d["partly_paid"] = bool(is_open and i["paid_mvr"] > 0)
        d["walk_in"] = i["student_id"] is None   # v0.8.45: a customer who is not in the portal
        return d

    def get_invoice(iid):
        r = one(INV_SQL + " WHERE i.id=?", (iid,))
        return shape(r) if r else None

    def mine_or_admin(iid):
        """(invoice, None) when the caller may see it, else (None, error). Another student's invoice looks like a missing one."""
        inv = get_invoice(iid)
        if not inv or (g.user["role"] == "student" and inv["student_id"] != g.user["id"]):
            return None, err("Invoice not found", 404)
        return inv, None

    # ---------- discounts ----------
    def calc(kind, value, fee):
        return value if kind == "fixed" else (fee * value + 50) // 100   # whole MVR, half rounds up

    def discount_for(enrollment_id, student_id, fee):
        """Recurring enrollment discounts plus the student's family concession, each worked out on the fee and added up; never more than the fee."""
        parts = []
        for d in rows("SELECT * FROM discounts WHERE scope='enrollment' AND enrollment_id=? AND active=1 ORDER BY id", (enrollment_id,)):
            parts.append((calc(d["kind"], d["value"], fee), d["reason"]))
        fam = one("SELECT f.name, f.concession_kind, f.concession_value, f.concession_reason, m.concession_applies FROM family_members m "
                  "JOIN families f ON f.id=m.family_id WHERE m.student_id=?", (student_id,))
        if fam and fam["concession_applies"] and fam["concession_value"] > 0 and fam["concession_kind"]:
            parts.append((calc(fam["concession_kind"], fam["concession_value"], fee), "Family: " + (fam["concession_reason"] or fam["name"])))
        total = min(sum(a for a, _ in parts), fee)
        note = "; ".join(f"-{a} {r}" for a, r in parts if a) or None
        return total, note

    # ---------- invoice creation ----------
    def make_invoice(e, period, first, user_id):
        """e: row with eid, student_id, bid, code, cid, cname, level, fee. Returns the new invoice id, or None when one already exists."""
        disc, note = discount_for(e["eid"], e["student_id"], e["fee"])
        cur = db().execute(
            "INSERT INTO invoices(enrollment_id,student_id,course_id,batch_id,period,description,amount_mvr,discount_mvr,amount_due_mvr,due_date,status,discount_note,created_by,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,'unpaid',?,?,?) ON CONFLICT (enrollment_id, period) DO NOTHING",
            (e["eid"], e["student_id"], e["cid"], e["bid"], period, describe(e["cname"], e["level"], e["code"], period), e["fee"], disc, e["fee"] - disc,
             due_date_for(period, first), note, user_id, stamp()))
        if not cur.rowcount: return None
        P.recompute(cur.lastrowid)   # a fully discounted invoice becomes 'waived' here
        return cur.lastrowid

    ENR_SQL = ("SELECT e.id AS eid, e.student_id, e.enrolled_at, e.status AS estatus, b.id AS bid, b.code, c.id AS cid, c.name AS cname, c.level, "
               "c.monthly_fee_mvr AS fee, c.is_active AS cactive, u.is_active, u.full_name AS sname FROM enrollments e JOIN batches b ON b.id=e.batch_id JOIN courses c ON c.id=b.course_id "
               "JOIN users u ON u.id=e.student_id")

    def enrolled_month(enrolled_at):
        """enrolled_at is stored as UTC 'YYYY-MM-DD HH:MM:SS'; the academy's month is Maldives time (UTC+5)."""
        try:
            d = dt.datetime.strptime(enrolled_at[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc).astimezone(MVT)
        except ValueError:
            return "0000-00"
        return month_of(d)

    SKIP_MSG = {"course_inactive": "Course or tuition class is inactive (no new invoices)",
                "fee_zero": "Course fee is 0 - set a monthly fee on the course",
                "inactive_student": "Student account is deactivated",
                "not_enrolled_yet": "Student enrolled after this billing month",
                "first_month_skipped": "First month is not billed (setting first_invoice_mode = skip)",
                "already_invoiced": "Invoice for this month already exists",
                "not_active": "Enrolment is not active (waitlist or dropped); invoiced when it becomes active",
                "not_found": "Enrolment not found"}

    def registration_invoice(e, user_id):
        """Session 31: the one-time registration fee, once per student and course (a transfer to another batch of the same course, or a later
        re-enrolment, is not charged again). Not discounted (family concessions and discounts apply to the monthly fee only). Returns the invoice id or None."""
        fee = int(one("SELECT registration_fee_mvr AS r FROM courses WHERE id=?", (e["cid"],))["r"] or 0)
        if fee <= 0 or one("SELECT 1 x FROM invoices WHERE student_id=? AND course_id=? AND kind='registration'", (e["student_id"], e["cid"])): return None
        try: grace = int(setting("first_invoice_grace_days", "7"))
        except ValueError: grace = 7
        cur = db().execute(
            "INSERT INTO invoices(enrollment_id,student_id,course_id,batch_id,period,description,kind,amount_mvr,discount_mvr,amount_due_mvr,due_date,status,created_by,created_at) "
            "VALUES(?,?,?,?,'REG-FEE',?,'registration',?,0,?,?,'unpaid',?,?) ON CONFLICT (enrollment_id, period) DO NOTHING",
            (e["eid"], e["student_id"], e["cid"], e["bid"], f"Registration fee · {e['cname']}{' ' + e['level'] if e['level'] else ''} · Batch {e['code']}", fee, fee,
             (today() + dt.timedelta(days=grace)).isoformat(), user_id, stamp()))
        return cur.lastrowid if cur.rowcount else None

    def first_invoice_result(eid, user_id=None):
        """Bills the current month in full (first_invoice_mode='skip' starts next month). Returns {invoice_id, reason, message}; reason is None when an invoice was created."""
        e = one(ENR_SQL + " WHERE e.id=?", (eid,))
        reason = ("not_found" if not e else "not_active" if e["estatus"] != "active" else "course_inactive" if not e["cactive"] else "fee_zero" if e["fee"] <= 0
                  else "first_month_skipped" if setting("first_invoice_mode", "full") == "skip" else None)
        iid = None
        if e and e["estatus"] == "active" and e["cactive"]:
            registration_invoice(e, user_id if user_id is not None else (getattr(g, "user", None) or {}).get("id"))
        if not reason:
            if user_id is None: user_id = (getattr(g, "user", None) or {}).get("id")
            iid = make_invoice(e, month_of(today()), True, user_id)
            if not iid: reason = "already_invoiced"
        return {"invoice_id": iid, "reason": reason, "message": SKIP_MSG.get(reason)}

    def first_invoice(eid, user_id=None):
        return first_invoice_result(eid, user_id)["invoice_id"]

    def on_transfer(old_eid, new_eid):
        """Moved to another batch: open invoices for this month onward follow the student when the course is the same (no double billing)."""
        o, n = one(ENR_SQL + " WHERE e.id=?", (old_eid,)), one(ENR_SQL + " WHERE e.id=?", (new_eid,))
        if o and n and o["cid"] == n["cid"]:
            for i in rows("SELECT * FROM invoices WHERE enrollment_id=? AND kind='monthly' AND period>=? AND status!='void'", (old_eid, month_of(today()))):
                if not one("SELECT 1 x FROM invoices WHERE enrollment_id=? AND period=?", (new_eid, i["period"])):
                    db().execute("UPDATE invoices SET enrollment_id=?, batch_id=?, description=? WHERE id=?",
                                 (new_eid, n["bid"], describe(n["cname"], n["level"], n["code"], i["period"]), i["id"]))
        return first_invoice(new_eid)

    def generate(period, user_id):
        """Creates the missing invoices for a month. `skipped` counts each reason; `details` names every enrolment that got no new invoice and why (first 500)."""
        out = {"period": period, "created": 0, "skipped": {}, "details": []}
        sk = out["skipped"]
        def bump(k, e):
            sk[k] = sk.get(k, 0) + 1
            if len(out["details"]) < 500:
                out["details"].append({"enrollment_id": e["eid"], "student": e["sname"], "course": e["cname"], "batch": e["code"], "reason": k, "message": SKIP_MSG[k]})
        for e in rows(ENR_SQL + " WHERE e.status='active' ORDER BY e.id"):
            if not e["cactive"]: bump("course_inactive", e); continue   # Session 12: inactive courses get no new invoices (old ones stay in reports)
            if e["fee"] <= 0: bump("fee_zero", e); continue
            if not e["is_active"]: bump("inactive_student", e); continue
            em = enrolled_month(e["enrolled_at"])
            if em > period: bump("not_enrolled_yet", e); continue
            if em == period and setting("first_invoice_mode", "full") == "skip": bump("first_month_skipped", e); continue
            if make_invoice(e, period, False, user_id): out["created"] += 1
            else: bump("already_invoiced", e)
        out["skipped_total"] = sum(sk.values())
        out["details_truncated"] = out["skipped_total"] > len(out["details"])
        return out

    def catch_up(user_id=None, how="catch-up"):
        """Creates whatever is missing for the current month. Safe to repeat (UNIQUE enrollment_id, period). Logged only when something was created."""
        r = generate(month_of(today()), user_id)
        if r["created"]:
            audit_c("generate_invoices", "invoice", None, f"{r['period']}: created {r['created']}, skipped {r['skipped_total']} ({how})", **({"role": "system"} if user_id is None else {}))
        db().commit()
        return r

    def back_bill(eid, user_id=None):
        """v0.8.43: a student added now who started earlier (start date in the past) is billed every month from the start month up to
        last month. The current month is billed by first_invoice as before. Returns how many invoices were made."""
        e = one(ENR_SQL + " WHERE e.id=?", (eid,))
        if not e or e["estatus"] != "active" or not e["cactive"] or e["fee"] <= 0 or not e["is_active"]: return 0
        if user_id is None: user_id = (getattr(g, "user", None) or {}).get("id")
        p, cur, n = enrolled_month(e["enrolled_at"]), month_of(today()), 0
        if p == "0000-00": return 0
        if setting("first_invoice_mode", "full") == "skip": p = next_month_start(p).isoformat()[:7]
        while p < cur:
            if make_invoice(e, p, False, user_id): n += 1
            p = next_month_start(p).isoformat()[:7]
        return n

    # ---------- admin: generate, list, detail ----------
    @app.post("/api/invoices/generate")
    @auth("admin", perm="fees")
    def inv_generate():
        period = parse_period(body().get("month"))
        if not period: return err("Choose a month like 2026-03 (not further ahead than next month)")
        start = body().get("from_month")
        if not start:
            r = generate(period, g.user["id"])
            audit_c("generate_invoices", "invoice", None, f"{period}: created {r['created']}, skipped {r['skipped_total']}"); db().commit()
            return jsonify(r)
        # v0.8.43: a range of months at once (catching up on months before the portal was used)
        start = parse_period(start)
        if not start or start > period: return err("'From' must be a month like 2026-04, not after the last month")
        months = []
        while start <= period:
            months.append(start); start = next_month_start(start).isoformat()[:7]
        if len(months) > 24: return err("Generate at most 24 months at a time")
        out = {"period": period, "from_month": months[0], "months": [], "created": 0, "skipped": {}, "details": [], "skipped_total": 0}
        for m in months:
            r = generate(m, g.user["id"])
            out["months"].append({"period": m, "created": r["created"]})
            out["created"] += r["created"]; out["skipped_total"] += r["skipped_total"]
            for k, v in r["skipped"].items(): out["skipped"][k] = out["skipped"].get(k, 0) + v
            for x in r["details"]:
                if x["reason"] not in ("already_invoiced", "not_enrolled_yet") and len(out["details"]) < 500: out["details"].append({**x, "period": m})
        out["details_truncated"] = False
        audit_c("generate_invoices", "invoice", None, f"{months[0]} to {period}: created {out['created']}, skipped {out['skipped_total']}"); db().commit()
        return jsonify(out)

    @app.post("/api/invoices/catch-up")
    @auth("admin", perm="fees")
    def inv_catch_up():
        r = catch_up(g.user["id"], "catch-up on opening Fees")
        return jsonify(period=r["period"], created=r["created"])

    @app.get("/api/invoices/<int:iid>/invoice.pdf")
    @auth("admin", perm="fees")
    def invoice_pdf(iid):
        i = get_invoice(iid)
        if not i: return err("Invoice not found", 404)
        c_ = one("SELECT level FROM courses WHERE id=?", (i["course_id"],))
        data = receipts.build_invoice({"academy": setting("academy_name", "Baleegh Academy"), "phone": setting("contact_phone"), "invoice_no": i["number"],
                                       "student_id": i["student_id"], "student": i["student_name"], "course": (i["course_name"] + (" " + c_["level"] if c_ and c_["level"] else "")) if i["course_name"] else i["description"],
                                       "batch": i["batch_code"] or "-", "period": i["period"], "due_date": i["due_date"], "amount": i["amount_mvr"], "discount": i["discount_mvr"],
                                       "amount_due": i["amount_due_mvr"], "paid": i["paid_mvr"], "balance": i["balance"], "status": i["status"]})
        audit_c("view_invoice_pdf", "invoice", iid, None); db().commit()
        resp = Response(data, mimetype="application/pdf")
        resp.headers["Content-Disposition"] = f'attachment; filename="{i["number"]}.pdf"'
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    @app.get("/api/invoices")
    @auth("admin", perm="fees")
    def inv_list():
        w, a = [], []
        month = request.args.get("month")
        if month:
            if not PERIOD.match(month): return err("Month must look like 2026-03")
            w.append("i.period=?"); a.append(month)
        st, t = request.args.get("status"), today().isoformat()
        if st == "overdue": w.append("i.status IN ('unpaid','slip_submitted') AND i.due_date<?"); a.append(t)
        elif st == "open": w.append("i.status IN ('unpaid','slip_submitted')")
        elif st in ("unpaid", "slip_submitted", "paid", "void", "waived"): w.append("i.status=?"); a.append(st)
        elif st == "all": pass
        elif st: return err("Unknown status")
        # v0.8.35: voided invoices are left out of the normal list; find them with status=void (or all), or by their exact number
        elif not re.match(r"^INV-\d{6}-\d+$", (request.args.get("q") or "").strip().upper()): w.append("i.status<>'void'")
        if request.args.get("student_id"):
            if not request.args["student_id"].isdigit(): return err("Bad student id")
            w.append("i.student_id=?"); a.append(int(request.args["student_id"]))
        q = (request.args.get("q") or "").strip()
        if q:
            m = re.match(r"^INV-\d{6}-(\d+)$", q.upper())
            if m: w.append("i.id=?"); a.append(int(m.group(1)))
            else: w.append("(LOWER(COALESCE(u.full_name, i.customer_name)) LIKE ? OR LOWER(i.description) LIKE ?)"); a += ["%" + q.lower() + "%"] * 2
        if request.args.get("revenue_type"):   # v0.8.45
            if not request.args["revenue_type"].isdigit(): return err("Bad revenue type")
            w.append("rt.id=?"); a.append(int(request.args["revenue_type"]))
        lim = min(max(request.args.get("limit", 500, type=int), 1), 5000)   # v0.8.38: the Excel export asks for up to 5000
        sql = INV_SQL + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY i.period DESC, COALESCE(u.full_name, i.customer_name), i.id LIMIT ?"
        t0 = today()
        return jsonify([shape(r, t0) for r in rows(sql, a + [lim])])

    def slip_row(s, admin):
        d = {k: s[k] for k in ("id", "invoice_id", "amount_mvr", "transfer_date", "reference", "status", "reject_reason", "created_at", "file_name")}
        if admin:
            d.update(reviewed_at=s["reviewed_at"], file_hash=s["file_hash"])
        return d

    @app.get("/api/invoices/<int:iid>")
    @auth("admin", "student", perm="fees")
    def inv_get(iid):
        inv, e = mine_or_admin(iid)
        if e: return e
        admin = g.user["role"] == "admin"
        out = {"invoice": inv,
               "payments": rows("SELECT id,amount_mvr,method,paid_on,reference,receipt_no,reversed_at,reverse_reason,created_at FROM payments WHERE invoice_id=? ORDER BY id", (iid,)),
               "slips": [slip_row(s, admin) for s in rows("SELECT * FROM payment_slips WHERE invoice_id=? ORDER BY id", (iid,))]}
        if admin:
            out["discounts"] = rows("SELECT d.*, u.full_name AS by_name FROM discounts d LEFT JOIN users u ON u.id=d.created_by WHERE d.invoice_id=? ORDER BY d.id", (iid,))
            out["reminders"] = rows("SELECT r.*, u.full_name AS by_name FROM reminders r LEFT JOIN users u ON u.id=r.sent_by WHERE r.invoice_id=? ORDER BY r.id DESC", (iid,))
        else:
            for k in ("created_by", "notes", "student_email", "student_phone"): out["invoice"].pop(k, None)
        return jsonify(out)

    # ---------- admin: change an invoice (discount, void, waive, reopen) ----------
    def reason_of(d):
        r = str(d.get("reason", "")).strip()
        return r[:300] if r else None

    @app.post("/api/invoices/<int:iid>/discount")
    @auth("admin", perm="fees")
    def inv_discount(iid):
        d = body()
        inv = get_invoice(iid)
        if not inv: return err("Invoice not found", 404)
        reason = reason_of(d)
        if not reason: return err("Give a reason for the discount")
        if d.get("kind") not in ("fixed", "percent"): return err("Choose fixed (MVR) or percent")
        try: value = pay.as_int(d.get("value"), "Discount")
        except pay.PayError as x: return money_err(x)
        if d["kind"] == "percent" and value > 100: return err("A percent discount cannot be more than 100")
        if inv["status"] in ("void", "waived"): return err(f"This invoice is {inv['status']}", 409)
        room = inv["amount_mvr"] - inv["discount_mvr"]
        applied = min(calc(d["kind"], value, inv["amount_mvr"]), room)   # never below 0
        if applied <= 0: return err("There is nothing left to discount on this invoice", 409)
        new_disc = inv["discount_mvr"] + applied
        if inv["amount_mvr"] - new_disc < inv["paid_mvr"]:
            return err(f"That would take the amount due below the MVR {inv['paid_mvr']} already paid", 409)
        note = ((inv["discount_note"] + "; ") if inv["discount_note"] else "") + f"-{applied} {reason}"
        db().execute("UPDATE invoices SET discount_mvr=?, amount_due_mvr=?, discount_note=? WHERE id=?", (new_disc, inv["amount_mvr"] - new_disc, note, iid))
        db().execute("INSERT INTO discounts(scope,invoice_id,kind,value,amount_mvr,reason,created_by,created_at) VALUES('invoice',?,?,?,?,?,?,?)",
                     (iid, d["kind"], value, applied, reason, g.user["id"], stamp()))
        P.recompute(iid)
        audit_c("invoice_discount", "invoice", iid, f"-{applied} MVR ({d['kind']} {value}): {reason}"); db().commit()
        return jsonify(applied=applied, invoice=get_invoice(iid))

    # ---------- v0.8.45: revenue types ----------
    def revenue_type(rid, active_only=True):
        try: rid = int(rid)
        except (TypeError, ValueError): return None
        r = one("SELECT * FROM revenue_types WHERE id=?", (rid,))
        return r if r and (r["is_active"] or not active_only) else None

    @app.get("/api/revenue-types")
    @auth("admin", perm="fees")
    def rt_list():
        out = rows("SELECT rt.*, (SELECT COUNT(*) FROM invoices i WHERE i.revenue_type_id=rt.id OR (i.revenue_type_id IS NULL AND i.kind=rt.code)) AS invoices "
                   "FROM revenue_types rt ORDER BY rt.is_active DESC, rt.code IS NULL, rt.name")
        for r in out: r["built_in"] = bool(r["code"])
        return jsonify(out)

    def rt_name(d):
        name = re.sub(r"\s+", " ", str(d.get("name") or "")).strip()
        if not name: return None, err("Give the revenue type a name")
        if len(name) > 60: return None, err("Keep the name under 60 characters")
        return name, None

    @app.post("/api/revenue-types")
    @auth("admin", perm="fees")
    def rt_create():
        name, e_ = rt_name(body())
        if e_: return e_
        if one("SELECT 1 x FROM revenue_types WHERE LOWER(name)=?", (name.lower(),)): return err("There is already a revenue type with that name", 409)
        rid = db().execute("INSERT INTO revenue_types(name,is_active,created_at) VALUES(?,1,?)", (name, stamp())).lastrowid
        audit_c("revenue_type_create", "revenue_type", rid, name); db().commit()
        return jsonify(id=rid, name=name), 201

    @app.patch("/api/revenue-types/<int:rid>")
    @auth("admin", perm="fees")
    def rt_update(rid):
        d, r = body(), revenue_type(rid, active_only=False)
        if not r: return err("Revenue type not found", 404)
        if "name" in d:
            name, e_ = rt_name(d)
            if e_: return e_
            if one("SELECT 1 x FROM revenue_types WHERE LOWER(name)=? AND id<>?", (name.lower(), rid)): return err("There is already a revenue type with that name", 409)
            db().execute("UPDATE revenue_types SET name=? WHERE id=?", (name, rid))
            audit_c("revenue_type_rename", "revenue_type", rid, f"{r['name']} -> {name}")
        if "is_active" in d:
            on = 1 if d["is_active"] in (True, 1, "1", "true") else 0
            if not on and r["code"]: return err("The built-in types (monthly and registration fees) are used by the portal and cannot be turned off", 409)
            db().execute("UPDATE revenue_types SET is_active=? WHERE id=?", (on, rid))
            audit_c("revenue_type_" + ("on" if on else "off"), "revenue_type", rid, r["name"])
        db().commit()
        return jsonify(ok=True)

    # ---------- v0.8.45: manual invoices (a student, or a customer who is not in the portal) ----------
    @app.post("/api/invoices/manual")
    @auth("admin", perm="fees")
    def inv_manual():
        """Multipart (when a slip is attached) or JSON. Who: student_id, or customer_name (+ customer_phone). What: revenue_type_id, amount_mvr,
        description, invoice_date (its month is the invoice's period), due_date, batch_id (optional, one of the student's batches: then the
        invoice counts for that course/batch in reports, and for the teacher's earnings when the type is Monthly fees), note.
        paid=1 records the payment in the same step (method, paid_on, reference, file, notify), for money already received."""
        d = request.form.to_dict() if request.form else body()
        sid = str(d.get("student_id") or "").strip()
        cname = re.sub(r"\s+", " ", str(d.get("customer_name") or "")).strip()
        cphone = str(d.get("customer_phone") or "").strip()[:30] or None
        if sid and cname: return err("Choose a student or type a customer name, not both")
        if not sid and not cname: return err("Choose a student, or type the customer's name")
        if len(cname) > 100: return err("Keep the customer name under 100 characters")
        st = None
        if sid:
            st = one("SELECT id, full_name FROM users WHERE id=? AND role='student'", (int(sid) if sid.isdigit() else -1,))
            if not st: return err("Student not found", 404)
        rt = revenue_type(d.get("revenue_type_id"))
        if not rt: return err("Choose the revenue type")
        try: amount = pay.as_int(d.get("amount_mvr"))
        except pay.PayError as x: return money_err(x)
        try: idate = dt.date.fromisoformat((d.get("invoice_date") or "").strip() or today().isoformat())
        except ValueError: return err("Enter a real invoice date")
        if idate > today() + dt.timedelta(days=62): return err("The invoice date is too far ahead")
        try: due = dt.date.fromisoformat((d.get("due_date") or "").strip() or idate.isoformat())
        except ValueError: return err("Enter a real due date")
        if due < idate: return err("The due date cannot be before the invoice date")
        course_id = batch_id = None
        if str(d.get("batch_id") or "").strip():
            if not st: return err("A course or batch can only be linked for a student in the portal")
            b = one("SELECT b.id, b.course_id FROM batches b JOIN enrollments e ON e.batch_id=b.id WHERE b.id=? AND e.student_id=?",
                    (int(d["batch_id"]) if str(d["batch_id"]).isdigit() else -1, st["id"]))
            if not b: return err("That student is not in that batch")
            course_id, batch_id = b["course_id"], b["id"]
        desc = re.sub(r"\s+", " ", str(d.get("description") or "")).strip()[:200] or rt["name"]
        paid = str(d.get("paid", "")).lower() in ("1", "true", "on", "yes")
        method, pd, slip = d.get("method") or "bank_transfer", None, None
        if paid:
            if method not in ("bank_transfer", "cash", "other"): return err("Choose how it was paid: bank transfer, cash or other")
            pd, e_ = paid_date(d)
            if e_: return e_
            pamt = str(d.get("paid_amount_mvr") or "").strip() or None
            if pamt:
                try:
                    if pay.as_int(pamt) > amount: return err("The amount paid is more than the invoice")
                except pay.PayError as x: return money_err(x)
            slip, e_ = take_slip()
            if e_: return e_
        try:
            iid = db().execute("INSERT INTO invoices(enrollment_id,student_id,course_id,batch_id,period,description,kind,amount_mvr,discount_mvr,amount_due_mvr,due_date,status,"
                               "notes,created_by,created_at,customer_name,customer_phone,revenue_type_id) VALUES(NULL,?,?,?,?,?,'manual',?,0,?,?,'unpaid',?,?,?,?,?,?)",
                               (st["id"] if st else None, course_id, batch_id, idate.isoformat()[:7], desc, amount, amount, due.isoformat(),
                                (d.get("note") or "").strip()[:300] or None, g.user["id"], stamp(), None if st else cname, None if st else cphone, rt["id"])).lastrowid
            who = st["full_name"] if st else cname + " (not in the portal)"
            audit_c("invoice_manual", "invoice", iid, f"{who}: {rt['name']}, {amount} MVR, {desc}")
            out, warn = record_paid([get_invoice(iid)], pamt, method, pd, d, slip) if paid else ([], [])
            db().commit()
        except pay.PayError as x:
            db().rollback(); drop_slip(slip)
            return money_err(x)
        except Exception:
            db().rollback(); drop_slip(slip)
            raise
        return jsonify(invoice=get_invoice(iid), payments=out, warnings=warn), 201

    # ---------- v0.8.45: edit an invoice (amount, description, due date, revenue type; name and phone of a customer not in the portal) ----------
    @app.patch("/api/invoices/<int:iid>")
    @auth("admin", perm="fees")
    def inv_edit(iid):
        d = body()
        inv = get_invoice(iid)
        if not inv: return err("Invoice not found", 404)
        if inv["status"] == "void": return err("This invoice is void; reopen it first", 409)
        sets, args, notes = [], [], []
        if "amount_mvr" in d and str(d["amount_mvr"]).strip() != str(inv["amount_mvr"]):
            if inv["status"] == "waived": return err("This invoice is waived; reopen it before changing the amount", 409)
            try: amount = pay.as_int(d["amount_mvr"])
            except pay.PayError as x: return money_err(x)
            if amount < inv["discount_mvr"]: return err(f"The amount cannot be less than the MVR {inv['discount_mvr']} discount on it", 409)
            if amount - inv["discount_mvr"] < inv["paid_mvr"] + inv["waived_mvr"]:
                return err(f"MVR {inv['paid_mvr']} is already paid on this invoice; reverse a payment first to bring it lower", 409)
            if not reason_of(d): return err("Give a reason for changing the amount")
            sets += ["amount_mvr=?", "amount_due_mvr=?"]; args += [amount, amount - inv["discount_mvr"]]
            notes.append(f"amount {inv['amount_mvr']} -> {amount} MVR ({reason_of(d)})")
        if "description" in d:
            desc = re.sub(r"\s+", " ", str(d["description"] or "")).strip()[:200]
            if not desc: return err("The description cannot be empty")
            if desc != inv["description"]: sets.append("description=?"); args.append(desc); notes.append("description")
        if "due_date" in d and d["due_date"] != inv["due_date"]:
            try: due = dt.date.fromisoformat(str(d["due_date"]).strip())
            except ValueError: return err("Enter a real due date")
            sets.append("due_date=?"); args.append(due.isoformat()); notes.append(f"due {inv['due_date']} -> {due.isoformat()}")
        if "revenue_type_id" in d and str(d["revenue_type_id"]) != str(inv["revenue_type"]):
            rt = revenue_type(d["revenue_type_id"])
            if not rt: return err("Choose the revenue type")
            sets.append("revenue_type_id=?"); args.append(rt["id"]); notes.append(f"type {inv['revenue_type_name']} -> {rt['name']}")
        for k, lim in (("customer_name", 100), ("customer_phone", 30)):
            if k in d:
                if not inv["walk_in"]: return err("Name and phone can be changed only for a customer who is not in the portal")
                v = re.sub(r"\s+", " ", str(d[k] or "")).strip()[:lim]
                if k == "customer_name" and not v: return err("The customer name cannot be empty")
                sets.append(f"{k}=?"); args.append(v or None); notes.append(k.replace("_", " "))
        if not sets: return jsonify(invoice=inv, changed=False)
        db().execute(f"UPDATE invoices SET {', '.join(sets)} WHERE id=?", tuple(args) + (iid,))
        P.recompute(iid)
        audit_c("invoice_edit", "invoice", iid, "; ".join(notes)); db().commit()
        return jsonify(invoice=get_invoice(iid), changed=True)

    def invoice_state_change(iid, new_status):
        d = body()
        inv = get_invoice(iid)
        if not inv: return None, None, err("Invoice not found", 404)
        reason = reason_of(d)
        if not reason: return None, None, err("Give a reason")
        return inv, reason, None

    @app.post("/api/invoices/<int:iid>/void")
    @auth("admin", perm="fees")
    def inv_void(iid):
        inv, reason, e = invoice_state_change(iid, "void")
        if e: return e
        if inv["status"] == "void": return err("Already void", 409)
        if inv["paid_mvr"] > 0: return err("This invoice has payments. Reverse them first, or waive the balance instead.", 409)
        if one("SELECT 1 x FROM payment_slips WHERE invoice_id=? AND status='pending'", (iid,)): return err("A slip is waiting for review. Verify or reject it first.", 409)
        db().execute("UPDATE invoices SET status='void', status_reason=? WHERE id=?", (reason, iid))
        audit_c("invoice_void", "invoice", iid, reason); db().commit()
        return jsonify(invoice=get_invoice(iid))

    @app.post("/api/invoices/<int:iid>/waive")
    @auth("admin", perm="fees")
    def inv_waive(iid):
        inv, reason, e = invoice_state_change(iid, "waived")
        if e: return e
        if inv["status"] not in OPEN or inv["balance"] <= 0: return err("Only an invoice with a balance can be waived", 409)
        if one("SELECT 1 x FROM payment_slips WHERE invoice_id=? AND status='pending'", (iid,)): return err("A slip is waiting for review. Verify or reject it first.", 409)
        db().execute("UPDATE invoices SET status='waived', waived_mvr=?, status_reason=? WHERE id=?", (inv["balance"], reason, iid))
        audit_c("invoice_waive", "invoice", iid, f"{inv['balance']} MVR: {reason}"); db().commit()
        return jsonify(invoice=get_invoice(iid))

    @app.post("/api/invoices/<int:iid>/reopen")
    @auth("admin", perm="fees")
    def inv_reopen(iid):
        inv, reason, e = invoice_state_change(iid, "unpaid")
        if e: return e
        if inv["status"] not in ("void", "waived"): return err("Only a void or waived invoice can be reopened", 409)
        db().execute("UPDATE invoices SET status='unpaid', waived_mvr=0, status_reason=NULL WHERE id=?", (iid,))
        P.recompute(iid)
        audit_c("invoice_reopen", "invoice", iid, reason); db().commit()
        return jsonify(invoice=get_invoice(iid))

    @app.post("/api/enrollments/<int:eid>/void-open-invoices")
    @auth("admin", perm="fees")
    def void_open(eid):
        """After a student drops: void their unpaid invoices from `from_month` (default: this month) on. Invoices with payments or a waiting slip are left alone."""
        d = body()
        reason = reason_of(d)
        if not reason: return err("Give a reason")
        en = one("SELECT status FROM enrollments WHERE id=?", (eid,))
        if not en: return err("Enrollment not found", 404)
        if en["status"] == "active": return err("This enrollment is still active", 409)
        start = d.get("from_month") or month_of(today())
        if not PERIOD.match(str(start)): return err("From month must look like 2026-03")
        n = 0
        for i in rows("SELECT id FROM invoices WHERE enrollment_id=? AND kind='monthly' AND period>=? AND status='unpaid' AND paid_mvr=0", (eid, start)):
            db().execute("UPDATE invoices SET status='void', status_reason=? WHERE id=?", (reason, i["id"]))
            audit_c("invoice_void", "invoice", i["id"], "enrollment dropped: " + reason); n += 1
        db().commit()
        return jsonify(voided=n)

    # ---------- recurring discounts and families ----------
    @app.get("/api/discounts")
    @auth("admin", perm="fees")
    def disc_list():
        return jsonify(rows("SELECT d.*, u.full_name AS student_name, c.name AS course_name, b.code AS batch_code FROM discounts d "
                            "JOIN enrollments e ON e.id=d.enrollment_id JOIN users u ON u.id=e.student_id JOIN batches b ON b.id=e.batch_id "
                            "JOIN courses c ON c.id=b.course_id WHERE d.scope='enrollment' AND d.active=1 ORDER BY d.id DESC"))

    @app.post("/api/discounts")
    @auth("admin", perm="fees")
    def disc_create():
        d = body()
        reason = reason_of(d)
        if not reason: return err("Give a reason for the discount")
        if d.get("kind") not in ("fixed", "percent"): return err("Choose fixed (MVR) or percent")
        try: value = pay.as_int(d.get("value"), "Discount")
        except pay.PayError as x: return money_err(x)
        if d["kind"] == "percent" and value > 100: return err("A percent discount cannot be more than 100")
        if not str(d.get("enrollment_id", "")).isdigit() or not one("SELECT id FROM enrollments WHERE id=?", (d["enrollment_id"],)): return err("Enrollment not found", 404)
        cur = db().execute("INSERT INTO discounts(scope,enrollment_id,kind,value,reason,created_by,created_at) VALUES('enrollment',?,?,?,?,?,?)",
                           (int(d["enrollment_id"]), d["kind"], value, reason, g.user["id"], stamp()))
        audit_c("discount_add", "enrollment", int(d["enrollment_id"]), f"{d['kind']} {value}: {reason}"); db().commit()
        return jsonify(id=cur.lastrowid), 201

    @app.delete("/api/discounts/<int:did>")
    @auth("admin", perm="fees")
    def disc_end(did):
        cur = db().execute("UPDATE discounts SET active=0, ended_by=?, ended_at=? WHERE id=? AND active=1 AND scope='enrollment'", (g.user["id"], stamp(), did))
        if not cur.rowcount: return err("Discount not found", 404)
        audit_c("discount_end", "discount", did); db().commit()
        return jsonify(ok=True)

    def family_full(fid):
        f = one("SELECT * FROM families WHERE id=?", (fid,))
        if f: f["members"] = rows("SELECT m.student_id, m.concession_applies, u.full_name FROM family_members m JOIN users u ON u.id=m.student_id WHERE m.family_id=? ORDER BY u.full_name", (fid,))
        return f

    @app.get("/api/families")
    @auth("admin", perm="fees")
    def fam_list():
        return jsonify([family_full(f["id"]) for f in rows("SELECT id FROM families ORDER BY id DESC")])

    def fam_fields(d, partial=False):
        out = {}
        if "name" in d or not partial:
            if not str(d.get("name", "")).strip(): return None, "Give the family a name"
            out["name"] = str(d["name"]).strip()[:80]
        if "concession_kind" in d or "concession_value" in d or not partial:
            kind, val = d.get("concession_kind") or None, d.get("concession_value", 0) or 0
            try: val = int(val)
            except (TypeError, ValueError): return None, "Concession must be a whole number"
            if val < 0: return None, "Concession cannot be negative"
            if val and kind not in ("fixed", "percent"): return None, "Choose fixed (MVR) or percent for the concession"
            if kind == "percent" and val > 100: return None, "A percent concession cannot be more than 100"
            out.update(concession_kind=kind if val else None, concession_value=val)
        if "concession_reason" in d or not partial: out["concession_reason"] = str(d.get("concession_reason", "") or "").strip()[:200] or None
        return out, None

    @app.post("/api/families")
    @auth("admin", perm="fees")
    def fam_create():
        f, e = fam_fields(body())
        if e: return err(e)
        cur = db().execute("INSERT INTO families(name,concession_kind,concession_value,concession_reason,created_at) VALUES(?,?,?,?,?)",
                           (f["name"], f["concession_kind"], f["concession_value"], f["concession_reason"], stamp()))
        audit_c("family_create", "family", cur.lastrowid, f["name"]); db().commit()
        return jsonify(id=cur.lastrowid), 201

    @app.patch("/api/families/<int:fid>")
    @auth("admin", perm="fees")
    def fam_update(fid):
        if not one("SELECT id FROM families WHERE id=?", (fid,)): return err("Family not found", 404)
        f, e = fam_fields(body(), partial=True)
        if e: return err(e)
        if not f: return err("Nothing to update")
        db().execute(f"UPDATE families SET {','.join(k + '=?' for k in f)} WHERE id=?", (*f.values(), fid))
        audit_c("family_update", "family", fid, ", ".join(f"{k}={v}" for k, v in f.items())); db().commit()
        return jsonify(ok=True)

    @app.post("/api/families/<int:fid>/members")
    @auth("admin", perm="fees")
    def fam_add(fid):
        d = body()
        if not one("SELECT id FROM families WHERE id=?", (fid,)): return err("Family not found", 404)
        if not str(d.get("student_id", "")).isdigit() or not one("SELECT id FROM users WHERE id=? AND role='student'", (d["student_id"],)): return err("Student not found", 404)
        sid = int(d["student_id"])
        if one("SELECT 1 x FROM family_members WHERE student_id=?", (sid,)): return err("This student is already in a family", 409)
        db().execute("INSERT INTO family_members(student_id,family_id,concession_applies) VALUES(?,?,?)", (sid, fid, 0 if d.get("concession_applies") in (0, False) else 1))
        audit_c("family_add_member", "family", fid, f"student {sid}"); db().commit()
        return jsonify(ok=True), 201

    @app.patch("/api/families/<int:fid>/members/<int:sid>")
    @auth("admin", perm="fees")
    def fam_member(fid, sid):
        cur = db().execute("UPDATE family_members SET concession_applies=? WHERE family_id=? AND student_id=?", (0 if body().get("concession_applies") in (0, False) else 1, fid, sid))
        if not cur.rowcount: return err("Member not found", 404)
        audit_c("family_member_concession", "family", fid, f"student {sid}: {body().get('concession_applies')}"); db().commit()
        return jsonify(ok=True)

    @app.delete("/api/families/<int:fid>/members/<int:sid>")
    @auth("admin", perm="fees")
    def fam_remove(fid, sid):
        cur = db().execute("DELETE FROM family_members WHERE family_id=? AND student_id=?", (fid, sid))
        if not cur.rowcount: return err("Member not found", 404)
        audit_c("family_remove_member", "family", fid, f"student {sid}"); db().commit()
        return jsonify(ok=True)

    # ---------- student: my fees ----------
    def bank():
        s = {k: setting(k) for k in ("bank_name", "bank_account_name", "bank_account_number")}
        return {**s, "configured": all(s.values())}

    def open_totals(student_id):
        t = today().isoformat()
        r = one("SELECT COALESCE(SUM(amount_due_mvr-waived_mvr-paid_mvr),0) AS bal, COUNT(*) AS n, MIN(due_date) AS first_due FROM invoices "
                "WHERE student_id=? AND status IN ('unpaid','slip_submitted') AND amount_due_mvr-waived_mvr-paid_mvr>0", (student_id,))
        od = one("SELECT COUNT(*) n FROM invoices WHERE student_id=? AND status IN ('unpaid','slip_submitted') AND amount_due_mvr-waived_mvr-paid_mvr>0 AND due_date<?", (student_id, t))["n"]
        return {"balance_due": r["bal"], "open_count": r["n"], "overdue_count": od, "next_due": r["first_due"]}

    @app.get("/api/my/fees/summary")
    @auth("student", perm="fees")
    def my_fees_summary():
        return jsonify(open_totals(g.user["id"]))

    @app.get("/api/my/fees")
    @auth("student", perm="fees")
    def my_fees():
        uid, t = g.user["id"], today()
        invs = [shape(r, t) for r in rows(INV_SQL + " WHERE i.student_id=? AND i.status!='void' ORDER BY i.period DESC, i.id DESC", (uid,))]
        slips = {}
        for s in rows("SELECT * FROM payment_slips WHERE student_id=? ORDER BY id", (uid,)):
            slips.setdefault(s["invoice_id"], []).append(s)
        for i in invs:
            ss = slips.get(i["id"], [])
            pend = next((s for s in reversed(ss) if s["status"] == "pending"), None)
            last = ss[-1] if ss else None
            i["pending_slip"] = slip_row(pend, False) if pend else None
            i["last_rejection"] = ({"reason": last["reject_reason"], "at": last["reviewed_at"], "amount_mvr": last["amount_mvr"]} if last and last["status"] == "rejected" and not pend else None)
            i["can_upload"] = bool(i["status"] == "unpaid" and i["balance"] > 0)
            for k in ("created_by", "notes", "student_email", "student_phone"): i.pop(k, None)
        pays = rows("SELECT p.id,p.invoice_id,p.amount_mvr,p.method,p.paid_on,p.receipt_no,p.reversed_at,i.period FROM payments p JOIN invoices i ON i.id=p.invoice_id "
                    "WHERE p.student_id=? ORDER BY p.id DESC", (uid,))
        return jsonify(bank=bank(), invoices=invs, payments=pays, summary=open_totals(uid))

    # ---------- slips: upload (student) ----------
    @app.post("/api/invoices/<int:iid>/slips")
    @auth("student", perm="fees")
    def slip_upload(iid):
        inv = get_invoice(iid)
        if not inv or inv["student_id"] != g.user["id"]: return err("Invoice not found", 404)
        n = now().timestamp()
        hits = slip_hits[g.user["id"]] = [x for x in slip_hits.get(g.user["id"], []) if n - x < 3600]
        if len(hits) >= app.config["SLIP_LIMIT"]: return err("Too many uploads. Please try again in a while or contact the academy.", 429)
        hits.append(n)
        if inv["status"] in ("paid", "void", "waived") or inv["balance"] <= 0: return err("This invoice does not need a payment", 409)
        if one("SELECT 1 x FROM payment_slips WHERE invoice_id=? AND status='pending'", (iid,)): return err("Your earlier slip for this invoice is still waiting to be checked", 409)
        f = request.form
        try: amount = pay.as_int(f.get("amount_mvr"), "The amount you transferred")
        except pay.PayError as x: return money_err(x)
        try: tdate = dt.date.fromisoformat(f.get("transfer_date", ""))
        except ValueError: return err("Enter the date you made the transfer")
        if tdate > today(): return err("The transfer date cannot be in the future")
        if tdate < today() - dt.timedelta(days=365): return err("That transfer date is too old. Contact the academy.")
        try: name, digest, shown = common.save_private(request.files.get("file"), store, "slips")
        except ValueError as x: return err(str(x))
        try:
            cur = db().execute("INSERT INTO payment_slips(invoice_id,student_id,file,file_name,file_hash,amount_mvr,transfer_date,reference,status,created_at) VALUES(?,?,?,?,?,?,?,?,'pending',?)",
                               (iid, g.user["id"], name, shown, digest, amount, tdate.isoformat(), (f.get("reference") or "").strip()[:80] or None, stamp()))
            P.recompute(iid)
            audit_c("slip_upload", "invoice", iid, f"slip {cur.lastrowid}, claimed {amount} MVR")
            c.notify(c.notify_admins_with("fees"), "slip_uploaded", "New payment slip", f"{g.user['full_name']} sent a slip for {amount} MVR.", f"fees:{iid}")   # Session 28
            db().commit()
        except Exception:
            db().rollback()
            store.delete("slips", name)
            raise
        return jsonify(id=cur.lastrowid, invoice=get_invoice(iid)), 201

    @app.get("/api/slips/<int:sid>/file")
    @auth("admin", "student", perm="fees")
    def slip_file(sid):
        s = one("SELECT * FROM payment_slips WHERE id=?", (sid,))
        if not s or (g.user["role"] == "student" and s["student_id"] != g.user["id"]): return err("Slip not found", 404)
        audit_c("view_slip", "slip", sid, g.user["role"]); db().commit()
        return common.file_headers(store.send("slips", s["file"], s["file_name"] or s["file"], as_attachment=True), s["file_name"] or s["file"], attachment=True)

    # ---------- slips: admin queue, verify, reject ----------
    def with_dupes(s):
        s = dict(s)
        s["duplicates"] = [{"slip_id": d["id"], "invoice_number": inv_no({"period": d["period"], "id": d["invoice_id"]}), "student_name": d["student_name"], "status": d["status"]}
                           for d in rows("SELECT s.id, s.invoice_id, s.status, i.period, COALESCE(u.full_name, i.customer_name) AS student_name FROM payment_slips s JOIN invoices i ON i.id=s.invoice_id "
                                         "LEFT JOIN users u ON u.id=s.student_id WHERE s.file_hash=? AND s.id!=? ORDER BY s.id", (s["file_hash"], s["id"]))]
        s["duplicate_verified"] = any(d["status"] == "verified" for d in s["duplicates"])
        return s

    @app.get("/api/slips")
    @auth("admin", perm="fees")
    def slips_list():
        st = request.args.get("status", "pending")
        if st not in ("pending", "verified", "rejected", "reversed", "all"): return err("Unknown status")
        sql = ("SELECT s.*, i.period, i.amount_due_mvr, i.waived_mvr, i.paid_mvr, i.status AS invoice_status, COALESCE(u.full_name, i.customer_name) AS student_name, COALESCE(c.name, i.description) AS course_name, b.code AS batch_code "
               "FROM payment_slips s JOIN invoices i ON i.id=s.invoice_id LEFT JOIN users u ON u.id=s.student_id LEFT JOIN courses c ON c.id=i.course_id LEFT JOIN batches b ON b.id=i.batch_id")
        data = rows(sql + ("" if st == "all" else " WHERE s.status=?") + " ORDER BY s.id DESC LIMIT 300", () if st == "all" else (st,))
        out = []
        for s in data:
            s = with_dupes(s)
            s["invoice_number"] = inv_no({"period": s["period"], "id": s["invoice_id"]})
            s["balance"] = max(s["amount_due_mvr"] - s["waived_mvr"] - s["paid_mvr"], 0)
            s.pop("file", None)
            out.append(s)
        return jsonify(out)

    @app.post("/api/slips/<int:sid>/verify")
    @auth("admin", perm="fees")
    def slip_verify(sid):
        d = body()
        s = one("SELECT * FROM payment_slips WHERE id=?", (sid,))
        if not s: return err("Slip not found", 404)
        if s["status"] != "pending": return err(f"This slip was already {s['status']}", 409)
        dup = with_dupes(s)
        if dup["duplicate_verified"] and not d.get("confirm_duplicate"):
            return jsonify(error="The same file was already accepted on another payment. Check before accepting it again.", needs_confirm=True, duplicates=dup["duplicates"]), 409
        amount = d.get("amount_mvr", s["amount_mvr"])
        cur = db().execute("UPDATE payment_slips SET status='verified', reviewed_by=?, reviewed_at=? WHERE id=? AND status='pending'", (g.user["id"], stamp(), sid))
        if not cur.rowcount: db().rollback(); return err("This slip was already checked", 409)
        try:
            p = P.record(s["invoice_id"], amount, "bank_transfer", d.get("paid_on") or s["transfer_date"], s["reference"], None, sid, g.user["id"])
        except pay.PayError as x:
            db().rollback()
            return money_err(x)
        audit_c("slip_verify", "payment", p["id"], f"slip {sid}, invoice {s['invoice_id']}, {p['amount_mvr']} MVR, {p['receipt_no']}" + (", duplicate confirmed" if dup["duplicates"] else ""))
        c.notify([s["student_id"]], "slip_verified", "Payment received", f"We received {p['amount_mvr']} MVR. Receipt {p['receipt_no']}.", f"fees:{s['invoice_id']}")   # Session 28
        db().commit()
        return jsonify(payment_id=p["id"], receipt_no=p["receipt_no"], invoice=get_invoice(s["invoice_id"]), warnings=[{"duplicate_of": dup["duplicates"]}] if dup["duplicates"] else [])

    @app.post("/api/slips/<int:sid>/reject")
    @auth("admin", perm="fees")
    def slip_reject(sid):
        reason = reason_of(body())
        if not reason: return err("Give a reason so the student knows what to fix")
        cur = db().execute("UPDATE payment_slips SET status='rejected', reject_reason=?, reviewed_by=?, reviewed_at=? WHERE id=? AND status='pending'", (reason, g.user["id"], stamp(), sid))
        if not cur.rowcount:
            s = one("SELECT status FROM payment_slips WHERE id=?", (sid,))
            return err("Slip not found", 404) if not s else err(f"This slip was already {s['status']}", 409)
        P.recompute(one("SELECT invoice_id FROM payment_slips WHERE id=?", (sid,))["invoice_id"])
        audit_c("slip_reject", "slip", sid, reason)
        sl = one("SELECT student_id,invoice_id FROM payment_slips WHERE id=?", (sid,))
        c.notify([sl["student_id"]], "slip_rejected", "Payment slip not accepted", f"Reason: {reason}. Please send a new slip.", f"fees:{sl['invoice_id']}")   # Session 28; link: Session 16
        db().commit()
        return jsonify(ok=True)

    # ---------- payments: manual, list, reverse, receipts ----------
    @app.post("/api/payments")
    @auth("admin", perm="fees")
    def pay_manual():
        d = body()
        if not str(d.get("invoice_id", "")).isdigit(): return err("Choose an invoice")
        if d.get("method") not in ("bank_transfer", "cash", "other"): return err("Choose how it was paid: bank transfer, cash or other")   # 'gateway' is reserved for a future online gateway
        try: p = P.record(int(d["invoice_id"]), d.get("amount_mvr"), d.get("method"), d.get("paid_on"), d.get("reference"), d.get("note"), None, g.user["id"])
        except pay.PayError as x:
            db().rollback()
            return money_err(x)
        audit_c("payment_record", "payment", p["id"], f"invoice {p['invoice_id']}, {p['amount_mvr']} MVR {p['method']}, {p['receipt_no']}"); db().commit()
        return jsonify(payment=p, invoice=get_invoice(p["invoice_id"])), 201

    # ---------- v0.8.43: the office marks invoices paid, with the slip the person sent (WhatsApp, Viber, in person) ----------
    def mark_paid_ids(d):
        raw = d.get("invoice_ids") if d.get("invoice_ids") not in (None, "") else d.get("invoice_id")
        parts = raw if isinstance(raw, list) else str(raw or "").split(",")
        out = []
        for x in parts:
            x = str(x).strip()
            if not x: continue
            if not x.isdigit(): return None
            if int(x) not in out: out.append(int(x))
        return out

    # v0.8.45: the parts of "mark paid" shared with the manual invoice form (which can record the payment in the same step)
    def paid_date(d):
        paid_on = (d.get("paid_on") or "").strip() or today().isoformat()
        try: pd = dt.date.fromisoformat(paid_on)
        except ValueError: return None, err("Enter a real payment date")
        if pd > today(): return None, err("The payment date cannot be in the future")
        return pd, None

    def take_slip():
        f = request.files.get("file")
        if not (f and f.filename): return None, None
        try: return common.save_private(f, store, "slips"), None
        except ValueError as x: return None, err(str(x))

    def drop_slip(slip):
        if slip: store.delete("slips", slip[0])

    def record_paid(invs, amount, method, pd, d, slip):
        """Record the payments (and the verified slip rows) without committing. Raises pay.PayError."""
        out, warn = [], []
        name, digest, shown = slip or (None, None, None)
        for inv in invs:
            amt = amount or inv["balance"]
            slip_id = None
            if name:
                claimed = pay.as_int(amt)
                slip_id = db().execute("INSERT INTO payment_slips(invoice_id,student_id,file,file_name,file_hash,amount_mvr,transfer_date,reference,status,reviewed_by,reviewed_at,created_at) "
                                       "VALUES(?,?,?,?,?,?,?,?,'verified',?,?,?)",
                                       (inv["id"], inv["student_id"], name, shown, digest, claimed, pd.isoformat(), (d.get("reference") or "").strip()[:80] or None,
                                        g.user["id"], stamp(), stamp())).lastrowid
            p = P.record(inv["id"], amt, method, pd.isoformat(), d.get("reference"), d.get("note"), slip_id, g.user["id"])
            audit_c("payment_record", "payment", p["id"], f"invoice {inv['id']}, {p['amount_mvr']} MVR {method}, {p['receipt_no']}, marked paid" + (f", slip {slip_id} attached" if slip_id else ""))
            if one("SELECT 1 x FROM payment_slips WHERE invoice_id=? AND status='pending'", (inv["id"],)):
                warn.append(f"{inv['number']}: the student also sent a slip that is waiting in Slips to check. Reject it there if it is the same payment.")
            if inv["student_id"] and str(d.get("notify", "")).lower() in ("1", "true", "on", "yes"):
                c.notify([inv["student_id"]], "slip_verified", "Payment received", f"We received {p['amount_mvr']} MVR. Receipt {p['receipt_no']}.", f"fees:{inv['id']}")
            out.append(p)
        return out, warn

    @app.post("/api/payments/mark-paid")
    @auth("admin", perm="fees")
    def pay_mark_paid():
        """One or more open invoices paid. Multipart (with an optional `file`, the slip) or JSON. One invoice: `amount_mvr` (default: the
        balance). Several invoices: each is paid in full (one transfer that covered several months). The slip is stored once and shown on
        every payment it covers. The slip rows are saved as already verified, so they never enter the Slips to check queue."""
        d = request.form.to_dict() if request.form else body()
        ids = mark_paid_ids(d)
        if not ids: return err("Choose the invoices that were paid")
        if len(ids) > 24: return err("Mark at most 24 invoices at a time")
        method = d.get("method") or "bank_transfer"
        if method not in ("bank_transfer", "cash", "other"): return err("Choose how it was paid: bank transfer, cash or other")
        amount = str(d.get("amount_mvr") or "").strip() or None
        if amount and len(ids) > 1: return err("With several invoices each is marked paid in full; leave the amount empty")
        invs = []
        for iid in ids:
            inv = get_invoice(iid)
            if not inv: return err(f"Invoice {iid} not found", 404)
            if inv["status"] not in OPEN or inv["balance"] <= 0: return err(f"{inv['number']} ({inv['student_name']}) is {inv['status']}, nothing to pay", 409)
            invs.append(inv)
        pd, e_ = paid_date(d)
        if e_: return e_
        slip, e_ = take_slip()
        if e_: return e_
        try:
            out, warn = record_paid(invs, amount, method, pd, d, slip)
            db().commit()
        except pay.PayError as x:
            db().rollback(); drop_slip(slip)
            return money_err(x)
        except Exception:
            db().rollback(); drop_slip(slip)
            raise
        return jsonify(payments=out, invoices=[get_invoice(i["id"]) for i in invs], total_mvr=sum(p["amount_mvr"] for p in out), warnings=warn), 201

    @app.get("/api/payments")
    @auth("admin", perm="fees")
    def pay_list():
        w, a = [], []
        if request.args.get("month"):
            m = request.args["month"]
            if not PERIOD.match(m): return err("Month must look like 2026-03")
            w += ["p.paid_on>=?", "p.paid_on<?"]; a += [m + "-01", next_month_start(m).isoformat()]
        if request.args.get("invoice_id", "").isdigit(): w.append("p.invoice_id=?"); a.append(int(request.args["invoice_id"]))
        sql = ("SELECT p.*, i.period, i.description, COALESCE(u.full_name, i.customer_name) AS student_name, s.file_name AS slip_file_name, rt.name AS revenue_type_name "
               "FROM payments p JOIN invoices i ON i.id=p.invoice_id LEFT JOIN users u ON u.id=p.student_id" + RT_JOIN +
               " LEFT JOIN payment_slips s ON s.id=p.slip_id"
               + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY p.id DESC LIMIT 500")
        out = rows(sql, a)
        for p in out: p["invoice_number"] = inv_no({"period": p["period"], "id": p["invoice_id"]})
        return jsonify(out)

    @app.post("/api/payments/<int:pid>/reverse")
    @auth("admin", perm="fees")
    def pay_reverse(pid):
        try: p = P.reverse(pid, body().get("reason"), g.user["id"])
        except pay.PayError as x:
            db().rollback()
            return money_err(x)
        audit_c("payment_reverse", "payment", pid, f"{p['amount_mvr']} MVR, {p['receipt_no']}: {body().get('reason')}"); db().commit()
        return jsonify(invoice=get_invoice(p["invoice_id"]))

    METHOD_LABEL = {"bank_transfer": "Bank transfer", "cash": "Cash", "other": "Other", "gateway": "Online payment"}

    @app.get("/api/payments/<int:pid>/receipt.pdf")
    @auth("admin", "student", perm="fees")
    def receipt_pdf(pid):
        p = one("SELECT p.*, i.period, i.description, COALESCE(u.full_name, i.customer_name) AS student_name, c.name AS cname, c.level, b.code FROM payments p JOIN invoices i ON i.id=p.invoice_id "
                "LEFT JOIN users u ON u.id=p.student_id LEFT JOIN courses c ON c.id=i.course_id LEFT JOIN batches b ON b.id=i.batch_id WHERE p.id=?", (pid,))
        if not p or (g.user["role"] == "student" and p["student_id"] != g.user["id"]): return err("Receipt not found", 404)
        data = receipts.build({"academy": setting("academy_name", "Baleegh Academy"), "phone": setting("contact_phone"), "receipt_no": p["receipt_no"], "paid_on": p["paid_on"],
                               "student": p["student_name"], "course": (p["cname"] + (" " + p["level"] if p["level"] else "")) if p["cname"] else p["description"], "batch": p["code"] or "-",
                               "invoice_no": inv_no({"period": p["period"], "id": p["invoice_id"]}), "period": p["period"], "amount": p["amount_mvr"],
                               "method": METHOD_LABEL.get(p["method"], p["method"]), "reference": p["reference"], "reversed": bool(p["reversed_at"])})
        audit_c("view_receipt", "payment", pid, g.user["role"]); db().commit()
        resp = Response(data, mimetype="application/pdf")
        resp.headers["Content-Disposition"] = f'attachment; filename="receipt-{re.sub(r"[^A-Za-z0-9_-]", "", p["receipt_no"])}.pdf"'
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    # ---------- v0.8.36: fee statement (all invoices and payments of one student, as a PDF) ----------
    def statement(sid):
        u = one("SELECT u.id,u.full_name,s.student_code FROM users u LEFT JOIN students s ON s.user_id=u.id WHERE u.id=? AND u.role='student'", (sid,))
        if not u: return None
        t0 = today()
        invs = [shape(r, t0) for r in rows(INV_SQL + " WHERE i.student_id=? AND i.status!='void' ORDER BY i.period, i.id", (sid,))]
        pays = rows("SELECT p.*, i.period FROM payments p JOIN invoices i ON i.id=p.invoice_id WHERE p.student_id=? AND i.status!='void' ORDER BY p.paid_on, p.id", (sid,))
        il = [{"number": i["number"], "period": i["period"], "course": (i["course_name"] + " " + (i["batch_code"] or "")).strip() if i["course_name"] else i["description"], "due_date": i["due_date"],
               "amount_due": i["amount_due_mvr"], "waived": i["waived_mvr"], "paid": i["paid_mvr"], "balance": i["balance"],
               "status": "overdue" if i["overdue"] else i["status"]} for i in invs]
        pl = [{"paid_on": p["paid_on"], "receipt_no": p["receipt_no"], "invoice_number": inv_no({"period": p["period"], "id": p["invoice_id"]}),
               "method": METHOD_LABEL.get(p["method"], p["method"]), "amount": p["amount_mvr"], "reversed": bool(p["reversed_at"])} for p in pays]
        tot = {"due": sum(i["amount_due"] - i["waived"] for i in il), "paid": sum(p["amount"] for p in pl if not p["reversed"]), "balance": sum(i["balance"] for i in il)}
        data = receipts.build_statement({"academy": setting("academy_name", "Baleegh Academy"), "phone": setting("contact_phone"), "student": u["full_name"],
                                         "student_code": u["student_code"], "generated": t0.isoformat(), "invoices": il, "payments": pl, "totals": tot})
        audit_c("view_statement", "user", sid, g.user["role"]); db().commit()
        resp = Response(data, mimetype="application/pdf")
        resp.headers["Content-Disposition"] = f'attachment; filename="fee-statement-{sid}-{t0.isoformat()}.pdf"'
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    @app.get("/api/my/fees/statement.pdf")
    @auth("student", perm="fees")
    def my_statement():
        return statement(g.user["id"])

    @app.get("/api/students/<int:sid>/statement.pdf")
    @auth("admin", perm="fees")
    def student_statement(sid):
        return statement(sid) or err("Student not found", 404)

    # ---------- overdue and reminders ----------
    def template_text():
        return setting("reminder_template_en") or DEFAULT_REMINDER_EN

    def email_enabled():
        cf = app.config
        return bool(cf.get("EMAIL_ENABLED") and cf.get("SMTP_HOST") and cf.get("SMTP_FROM"))

    def reminder_info(i):
        """Message text and click-to-chat links for one overdue invoice (student, and guardian when under 18 and a number is on file)."""
        st = one("SELECT u.phone, s.guardian_name, s.guardian_phone FROM users u LEFT JOIN students s ON s.user_id=u.id WHERE u.id=?", (i["student_id"],)) or {}
        vals = {"name": i["student_name"], "amount": i["balance"], "invoice": i["number"], "due_date": i["due_date"], "period": i["period"],
                "academy": setting("academy_name", "Baleegh Academy"), "course": i["course_name"] or i["description"], "days_overdue": i["days_overdue"], "guardian": st.get("guardian_name") or ""}
        text = fill(template_text(), vals)
        links = {}
        for who, phone in (("student", st.get("phone") or i.get("student_phone")), ("guardian", st.get("guardian_phone"))):
            num = common.digits_intl(phone)
            if num: links[who] = {"phone": phone, "whatsapp": f"https://wa.me/{num}?text={quote(text)}", "viber": f"viber://chat?number=%2B{num}"}
        return text, links

    @app.get("/api/fees/overdue")
    @auth("admin", perm="fees")
    def overdue_list():
        t = today()
        out = []
        for r in rows(INV_SQL + " WHERE i.status IN ('unpaid','slip_submitted') AND i.due_date<? AND i.amount_due_mvr-i.waived_mvr-i.paid_mvr>0 ORDER BY i.due_date, COALESCE(u.full_name, i.customer_name)", (t.isoformat(),)):
            i = shape(r, t)
            i["message"], i["links"] = reminder_info(i)
            rem = rows("SELECT r.channel, r.recipient, r.sent_at, u.full_name AS by_name FROM reminders r LEFT JOIN users u ON u.id=r.sent_by WHERE r.invoice_id=? ORDER BY r.id DESC", (i["id"],))
            i["reminders_sent"], i["last_reminder"] = len(rem), rem[0] if rem else None
            i["reminded_today"] = bool(rem and rem[0]["sent_at"][:10] == t.isoformat())
            for k in ("student_email", "created_by", "notes"): i.pop(k, None)
            out.append(i)
        return jsonify(items=out, email_enabled=email_enabled())

    @app.post("/api/invoices/<int:iid>/reminders")
    @auth("admin", perm="fees")
    def remind_log(iid):
        d = body()
        inv = get_invoice(iid)
        if not inv: return err("Invoice not found", 404)
        if d.get("channel") not in ("whatsapp", "viber"): return err("Channel must be whatsapp or viber")
        if d.get("to", "student") not in ("student", "guardian"): return err("Send to the student or the guardian")
        if inv["status"] not in OPEN or inv["balance"] <= 0: return err("This invoice has nothing outstanding", 409)
        cur = db().execute("INSERT INTO reminders(invoice_id,channel,recipient,sent_by,sent_at) VALUES(?,?,?,?,?)", (iid, d["channel"], d.get("to", "student"), g.user["id"], stamp()))
        audit_c("reminder_sent", "invoice", iid, f"{d['channel']} to {d.get('to', 'student')}"); db().commit()
        return jsonify(id=cur.lastrowid), 201

    def send_mail(to, subject, text):
        cf = app.config
        m = EmailMessage()
        m["From"], m["To"], m["Subject"] = cf["SMTP_FROM"], to, subject
        m.set_content(text)
        with smtplib.SMTP(cf["SMTP_HOST"], int(cf["SMTP_PORT"]), timeout=15) as s:
            if str(cf["SMTP_STARTTLS"]) not in ("0", "false", "False", ""): s.starttls()
            if cf.get("SMTP_USER"): s.login(cf["SMTP_USER"], cf["SMTP_PASSWORD"])
            s.send_message(m)

    @app.post("/api/invoices/<int:iid>/reminders/email")
    @auth("admin", perm="fees")
    def remind_email(iid):
        inv = get_invoice(iid)
        if not inv: return err("Invoice not found", 404)
        if not email_enabled():   # never pretend: nothing is sent and nothing is recorded
            return jsonify(error="Email sending is turned off. Use the WhatsApp or Viber links, or ask the administrator to set it up.", email_enabled=False), 409
        if inv["status"] not in OPEN or inv["balance"] <= 0: return err("This invoice has nothing outstanding", 409)
        text, _ = reminder_info(inv)
        try: send_mail(inv["student_email"], "Fee reminder - " + setting("academy_name", "Baleegh Academy"), text)
        except (smtplib.SMTPException, OSError) as x:
            return err("The email could not be sent: " + str(x)[:120], 502)
        db().execute("INSERT INTO reminders(invoice_id,channel,recipient,sent_by,sent_at) VALUES(?,'email','student',?,?)", (iid, g.user["id"], stamp()))
        audit_c("reminder_sent", "invoice", iid, "email to student"); db().commit()
        return jsonify(ok=True), 201

    # ---------- monthly report, dashboard ----------
    def report(month):
        t = today()
        invs = [shape(r, t) for r in rows(INV_SQL + " WHERE i.period=? AND i.status!='void' ORDER BY COALESCE(u.full_name, i.customer_name), i.id", (month,))]
        tot = {"invoiced": sum(i["amount_due_mvr"] - i["waived_mvr"] for i in invs), "collected": sum(i["paid_mvr"] for i in invs),
               "outstanding": sum(i["balance"] for i in invs), "overdue_count": sum(1 for i in invs if i["overdue"]), "invoice_count": len(invs),
               "waived": sum(i["waived_mvr"] for i in invs), "discounts": sum(i["discount_mvr"] for i in invs)}
        per = {}
        for i in invs:
            p = per.setdefault(i["course_id"], {"course_id": i["course_id"], "course_name": i["course_name"] or "Other (no course)", "invoiced": 0, "collected": 0, "outstanding": 0, "invoices": 0})
            p["invoiced"] += i["amount_due_mvr"] - i["waived_mvr"]; p["collected"] += i["paid_mvr"]; p["outstanding"] += i["balance"]; p["invoices"] += 1
        by_type = {}   # v0.8.46
        for i in invs:
            p = by_type.setdefault(i["revenue_type"], {"revenue_type": i["revenue_type"], "revenue_type_name": i["revenue_type_name"] or "-", "invoiced": 0, "collected": 0, "outstanding": 0, "invoices": 0})
            p["invoiced"] += i["amount_due_mvr"] - i["waived_mvr"]; p["collected"] += i["paid_mvr"]; p["outstanding"] += i["balance"]; p["invoices"] += 1
        owing = [{k: i[k] for k in ("id", "number", "student_id", "student_name", "course_name", "batch_code", "balance", "due_date", "overdue", "days_overdue", "status",
                                    "description", "revenue_type_name", "walk_in")} for i in invs if i["balance"] > 0]
        return {"month": month, "totals": tot, "by_course": list(per.values()), "by_type": sorted(by_type.values(), key=lambda x: -x["invoiced"]), "owing": owing, "invoices": invs}

    @app.get("/api/fees/report")
    @auth("admin", perm="fees")
    def fees_report():
        month = request.args.get("month") or month_of(today())
        if not PERIOD.match(month): return err("Month must look like 2026-03")
        r = report(month)
        r.pop("invoices")
        return jsonify(r)

    def fees_report_export(ext):
        import excelio
        month = request.args.get("month") or month_of(today())
        if not PERIOD.match(month): return err("Month must look like 2026-03")
        head = ["invoice", "period", "student", "course", "batch", "fee_mvr", "discount_mvr", "amount_due_mvr", "waived_mvr", "paid_mvr", "balance_mvr", "due_date", "status", "overdue", "revenue_type", "description"]   # v0.8.46: the last two
        table = [[i["number"], i["period"], i["student_name"], i["course_name"] or "", i["batch_code"] or "", i["amount_mvr"], i["discount_mvr"], i["amount_due_mvr"],
                  i["waived_mvr"], i["paid_mvr"], i["balance"], i["due_date"], i["status"], "yes" if i["overdue"] else "no", i["revenue_type_name"] or "", i["description"]] for i in report(month)["invoices"]]
        audit_c(f"export_fees_{ext}", "report", None, month); db().commit()
        return excelio.send_table(ext, f"fees-{month}", head, table, f"Fees {month}")

    @app.get("/api/fees/report.csv")
    @auth("admin", perm="fees")
    def fees_report_csv(): return fees_report_export("csv")

    @app.get("/api/fees/report.xlsx")
    @auth("admin", perm="fees")
    def fees_report_xlsx(): return fees_report_export("xlsx")   # v0.8.38

    def dashboard_extra():
        t = today()
        first = t.replace(day=1)
        r = one("SELECT (SELECT COUNT(*) FROM invoices WHERE status IN ('unpaid','slip_submitted') AND amount_due_mvr-waived_mvr-paid_mvr>0) AS unpaid_invoices,"
                " (SELECT COUNT(*) FROM invoices WHERE status IN ('unpaid','slip_submitted') AND amount_due_mvr-waived_mvr-paid_mvr>0 AND due_date<?) AS overdue_invoices,"
                " (SELECT COUNT(*) FROM payment_slips WHERE status='pending') AS slips_pending,"
                " (SELECT COALESCE(SUM(p.amount_mvr),0) FROM payments p JOIN invoices iv ON iv.id=p.invoice_id WHERE p.reversed_at IS NULL AND iv.status<>'void' AND p.paid_on>=? AND p.paid_on<?) AS month_collection_mvr",
                (t.isoformat(), first.isoformat(), next_month_start(month_of(t)).isoformat()))
        return {k: r[k] for k in ("unpaid_invoices", "overdue_invoices", "slips_pending", "month_collection_mvr")}

    app.extensions["fees"] = {"first_invoice": first_invoice, "first_invoice_result": first_invoice_result, "catch_up": catch_up, "back_bill": back_bill, "on_transfer": on_transfer, "generate": generate, "dashboard": dashboard_extra,
                              "validate_setting": validate_setting, "today": today, "month_of": month_of, "parse_period": parse_period}
