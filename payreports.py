"""Session 26: payment reports.

Admin only, area "fees" (a limited admin without it gets 403, students and teachers too).

  GET /api/fees/payment-report        ?month=YYYY-MM&course_id=&batch_id=&kind=course|tuition&status=paid|unpaid|partial|waived|none
                                      -> {month, filters, totals, rows}
  GET /api/fees/payment-report.csv    same filters, CSV download
  GET /api/fees/payment-report.xlsx   same filters, Excel download
  GET /api/fees/student-history/<id>  every invoice of one student with its payments (all months) -> {student, totals, invoices}

One row per student per batch. Who is listed: students with an active enrolment in the batch, plus anyone (dropped, completed,
transferred) who has a non-void invoice for that month, so the report always adds up to the invoices. Money is read from
the invoices and from payments with reversed_at IS NULL (the same rules as payments.balance and the Session 24 revenue).
Status: Paid (nothing left to pay), Partially Paid (some paid, balance left), Unpaid (nothing paid, balance left),
Waived (the whole amount was waived or discounted away), No invoice (enrolled but nothing billed that month; fee shown from the course).

to_xlsx(rows, headers) is the ONE Excel helper for the project; later sessions import it from here.
"""
import csv, datetime as dt, io, re
from flask import Response, jsonify, request

import payments as pay
from fees import inv_no

PERIOD = re.compile(r"^(20\d\d)-(0[1-9]|1[0-2])$")
STATUS_KEYS = {"paid": "Paid", "partial": "Partially Paid", "unpaid": "Unpaid", "waived": "Waived", "none": "No invoice"}
HEADERS = ["Student ID", "Student", "Course", "Type", "Batch", "Month", "Monthly fee (MVR)", "Amount due (MVR)", "Paid (MVR)",
           "Balance (MVR)", "Status", "Invoice", "Payment dates", "Last payment"]
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def csv_safe(v):
    """A text cell starting with = + - @ gets a leading apostrophe (spreadsheet formula injection)."""
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r") else ("" if v is None else v)


def to_xlsx(rows, headers, sheet="Report"):
    """rows: list of lists (or dicts keyed by header) -> bytes of an .xlsx file. Text is made formula-safe."""
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = (sheet or "Report")[:31]
    ws.append(list(headers))
    for r in rows:
        vals = [r.get(h) for h in headers] if isinstance(r, dict) else list(r)
        ws.append([csv_safe(v) for v in vals])
    for i, h in enumerate(headers, 1):
        width = max([len(str(h))] + [len(str((r.get(h) if isinstance(r, dict) else r[i - 1]) or "")) for r in rows[:200]])
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = min(max(width + 2, 10), 48)
    out = io.BytesIO(); wb.save(out)
    return out.getvalue()


