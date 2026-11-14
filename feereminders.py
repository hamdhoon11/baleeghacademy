"""v0.8.48: fee reminders worked out per person (total owed and which months), not per invoice.

  GET  /api/fees/reminders                 admin, Fees   {window_days, overdue: [person], due_soon: [person], totals}
  POST /api/fees/reminders/sent            admin, Fees   {key, kind: overdue|due_soon, to: student|guardian, channel: whatsapp|viber}
                                                         records that the chat was opened (one `reminders` row per invoice in it) and logs it
  GET  /api/my/fees/summary                (fees.py) now also carries `reminder`: the student's own overdue total and months, and what falls
                                           due in the next `remind_fee_days_before` days (default 5). Home shows it as a banner in that window.

Rules (one place, used by the WhatsApp list, the student's Home and the daily in-app reminders in notify.py):
- An invoice is "open" when its status is unpaid and something is left to pay. Invoices with a slip waiting for the office
  (`slip_submitted`) are left out of the amount and the message (the student has already paid; the office has to check it), and are
  counted separately as `slips_waiting`.
- Overdue = due date before today. Due soon = due date from today to today + window (inclusive). Void and waived invoices never count.
- People not in the portal (hand-made invoices with a name and phone) are grouped by name and phone, and get the WhatsApp message too.
Nothing here sends a WhatsApp message by itself: a normal WhatsApp number cannot be automated (see whatsapp.py). The list opens
WhatsApp with the message written; the in-app notice and the Home banner reach the student automatically.
"""
import datetime as dt
import re
from urllib.parse import quote

import common
import settings_schema as SS

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
PERIOD = re.compile(r"^(\d{4})-(\d{2})$")
KINDS = ("overdue", "due_soon")


def month_label(period):
    """'2026-11' -> 'Nov 2026'; anything else (REG-FEE, a hand-made description month) as it is."""
    m = PERIOD.match(str(period or ""))
    if not m or not 1 <= int(m.group(2)) <= 12:
        return "Registration" if period == "REG-FEE" else str(period or "")
    return f"{MONTHS[int(m.group(2)) - 1]} {m.group(1)}"


def nice_date(iso):
    """'2026-11-10' -> '10 Nov 2026'."""
    try: d = dt.date.fromisoformat(str(iso)[:10])
    except ValueError: return str(iso or "")
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def join_words(xs):
    xs = list(xs)
    if len(xs) <= 1: return "".join(xs)
    return ", ".join(xs[:-1]) + " and " + xs[-1]


def money(n):
    return f"{int(n or 0):,}"


def fill(template, vals):
    return re.sub(r"\{(\w+)\}", lambda m: str(vals.get(m.group(1), m.group(0))), template)


def block(items, t):
    """Summary of a list of open invoices (already filtered to one kind)."""
    if not items: return None
    items = sorted(items, key=lambda i: (i["due_date"], i["period"], i["id"]))
    months = list(dict.fromkeys(month_label(i["period"]) for i in items))
    first_due = items[0]["due_date"]
    return {"total": sum(i["balance"] for i in items), "count": len(items), "months": months, "months_text": join_words(months),
            "first_due": first_due, "last_due": items[-1]["due_date"], "invoice_ids": [i["id"] for i in items],
            "days_overdue": max(0, (t - dt.date.fromisoformat(first_due)).days),
            "days_left": max(0, (dt.date.fromisoformat(first_due) - t).days),
            "items": [{k: i[k] for k in ("id", "number", "period", "month", "what", "balance", "due_date", "status")} for i in items]}


def details_text(b):
    return "\n".join(f"- {i['month']} · {i['what']}: MVR {money(i['balance'])} (due {nice_date(i['due_date'])})" for i in b["items"])


