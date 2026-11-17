"""v0.8.60: Interest list. A note of people who want to join a batch that has not started (or is full), batch by batch, before they apply or
are enrolled. Only a reference: nothing here creates an account, an enrolment or an invoice.

Who: admins with the "admissions" area (the tab sits next to Admissions).

  GET    /api/interest?batch_id=&status=&q=      entries (newest batch first) and the batches to choose from, each with its count
  POST   /api/interest                           {batch_id, full_name, id_card, phone, email, notes}
  PATCH  /api/interest/<id>                      any of those, and status (waiting, contacted, joined, not_joining)
  DELETE /api/interest/<id>
  GET    /api/interest/report.pdf?batch_id=&status=   the same list as a PDF, one section per batch
"""
import re

from flask import g, jsonify, request

STATUSES = ("waiting", "contacted", "joined", "not_joining")
STATUS_LABEL = {"waiting": "New", "contacted": "Contacted", "joined": "Joined", "not_joining": "Not joining"}
ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-/]{2,19}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def phone_problem(p):
    if not p: return "Enter a contact number"
    if len(p) > 30 or not re.fullmatch(r"\+?[\d\s\-()]{7,}", p) or len(re.sub(r"\D", "", p)) < 7:
        return "Enter a valid contact number (at least 7 digits), like 7771234 or +960 7771234"
    return None


