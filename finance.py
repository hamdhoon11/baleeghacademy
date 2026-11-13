"""Session 23: finance part 1, expenses.

All routes are admin only and need the "finance" area (a limited admin without it gets 403; a full admin has it).
Amounts are whole MVR, like payments. Receipts (PDF, JPG, PNG) go to the private "receipts" storage area and are only
served through the download route below. Every create, edit and delete writes an activity-log row with old and new values.

  GET    /api/expense-categories                    all categories (with how many expenses each has)
  POST   /api/expense-categories                    name
  PATCH  /api/expense-categories/<id>               name and/or is_active (inactive ones leave the form dropdown, old expenses keep them)
  DELETE /api/expense-categories/<id>               only when no expense uses it (409 otherwise: deactivate instead)
  GET    /api/expenses                              ?category_id=&date_from=&date_to=&q=&page=&per_page= -> {items, count, total_mvr, page, per_page}
  POST   /api/expenses                              multipart or JSON: expense_date, amount_mvr, category_id, description, file (receipt, optional)
  PATCH  /api/expenses/<id>                         same fields, all optional; file replaces the receipt; remove_receipt=1 removes it
  DELETE /api/expenses/<id>                         removes the row and its receipt file (the log keeps what it was)
  GET    /api/expenses/<id>/receipt                 the receipt file (view is logged)

Session 24 (same area):
  GET    /api/finance/revenue                       ?date_from=&date_to=&course_id=&batch_id=&kind=course|tuition -> collected, by kind/course/batch/month, outstanding
  GET    /api/finance/dashboard                     ?date_from=&date_to= (default: this month so far) -> revenue, expenses, net, outstanding, 12-month series"""
import datetime as dt
from flask import g, jsonify, request
import common
import payments as pay


