"""v0.8.64: the academy's Excel registry (Revenue Registry, Expense Registry, Monthly Report) and the portal, both ways.

Imports (Check file first: nothing is saved; then Import). The academy's own registry workbook can be uploaded as it is: the importer finds the
"Revenue Registry" / "Expense Registry" sheet and the row with the column names (the registry has a title row above it). The templates have the
same sheets and columns, so rows can be copied between the two.
  POST /api/import/revenue        Fees area      template: GET /api/import/revenue/template.xlsx
       ?unknown=refuse|walkin (a Student ID that is not in the portal: refuse the row (default) or record it under the name, "not in the portal")
       ?add_codes=1|0 (default 1: a Revenue Code the portal does not know yet becomes a new revenue type named after the Payment Type)
  POST /api/import/expenses       Finance area   template: GET /api/import/expenses/template.xlsx
       ?add_codes=1|0 (default 1: an Expense Code the portal does not know yet becomes a new category named after the Expense Type)
       The v0.8.38 template (expense_date, amount_mvr, category, description) is still accepted.

What a revenue row does (each row goes through the screen's own route, so it gets the same checks and the same activity-log line):
  1. The same payment is already in the portal (same person, day, amount and revenue type): skipped, so the same file can be imported twice.
  2. Monthly fee (or registration fee) of a student whose invoice for that fee month (course) is open: the payment is recorded on that invoice
     (Fees -> Record payment). Already paid in the portal before this import: skipped. Paid by an earlier row of the same file: refused, with
     a request to write the Fee Month (the registry has no fee-month column; the payment date's month is used).
  3. Anything else: a new invoice, already paid (Fees -> New invoice with "Already paid").

Reports (Finance area):
  GET /api/finance/income-statement            ?year=2026 (default this year) -> the registry's Monthly Report: revenue by revenue code, fees
                                               invoiced but not paid (accrued) by batch, expenses by code, capital spending apart, profit.
  GET /api/finance/income-statement.xlsx|.pdf  the same; the .xlsx has the Monthly Report's layout with live SUM formulas.
  GET /api/finance/registry.xlsx               ?year= the whole registry workbook made from the portal: Revenue Registry (every payment),
                                               Expense Registry (every expense), Monthly Report, and one payment-history sheet per batch.
"""
import datetime as dt, io, re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from flask import g, jsonify, request
import excelio as X

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS_LONG = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]
EMPTY = ("", "-", "--", "—", "n/a", "na", "none", "nil")

# the registry's columns -> the importer's keys (headers are compared in lower case with anything but letters, digits and $ removed)
REV_HEAD = {"no": "no", "sno": "no", "date": "date", "paymentdate": "date", "datepaid": "date", "paidon": "date", "studentid": "student_id",
            "studentcode": "student_id", "id": "student_id", "name": "name", "studentname": "name", "student": "name", "course": "course",
            "batch": "course", "coursebatch": "course", "revenuecode": "revenue_code", "code": "revenue_code", "paymenttype": "payment_type",
            "revenuetype": "payment_type", "type": "payment_type", "gst": "gst", "gstmvr": "gst", "discount": "discount", "amountdue": "amount_due",
            "totalpaid": "total_paid", "amountpaid": "total_paid", "paid": "total_paid", "invoiceno": "invoice_no", "invoicenumber": "invoice_no",
            "invoice": "invoice_no", "feemonth": "fee_month", "month": "fee_month", "formonth": "fee_month", "method": "method",
            "paymentmethod": "method", "reference": "reference", "ref": "reference", "note": "note", "notes": "note", "comments": "note"}
EXP_HEAD = {"no": "no", "sno": "no", "date": "date", "expensedate": "date", "gstno": "gst_no", "gstnumber": "gst_no", "tin": "gst_no",
            "name": "name", "supplier": "name", "paidto": "name", "vendor": "name", "invoiceno": "invoice_no", "invoicenumber": "invoice_no",
            "invoice": "invoice_no", "expensecode": "expense_code", "code": "expense_code", "expensetype": "expense_type", "type": "expense_type",
            "category": "expense_type", "mvr": "mvr", "amountmvr": "mvr", "gst": "gst", "gstmvr": "gst", "discount": "discount",
            "amountdue": "amount_due", "$": "usd", "usd": "usd", "us$": "usd", "amountusd": "usd", "rate": "rate", "usdrate": "rate",
            "total": "total", "totalmvr": "total", "description": "description", "details": "description", "note": "description"}


def canon(h):
    return re.sub(r"[^a-z0-9$]+", "", str(h or "").lower().replace("us dollar", "usd"))


def header_reader(table, needs):
    """A header(cells) function for excelio.read_table: the row is the header when every key set in one of `needs` is present."""
    def header(cells):
        keys = [table.get(canon(c), "") if str(c or "").strip() else "" for c in cells]
        seen, out = set(), []
        for k in keys:   # a column name used twice keeps the first one
            out.append(k if k and k not in seen else ""); seen.add(k)
        return out if any(all(k in out for k in need) for need in needs) else None
    return header


def blank(v):
    return str(v if v is not None else "").strip().lower() in EMPTY


def number(v, what):
    """A money cell -> Decimal or None. '-' and empty are None. 1,944.50 and 'MVR 350' are read."""
    if blank(v): return None
    t = re.sub(r"(?i)\b(mvr|rf|usd|us\$)\b|[,\s$]", "", str(v))
    try: d = Decimal(t)
    except InvalidOperation: raise ValueError(f"{what} must be a number (it is {str(v)[:20]})")
    if d < 0: raise ValueError(f"{what} cannot be below 0")
    return d