def register(app, c, now):
    rows, one, err, auth, audit, db = c.rows, c.one, c.err, c.auth, c.audit, c.db

    def conf(key):
        v = (c.raw_setting(key) or "").strip()
        return v or SS.SETTINGS[key]["default"]

    def window():
        try: return max(0, min(14, int(conf("remind_fee_days_before"))))
        except ValueError: return int(SS.SETTINGS["remind_fee_days_before"]["default"])

    def today():
        return now().date()

    SQL = ("SELECT i.id, i.period, i.due_date, i.status, i.student_id, i.customer_name, i.customer_phone, i.description,"
           " i.amount_due_mvr-i.waived_mvr-i.paid_mvr AS balance, c.name AS course_name, b.code AS batch_code,"
           " u.full_name, u.phone, u.is_active, s.student_code, s.guardian_name, s.guardian_phone"
           " FROM invoices i LEFT JOIN courses c ON c.id=i.course_id LEFT JOIN batches b ON b.id=i.batch_id"
           " LEFT JOIN users u ON u.id=i.student_id LEFT JOIN students s ON s.user_id=i.student_id"
           " WHERE i.status IN ('unpaid','slip_submitted') AND i.amount_due_mvr-i.waived_mvr-i.paid_mvr>0")

    def dues(t=None, student_id=None, days=None):
        """{key: person} for everyone with something overdue or due within `days`. key = 's<id>' or 'w<name>|<phone>' (not in the portal)."""
        t = t or today(); days = window() if days is None else days
        sql, args = SQL, []
        if student_id is not None: sql += " AND i.student_id=?"; args.append(student_id)
        horizon = (t + dt.timedelta(days=days)).isoformat()
        sql += " AND i.due_date<=?"; args.append(horizon)
        people = {}
        for r in rows(sql + " ORDER BY i.due_date, i.id", args):
            key = f"s{r['student_id']}" if r["student_id"] else f"w{(r['customer_name'] or '').strip()}|{common.digits_intl(r['customer_phone'])}"
            p = people.setdefault(key, {"key": key, "student_id": r["student_id"], "name": r["full_name"] or r["customer_name"] or "",
                                        "student_code": r["student_code"], "walk_in": not r["student_id"], "phone": r["phone"] or r["customer_phone"],
                                        "guardian_name": r["guardian_name"], "guardian_phone": r["guardian_phone"],
                                        "_over": [], "_soon": [], "slips_waiting": 0, "slip_items": []})
            what = (r["course_name"] + (" " + r["batch_code"] if r["batch_code"] else "")) if r["course_name"] else (r["description"] or "Fee")
            i = {"id": r["id"], "number": f"INV-{r['period'].replace('-', '')}-{r['id']:04d}", "period": r["period"], "month": month_label(r["period"]),
                 "what": what, "balance": r["balance"], "due_date": r["due_date"], "status": r["status"]}
            if r["status"] == "slip_submitted":
                p["slips_waiting"] += 1; p["slip_items"].append(i); continue
            (p["_over"] if r["due_date"] < t.isoformat() else p["_soon"]).append(i)
        out = {}
        for k, p in people.items():
            p["overdue"], p["due_soon"] = block(p.pop("_over"), t), block(p.pop("_soon"), t)
            if p["overdue"] or p["due_soon"] or p["slips_waiting"]: out[k] = p
        return out

    def message(p, kind):
        b = p[kind]
        vals = {"name": p["name"], "academy": conf("academy_name"),
                "amount": money(b["total"]), "months": b["months_text"], "count": b["count"], "month_word": "month" if b["count"] == 1 else "months",
                "due_date": nice_date(b["first_due"]), "days_left": b["days_left"], "days_overdue": b["days_overdue"],
                "details": details_text(b), "guardian": p.get("guardian_name") or ""}
        return fill(conf("wa_overdue_template" if kind == "overdue" else "wa_due_soon_template"), vals).strip()

    def links(p, text):
        out = {}
        for who, phone in (("student", p["phone"]), ("guardian", p.get("guardian_phone"))):
            n = common.digits_intl(phone)
            if n and len(n) >= 7: out[who] = {"phone": phone, "whatsapp": f"https://wa.me/{n}?text={quote(text)}", "viber": f"viber://chat?number=%2B{n}"}
        return out

    def last_sent(ids):
        if not ids: return None
        q = ",".join("?" * len(ids))
        return one(f"SELECT r.channel, r.recipient, r.sent_at, u.full_name AS by_name FROM reminders r LEFT JOIN users u ON u.id=r.sent_by "
                   f"WHERE r.invoice_id IN ({q}) ORDER BY r.sent_at DESC, r.id DESC LIMIT 1", ids)

    def notice(b, kind):
        """The short text a student reads in the portal (bell and Home)."""
        if kind == "overdue":
            late = b["days_overdue"]
            return (f"MVR {money(b['total'])} for {b['months_text']} is overdue ({b['count']} unpaid {'month' if b['count'] == 1 else 'months'}, "
                    f"the oldest {late} day{'s' if late != 1 else ''} late). "
                    "Please settle the payment as soon as possible. If you have already paid, upload the slip in Fees.")
        when = "today" if b["days_left"] == 0 else f"on {nice_date(b['first_due'])}"
        return f"MVR {money(b['total'])} for {b['months_text']} is due {when}. Please settle the payment before the due date."

    app.extensions["feedue"] = {"dues": dues, "window": window, "notice": notice, "month_label": month_label, "nice_date": nice_date}

    @app.get("/api/fees/reminders")
    @auth("admin", perm="fees")
    def fr_list():
        t = today(); w = window()
        ppl = dues(t, days=w)
        out = {"overdue": [], "due_soon": [], "slips_only": []}
        for p in ppl.values():
            for kind in KINDS:
                if not p[kind]: continue
                text = message(p, kind)
                last = last_sent(p[kind]["invoice_ids"])
                x = {k: p[k] for k in ("key", "student_id", "name", "student_code", "walk_in", "slips_waiting")}
                x.update(p[kind]); x.pop("invoice_ids", None)
                x.update(kind=kind, message=text, links=links(p, text), last_reminder=last,
                         reminded_today=bool(last and str(last["sent_at"])[:10] == t.isoformat()))
                out[kind].append(x)
            if not p["overdue"] and not p["due_soon"]:
                out["slips_only"].append({"key": p["key"], "name": p["name"], "slips_waiting": p["slips_waiting"], "items": p["slip_items"]})
        out["overdue"].sort(key=lambda x: (-x["days_overdue"], -x["total"], x["name"].lower()))
        out["due_soon"].sort(key=lambda x: (x["first_due"], x["name"].lower()))
        tot = {k: {"people": len(out[k]), "amount": sum(x["total"] for x in out[k])} for k in KINDS}
        from flask import jsonify
        resp = jsonify(window_days=w, today=t.isoformat(), totals=tot, **out)
        resp.headers["Cache-Control"] = "private, no-store"   # phone numbers
        return resp

    @app.post("/api/fees/reminders/sent")
    @auth("admin", perm="fees")
    def fr_sent():
        from flask import g, request
        d = request.get_json(silent=True) or {}
        kind, to, ch = d.get("kind"), d.get("to", "student"), d.get("channel", "whatsapp")
        if kind not in KINDS: return err("Choose overdue or due soon")
        if to not in ("student", "guardian"): return err("Send to the student or the guardian")
        if ch not in ("whatsapp", "viber"): return err("Channel must be whatsapp or viber")
        p = dues().get(str(d.get("key") or ""))
        if not p or not p[kind]: return err("Nothing is left to remind this person about", 409)
        stamp = now().isoformat(timespec="seconds")
        for iid in p[kind]["invoice_ids"]:
            db().execute("INSERT INTO reminders(invoice_id,channel,recipient,sent_by,sent_at) VALUES(?,?,?,?,?)", (iid, ch, to, g.user["id"], stamp))
        audit("reminder_sent", "student" if p["student_id"] else "invoice", p["student_id"] or p[kind]["invoice_ids"][0],
              f"{ch} to {to}: {'overdue' if kind == 'overdue' else 'due soon'}, MVR {p[kind]['total']} for {p[kind]['months_text']}")
        db().commit()
        return {"ok": True, "invoices": len(p[kind]["invoice_ids"])}, 201

    @app.get("/api/fees/reminders.pdf")
    @auth("admin", perm="fees")
    def fr_pdf():   # who owes what: overdue (total and months) and due in the next days
        data = fr_list().get_json()
        blocks = [("stats", [("People overdue", data["totals"]["overdue"]["people"]), ("Overdue (MVR)", data["totals"]["overdue"]["amount"]),
                             (f"Due in {data['window_days']} days", data["totals"]["due_soon"]["people"]), ("Due soon (MVR)", data["totals"]["due_soon"]["amount"])])]
        for kind, title in (("overdue", "Overdue"), ("due_soon", f"Due in the next {data['window_days']} days")):
            blocks += [("heading", title),
                       ("table", ["Name", "ID", "Months", "Oldest due" if kind == "overdue" else "Due on", "Days late" if kind == "overdue" else "Days left", "Total (MVR)", "Last reminder"],
                        [[x["name"] + (" (not in the portal)" if x["walk_in"] else ""), x["student_code"] or "", x["months_text"], x["first_due"],
                          x["days_overdue"] if kind == "overdue" else x["days_left"], x["total"],
                          f"{str(x['last_reminder']['sent_at'])[:10]} {x['last_reminder']['channel']}" if x["last_reminder"] else ""] for x in data[kind]],
                        {"widths": [3, 1.8, 3.4, 1.4, 1, 1.2, 1.8], "right": {4, 5},
                         "total": ["Total", "", "", "", "", sum(x["total"] for x in data[kind]), ""]})]
        audit("export_fee_reminders_pdf", "report", None, f"{data['totals']['overdue']['people']} overdue, {data['totals']['due_soon']['people']} due soon"); db().commit()
        return app.extensions["pdf"]("Fees overdue and due soon", blocks, f"fees-due-{data['today']}", subtitle=f"As of {nice_date(data['today'])} · amounts in MVR")