def register(app, c, today):
    db, rows, one, err, auth, audit, store = c.db, c.rows, c.one, c.err, c.auth, c.audit, c.store
    AREA = "finance"

    def iso(v, what="Date"):
        try: d = dt.date.fromisoformat(str(v or ""))
        except ValueError: raise ValueError(f"{what} must be a date (YYYY-MM-DD)")
        return d

    def data():
        """Form fields (multipart) or JSON, whichever came."""
        return request.form if (request.form or request.files) else (request.get_json(silent=True) or {})

    def category_name(raw):
        n = " ".join(str(raw or "").split())
        if not n: raise ValueError("Category name is required")
        if len(n) > 60: raise ValueError("Category name is too long (60 letters max)")
        return n

    # ---------- categories ----------
    @app.get("/api/expense-categories")
    @auth("admin", perm=AREA)
    def exp_cat_list():
        return jsonify(rows("SELECT k.id,k.name,k.is_active,k.created_at,(SELECT COUNT(*) FROM expenses e WHERE e.category_id=k.id) AS expense_count "
                            "FROM expense_categories k ORDER BY k.name"))

    @app.post("/api/expense-categories")
    @auth("admin", perm=AREA)
    def exp_cat_create():
        try: n = category_name((request.get_json(silent=True) or {}).get("name"))
        except ValueError as x: return err(str(x))
        if one("SELECT 1 x FROM expense_categories WHERE LOWER(name)=LOWER(?)", (n,)): return err("That category already exists", 409)
        cur = db().execute("INSERT INTO expense_categories(name) VALUES(?)", (n,))
        audit("expense_category_create", "expense_category", cur.lastrowid, n, new=n); db().commit()
        return jsonify(id=cur.lastrowid, name=n), 201

    @app.patch("/api/expense-categories/<int:kid>")
    @auth("admin", perm=AREA)
    def exp_cat_update(kid):
        k = one("SELECT * FROM expense_categories WHERE id=?", (kid,))
        if not k: return err("Category not found", 404)
        d = request.get_json(silent=True) or {}
        name, active = k["name"], k["is_active"]
        if "name" in d:
            try: name = category_name(d["name"])
            except ValueError as x: return err(str(x))
            if one("SELECT 1 x FROM expense_categories WHERE LOWER(name)=LOWER(?) AND id<>?", (name, kid)): return err("That category already exists", 409)
        if "is_active" in d: active = 1 if d["is_active"] in (True, 1, "1", "true") else 0
        db().execute("UPDATE expense_categories SET name=?, is_active=? WHERE id=?", (name, active, kid))
        audit("expense_category_update", "expense_category", kid, f"{k['name']} -> {name}; active {k['is_active']} -> {active}",
              old=f"{k['name']} (active={k['is_active']})", new=f"{name} (active={active})"); db().commit()
        return jsonify(ok=True)

    @app.delete("/api/expense-categories/<int:kid>")
    @auth("admin", perm=AREA)
    def exp_cat_delete(kid):
        k = one("SELECT * FROM expense_categories WHERE id=?", (kid,))
        if not k: return err("Category not found", 404)
        if one("SELECT 1 x FROM expenses WHERE category_id=?", (kid,)): return err("Expenses use this category. Make it inactive instead of deleting it.", 409)
        db().execute("DELETE FROM expense_categories WHERE id=?", (kid,))
        audit("expense_category_delete", "expense_category", kid, k["name"], old=k["name"]); db().commit()
        return jsonify(ok=True)

    # ---------- expenses ----------
    BASE = ("SELECT e.id,e.expense_date,e.amount_mvr,e.category_id,k.name AS category,e.description,e.receipt_name,(e.receipt_file IS NOT NULL) AS has_receipt,e.recurring_id,"
            "e.entered_by,u.full_name AS entered_by_name,e.created_at,e.updated_at FROM expenses e JOIN expense_categories k ON k.id=e.category_id LEFT JOIN users u ON u.id=e.entered_by")

    def shape(r):
        r["has_receipt"] = bool(r["has_receipt"])
        return r

    def parse(d, cur=None):
        """Validated values for create (cur None) or edit. Raises ValueError / pay.PayError with a message fit to show."""
        v = {}
        if cur is None or "expense_date" in d:
            day = iso(d.get("expense_date"), "Expense date")
            if day > today(): raise ValueError("The expense date cannot be in the future")
            if day < today() - dt.timedelta(days=366 * 5): raise ValueError("That expense date is too old")
            v["expense_date"] = day.isoformat()
        if cur is None or "amount_mvr" in d: v["amount_mvr"] = pay.as_int(d.get("amount_mvr"), "The amount")
        if cur is None or "category_id" in d:
            try: kid = int(d.get("category_id"))
            except (TypeError, ValueError): raise ValueError("Choose a category")
            k = one("SELECT id,is_active FROM expense_categories WHERE id=?", (kid,))
            if not k: raise ValueError("Category not found")
            if not k["is_active"] and (cur is None or kid != cur["category_id"]): raise ValueError("That category is inactive")
            v["category_id"] = kid
        if cur is None or "description" in d:
            ds = " ".join(str(d.get("description") or "").split())
            if len(ds) > 500: raise ValueError("The description is too long (500 letters max)")
            v["description"] = ds or None
        return v

    @app.get("/api/expenses")
    @auth("admin", perm=AREA)
    def exp_list():
        if "recurring" in app.extensions: app.extensions["recurring"]()   # v0.8.37: write monthly expenses that are due
        a = request.args
        where, args = [], []
        if a.get("category_id"):
            try: where.append("e.category_id=?"); args.append(int(a["category_id"]))
            except ValueError: return err("Bad category")
        for key, op in (("date_from", ">="), ("date_to", "<=")):
            if a.get(key):
                try: where.append(f"e.expense_date{op}?"); args.append(iso(a[key]).isoformat())
                except ValueError as x: return err(str(x))
        if a.get("q"):
            where.append("(LOWER(COALESCE(e.description,'')) LIKE ? OR LOWER(k.name) LIKE ?)"); like = "%" + a["q"].lower()[:60] + "%"; args += [like, like]
        w = (" WHERE " + " AND ".join(where)) if where else ""
        try: page, per = max(1, int(a.get("page", 1))), min(200, max(1, int(a.get("per_page", 50))))
        except ValueError: return err("Bad paging")
        tot = one("SELECT COUNT(*) n, COALESCE(SUM(e.amount_mvr),0) s FROM expenses e JOIN expense_categories k ON k.id=e.category_id" + w, tuple(args))
        items = rows(BASE + w + " ORDER BY e.expense_date DESC, e.id DESC LIMIT ? OFFSET ?", tuple(args) + (per, (page - 1) * per))
        return jsonify(items=[shape(r) for r in items], count=tot["n"], total_mvr=int(tot["s"]), page=page, per_page=per)

    @app.post("/api/expenses")
    @auth("admin", perm=AREA)
    def exp_create():
        d = data()
        try: v = parse(d)
        except (ValueError, pay.PayError) as x: return err(str(x))
        name = shown = None
        if request.files.get("file") and request.files["file"].filename:
            try: name, _, shown = common.save_private(request.files["file"], store, "receipts")
            except ValueError as x: return err(str(x))
        try:
            cur = db().execute("INSERT INTO expenses(expense_date,amount_mvr,category_id,description,receipt_file,receipt_name,entered_by) VALUES(?,?,?,?,?,?,?)",
                               (v["expense_date"], v["amount_mvr"], v["category_id"], v["description"], name, shown, g.user["id"]))
            audit("expense_create", "expense", cur.lastrowid, f"{v['expense_date']} MVR {v['amount_mvr']}" + (", receipt attached" if name else ""), new=v["amount_mvr"]); db().commit()
        except Exception:
            db().rollback()
            if name: store.delete("receipts", name)
            raise
        return jsonify(id=cur.lastrowid), 201

    @app.patch("/api/expenses/<int:eid>")
    @auth("admin", perm=AREA)
    def exp_update(eid):
        cur = one("SELECT * FROM expenses WHERE id=?", (eid,))
        if not cur: return err("Expense not found", 404)
        d = data()
        try: v = parse(d, cur)
        except (ValueError, pay.PayError) as x: return err(str(x))
        name, shown, drop = cur["receipt_file"], cur["receipt_name"], None
        new_file = None
        if request.files.get("file") and request.files["file"].filename:
            try: new_file, _, nshown = common.save_private(request.files["file"], store, "receipts")
            except ValueError as x: return err(str(x))
            drop, name, shown = cur["receipt_file"], new_file, nshown
        elif str(d.get("remove_receipt", "")) in ("1", "true", "True") and cur["receipt_file"]:
            drop, name, shown = cur["receipt_file"], None, None
        v["receipt_file"], v["receipt_name"] = name, shown
        changed = [k for k in ("expense_date", "amount_mvr", "category_id", "description") if k in v and v[k] != cur[k]]
        if name != cur["receipt_file"]: changed.append("receipt")
        try:
            sets = ", ".join(f"{k}=?" for k in v) + ", updated_by=?, updated_at=datetime('now')"
            db().execute(f"UPDATE expenses SET {sets} WHERE id=?", tuple(v.values()) + (g.user["id"], eid))
            if changed:
                audit("expense_update", "expense", eid, "changed: " + ", ".join(changed) + "; was " + f"{cur['expense_date']} MVR {cur['amount_mvr']}",
                      old=cur["amount_mvr"], new=v.get("amount_mvr", cur["amount_mvr"]))
            db().commit()
        except Exception:
            db().rollback()
            if new_file: store.delete("receipts", new_file)
            raise
        if drop:
            try: store.delete("receipts", drop)
            except Exception: pass   # an orphaned file is harmless; the row no longer points to it
        return jsonify(ok=True, changed=changed)

    @app.delete("/api/expenses/<int:eid>")
    @auth("admin", perm=AREA)
    def exp_delete(eid):
        cur = one(BASE + " WHERE e.id=?", (eid,))
        if not cur: return err("Expense not found", 404)
        row = one("SELECT receipt_file FROM expenses WHERE id=?", (eid,))
        db().execute("DELETE FROM expenses WHERE id=?", (eid,))
        audit("expense_delete", "expense", eid, f"{cur['expense_date']} {cur['category']} MVR {cur['amount_mvr']} {cur['description'] or ''}".strip(), old=cur["amount_mvr"]); db().commit()
        if row["receipt_file"]:
            try: store.delete("receipts", row["receipt_file"])
            except Exception: pass
        return jsonify(ok=True)

    @app.get("/api/expenses/<int:eid>/receipt")
    @auth("admin", perm=AREA)
    def exp_receipt(eid):
        e = one("SELECT id,receipt_file,receipt_name FROM expenses WHERE id=?", (eid,))
        if not e: return err("Expense not found", 404)
        if not e["receipt_file"]: return err("This expense has no receipt", 404)
        audit("view_expense_receipt", "expense", eid, g.user["role"]); db().commit()
        return common.file_headers(store.send("receipts", e["receipt_file"], e["receipt_name"] or e["receipt_file"], as_attachment=True), e["receipt_name"] or e["receipt_file"], attachment=True)

    # ---------- Session 24: revenue and the financial dashboard ----------
    # Revenue is ONLY money that really came in: rows of `payments` that are not reversed, counted on the day paid (paid_on).
    # v0.8.35 (decision): payments on a voided invoice are not revenue either (voiding already requires reversing payments first).
    # Invoices are never revenue; they only feed "outstanding". Course, batch and tuition class come from the payment's invoice.
    # v0.8.45: LEFT JOINs (manual invoices may have no course or batch); rt = the invoice's revenue type
    RT_JOIN = " LEFT JOIN revenue_types rt ON rt.id=COALESCE(i.revenue_type_id, (SELECT r2.id FROM revenue_types r2 WHERE r2.code=i.kind))"
    PAID_FROM = "FROM payments p JOIN invoices i ON i.id=p.invoice_id LEFT JOIN courses c ON c.id=i.course_id LEFT JOIN batches b ON b.id=i.batch_id" + RT_JOIN
    OWED = "CASE WHEN i.amount_due_mvr-i.waived_mvr-i.paid_mvr>0 THEN i.amount_due_mvr-i.waived_mvr-i.paid_mvr ELSE 0 END"   # same rule as payments.balance()

    def span(a):
        """(date_from, date_to) as ISO strings or None; raises ValueError."""
        out = []
        for k in ("date_from", "date_to"):
            out.append(iso(a[k], "Date").isoformat() if a.get(k) else None)
        if out[0] and out[1] and out[0] > out[1]: raise ValueError("The start date is after the end date")
        return out

    def scope(a):
        """Filters on the invoice's course / batch / batch teacher / kind -> (sql conditions, args)."""
        w, args = [], []
        for key, col in (("course_id", "i.course_id"), ("batch_id", "i.batch_id"), ("teacher_id", "b.teacher_id")):
            if a.get(key):
                try: args.append(int(a[key]))
                except ValueError: raise ValueError("Bad " + key.replace("_", " "))
                w.append(f"{col}=?")
        if a.get("revenue_type"):   # v0.8.45
            try: args.append(int(a["revenue_type"]))
            except ValueError: raise ValueError("Bad revenue type")
            w.append("rt.id=?")
        if a.get("kind"):
            if a["kind"] not in ("course", "tuition"): raise ValueError("kind must be course or tuition")
            w.append("c.kind=?"); args.append(a["kind"])
        return w, args

    def paid_where(a, reversed_=False):
        d1, d2 = span(a); w, args = scope(a)
        w.append("p.reversed_at IS NOT NULL" if reversed_ else "p.reversed_at IS NULL AND i.status<>'void'")   # v0.8.35: a voided invoice is never revenue
        if d1: w.append("p.paid_on>=?"); args.append(d1)
        if d2: w.append("p.paid_on<=?"); args.append(d2)
        return " WHERE " + " AND ".join(w), tuple(args)

    def collected(a):
        w, args = paid_where(a)
        r = one("SELECT COALESCE(SUM(p.amount_mvr),0) s, COUNT(*) n " + PAID_FROM + w, args)
        return int(r["s"]), r["n"]

    def outstanding(a):
        w, args = scope(a)
        w.append("i.status<>'void'")
        return int(one(f"SELECT COALESCE(SUM({OWED}),0) s FROM invoices i LEFT JOIN courses c ON c.id=i.course_id LEFT JOIN batches b ON b.id=i.batch_id" + RT_JOIN + " WHERE " + " AND ".join(w), tuple(args))["s"])

    def expenses_total(d1, d2):
        w, args = [], []
        if d1: w.append("expense_date>=?"); args.append(d1)
        if d2: w.append("expense_date<=?"); args.append(d2)
        return int(one("SELECT COALESCE(SUM(amount_mvr),0) s FROM expenses" + (" WHERE " + " AND ".join(w) if w else ""), tuple(args))["s"])

    @app.get("/api/finance/revenue")
    @auth("admin", perm=AREA)
    def fin_revenue():
        a = request.args
        try: w, args = paid_where(a); wr, ar = paid_where(a, True); out = outstanding(a)
        except ValueError as x: return err(str(x))
        total, n = collected(a)
        grp = lambda cols, by: rows(f"SELECT {cols}, SUM(p.amount_mvr) AS collected, COUNT(*) AS payments " + PAID_FROM + w + f" GROUP BY {by} ORDER BY collected DESC", args)
        by_course = grp("c.id AS course_id, c.name AS course_name, c.kind", "c.id, c.name, c.kind")
        by_batch = grp("b.id AS batch_id, b.code AS batch_code, c.id AS course_id, c.name AS course_name, c.kind", "b.id, b.code, c.id, c.name, c.kind")
        by_month = rows("SELECT SUBSTR(p.paid_on,1,7) AS month, SUM(p.amount_mvr) AS collected, COUNT(*) AS payments " + PAID_FROM + w + " GROUP BY SUBSTR(p.paid_on,1,7) ORDER BY month", args)
        by_type = grp("rt.id AS revenue_type, rt.name AS revenue_type_name", "rt.id, rt.name")   # v0.8.45
        kinds = {"course": 0, "tuition": 0}
        for r in by_course:
            k = r["kind"] if r["kind"] in kinds else "other"   # v0.8.45: manual invoices without a course
            kinds[k] = kinds.get(k, 0) + int(r["collected"])
        rev = int(one("SELECT COALESCE(SUM(p.amount_mvr),0) s " + PAID_FROM + wr, ar)["s"])
        return jsonify(total_collected=total, payment_count=n, outstanding=out, reversed_not_counted=rev, by_kind=kinds, by_type=by_type, by_course=by_course, by_batch=by_batch, by_month=by_month,
                       note="Revenue = payments received (reversed payments and payments on voided invoices excluded), by the day paid. Outstanding = unpaid balance of all non-void invoices in the same course/batch/kind filter, whatever the dates.")

    @app.get("/api/finance/dashboard")
    @auth("admin", perm=AREA)
    def fin_dashboard():
        if "recurring" in app.extensions: app.extensions["recurring"]()   # v0.8.37
        a = request.args.to_dict()
        t = today()
        if not a.get("date_from") and not a.get("date_to"): a["date_from"], a["date_to"] = t.replace(day=1).isoformat(), t.isoformat()   # default: this month so far
        try: d1, d2 = span(a); rev, _ = collected({"date_from": d1, "date_to": d2}); out = outstanding({})
        except ValueError as x: return err(str(x))
        exp = expenses_total(d1, d2)
        months, y, m = [], t.year, t.month
        for _ in range(12):
            first = dt.date(y, m, 1); last = dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)
            r_, e_ = collected({"date_from": first.isoformat(), "date_to": last.isoformat()})[0], expenses_total(first.isoformat(), last.isoformat())
            months.append({"month": f"{y:04d}-{m:02d}", "revenue": r_, "expenses": e_, "net": r_ - e_})
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        ex = app.extensions["earnings"]; ap = ex["approved_in"]((d1 or "0000-00")[:7], (d2 or "9999-12")[:7])
        return jsonify(date_from=d1, date_to=d2, revenue=rev, expenses=exp, net=rev - exp, outstanding_fees=out, months=list(reversed(months)),
                       teacher_earnings=int(ap["t"]), academy_revenue=int(ap["a"]), teacher_paid=ex["paid_in"](d1, d2),   # Session 31: approved months only (a month needs approval first)
                       earnings_note="Teacher earnings and academy share come from approved months inside the dates; registration fees are not part of them.")

    app.extensions["finance"] = {"collected": collected, "outstanding": outstanding, "expenses_total": expenses_total}   # Session 25: the admin dashboard reuses these