def whole(d):
    return int(d.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def a_date(v, what="Date"):
    """2026-04-02 (Excel dates arrive like this), 02/04/2026 or 2/4/26 (day first, as in the Maldives), 2 Apr 2026."""
    t = str(v or "").strip()
    if not t: raise ValueError(f"{what} is missing")
    t = t[:10] if re.match(r"^\d{4}-\d\d-\d\d", t) else t
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%b %d %Y", "%B %d %Y"):
        try: return dt.datetime.strptime(t.replace(",", ""), f).date()
        except ValueError: pass
    raise ValueError(f"{what} is not a date (write it like 2026-04-02)")


def a_month(v):
    """Fee Month: 2026-05, May 2026, 2026-05-01, 05/2026 -> 'YYYY-MM' or None."""
    t = str(v or "").strip()
    if blank(t): return None
    m = re.match(r"^(\d{4})-(\d{1,2})", t)
    if m: y, mo = int(m.group(1)), int(m.group(2))
    else:
        m = re.match(r"^(\d{1,2})[/.-](\d{4})$", t)
        if m: mo, y = int(m.group(1)), int(m.group(2))
        else:
            m = re.match(r"^([A-Za-z]+)\.?\s+(\d{4})$", t)
            if not m: raise ValueError(f"Fee Month must look like 2026-05 or May 2026 (it is {t[:20]})")
            name = m.group(1)[:3].lower()
            if name not in [x.lower() for x in MONTHS]: raise ValueError(f"Fee Month: {m.group(1)} is not a month")
            mo, y = [x.lower() for x in MONTHS].index(name) + 1, int(m.group(2))
    if not (1 <= mo <= 12 and 2000 <= y <= 2100): raise ValueError(f"Fee Month {t[:20]} is not a real month")
    return f"{y:04d}-{mo:02d}"


def month_label(p):
    return f"{MONTHS_LONG[int(p[5:7]) - 1]} {p[:4]}" if p and re.match(r"^\d{4}-\d\d$", p) else (p or "")


def fuzzy_code(code):
    """Student IDs typed with the letter I or O for the digit 1 or 0 (BAL/ALI/0NN for BAL/AL1/0NN): compared with these swapped."""
    return re.sub(r"\s+", "", (code or "").upper()).replace("I", "1").replace("O", "0").replace("L1", "L1")


def squash(t):
    return re.sub(r"[^A-Z0-9]+", "", str(t or "").upper())


def register(app, c, today):
    db, rows, one, err, auth, audit = c.db, c.rows, c.one, c.err, c.auth, c.audit
    imp = app.extensions["imports"]

    def flag(name, default="1"):
        return request.args.get(name, default).lower() not in ("0", "false", "no", "off")

    def usd_rate():
        try:
            r = float((c.raw_setting("usd_rate") or "").strip() or "15.42")
            return r if 1 <= r <= 100 else 15.42
        except ValueError: return 15.42

    def call_ok(method, path, body):
        code, res = X.call(method, path, json=body)
        if code >= 400: raise ValueError(res.get("error") or f"Refused ({code})")
        return res

    # ======================= revenue =======================
    def students_index():
        st = rows("SELECT u.id, u.full_name, s.student_code FROM users u JOIN students s ON s.user_id=u.id WHERE u.role='student'")
        by_code = {squash(x["student_code"]): x for x in st if x["student_code"]}
        fuzzy = {}
        for x in st:
            if x["student_code"]: fuzzy.setdefault(fuzzy_code(x["student_code"]), []).append(x)
        names = {}
        for x in st: names.setdefault(" ".join((x["full_name"] or "").lower().split()), []).append(x)
        return by_code, fuzzy, names

    def find_student(idx, code, name):
        """-> (student row or None, note or None)."""
        by_code, fuzzy, names = idx
        code = (code or "").strip()
        if code and not blank(code):
            s = by_code.get(squash(code))
            if s: return s, None
            f = fuzzy.get(fuzzy_code(code), [])
            if len(f) == 1: return f[0], f"Student ID {code} read as {f[0]['student_code']} ({f[0]['full_name']})"
        n = " ".join((name or "").lower().split())
        hit = names.get(n, []) if n else []
        if len(hit) == 1: return hit[0], (f"No student with ID {code}; matched by name to {hit[0]['student_code'] or hit[0]['full_name']}" if code and not blank(code) else None)
        return None, None

    def enrolments_of(sid):
        return rows("SELECT e.id, e.status, b.id AS batch_id, b.code AS batch_code, c.id AS course_id, c.code AS course_code, c.name AS course_name "
                    "FROM enrollments e JOIN batches b ON b.id=e.batch_id JOIN courses c ON c.id=b.course_id WHERE e.student_id=? ORDER BY e.id", (sid,))

    def match_batch(ens, text):
        """The registry's Course cell (e.g. "Arabic - L1001") -> one of the student's batches, or None."""
        t = squash(text)
        if t:
            for e in ens:
                keys = {squash(e["batch_code"]), squash((e["course_code"] or "") + (e["batch_code"] or "")), squash(e["course_name"] + (e["batch_code"] or ""))}
                if t in keys: return e
            ends = [e for e in ens if e["batch_code"] and len(squash(e["batch_code"])) >= 2 and t.endswith(squash(e["batch_code"]))]
            if len(ends) == 1: return ends[0]
            byc = [e for e in ens if (e["course_code"] and squash(e["course_code"]) == t) or squash(e["course_name"]) == t]
            if len(byc) == 1: return byc[0]
        return ens[0] if len(ens) == 1 else None

    def revenue_types():
        return rows("SELECT id, name, code, ledger_code, is_active FROM revenue_types ORDER BY id")

    def find_type(code, ptype, add):
        """-> (revenue type row, note). Matches the Revenue Code, then the Payment Type's name. add=True creates a missing code."""
        ts = revenue_types()
        code = "" if blank(code) else str(code).strip()
        if code.endswith(".0"): code = code[:-2]
        if code:
            for t in ts:
                if t["ledger_code"] and t["ledger_code"].upper() == code.upper(): return t, None
        p = " ".join(str(ptype or "").lower().split())
        if p and not blank(p):
            for t in ts:
                n = t["name"].lower()
                if n == p or n.rstrip("s") == p.rstrip("s") or (t["code"] and (t["code"] in p or p in t["code"])): return t, None
        if code and add and p and not blank(p):
            name = " ".join(str(ptype).split())[:60]
            if any(t["name"].lower() == name.lower() for t in ts): name = f"{name} ({code})"
            res = call_ok("POST", "/api/revenue-types", {"name": name, "ledger_code": code})
            return one("SELECT id, name, code, ledger_code, is_active FROM revenue_types WHERE id=?", (res["id"],)), f"new revenue type {code} {name}"
        if code: raise ValueError(f"No revenue type has the code {code}. Give one that code in Fees > New invoice > Revenue types, or tick 'Add new codes'")
        if p and not blank(p): raise ValueError(f"No revenue type called {' '.join(str(ptype).split())}. Add it in Fees > New invoice > Revenue types, or write its Revenue Code")
        raise ValueError("Revenue Code and Payment Type are both empty")

    METHODS = {"cash": "cash", "bank": "bank_transfer", "banktransfer": "bank_transfer", "transfer": "bank_transfer", "bml": "bank_transfer",
               "mib": "bank_transfer", "online": "bank_transfer", "other": "other", "card": "other", "cheque": "other"}

    def revenue_reader():
        return X.read_table(sheets=("Revenue Registry", "Revenue", "Data"),
                            header=header_reader(REV_HEAD, [("date", "total_paid", "student_id"), ("date", "total_paid", "name")]))

    def revenue_run():
        idx = students_index()
        start = int(one("SELECT COALESCE(MAX(id),0) n FROM payments")["n"])   # payments of earlier imports; later ids are this file's own rows
        walkin, add = request.args.get("unknown", "refuse") == "walkin", flag("add_codes")

        def row(r):
            if blank(r.get("date")) and blank(r.get("student_id")) and blank(r.get("name")):
                return ("skip", "no date, student or name (an empty or totals row)")   # the registry's numbered empty rows and its SUM row
            notes = []
            day = a_date(r.get("date"), "Date")
            if day > today(): raise ValueError("The date is in the future")
            paid = number(r.get("total_paid"), "Total Paid")
            if not paid: raise ValueError("Total Paid is empty or 0")
            amt = whole(paid)
            if Decimal(amt) != paid: notes.append(f"MVR {paid} rounded to {amt}")
            due = number(r.get("amount_due"), "Amount Due")
            disc = number(r.get("discount"), "Discount")
            gst = number(r.get("gst"), "GST")
            rt, n_ = find_type(r.get("revenue_code"), r.get("payment_type"), add)
            if n_: notes.append(n_)
            who_name = " ".join(str(r.get("name") or "").split())
            if blank(r.get("student_id")) and who_name and one("SELECT 1 x FROM invoices WHERE student_id IS NULL AND LOWER(customer_name)=LOWER(?)", (who_name,)):
                st, n_ = None, None   # no ID, and a customer by that name is already recorded as not in the portal: that customer, not a student
            else:
                st, n_ = find_student(idx, r.get("student_id"), r.get("name"))
            if n_: notes.append(n_)
            if not st:
                sc = (r.get("student_id") or "").strip()
                if not walkin:
                    raise ValueError(f"No student {sc or who_name} in the portal. Add them in People first, or choose 'Record under their name' and check again")
                if not who_name: raise ValueError("No student in the portal and no Name to record it under")
                notes.append("recorded under the name (not in the portal)")
            fee_month = a_month(r.get("fee_month")) or day.isoformat()[:7]
            ref = None if blank(r.get("reference")) else str(r["reference"]).strip()[:80]
            inv_no = None if blank(r.get("invoice_no")) else str(r["invoice_no"]).strip()[:40]
            method = METHODS.get(squash(r.get("method")).lower(), "bank_transfer") if not blank(r.get("method")) else "bank_transfer"
            note = "Revenue registry" + (f" {inv_no}" if inv_no else "") + (f"; GST {gst}" if gst else "") + (f"; {str(r.get('note')).strip()[:120]}" if not blank(r.get("note")) else "")
            rtj = "COALESCE(i.revenue_type_id, (SELECT r2.id FROM revenue_types r2 WHERE r2.code=i.kind))"
            # 1. already in the portal: the same payment
            who_sql, who_arg = ("i.student_id=?", st["id"]) if st else ("i.student_id IS NULL AND LOWER(i.customer_name)=LOWER(?)", who_name)
            dup = one(f"SELECT p.receipt_no FROM payments p JOIN invoices i ON i.id=p.invoice_id WHERE {who_sql} AND p.paid_on=? AND p.amount_mvr=? "
                      f"AND p.reversed_at IS NULL AND {rtj}=? AND p.id<=? ORDER BY p.id LIMIT 1", (who_arg, day.isoformat(), amt, rt["id"], start))
            if dup: return ("skip", f"already in the portal (receipt {dup['receipt_no']})")
            batch = None
            if st:
                ens = enrolments_of(st["id"])
                batch = match_batch(ens, r.get("course"))
                if not batch and len(ens) > 1 and rt["code"] == "monthly":
                    raise ValueError(f"{st['full_name']} is in {len(ens)} batches ({', '.join(e['course_name'] + ' ' + e['batch_code'] for e in ens)}). "
                                     "Write the batch in the Course column (as in the Lists sheet)")
            # 2. the student's own open invoice for that fee month (monthly) or course (registration)
            if st and rt["code"] in ("monthly", "registration"):
                w, a = [f"i.student_id=?", "i.status<>'void'", f"{rtj}=?"], [st["id"], rt["id"]]
                if rt["code"] == "monthly":
                    w.append("i.period=?"); a.append(fee_month)
                    if batch: w.append("(i.batch_id=? OR i.batch_id IS NULL)"); a.append(batch["batch_id"])
                elif batch: w.append("(i.course_id=? OR i.course_id IS NULL)"); a.append(batch["course_id"])
                invs = rows("SELECT i.id, i.period, i.status, i.amount_due_mvr-i.waived_mvr-i.paid_mvr AS balance, "
                            "(SELECT MAX(p.id) FROM payments p WHERE p.invoice_id=i.id AND p.reversed_at IS NULL) AS last_pay, "
                            "(SELECT p.receipt_no FROM payments p WHERE p.invoice_id=i.id AND p.reversed_at IS NULL ORDER BY p.id DESC LIMIT 1) AS receipt "
                            "FROM invoices i WHERE " + " AND ".join(w) + " ORDER BY i.id", tuple(a))
                what = month_label(fee_month) if rt["code"] == "monthly" else "The registration fee" + (f" for {batch['course_name']}" if batch else "")
                open_ = [x for x in invs if x["status"] in ("unpaid", "slip_submitted") and x["balance"] > 0]
                if open_:
                    i = open_[0]
                    if amt > i["balance"]:
                        raise ValueError(f"Total Paid {amt} is more than the MVR {i['balance']} still to pay on the portal's invoice for {what}. "
                                         "Check the amount, or write the right Fee Month")
                    no = f"INV-{(i['period'] or '').replace('-', '')}-{i['id']:04d}"
                    return ("POST", "/api/payments", {"invoice_id": i["id"], "amount_mvr": amt, "method": method, "paid_on": day.isoformat(),
                                                      "reference": ref or inv_no, "note": note}, "; ".join([f"paid the portal's invoice {no}"] + notes))
                done = [x for x in invs if x["status"] == "paid" or (x["status"] == "waived")]
                if done:
                    x = done[0]
                    if x["status"] == "waived": return ("skip", f"{what} is waived in the portal")
                    if (x["last_pay"] or 0) <= start: return ("skip", f"{what} is already paid in the portal (receipt {x['receipt'] or '-'})")
                    if rt["code"] == "monthly":
                        raise ValueError(f"{what} was already paid by an earlier row of this file. If this payment is for another month, "
                                         "write that month in the Fee Month column (like 2026-07)")
                    raise ValueError(f"{what} was already paid by an earlier row of this file. A second registration fee for the same course "
                                     "looks like a mistake in the registry; if it is something else, give it another Revenue Code")
            # 3. a new invoice, already paid
            invoice_amt = amt
            if due is not None and whole(due) > amt: invoice_amt = whole(due)
            label = " ".join(str(r.get("payment_type") or "").split()) or rt["name"]
            if blank(label): label = rt["name"]
            desc = label + (f" · {batch['course_name']} {batch['batch_code']}" if batch else (f" · {' '.join(str(r.get('course')).split())}" if not blank(r.get("course")) else "")) \
                + (f" · {month_label(fee_month)}" if rt["code"] == "monthly" else "") + (f" · discount {disc}" if disc else "")
            body = {"revenue_type_id": rt["id"], "amount_mvr": invoice_amt, "description": desc[:200], "invoice_date": fee_month + "-01" if rt["code"] == "monthly" else day.isoformat(),
                    "paid": "1", "paid_amount_mvr": amt, "method": method, "paid_on": day.isoformat(), "reference": ref or inv_no or "", "note": note}
            if st:
                body["student_id"] = st["id"]
                if batch: body["batch_id"] = batch["batch_id"]
            else: body["customer_name"] = who_name[:100]
            if invoice_amt > amt: notes.append(f"MVR {invoice_amt - amt} left to pay")
            return ("POST", "/api/invoices/manual", body, "; ".join(["new invoice, paid"] + notes))
        return imp["run"]("revenue", ["date", "total_paid"], row, reader=revenue_reader)

    def revenue_template():
        from openpyxl import Workbook
        from openpyxl.comments import Comment
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.worksheet.datavalidation import DataValidation
        from openpyxl.utils import get_column_letter as L
        st = rows("SELECT s.student_code, u.full_name FROM users u JOIN students s ON s.user_id=u.id WHERE u.role='student' AND s.student_code IS NOT NULL ORDER BY s.student_code")
        bs = rows("SELECT c.code AS cc, c.name AS cn, b.code AS bc FROM batches b JOIN courses c ON c.id=b.course_id ORDER BY c.name, b.code")
        ts = [t for t in revenue_types() if t["is_active"]]
        cols = [("No", "Your own row number (optional; not used).", 6, False), ("Date", "The day the money was received, like 2026-04-02.", 12, True),
                ("Student ID", "The student's ID in the portal, like BAL/AL1/0NN (see Lists).", 15, True), ("Name", "The student's or customer's name.", 26, False),
                ("Course", "The batch, as in the Lists sheet. Needed for monthly fees when the student is in more than one batch.", 18, False),
                ("Revenue Code", "1001 registration, 1002 monthly fee, ... (see Lists).", 9, True), ("Payment Type", "Registration Fee, Monthly Fee, ...", 18, False),
                ("GST %", "GST, if any (kept as a note).", 8, False), ("Discount", "Discount given, in MVR (kept in the description).", 9, False),
                ("Amount Due", "Leave empty or '-' when it equals Total Paid. More than Total Paid: the rest stays to pay.", 10, False),
                ("Total Paid", "MVR received.", 10, True), ("Invoice No.", "Your registry invoice number, like INV2026/001 (kept as the payment reference).", 14, False),
                ("Fee Month", "Optional: the month the fee is for, like 2026-05. Empty = the month of Date.", 11, False),
                ("Method", "bank, cash or other. Empty = bank transfer.", 10, False), ("Reference", "Optional: bank reference.", 14, False)]
        wb = Workbook(); ws = wb.active; ws.title = "Revenue Registry"
        ws["A1"] = "Revenue Registry (Invoices)"; ws["A1"].font = Font(bold=True, size=13)
        for i, (h, help_, w, req) in enumerate(cols, 1):
            cell = ws.cell(row=2, column=i, value=h)
            cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor=X.REQ_FILL if req else X.HEAD_FILL)
            cell.alignment = Alignment(vertical="center", wrap_text=True); cell.comment = Comment(("Required. " if req else "") + help_, "Baleegh Academy")
            ws.column_dimensions[L(i)].width = w
        ws.column_dimensions["B"].number_format = "yyyy-mm-dd"   # whole columns: the sheet stays empty (no formatted blank rows)
        for col in ("C", "L", "M"): ws.column_dimensions[col].number_format = "@"
        ws.freeze_panes = "A3"
        ls = wb.create_sheet("Lists")
        lists = [("Student ID", [x["student_code"] for x in st]), ("Student name", [x["full_name"] for x in st]),
                 ("Course (batch)", [f"{x['cc'] or x['cn']}/{x['bc']}" for x in bs]), ("Course name", [x["cn"] for x in bs]),
                 ("Revenue Code", [t["ledger_code"] or "" for t in ts]), ("Payment Type", [t["name"] for t in ts]), ("Method", ["bank", "cash", "other"])]
        for j, (name, vals) in enumerate(lists, 1):
            ls.cell(row=1, column=j, value=name).font = Font(bold=True)
            for k, v in enumerate(vals, 2): ls.cell(row=k, column=j, value=X.csv_safe(v))
            ls.column_dimensions[L(j)].width = max(14, min(40, max([len(name)] + [len(str(v)) for v in vals]) + 2))
        for colname, j, free in (("C", 1, True), ("E", 3, True), ("F", 5, True), ("G", 6, True), ("N", 7, True)):
            n = len(lists[j - 1][1])
            if not n: continue
            dv = DataValidation(type="list", formula1=f"Lists!${L(j)}$2:${L(j)}${n + 1}", allow_blank=True, showErrorMessage=not free)
            ws.add_data_validation(dv); dv.add(f"{colname}3:{colname}1002")
        ins = wb.create_sheet("Instructions")
        for line in ["Import into the portal: Revenue Registry", "",
                     "Fill in the Revenue Registry sheet from row 3, one payment per row, exactly as in the academy's registry. Red column names are required.",
                     "You can also upload the registry workbook itself: the portal reads its Revenue Registry sheet and ignores the other sheets.",
                     "In the portal: Fees > New invoice > Import the revenue registry > Check file (nothing is saved) > Import.",
                     "", "What happens to each row:",
                     "- The same payment already in the portal (same person, day, amount and type) is skipped, so a file can be imported again safely.",
                     "- A monthly fee or registration fee with an open invoice in the portal is recorded on that invoice.",
                     "- A month that is already paid in the portal is skipped.",
                     "- Anything else becomes a new invoice that is already paid, with a receipt number.",
                     "- A Student ID not in the portal is refused, unless you choose 'Record under their name'.",
                     "- A Revenue Code the portal does not know becomes a new revenue type named after the Payment Type (untick 'Add new codes' to refuse instead).",
                     "", "Columns:"] + [f"{h}{' (required)' if req else ''}: {help_}" for h, help_, _, req in cols]:
            ins.append([line])
        ins["A1"].font = Font(bold=True, size=14); ins.column_dimensions["A"].width = 130
        out = io.BytesIO(); wb.save(out)
        return out.getvalue()

    # ======================= expenses =======================
    def categories():
        return rows("SELECT id, name, code, kind, is_active FROM expense_categories ORDER BY id")

    def find_category(code, etype, add):
        ks = categories()
        code = "" if blank(code) else str(code).strip()
        if code.endswith(".0"): code = code[:-2]
        if code:
            for k in ks:
                if k["code"] and k["code"].upper() == code.upper(): return k, None
        p = " ".join(str(etype or "").lower().split())
        strip = lambda x: re.sub(r"\s*(expenses?|costs?)$", "", x).replace("-", "").replace(" ", "")
        if p and not blank(p):
            for k in ks:
                n = k["name"].lower()
                if n == p or strip(n) == strip(p): return k, None
        if code and add and p and not blank(p):
            name = " ".join(str(etype).split())[:60]
            capital = bool(re.search(r"cap\W*ex|capital|equipment|furniture|asset", p))
            res = call_ok("POST", "/api/expense-categories", {"name": name, "code": code, "kind": "capital" if capital else "operating"})
            return one("SELECT id, name, code, kind, is_active FROM expense_categories WHERE id=?", (res["id"],)), f"new category {code} {name}" + (" (capital)" if capital else "")
        if code: raise ValueError(f"No category has the code {code}. Give one that code in Finance > Categories, or tick 'Add new codes'")
        if p and not blank(p): raise ValueError(f"No category called {' '.join(str(etype).split())}. Add it in Finance > Categories, or write its Expense Code")
        raise ValueError("Expense Code and Expense Type are both empty")

    def expense_reader():
        return X.read_table(sheets=("Expense Registry", "Expenses", "Data"),
                            header=lambda cells: legacy_header(cells) or header_reader(EXP_HEAD, [("date", "expense_code"), ("date", "expense_type"), ("date", "total"), ("date", "mvr")])(cells))

    def legacy_header(cells):   # the v0.8.38 template still works
        keys = [X.norm_head(x) for x in cells]
        return keys if all(k in keys for k in ("expense_date", "amount_mvr", "category")) else None

    def expense_run():
        start = int(one("SELECT COALESCE(MAX(id),0) n FROM expenses")["n"])
        add, rate0 = flag("add_codes"), usd_rate()

        def row(r):
            if "expense_date" in r or "amount_mvr" in r:   # v0.8.38 template
                return imp["legacy_expense_row"](r)
            if blank(r.get("date")) and blank(r.get("name")): return ("skip", "no date or name (an empty or totals row)")
            notes = []
            day = a_date(r.get("date"), "Date")
            k, n_ = find_category(r.get("expense_code"), r.get("expense_type"), add)
            if n_: notes.append(n_)
            mvr, usd, total = number(r.get("mvr"), "MVR"), number(r.get("usd"), "$"), number(r.get("total"), "Total")
            disc, due, gst = number(r.get("discount"), "Discount"), number(r.get("amount_due"), "Amount Due"), number(r.get("gst"), "GST")
            rate = number(r.get("rate"), "Rate") or Decimal(str(rate0))
            if total is not None and total > 0: exact = total
            elif due is not None and due > 0: exact = due
            else: exact = (mvr or 0) + (usd or 0) * rate - (disc or 0)
            if exact <= 0: raise ValueError("No amount: fill in MVR, $ or Total")
            amt = whole(exact)
            if amt <= 0: raise ValueError(f"The amount {exact} is less than 1 MVR")
            if Decimal(amt) != exact: notes.append(f"MVR {exact.quantize(Decimal('0.01'))} rounded to {amt}")
            supplier = None if blank(r.get("name")) else " ".join(str(r["name"]).split())[:100]
            inv = None if blank(r.get("invoice_no")) else " ".join(str(r["invoice_no"]).split())[:60]
            if inv:
                dup = one("SELECT id FROM expenses WHERE LOWER(COALESCE(invoice_no,''))=LOWER(?) AND LOWER(COALESCE(supplier,''))=LOWER(?) AND id<=?", (inv, supplier or "", start))
            else:
                dup = one("SELECT id FROM expenses WHERE expense_date=? AND amount_mvr=? AND category_id=? AND LOWER(COALESCE(supplier,''))=LOWER(?) AND id<=?",
                          (day.isoformat(), amt, k["id"], supplier or "", start))
            if dup: return ("skip", "already in the portal")
            body = {"expense_date": day.isoformat(), "amount_mvr": amt, "category_id": k["id"],
                    "description": " ".join(str(r.get("description")).split())[:500] if not blank(r.get("description")) else (supplier or ""),
                    "supplier": supplier or "", "supplier_gst_no": "" if blank(r.get("gst_no")) else str(r["gst_no"]).strip()[:40], "invoice_no": inv or "",
                    "gst_mvr": str(gst) if gst else "", "usd_amount": str(usd) if usd else "", "fx_rate": str(rate) if usd else "", "amount_exact": str(exact.quantize(Decimal("0.0001")))}
            if usd: notes.append(f"USD {usd} x {rate}")
            return ("POST", "/api/expenses", body, "; ".join(notes))
        return imp["run"]("expenses", [], row, reader=expense_reader)

    def expense_template():
        from openpyxl import Workbook
        from openpyxl.comments import Comment
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.worksheet.datavalidation import DataValidation
        from openpyxl.utils import get_column_letter as L
        ks = [k for k in categories() if k["is_active"]]
        rate = usd_rate()
        cols = [("No", "Your own row number (optional).", 6, False), ("Date", "The day it was paid, like 2026-03-12 (not in the future).", 12, True),
                ("GST No.", "The supplier's GST number, if any.", 15, False), ("Name", "Who was paid (Meta ads, Google, the shop, the person).", 22, True),
                ("Invoice No.", "The supplier's invoice or bill number. Used to see that an expense is already in the portal.", 20, False),
                ("Expense Code", "5001 marketing, 5002 maintenance, ... (see Lists).", 9, True), ("Expense Type", "The category's name (see Lists).", 20, False),
                ("MVR", "The amount paid in MVR (with GST).", 10, False), ("GST %", "The GST in MVR, if any (information only).", 8, False),
                ("Discount", "Discount in MVR (taken off when Total is empty).", 9, False), ("Amount Due", "Leave empty or '-'.", 10, False),
                ("$", f"The amount paid in US dollars. Turned into MVR at {rate} (Settings > Fees > US dollar rate).", 8, False),
                ("Total", f"MVR in all. Empty = MVR + $ x {rate} - Discount. Amounts are rounded to whole MVR.", 11, False),
                ("Description", "Optional: what it was for. Empty = the Name.", 30, False)]
        wb = Workbook(); ws = wb.active; ws.title = "Expense Registry"
        ws["A1"] = "Invoice registry ( Expenses )"; ws["A1"].font = Font(bold=True, size=13)
        for i, (h, help_, w, req) in enumerate(cols, 1):
            cell = ws.cell(row=2, column=i, value=h)
            cell.font = Font(bold=True, color="FFFFFF"); cell.fill = PatternFill("solid", fgColor=X.REQ_FILL if req else X.HEAD_FILL)
            cell.alignment = Alignment(vertical="center", wrap_text=True); cell.comment = Comment(("Required. " if req else "") + help_, "Baleegh Academy")
            ws.column_dimensions[L(i)].width = w
        ws.column_dimensions["B"].number_format = "yyyy-mm-dd"
        for col in ("C", "E"): ws.column_dimensions[col].number_format = "@"
        ws.freeze_panes = "A3"
        ls = wb.create_sheet("Lists")
        lists = [("Expense Code", [k["code"] or "" for k in ks]), ("Expense Type", [k["name"] for k in ks]), ("Kind", [k["kind"] for k in ks])]
        for j, (name, vals) in enumerate(lists, 1):
            ls.cell(row=1, column=j, value=name).font = Font(bold=True)
            for kk, v in enumerate(vals, 2): ls.cell(row=kk, column=j, value=X.csv_safe(v))
            ls.column_dimensions[L(j)].width = max(14, min(40, max([len(name)] + [len(str(v)) for v in vals]) + 2))
        for colname, j in (("F", 1), ("G", 2)):
            if ks:
                dv = DataValidation(type="list", formula1=f"Lists!${L(j)}$2:${L(j)}${len(ks) + 1}", allow_blank=True, showErrorMessage=False)
                ws.add_data_validation(dv); dv.add(f"{colname}3:{colname}1002")
        ins = wb.create_sheet("Instructions")
        for line in ["Import into the portal: Expense Registry", "",
                     "Fill in the Expense Registry sheet from row 3, one expense per row, as in the academy's registry. Red column names are required.",
                     "You can also upload the registry workbook itself: the portal reads its Expense Registry sheet.",
                     "In the portal: Finance > Import expenses > Check file (nothing is saved) > Import.",
                     "", "What happens to each row:",
                     "- An expense already in the portal (same supplier and invoice number; or, without one, same day, amount, category and supplier) is skipped.",
                     f"- The amount is Total; when Total is empty, MVR + $ x {rate} - Discount. It is rounded to whole MVR; the exact amount is kept with the expense.",
                     "- An Expense Code the portal does not know becomes a new category named after the Expense Type. Cap-EX / capital types become capital spending,",
                     "  which the income statement shows apart from running expenses. Untick 'Add new codes' to refuse such rows instead.",
                     "- Receipts cannot be imported: attach them afterwards with Edit.", "", "Columns:"] + [f"{h}{' (required)' if req else ''}: {help_}" for h, help_, _, req in cols]:
            ins.append([line])
        ins["A1"].font = Font(bold=True, size=14); ins.column_dimensions["A"].width = 130
        out = io.BytesIO(); wb.save(out)
        return out.getvalue()

    @app.post("/api/import/revenue")
    @auth("admin", perm="fees")
    def reg_imp_revenue():
        return revenue_run()

    @app.get("/api/import/revenue/template.xlsx")
    @auth("admin", perm="fees")
    def reg_tpl_revenue():
        audit("download_template", "import", None, "revenue registry"); db().commit()
        return X.send_xlsx(revenue_template(), "revenue-registry-template")

    @app.post("/api/import/expenses")
    @auth("admin", perm="finance")
    def sh_imp_expenses():
        return expense_run()

    @app.get("/api/import/expenses/template.xlsx")
    @auth("admin", perm="finance")
    def sh_tpl_expenses():
        audit("download_template", "import", None, "expenses"); db().commit()
        return X.send_xlsx(expense_template(), "expense-registry-template")

    # ======================= income statement (the registry's Monthly Report) =======================
    RT_JOIN = " LEFT JOIN revenue_types rt ON rt.id=COALESCE(i.revenue_type_id, (SELECT r2.id FROM revenue_types r2 WHERE r2.code=i.kind))"

    def year_arg():
        y = request.args.get("year") or str(today().year)
        if not re.match(r"^20\d\d$", y): raise ValueError("Year must look like 2026")
        return int(y)

    def statement(year):
        t = today()
        last = 12 if year < t.year else t.month if year == t.year else 0
        months = [f"{year}-{m:02d}" for m in range(1, 13)]
        d1, d2 = f"{year}-01-01", f"{year}-12-31"
        rev = rows("SELECT rt.id AS type_id, rt.name, rt.ledger_code AS code, SUBSTR(p.paid_on,1,7) AS m, SUM(p.amount_mvr) AS s FROM payments p JOIN invoices i ON i.id=p.invoice_id"
                   + RT_JOIN + " WHERE p.reversed_at IS NULL AND i.status<>'void' AND p.paid_on BETWEEN ? AND ? GROUP BY rt.id, rt.name, rt.ledger_code, SUBSTR(p.paid_on,1,7)", (d1, d2))
        types = {}
        for r in rev:
            x = types.setdefault(r["type_id"], {"code": r["code"], "name": r["name"] or "Other", "months": {m: 0 for m in months}})
            x["months"][r["m"]] += int(r["s"])
        # every revenue type with a code shows, even with nothing yet (the registry lists 1001-1003 every year)
        for rt in rows("SELECT id, name, ledger_code FROM revenue_types WHERE ledger_code IS NOT NULL AND is_active=1"):
            types.setdefault(rt["id"], {"code": rt["ledger_code"], "name": rt["name"], "months": {m: 0 for m in months}})
        revenue = sorted(types.values(), key=lambda x: (x["code"] is None, x["code"] or "", x["name"]))
        # accrued: fees for a month of this year still to pay (invoices, not void, by fee month), by batch
        acc = rows("SELECT i.batch_id, COALESCE(c.name,'') AS course, COALESCE(b.code,'') AS batch, i.period AS m, "
                   "SUM(CASE WHEN i.amount_due_mvr-i.waived_mvr-i.paid_mvr>0 THEN i.amount_due_mvr-i.waived_mvr-i.paid_mvr ELSE 0 END) AS s "
                   "FROM invoices i LEFT JOIN batches b ON b.id=i.batch_id LEFT JOIN courses c ON c.id=i.course_id "
                   "WHERE i.status NOT IN ('void','waived') AND i.period BETWEEN ? AND ? GROUP BY i.batch_id, c.name, b.code, i.period", (months[0], months[-1]))
        batches = {}
        for r in acc:
            if not r["s"]: continue
            x = batches.setdefault(r["batch_id"], {"name": (f"{r['course']} {r['batch']}".strip() or "No batch"), "months": {m: 0 for m in months}})
            x["months"][r["m"]] += int(r["s"])
        accrued = sorted(batches.values(), key=lambda x: x["name"])
        ex = rows("SELECT k.id, k.name, k.code, k.kind, SUBSTR(e.expense_date,1,7) AS m, SUM(e.amount_mvr) AS s FROM expenses e JOIN expense_categories k ON k.id=e.category_id "
                  "WHERE e.expense_date BETWEEN ? AND ? GROUP BY k.id, k.name, k.code, k.kind, SUBSTR(e.expense_date,1,7)", (d1, d2))
        cats = {}
        for r in ex:
            x = cats.setdefault(r["id"], {"code": r["code"], "name": r["name"], "kind": r["kind"] or "operating", "months": {m: 0 for m in months}})
            x["months"][r["m"]] += int(r["s"])
        for k in rows("SELECT id, name, code, kind FROM expense_categories WHERE code IS NOT NULL AND is_active=1"):
            cats.setdefault(k["id"], {"code": k["code"], "name": k["name"], "kind": k["kind"] or "operating", "months": {m: 0 for m in months}})
        allx = sorted(cats.values(), key=lambda x: (x["code"] is None, x["code"] or "", x["name"]))
        sm = lambda items: {m: sum(x["months"][m] for x in items) for m in months}
        tot = lambda d: sum(d.values())
        for coll in (revenue, accrued, allx):
            for x in coll: x["total"] = tot(x["months"])
        R, A = sm(revenue), sm(accrued)
        OP, CAP = sm([x for x in allx if x["kind"] != "capital"]), sm([x for x in allx if x["kind"] == "capital"])
        pl = {"collected": R, "operating": OP, "capital": CAP,
              "profit": {m: R[m] - OP[m] for m in months},                      # the registry's "Actual Collected Profit"
              "if_all_paid": {m: R[m] + A[m] - OP[m] for m in months},          # the registry's "Budgeted Profit"
              "after_capital": {m: R[m] - OP[m] - CAP[m] for m in months}}
        return {"year": year, "months": months, "months_shown": last, "revenue": revenue, "accrued": accrued,
                "expenses": [x for x in allx if x["kind"] != "capital"], "capital": [x for x in allx if x["kind"] == "capital"],
                "totals": {"revenue": R, "accrued": A, "operating": OP, "capital": CAP}, "pl": pl,
                "year_totals": {k: tot(v) for k, v in pl.items()} | {"accrued": tot(A)},
                "note": "Revenue = payments received, in the month they were paid (reversed payments and voided invoices left out). "
                        "Accrued = fees for that month still to pay today. Capital spending (Cap-EX categories) is shown apart and is not part of the profit."}

    @app.get("/api/finance/income-statement")
    @auth("admin", perm="finance")
    def reg_statement():
        try: y = year_arg()
        except ValueError as x: return err(str(x))
        if "recurring" in app.extensions: app.extensions["recurring"]()
        return jsonify(statement(y))

    def statement_sheet(wb, s, title=None):
        """The Monthly Report sheet: Code | Name | Jan..Dec | Total, with SUM formulas for the totals (so it keeps working when edited)."""
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter as L
        ws = wb.create_sheet("Monthly Report")
        head_fill, bold = PatternFill("solid", fgColor=X.HEAD_FILL), Font(bold=True)
        ws["B2"] = title or f"Income Statement Report {s['year']}"; ws["B2"].font = Font(bold=True, size=13)
        M = s["months"]; first, lastc = 4, 4 + len(M) - 1; totc = lastc + 1
        def header(r, label):
            for j, v in enumerate(["Code", label] + MONTHS + ["Total"], 2):
                cell = ws.cell(row=r, column=j, value=v); cell.font = Font(bold=True, color="FFFFFF"); cell.fill = head_fill
        def line(r, code, name, months, b=False):
            ws.cell(row=r, column=2, value=int(code) if str(code or "").isdigit() else X.csv_safe(code)); ws.cell(row=r, column=3, value=X.csv_safe(name))
            for j, m in enumerate(M, first): ws.cell(row=r, column=j, value=months[m])
            ws.cell(row=r, column=totc, value=f"=SUM({L(first)}{r}:{L(lastc)}{r})")
            if b:
                for j in range(2, totc + 1): ws.cell(row=r, column=j).font = bold
        def sumline(r, name, r1, r2):
            ws.cell(row=r, column=3, value=name)
            for j in range(first, totc + 1): ws.cell(row=r, column=j, value=f"=SUM({L(j)}{r1}:{L(j)}{r2})" if r2 >= r1 else 0)
            for j in range(2, totc + 1): ws.cell(row=r, column=j).font = bold
        r = 4; header(r, "Revenue"); r += 1
        r1 = r
        for x in s["revenue"]: line(r, x["code"], x["name"], x["months"]); r += 1
        rev_tot = r; sumline(r, "Total Revenue (collected)", r1, r - 1); r += 2
        header(r, "Accrued (fees still to pay)"); r += 1; a1 = r
        for x in s["accrued"]: line(r, "", x["name"], x["months"]); r += 1
        acc_tot = r; sumline(r, "Total Accrued Revenue", a1, r - 1); r += 2
        header(r, "Expenses"); r += 1; e1 = r
        for x in s["expenses"]: line(r, x["code"], x["name"], x["months"]); r += 1
        exp_tot = r; sumline(r, "Total Expenses", e1, r - 1); r += 2
        header(r, "Capital spending (Cap-EX)"); r += 1; c1 = r
        for x in s["capital"]: line(r, x["code"], x["name"], x["months"]); r += 1
        cap_tot = r; sumline(r, "Total Capital spending", c1, r - 1); r += 2
        header(r, "Profit & Loss"); r += 1
        for name, f in (("Collected Profit (revenue - expenses)", lambda col: f"={col}{rev_tot}-{col}{exp_tot}"),
                        ("Budgeted Profit (if all fees were paid)", lambda col: f"={col}{rev_tot}+{col}{acc_tot}-{col}{exp_tot}"),
                        ("After capital spending", lambda col: f"={col}{rev_tot}-{col}{exp_tot}-{col}{cap_tot}")):
            ws.cell(row=r, column=3, value=name).font = bold
            for j in range(first, totc + 1): ws.cell(row=r, column=j, value=f(L(j))); ws.cell(row=r, column=j).font = bold
            r += 1
        r += 1
        ws.cell(row=r, column=3, value=s["note"]).alignment = Alignment(wrap_text=False)
        ws.column_dimensions["A"].width = 2; ws.column_dimensions["B"].width = 8; ws.column_dimensions["C"].width = 38
        for j in range(first, totc + 1):
            ws.column_dimensions[L(j)].width = 10
            for rr in range(5, r): ws.cell(row=rr, column=j).number_format = "#,##0"
        ws.freeze_panes = "D5"
        return ws

    @app.get("/api/finance/income-statement.xlsx")
    @auth("admin", perm="finance")
    def reg_statement_xlsx():
        from openpyxl import Workbook
        try: y = year_arg()
        except ValueError as x: return err(str(x))
        wb = Workbook(); wb.remove(wb.active)
        statement_sheet(wb, statement(y))
        out = io.BytesIO(); wb.save(out)
        audit("export_income_statement_xlsx", "report", None, str(y)); db().commit()
        return X.send_xlsx(out.getvalue(), f"income-statement-{y}")

    @app.get("/api/finance/income-statement.pdf")
    @auth("admin", perm="finance")
    def reg_statement_pdf():
        import reportpdf as R
        try: y = year_arg()
        except ValueError as x: return err(str(x))
        s = statement(y)
        n = s["months_shown"] or 12
        ms = s["months"][:n]
        head = ["Code", "Item"] + [MONTHS[int(m[5:]) - 1] for m in ms] + ["Total"]
        def tr(code, name, months): return [code or "", name] + [months[m] for m in ms] + [sum(months[m] for m in ms)]
        w = {"widths": [0.8, 2.6] + [0.85] * len(ms) + [1.1]}
        blocks = [("stats", [("Revenue (MVR)", s["year_totals"]["collected"]), ("Expenses (MVR)", s["year_totals"]["operating"]),
                             ("Profit (MVR)", s["year_totals"]["profit"]), ("Fees still to pay (MVR)", s["year_totals"]["accrued"]), ("Capital spending (MVR)", s["year_totals"]["capital"])]),
                  ("heading", "Revenue (money received)"), ("table", head, [tr(x["code"], x["name"], x["months"]) for x in s["revenue"]] + [tr("", "Total revenue", s["totals"]["revenue"])], w),
                  ("heading", "Accrued: fees for the month still to pay"), ("table", head, [tr("", x["name"], x["months"]) for x in s["accrued"]] + [tr("", "Total accrued", s["totals"]["accrued"])], w),
                  ("heading", "Expenses"), ("table", head, [tr(x["code"], x["name"], x["months"]) for x in s["expenses"]] + [tr("", "Total expenses", s["totals"]["operating"])], w),
                  ("heading", "Capital spending"), ("table", head, [tr(x["code"], x["name"], x["months"]) for x in s["capital"]] + [tr("", "Total capital", s["totals"]["capital"])], w),
                  ("heading", "Profit & Loss"), ("table", head, [tr("", "Revenue", s["pl"]["collected"]), tr("", "Expenses", s["pl"]["operating"]), tr("", "Collected profit", s["pl"]["profit"]),
                                                                  tr("", "Budgeted profit (if all fees were paid)", s["pl"]["if_all_paid"]), tr("", "After capital spending", s["pl"]["after_capital"])], w),
                  ("note", s["note"])]
        audit("export_income_statement_pdf", "report", None, str(y)); db().commit()
        return app.extensions["pdf"](f"Income statement {y}", blocks, f"income-statement-{y}", subtitle=f"January to {MONTHS_LONG[n - 1]} {y} · amounts in MVR")

    # ======================= the whole registry workbook, made from the portal =======================
    @app.get("/api/finance/registry.xlsx")
    @auth("admin", perm="finance")
    def reg_workbook():
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        from openpyxl.utils import get_column_letter as L
        try: y = year_arg()
        except ValueError as x: return err(str(x))
        wb = Workbook(); wb.remove(wb.active)
        hf = PatternFill("solid", fgColor=X.HEAD_FILL)
        def sheet(name, title, head, table, widths, money_cols=(), text_cols=()):
            ws = wb.create_sheet(name); ws["A1"] = title; ws["A1"].font = Font(bold=True, size=13)
            for j, h in enumerate(head, 1):
                c_ = ws.cell(row=2, column=j, value=h); c_.font = Font(bold=True, color="FFFFFF"); c_.fill = hf
                ws.column_dimensions[L(j)].width = widths[j - 1]
            for rr in table: ws.append([X.csv_safe(v) if isinstance(v, str) else v for v in rr])
            for j in text_cols:
                for rr in range(3, ws.max_row + 1): ws.cell(row=rr, column=j).number_format = "@"
            for j in money_cols:
                for rr in range(3, ws.max_row + 1): ws.cell(row=rr, column=j).number_format = "#,##0.##"
            ws.freeze_panes = "A3"
            if table: ws.auto_filter.ref = f"A2:{L(len(head))}{len(table) + 2}"
            return ws
        pays = rows("SELECT p.paid_on, p.amount_mvr, p.receipt_no, p.reference, p.method, i.id AS iid, i.period, i.amount_due_mvr, i.discount_mvr, i.description, "
                    "COALESCE(u.full_name, i.customer_name) AS name, s.student_code, c.name AS course, b.code AS batch, rt.name AS type, rt.ledger_code AS code "
                    "FROM payments p JOIN invoices i ON i.id=p.invoice_id LEFT JOIN users u ON u.id=i.student_id LEFT JOIN students s ON s.user_id=i.student_id "
                    "LEFT JOIN courses c ON c.id=i.course_id LEFT JOIN batches b ON b.id=i.batch_id" + RT_JOIN +
                    " WHERE p.reversed_at IS NULL AND i.status<>'void' AND p.paid_on BETWEEN ? AND ? ORDER BY p.paid_on, p.id", (f"{y}-01-01", f"{y}-12-31"))
        meth = {"bank_transfer": "bank", "cash": "cash", "other": "other", "gateway": "online"}
        rtab = [[n, dt.date.fromisoformat(p["paid_on"]), p["student_code"] or "", p["name"] or "", f"{p['course']} {p['batch'] or ''}".strip() if p["course"] else "",
                 int(p["code"]) if (p["code"] or "").isdigit() else (p["code"] or ""), p["type"] or "", "-", p["discount_mvr"] or "-", p["amount_due_mvr"], p["amount_mvr"],
                 f"INV-{p['period'].replace('-', '')}-{p['iid']:04d}", p["period"] if re.match(r"^\d{4}-\d\d$", p["period"] or "") else "", meth.get(p["method"], p["method"]),
                 p["reference"] or "", p["receipt_no"]] for n, p in enumerate(pays, 1)]
        ws = sheet("Revenue Registry", "Revenue Registry (Invoices)", ["No", "Date", "Student ID", "Name", "Course", "Revenue Code", "Payment Type", "GST %", "Discount",
                   "Amount Due", "Total Paid", "Invoice No.", "Fee Month", "Method", "Reference", "Receipt No."], rtab, [6, 12, 15, 26, 22, 9, 18, 7, 9, 10, 10, 18, 10, 9, 16, 14], (10, 11), (3,))
        for rr in range(3, ws.max_row + 1): ws.cell(row=rr, column=2).number_format = "yyyy-mm-dd"
        if rtab:
            ws.cell(row=len(rtab) + 3, column=10, value="Total").font = Font(bold=True)
            ws.cell(row=len(rtab) + 3, column=11, value=f"=SUM(K3:K{len(rtab) + 2})").font = Font(bold=True)
        exps = rows("SELECT e.expense_date, e.amount_mvr, e.description, e.supplier, e.supplier_gst_no, e.invoice_no, e.gst_mvr, e.usd_amount, e.fx_rate, e.amount_exact, "
                    "k.name AS type, k.code FROM expenses e JOIN expense_categories k ON k.id=e.category_id WHERE e.expense_date BETWEEN ? AND ? ORDER BY e.expense_date, e.id",
                    (f"{y}-01-01", f"{y}-12-31"))
        etab = []
        for n, e in enumerate(exps, 1):
            usd = e["usd_amount"]
            mvr_part = None if usd and e["amount_exact"] is None else (round(float(e["amount_exact"]) - float(usd) * float(e["fx_rate"] or 0), 2) if usd else e["amount_mvr"])
            etab.append([n, dt.date.fromisoformat(e["expense_date"]), e["supplier_gst_no"] or "-", e["supplier"] or e["description"] or "", e["invoice_no"] or "-",
                         int(e["code"]) if (e["code"] or "").isdigit() else (e["code"] or ""), e["type"], (mvr_part or None) if usd else e["amount_mvr"],
                         e["gst_mvr"] if e["gst_mvr"] else "-", "-", "-", usd if usd else None, e["amount_mvr"], e["description"] or ""])
        ws = sheet("Expense Registry", "Invoice registry ( Expenses )", ["No", "Date", "GST No.", "Name", "Invoice No.", "Expense Code", "Expense Type", "MVR", "GST %",
                   "Discount", "Amount Due", "$", "Total", "Description"], etab, [6, 12, 15, 22, 22, 9, 20, 10, 8, 8, 10, 8, 11, 30], (8, 12, 13), (3, 5))
        for rr in range(3, ws.max_row + 1): ws.cell(row=rr, column=2).number_format = "yyyy-mm-dd"
        if etab:
            ws.cell(row=len(etab) + 3, column=12, value="Total").font = Font(bold=True)
            ws.cell(row=len(etab) + 3, column=13, value=f"=SUM(M3:M{len(etab) + 2})").font = Font(bold=True)
        statement_sheet(wb, statement(y))
        grid = app.extensions.get("fee_grid_sheets")
        if grid: grid(wb, y)
        out = io.BytesIO(); wb.save(out)
        audit("export_registry_xlsx", "report", None, f"{y}: {len(rtab)} payments, {len(etab)} expenses"); db().commit()
        return X.send_xlsx(out.getvalue(), f"registry-{y}")

    app.extensions["registry"] = {"statement": statement}
