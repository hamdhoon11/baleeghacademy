"""v0.8.37: recurring (monthly) expenses, e.g. rent, internet, salaries paid as a fixed amount.

A rule says: this category, this amount, on this day of every month, from this month (until an end month, or for good). The portal
writes the real expense row for each month when that day has come: whenever Finance is opened, and on the scheduled run. Each month is
written once (a unique index on expenses(recurring_id, recurring_month)); a month that was written and then deleted by hand is not
written again. Catch-up goes back at most 12 months. Editing a rule changes the months still to come; expenses already written stay
as they are (edit them like any expense). Deleting a rule stops it; its expenses stay.

All routes are admin only with the "finance" area:
  GET    /api/recurring-expenses                 rules with next_date, last written month, total written
  POST   /api/recurring-expenses                 category_id, amount_mvr, day_of_month (1-28), description, start_month (YYYY-MM, default this month), end_month (optional)
  PATCH  /api/recurring-expenses/<id>            amount_mvr, description, day_of_month, end_month, category_id, is_active (pause/resume)
  DELETE /api/recurring-expenses/<id>            removes the rule; written expenses stay (their link to the rule is cleared)"""
import datetime as dt, re
from flask import g, jsonify, request
import payments as pay

MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
CATCH_UP_MONTHS = 12


def months_between(a, b):
    """'YYYY-MM' strings from a to b inclusive."""
    y, m = int(a[:4]), int(a[5:7]); out = []
    while f"{y:04d}-{m:02d}" <= b:
        out.append(f"{y:04d}-{m:02d}"); m += 1
        if m == 13: y, m = y + 1, 1
    return out


def add_months(ym, n):
    y, m = int(ym[:4]), int(ym[5:7]) - 1 + n
    return f"{y + m // 12:04d}-{m % 12 + 1:02d}"