def register(app, c):
    db, rows, one, audit, err, auth = c.db, c.rows, c.one, c.audit, c.err, c.auth
    WL = auth("admin", perm="admissions")

    BQ = ("SELECT b.id,b.code,b.days,b.start_time,b.end_time,b.start_date,b.status,b.capacity,c.name AS course_name,u.full_name AS teacher_name,"
          "(SELECT COUNT(*) FROM enrollments e WHERE e.batch_id=b.id AND e.status='active') AS enrolled,"
          "(SELECT COUNT(*) FROM interest_list w WHERE w.batch_id=b.id) AS waiting_all,"
          "(SELECT COUNT(*) FROM interest_list w WHERE w.batch_id=b.id AND w.status IN ('waiting','contacted')) AS waiting "
          "FROM batches b JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=b.teacher_id")

    def batches():
        # batches still to come or still taking people first, then the rest (a closed batch is listed only while it has names on it)
        bs = rows(BQ + " ORDER BY CASE b.status WHEN 'open' THEN 0 WHEN 'running' THEN 1 ELSE 2 END, COALESCE(b.start_date,'9999') , c.name, b.code")
        return [b for b in bs if b["status"] != "closed" or b["waiting_all"]]

    def clean(d, creating, old=None):
        v = {}
        if creating or "full_name" in d:
            n = re.sub(r"\s+", " ", str(d.get("full_name") or "")).strip()
            if not n: return None, "Enter the name"
            if len(n) > 120: return None, "The name can be at most 120 characters"
            v["full_name"] = n
        if creating or "id_card" in d:
            i = re.sub(r"\s+", "", str(d.get("id_card") or "")).upper()
            if not i: return None, "Enter the ID card number"
            if not ID_RE.match(i): return None, "Enter a valid ID card or passport number, like A123456"
            v["id_card"] = i
        if creating or "phone" in d:
            p = str(d.get("phone") or "").strip()
            m = phone_problem(p)
            if m: return None, m
            v["phone"] = p
        if "email" in d:
            e = str(d.get("email") or "").strip().lower()
            if e and (len(e) > 120 or not EMAIL_RE.match(e)): return None, "Enter a valid email, or leave it empty"
            v["email"] = e or None
        if "notes" in d: v["notes"] = (str(d.get("notes") or "").strip()[:1000]) or None
        if creating or "batch_id" in d:
            b = d.get("batch_id")
            if b in (None, "", 0, "0"): return None, "Choose the batch"
            bb = one("SELECT id,status FROM batches WHERE id=?", (b,))
            if not bb: return None, "Batch not found"
            if bb["status"] == "closed" and (creating or (old and old["batch_id"] != bb["id"])): return None, "That batch is closed. Choose another one."
            v["batch_id"] = bb["id"]
        if "status" in d:
            if d["status"] not in STATUSES: return None, "Unknown status"
            v["status"] = d["status"]
        return v, None

    def entries(batch_id=None, status=None, q=None):
        w, a = [], []
        if batch_id: w.append("w.batch_id=?"); a.append(batch_id)
        if status == "active": w.append("w.status IN ('waiting','contacted')")
        elif status in STATUSES: w.append("w.status=?"); a.append(status)
        if q:
            w.append("(LOWER(w.full_name) LIKE ? OR LOWER(w.id_card) LIKE ? OR w.phone LIKE ? OR LOWER(COALESCE(w.email,'')) LIKE ?)")
            a += [f"%{q.lower()}%"] * 4
        return rows("SELECT w.*,u.full_name AS added_by FROM interest_list w LEFT JOIN users u ON u.id=w.created_by"
                    + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY w.batch_id, w.id", a)

    def args():
        b = request.args.get("batch_id", type=int)
        s = request.args.get("status") or None
        if s and s != "active" and s not in STATUSES: s = None
        return b, s, (request.args.get("q") or "").strip()[:100]

    @app.get("/api/interest")
    @WL
    def wl_list():
        b, s, q = args()
        return jsonify(entries=entries(b, s, q), batches=batches(), statuses=list(STATUSES))

    @app.post("/api/interest")
    @WL
    def wl_add():
        v, m = clean(request.get_json(silent=True) or {}, True)
        if m: return err(m)
        dup = one("SELECT id FROM interest_list WHERE batch_id=? AND id_card=?", (v["batch_id"], v["id_card"]))
        if dup: return err("This ID card number is already on the list for this batch", 409)
        wid = db().execute("INSERT INTO interest_list(batch_id,full_name,id_card,phone,email,notes,status,created_by,created_at) VALUES(?,?,?,?,?,?,'waiting',?,?)",
                           (v["batch_id"], v["full_name"], v["id_card"], v["phone"], v.get("email"), v.get("notes"), g.user["id"], c.utc_stamp())).lastrowid
        audit("interest_add", "interest", wid, f"{v['full_name']} ({v['id_card']}) for batch {v['batch_id']}"); db().commit()
        return jsonify(id=wid), 201

    @app.patch("/api/interest/<int:wid>")
    @WL
    def wl_edit(wid):
        old = one("SELECT * FROM interest_list WHERE id=?", (wid,))
        if not old: return err("Not found", 404)
        v, m = clean(request.get_json(silent=True) or {}, False, old)
        if m: return err(m)
        v = {k: x for k, x in v.items() if old[k] != x}
        if not v: return jsonify(ok=True, changed=False)
        if one("SELECT id FROM interest_list WHERE batch_id=? AND id_card=? AND id<>?", (v.get("batch_id", old["batch_id"]), v.get("id_card", old["id_card"]), wid)):
            return err("This ID card number is already on the list for this batch", 409)
        db().execute(f"UPDATE interest_list SET {','.join(k + '=?' for k in v)}, updated_at=? WHERE id=?", (*v.values(), c.utc_stamp(), wid))
        audit("interest_update", "interest", wid, f"{old['full_name']}: " + "; ".join(f"{k}: {old[k]} -> {v[k]}" for k in v)); db().commit()
        return jsonify(ok=True, changed=True)

    @app.delete("/api/interest/<int:wid>")
    @WL
    def wl_del(wid):
        old = one("SELECT * FROM interest_list WHERE id=?", (wid,))
        if not old: return err("Not found", 404)
        db().execute("DELETE FROM interest_list WHERE id=?", (wid,))
        audit("interest_delete", "interest", wid, f"{old['full_name']} ({old['id_card']}), batch {old['batch_id']}"); db().commit()
        return jsonify(ok=True)

    @app.get("/api/interest/report.pdf")
    @WL
    def wl_pdf():
        b, s, q = args()
        es = entries(b, s, q)
        bs = {x["id"]: x for x in rows(BQ)}
        groups = {}
        for e in es: groups.setdefault(e["batch_id"], []).append(e)
        order = [x["id"] for x in batches() if x["id"] in groups] + [k for k in groups if k not in {x["id"] for x in batches()}]
        if b and b not in groups: order = [b] if b in bs else []
        blocks = [("stats", [("Batches", len(order)), ("People", len(es)),
                             ("New", sum(e["status"] == "waiting" for e in es)), ("Contacted", sum(e["status"] == "contacted" for e in es))])]
        for bid in order:
            x = bs[bid]
            when = " ".join(p for p in [(x["days"] or "").replace(",", ", "), (x["start_time"] or "") + (("–" + x["end_time"]) if x["start_time"] and x["end_time"] else "")] if p)
            blocks.append(("heading", f"{x['course_name']} · {x['code']}"))
            blocks.append(("note", " · ".join(p for p in [when, f"starts {x['start_date']}" if x["start_date"] else "", f"teacher {x['teacher_name']}" if x["teacher_name"] else "",
                                                      f"{x['enrolled']} of {x['capacity']} seats taken", f"{len(groups.get(bid, []))} on this list"] if p)))
            rs = [[i + 1, e["full_name"], e["id_card"], e["phone"], e["email"] or "", STATUS_LABEL[e["status"]], (e["created_at"] or "")[:10], e["notes"] or ""]
                  for i, e in enumerate(groups.get(bid, []))]
            blocks.append(("table", ["#", "Name", "ID card", "Contact", "Email", "Status", "Added", "Notes"], rs or [["", "Nobody on the list", "", "", "", "", "", ""]],
                           {"widths": [3, 18, 10, 11, 16, 8, 8, 26]}))
        if not order: blocks.append(("note", "Nobody on the interest list for this choice."))
        sub = []
        if b and b in bs: sub.append(f"{bs[b]['course_name']} {bs[b]['code']}")
        if s: sub.append("still to join (new or contacted)" if s == "active" else STATUS_LABEL[s])
        if q: sub.append(f'search "{q}"')
        audit("interest_pdf", "interest", None, ", ".join(sub) or "all batches"); db().commit()
        name = "interest-list" + (f"-{bs[b]['code']}" if b and b in bs else "") + ".pdf"
        return app.extensions["pdf"]("Interest list", blocks, re.sub(r"[^\w.\-]+", "-", name), subtitle=" · ".join(sub) or "All batches")