def register(app, c, today):
    db, rows, one, err, auth, audit = c.db, c.rows, c.one, c.err, c.auth, c.audit
    AREA = "fees"

    def month_end(m):
        y, mo = int(m[:4]), int(m[5:])
        return (dt.date(y + (mo == 12), mo % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()

    def status_of(has_invoice, due, waived, paid, balance, inv_status):
        if not has_invoice: return "none"
        if inv_status == "waived" or (due - waived <= 0): return "waived"
        if balance <= 0: return "paid"
        return "partial" if paid > 0 else "unpaid"

    def build(args):
        """Returns (month, rows, totals). Raises ValueError with a message for a bad filter."""
        month = args.get("month") or today().isoformat()[:7]
        if not PERIOD.match(month): raise ValueError("Month must look like 2026-03")
        w, a = [], []
        for key, col in (("course_id", "c.id"), ("batch_id", "b.id")):
            if args.get(key):
                if not str(args[key]).isdigit(): raise ValueError(key.replace("_", " ").capitalize() + " must be a number")
                w.append(col + "=?"); a.append(int(args[key]))
        if args.get("kind"):
            if args["kind"] not in ("course", "tuition"): raise ValueError("kind must be course or tuition")
            w.append("c.kind=?"); a.append(args["kind"])
        want = args.get("status") or ""
        if want and want not in STATUS_KEYS: raise ValueError("status must be one of: " + ", ".join(STATUS_KEYS))
        # enrolments in scope: active ones enrolled by the end of the month, or any enrolment with a non-void invoice that month
        sql = ("SELECT e.id AS enrollment_id, e.status AS enrollment_status, e.enrol_code, u.id AS student_id, u.full_name, st.student_code, "
               "c.id AS course_id, c.name AS course_name, c.kind, c.monthly_fee_mvr, b.id AS batch_id, b.code AS batch_code, "
               "i.id AS invoice_id, i.amount_mvr, i.amount_due_mvr, i.waived_mvr, i.status AS inv_status "
               "FROM enrollments e JOIN users u ON u.id=e.student_id LEFT JOIN students st ON st.user_id=u.id JOIN batches b ON b.id=e.batch_id JOIN courses c ON c.id=b.course_id "
               "LEFT JOIN invoices i ON i.enrollment_id=e.id AND i.period=? AND i.status!='void' "
               "WHERE (i.id IS NOT NULL OR (e.status='active' AND SUBSTR(e.enrolled_at,1,10)<=?))"
               + ("".join(" AND " + x for x in w)) + " ORDER BY c.name, b.code, u.full_name, e.id")
        out, tot = [], {"students": 0, "fee": 0, "due": 0, "paid": 0, "balance": 0, "invoice_count": 0,
                        "paid_count": 0, "partial_count": 0, "unpaid_count": 0, "waived_count": 0, "none_count": 0}
        for r in rows(sql, (month, month_end(month), *a)):
            pays = []
            if r["invoice_id"]:
                pays = rows("SELECT amount_mvr, paid_on, method, receipt_no FROM payments WHERE invoice_id=? AND reversed_at IS NULL ORDER BY paid_on, id", (r["invoice_id"],))
            paid = sum(p["amount_mvr"] for p in pays)
            has = bool(r["invoice_id"])
            due = r["amount_due_mvr"] if has else 0          # nothing billed: the fee is shown, but nothing is owed yet
            waived = r["waived_mvr"] if has else 0
            balance = pay.Payments.balance({"status": r["inv_status"], "amount_due_mvr": r["amount_due_mvr"], "waived_mvr": r["waived_mvr"], "paid_mvr": paid}) if has else 0
            st = status_of(has, due, waived, paid, balance, r["inv_status"])
            if want and st != want: continue
            row = {"student_id": r["student_id"], "student_code": r["student_code"], "student_name": r["full_name"], "course_id": r["course_id"],
                   "course_name": r["course_name"], "kind": r["kind"], "batch_id": r["batch_id"], "batch_code": r["batch_code"], "month": month,
                   "monthly_fee_mvr": r["amount_mvr"] if has else r["monthly_fee_mvr"], "amount_due_mvr": due, "waived_mvr": waived,
                   "paid_mvr": paid, "balance_mvr": balance, "status": st, "status_label": STATUS_KEYS[st], "invoice_id": r["invoice_id"],
                   "invoice_no": None, "enrollment_status": r["enrollment_status"],
                   "payments": [{"paid_on": p["paid_on"], "amount_mvr": p["amount_mvr"], "method": p["method"], "receipt_no": p["receipt_no"]} for p in pays],
                   "last_payment": pays[-1]["paid_on"] if pays else None}
            if has: row["invoice_no"] = inv_no({"id": r["invoice_id"], "period": month})
            out.append(row)
            tot["students"] += 1; tot["fee"] += row["monthly_fee_mvr"]; tot["due"] += due - waived
            tot["paid"] += paid; tot["balance"] += balance; tot["invoice_count"] += 1 if has else 0
            tot[st + "_count"] += 1
        return month, out, tot

    def sheet(out):
        return [[r["student_code"] or "", r["student_name"], r["course_name"], "Tuition class" if r["kind"] == "tuition" else "Course", r["batch_code"],
                 r["month"], r["monthly_fee_mvr"], r["amount_due_mvr"], r["paid_mvr"], r["balance_mvr"], r["status_label"], r["invoice_no"] or "",
                 ", ".join(f"{p['paid_on']} ({p['amount_mvr']})" for p in r["payments"]), r["last_payment"] or ""] for r in out]

    def args_of():
        return {k: request.args.get(k, "") for k in ("month", "course_id", "batch_id", "kind", "status")}

    @app.get("/api/fees/payment-report")
    @auth("admin", perm=AREA)
    def payrep():
        try: month, out, tot = build(args_of())
        except ValueError as x: return err(str(x))
        return jsonify(month=month, filters={k: v for k, v in args_of().items() if v and k != "month"}, totals=tot, rows=out)

    def download(ext):
        try: month, out, tot = build(args_of())
        except ValueError as x: return err(str(x))
        if ext == "csv":
            buf = io.StringIO(); w = csv.writer(buf); w.writerow(HEADERS)
            for r in sheet(out): w.writerow([csv_safe(v) for v in r])
            body, mime = "\ufeff" + buf.getvalue(), "text/csv; charset=utf-8"   # v0.8.34: BOM for Excel
        else:
            body, mime = to_xlsx(sheet(out), HEADERS, "Payments " + month), XLSX_MIME
        audit("export_payment_report", "report", None, f"{ext} {month} {len(out)} rows"); db().commit()
        resp = Response(body, mimetype=mime)
        resp.headers["Content-Disposition"] = f'attachment; filename="payments-{month}.{ext}"'
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    @app.get("/api/fees/payment-report.csv")
    @auth("admin", perm=AREA)
    def payrep_csv(): return download("csv")

    @app.get("/api/fees/payment-report.xlsx")
    @auth("admin", perm=AREA)
    def payrep_xlsx(): return download("xlsx")

    @app.get("/api/fees/student-history/<int:sid>")
    @auth("admin", perm=AREA)
    def student_history(sid):
        s = one("SELECT u.id, u.full_name, st.student_code FROM users u LEFT JOIN students st ON st.user_id=u.id WHERE u.id=? AND u.role='student'", (sid,))
        if not s: return err("Student not found", 404)
        invs = rows("SELECT i.id, i.period, i.amount_mvr, i.discount_mvr, i.amount_due_mvr, i.waived_mvr, i.due_date, i.status, c.name AS course_name, c.kind, b.code AS batch_code "
                    "FROM invoices i LEFT JOIN courses c ON c.id=i.course_id LEFT JOIN batches b ON b.id=i.batch_id WHERE i.student_id=? ORDER BY i.period DESC, i.id DESC", (sid,))
        tot = {"due": 0, "paid": 0, "balance": 0}
        for i in invs:
            ps = rows("SELECT id, amount_mvr, paid_on, method, receipt_no, reversed_at FROM payments WHERE invoice_id=? ORDER BY paid_on, id", (i["id"],))
            i["payments"] = ps
            i["paid_mvr"] = sum(p["amount_mvr"] for p in ps if not p["reversed_at"])
            i["balance_mvr"] = pay.Payments.balance({"status": i["status"], "amount_due_mvr": i["amount_due_mvr"], "waived_mvr": i["waived_mvr"], "paid_mvr": i["paid_mvr"]})
            if i["status"] != "void":
                tot["due"] += i["amount_due_mvr"] - i["waived_mvr"]; tot["paid"] += i["paid_mvr"]; tot["balance"] += i["balance_mvr"]
        audit("view_payment_history", "user", sid, s["full_name"]); db().commit()
        return jsonify(student=s, totals=tot, invoices=invs)