def register(app, c, today):
    db, rows, one, err, auth, audit = c.db, c.rows, c.one, c.err, c.auth, c.audit
    AREA = "finance"

    def due_months(r, t):
        """Months of rule r that are due by date t and not yet written."""
        this = t.isoformat()[:7]
        last = this if t.day >= r["day_of_month"] else add_months(this, -1)
        if r["end_month"] and r["end_month"] < last: last = r["end_month"]
        first = max(r["start_month"], add_months(this, -CATCH_UP_MONTHS))
        if first > last: return []
        done = {x["recurring_month"] for x in rows("SELECT recurring_month FROM recurring_done WHERE recurring_id=?", (r["id"],))}
        return [m for m in months_between(first, last) if m not in done]

    def catch_up(who=None):
        """Write every due month of every active rule. Returns how many expenses were written. Safe to call often."""
        t, n = today(), 0
        try:
            n = _write(t, who)
        except Exception as x:   # two requests catching up at the same moment: the other one wrote these months, so this one stands back
            if "Integrity" not in type(x).__name__ and "Unique" not in type(x).__name__: raise
            db().rollback(); return 0
        if n: db().commit()
        return n

    def _write(t, who):
        n = 0
        for r in rows("SELECT * FROM recurring_expenses WHERE is_active=1"):
            for m in due_months(r, t):
                day = f"{m}-{r['day_of_month']:02d}"
                cur = db().execute("INSERT INTO expenses(expense_date,amount_mvr,category_id,description,entered_by,recurring_id,recurring_month) VALUES(?,?,?,?,?,?,?)",
                                   (day, r["amount_mvr"], r["category_id"], (r["description"] or "") + (" " if r["description"] else "") + f"(monthly, {m})",
                                    r["created_by"], r["id"], m))
                db().execute("INSERT INTO recurring_done(recurring_id,recurring_month,expense_id) VALUES(?,?,?)", (r["id"], m, cur.lastrowid))
                audit("expense_recurring_create", "expense", cur.lastrowid, f"rule {r['id']}: {day} MVR {r['amount_mvr']}" + (f" ({who})" if who else ""), new=r["amount_mvr"])
                n += 1
        return n

    app.extensions["recurring"] = catch_up

    def parse(d, cur=None):
        v = {}
        if cur is None or "category_id" in d:
            try: kid = int(d.get("category_id"))
            except (TypeError, ValueError): raise ValueError("Choose a category")
            k = one("SELECT id,is_active FROM expense_categories WHERE id=?", (kid,))
            if not k: raise ValueError("Category not found")
            if not k["is_active"] and (cur is None or kid != cur["category_id"]): raise ValueError("That category is inactive")
            v["category_id"] = kid
        if cur is None or "amount_mvr" in d: v["amount_mvr"] = pay.as_int(d.get("amount_mvr"), "The amount")
        if cur is None or "day_of_month" in d:
            try: day = int(d.get("day_of_month") or 1)
            except (TypeError, ValueError): raise ValueError("Day of the month must be a number from 1 to 28")
            if not 1 <= day <= 28: raise ValueError("Day of the month must be from 1 to 28 (so it happens in every month)")
            v["day_of_month"] = day
        if cur is None or "description" in d:
            ds = " ".join(str(d.get("description") or "").split())
            if len(ds) > 200: raise ValueError("The description is too long (200 letters max)")
            v["description"] = ds or None
        if cur is None:
            sm = str(d.get("start_month") or today().isoformat()[:7])
            if not MONTH.match(sm): raise ValueError("Start month must be YYYY-MM")
            if sm < add_months(today().isoformat()[:7], -CATCH_UP_MONTHS): raise ValueError(f"The start month can be at most {CATCH_UP_MONTHS} months back")
            v["start_month"] = sm
        if cur is None or "end_month" in d:
            em = str(d.get("end_month") or "").strip() or None
            if em and not MONTH.match(em): raise ValueError("End month must be YYYY-MM")
            if em and em < (v.get("start_month") or cur["start_month"]): raise ValueError("The end month is before the start month")
            v["end_month"] = em
        if cur is not None and "is_active" in d: v["is_active"] = 1 if d.get("is_active") in (True, 1, "1", "true") else 0
        return v

    def shape(r, t):
        r = dict(r)
        this = t.isoformat()[:7]
        nxt = this if t.day < r["day_of_month"] else add_months(this, 1)
        if nxt < r["start_month"]: nxt = r["start_month"]
        r["next_date"] = None if (not r["is_active"] or (r["end_month"] and nxt > r["end_month"])) else f"{nxt}-{r['day_of_month']:02d}"
        return r

    @app.get("/api/recurring-expenses")
    @auth("admin", perm=AREA)
    def rec_list():
        catch_up()
        t = today()
        out = rows("SELECT r.*,k.name AS category,(SELECT MAX(recurring_month) FROM recurring_done d WHERE d.recurring_id=r.id) AS last_month,"
                   "(SELECT COUNT(*) FROM recurring_done d WHERE d.recurring_id=r.id) AS months_written FROM recurring_expenses r "
                   "JOIN expense_categories k ON k.id=r.category_id ORDER BY r.is_active DESC, r.day_of_month, r.id")
        return jsonify([shape(r, t) for r in out])

    @app.post("/api/recurring-expenses")
    @auth("admin", perm=AREA)
    def rec_create():
        try: v = parse(request.get_json(silent=True) or {})
        except (ValueError, pay.PayError) as x: return err(str(x))
        rid = db().execute("INSERT INTO recurring_expenses(category_id,amount_mvr,day_of_month,description,start_month,end_month,is_active,created_by,created_at) "
                           "VALUES(?,?,?,?,?,?,1,?,datetime('now'))", (v["category_id"], v["amount_mvr"], v["day_of_month"], v["description"], v["start_month"],
                                                                       v["end_month"], g.user["id"])).lastrowid
        audit("recurring_expense_create", "recurring_expense", rid, f"MVR {v['amount_mvr']} on day {v['day_of_month']} from {v['start_month']}", new=v["amount_mvr"])
        db().commit()
        written = catch_up()
        return jsonify(id=rid, written=written), 201

    @app.patch("/api/recurring-expenses/<int:rid>")
    @auth("admin", perm=AREA)
    def rec_update(rid):
        cur = one("SELECT * FROM recurring_expenses WHERE id=?", (rid,))
        if not cur: return err("Recurring expense not found", 404)
        try: v = parse(request.get_json(silent=True) or {}, cur)
        except (ValueError, pay.PayError) as x: return err(str(x))
        changed = [k for k in v if v[k] != cur[k]]
        if changed:
            db().execute(f"UPDATE recurring_expenses SET {', '.join(k + '=?' for k in changed)} WHERE id=?", tuple(v[k] for k in changed) + (rid,))
            audit("recurring_expense_update", "recurring_expense", rid, "changed: " + ", ".join(changed), old=cur["amount_mvr"], new=v.get("amount_mvr", cur["amount_mvr"]))
            db().commit()
        return jsonify(ok=True, changed=changed, written=catch_up())

    @app.delete("/api/recurring-expenses/<int:rid>")
    @auth("admin", perm=AREA)
    def rec_delete(rid):
        cur = one("SELECT * FROM recurring_expenses WHERE id=?", (rid,))
        if not cur: return err("Recurring expense not found", 404)
        db().execute("UPDATE expenses SET recurring_id=NULL WHERE recurring_id=?", (rid,))
        db().execute("DELETE FROM recurring_done WHERE recurring_id=?", (rid,))
        db().execute("DELETE FROM recurring_expenses WHERE id=?", (rid,))
        audit("recurring_expense_delete", "recurring_expense", rid, f"MVR {cur['amount_mvr']} on day {cur['day_of_month']}", old=cur["amount_mvr"]); db().commit()
        return jsonify(ok=True)
