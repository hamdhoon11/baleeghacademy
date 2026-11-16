"""v0.8.58: Teachers' room. A private place for staff: a group chat and a shared teachers' guide (files and links to teach from).

Who:   teachers and admins with the area "staff_room" (part of "everything" for both roles). Students never reach any route here.
Head:  an admin marks one or more teachers as head teacher (teachers.is_head). A head teacher, like an admin, moderates:
         - pins and unpins messages (pinned messages stay at the top; teachers get a notification),
         - deletes anyone's message,
         - creates, renames, locks and deletes guide folders (a LOCKED folder takes files from head teachers and admins only),
         - edits and deletes anyone's guide file.
       Every other member posts, replies, attaches files, edits and deletes their OWN messages and guide files.
Files: stored in the private "learning" area like class materials; every download goes through a route here that checks the person.

  GET    /api/staff/room                       who I am in the room (can_moderate), members, head teachers
  GET    /api/staff/messages?before=ID|after=ID   the latest 50 (or 50 older than ID / everything newer than ID), oldest first, plus pinned
  POST   /api/staff/messages                   {body, reply_to} or multipart with file
  PATCH  /api/staff/messages/<id>              {body}  own message only
  DELETE /api/staff/messages/<id>              own, or any for a head teacher / admin (soft: the text and file are removed)
  POST   /api/staff/messages/<id>/pin          {pinned: true|false}  head teacher / admin
  GET    /api/staff/messages/<id>/file
  GET    /api/staff/folders                    folders with file counts
  POST   /api/staff/folders                    {name, description, locked}  head teacher / admin
  PATCH  /api/staff/folders/<id>               head teacher / admin
  DELETE /api/staff/folders/<id>               head teacher / admin, empty folders only
  GET    /api/staff/files?folder_id=&q=
  POST   /api/staff/files                      multipart {title, description, folder_id, file} or {.., url}
  PATCH  /api/staff/files/<id>                 {title, description, folder_id}  own, or head teacher / admin
  DELETE /api/staff/files/<id>                 own, or head teacher / admin
  GET    /api/staff/files/<id>/file
  POST   /api/staff/head                       {user_id, is_head}  admins only: make or unmake a head teacher
"""
import os, re, uuid

from flask import g, jsonify, request

import common
from learning import ALLOWED_MATERIAL, magic_ok

AREA = "staff_room"
PAGE = 50
MAX_BODY = 4000


def register(app, c):
    db, rows, one, audit, err, auth, store = c.db, c.rows, c.one, c.audit, c.err, c.auth, c.store
    ROOM = auth("admin", "teacher", perm=AREA)

    # ---------- who may do what ----------
    def is_head(uid):
        r = one("SELECT t.is_head FROM teachers t JOIN users u ON u.id=t.user_id WHERE t.user_id=? AND u.role='teacher' AND u.is_active=1", (uid,))
        return bool(r and r["is_head"])

    def moderator():
        u = g.user
        return u["role"] == "admin" or is_head(u["id"])

    def members():
        """Everyone who can open the room: active teachers and admins whose permissions include the area."""
        us = rows("SELECT u.id,u.full_name,u.role,u.permissions,COALESCE(t.is_head,0) AS is_head FROM users u LEFT JOIN teachers t ON t.user_id=u.id "
                  "WHERE u.role IN ('teacher','admin') AND u.is_active=1 ORDER BY u.role DESC, u.full_name")
        return [u for u in us if c.has_perm(u, AREA)]

    def body():
        return request.form if request.form else (request.get_json(silent=True) or {})

    def save(f):
        if not f or not f.filename: raise ValueError("A file is required")
        ext = os.path.splitext(f.filename.lower())[1]
        if ext not in ALLOWED_MATERIAL: raise ValueError("This file type is not allowed. Allowed: " + ", ".join(ALLOWED_MATERIAL))
        mb = common.cap_mb(int(app.config.get("LEARNING_MAX_MB", 20)))
        data = f.read(mb * 1024 * 1024 + 1)
        if len(data) > mb * 1024 * 1024: raise ValueError(f"File is too large ({mb} MB max)")
        if not magic_ok(ext, data[:16]): raise ValueError("File content does not match its type")
        name = uuid.uuid4().hex + ext
        store.put("learning", name, data)
        return name, common.shown_name(f.filename)

    def rm(name):
        if name: store.delete("learning", name)

    def send(stored, shown):
        return common.file_headers(store.send("learning", stored, shown or stored, as_attachment=True), shown or stored, attachment=True)

    # ---------- room ----------
    @app.get("/api/staff/room")
    @ROOM
    def sr_room():
        ms = members()
        return jsonify(me={"id": g.user["id"], "can_moderate": moderator(), "is_admin": g.user["role"] == "admin", "is_head": is_head(g.user["id"])},
                       members=[{"id": m["id"], "full_name": m["full_name"], "role": m["role"], "is_head": bool(m["is_head"]) and m["role"] == "teacher"} for m in ms],
                       teachers=[{"id": u["id"], "full_name": u["full_name"], "is_head": bool(u["is_head"])} for u in
                                 rows("SELECT u.id,u.full_name,COALESCE(t.is_head,0) AS is_head FROM users u LEFT JOIN teachers t ON t.user_id=u.id "
                                      "WHERE u.role='teacher' AND u.is_active=1 ORDER BY u.full_name")] if g.user["role"] == "admin" else [])

    @app.post("/api/staff/head")
    @auth("admin", perm=AREA)
    def sr_head():
        d = request.get_json(silent=True) or {}
        u = one("SELECT u.id,u.full_name,u.is_active FROM users u WHERE u.id=? AND u.role='teacher'", (d.get("user_id"),))
        if not u: return err("Teacher not found", 404)
        on = 1 if d.get("is_head") in (True, 1, "1", "true") else 0
        old = one("SELECT is_head FROM teachers WHERE user_id=?", (u["id"],))
        if old is None: db().execute("INSERT INTO teachers(user_id,is_head) VALUES(?,?)", (u["id"], on))
        elif int(old["is_head"] or 0) == on: return jsonify(ok=True, changed=False)
        else: db().execute("UPDATE teachers SET is_head=? WHERE user_id=?", (on, u["id"]))
        audit("staff_head_set" if on else "staff_head_unset", "user", u["id"], u["full_name"], old=0 if on else 1, new=on)
        if on: c.notify([u["id"]], "staff_room", "You are now a head teacher", "You can pin messages, manage the teachers' guide folders and remove messages in the Teachers' room.", "staff_room")
        db().commit()
        return jsonify(ok=True, changed=True)

    # ---------- chat ----------
    MQ = ("SELECT m.id,m.user_id,m.body,m.file_name,m.reply_to,m.pinned_at,m.edited_at,m.deleted_at,m.created_at,u.full_name AS author,u.role AS author_role,"
          "COALESCE(t.is_head,0) AS author_head,r.body AS reply_body,r.deleted_at AS reply_deleted,ru.full_name AS reply_author "
          "FROM staff_messages m JOIN users u ON u.id=m.user_id LEFT JOIN teachers t ON t.user_id=m.user_id "
          "LEFT JOIN staff_messages r ON r.id=m.reply_to LEFT JOIN users ru ON ru.id=r.user_id")

    def shape(m, mod):
        me = g.user["id"]
        x = dict(m)
        x["has_file"] = bool(m["file_name"]) and not m["deleted_at"]
        x["author_head"] = bool(m["author_head"]) and m["author_role"] == "teacher"
        x["mine"] = m["user_id"] == me
        x["can_edit"] = x["mine"] and not m["deleted_at"]
        x["can_delete"] = (x["mine"] or mod) and not m["deleted_at"]
        x["reply_body"] = None if m["reply_deleted"] else (m["reply_body"] or "")[:140] if m["reply_to"] else None
        x.pop("reply_deleted", None)
        if m["deleted_at"]: x["body"], x["file_name"] = None, None
        return x

    @app.get("/api/staff/messages")
    @ROOM
    def sr_messages():
        mod = moderator()
        before, after = request.args.get("before", type=int), request.args.get("after", type=int)
        if after is not None:
            ms = rows(MQ + " WHERE m.id>? ORDER BY m.id LIMIT 200", (after,))
        elif before:
            ms = list(reversed(rows(MQ + " WHERE m.id<? ORDER BY m.id DESC LIMIT ?", (before, PAGE))))
        else:
            ms = list(reversed(rows(MQ + " ORDER BY m.id DESC LIMIT ?", (PAGE,))))
        pinned = rows(MQ + " WHERE m.pinned_at IS NOT NULL AND m.deleted_at IS NULL ORDER BY m.pinned_at DESC LIMIT 20")
        oldest = ms[0]["id"] if ms else None
        more = bool(oldest and one("SELECT 1 AS x FROM staff_messages WHERE id<? LIMIT 1", (oldest,)))
        # a cheap fingerprint of edits, deletes and pins, so a page that polls only redraws when something changed
        sig = one("SELECT COUNT(*) AS n, MAX(id) AS last, MAX(COALESCE(edited_at,'')) AS e, MAX(COALESCE(deleted_at,'')) AS d, MAX(COALESCE(pinned_at,'')) AS p, "
                  "COUNT(pinned_at) AS np FROM staff_messages")
        return jsonify(messages=[shape(m, mod) for m in ms], pinned=[shape(m, mod) for m in pinned], more=more, can_moderate=mod,
                       signature="|".join(str(sig[k] or "") for k in ("n", "last", "e", "d", "p", "np")))

    @app.post("/api/staff/messages")
    @ROOM
    def sr_post():
        d = body()
        text = (d.get("body") or "").strip()
        f = request.files.get("file")
        if not text and not (f and f.filename): return err("Write a message or attach a file")
        if len(text) > MAX_BODY: return err(f"A message can be at most {MAX_BODY} characters")
        reply = None
        if d.get("reply_to"):
            try: reply = int(d["reply_to"])
            except (TypeError, ValueError): return err("Reply not found", 404)
            if not one("SELECT id FROM staff_messages WHERE id=? AND deleted_at IS NULL", (reply,)): return err("The message you replied to was removed", 404)
        stored = shown = None
        if f and f.filename:
            try: stored, shown = save(f)
            except ValueError as x: return err(str(x))
        mid = db().execute("INSERT INTO staff_messages(user_id,body,file,file_name,reply_to,created_at) VALUES(?,?,?,?,?,?)",
                           (g.user["id"], text or None, stored, shown, reply, c.utc_stamp())).lastrowid
        if stored: audit("staff_message_file", "staff_message", mid, shown)
        db().commit()
        return jsonify(id=mid), 201

    def msg_or_404(mid):
        return one("SELECT * FROM staff_messages WHERE id=?", (mid,))

    @app.patch("/api/staff/messages/<int:mid>")
    @ROOM
    def sr_edit(mid):
        m = msg_or_404(mid)
        if not m or m["deleted_at"]: return err("Message not found", 404)
        if m["user_id"] != g.user["id"]: return err("You can only edit your own messages", 403)
        text = ((request.get_json(silent=True) or {}).get("body") or "").strip()
        if not text and not m["file"]: return err("A message cannot be empty. Delete it instead.")
        if len(text) > MAX_BODY: return err(f"A message can be at most {MAX_BODY} characters")
        if text == (m["body"] or ""): return jsonify(ok=True, changed=False)
        db().execute("UPDATE staff_messages SET body=?, edited_at=? WHERE id=?", (text or None, c.utc_stamp(), mid)); db().commit()
        return jsonify(ok=True, changed=True)

    @app.delete("/api/staff/messages/<int:mid>")
    @ROOM
    def sr_delete(mid):
        m = msg_or_404(mid)
        if not m or m["deleted_at"]: return err("Message not found", 404)
        own = m["user_id"] == g.user["id"]
        if not own and not moderator(): return err("Only the head teacher or an admin can remove other people's messages", 403)
        db().execute("UPDATE staff_messages SET body=NULL, file=NULL, file_name=NULL, pinned_at=NULL, pinned_by=NULL, deleted_at=?, deleted_by=? WHERE id=?",
                     (c.utc_stamp(), g.user["id"], mid))
        if not own:   # removing someone else's words is a moderation step: keep a record of what it said
            author = one("SELECT full_name FROM users WHERE id=?", (m["user_id"],))
            audit("staff_message_remove", "staff_message", mid, f"by {author['full_name'] if author else m['user_id']}: {(m['body'] or m['file_name'] or '')[:200]}")
        db().commit()
        rm(m["file"])
        return jsonify(ok=True)

    @app.post("/api/staff/messages/<int:mid>/pin")
    @ROOM
    def sr_pin(mid):
        if not moderator(): return err("Only the head teacher or an admin can pin messages", 403)
        m = msg_or_404(mid)
        if not m or m["deleted_at"]: return err("Message not found", 404)
        on = (request.get_json(silent=True) or {}).get("pinned", True) in (True, 1, "1", "true")
        if bool(m["pinned_at"]) == on: return jsonify(ok=True, changed=False)
        db().execute("UPDATE staff_messages SET pinned_at=?, pinned_by=? WHERE id=?", (c.utc_stamp() if on else None, g.user["id"] if on else None, mid))
        audit("staff_pin" if on else "staff_unpin", "staff_message", mid, (m["body"] or m["file_name"] or "")[:200])
        if on:
            who = [x["id"] for x in members() if x["id"] != g.user["id"]]
            c.notify(who, "staff_room", f"Pinned in the Teachers' room by {g.user['full_name']}", (m["body"] or m["file_name"] or "")[:300], "staff_room", f"staffpin:{mid}")
        db().commit()
        return jsonify(ok=True, changed=True)

    @app.get("/api/staff/messages/<int:mid>/file")
    @ROOM
    def sr_msg_file(mid):
        m = msg_or_404(mid)
        if not m or m["deleted_at"] or not m["file"]: return err("File not found", 404)
        return send(m["file"], m["file_name"])

    # ---------- teachers' guide: folders ----------
    def folder_fields(d, creating):
        out = {}
        if creating or "name" in d:
            name = (d.get("name") or "").strip()
            if not name: return None, "Give the folder a name"
            if len(name) > 80: return None, "A folder name can be at most 80 characters"
            out["name"] = name
        if "description" in d: out["description"] = (d.get("description") or "").strip()[:500] or None
        if creating or "locked" in d: out["locked"] = 1 if d.get("locked") in (True, 1, "1", "true", "on") else 0
        return out, None

    @app.get("/api/staff/folders")
    @ROOM
    def sr_folders():
        fs = rows("SELECT f.id,f.name,f.description,f.locked,f.created_at,u.full_name AS created_by_name,"
                  "(SELECT COUNT(*) FROM staff_files x WHERE x.folder_id=f.id) AS files FROM staff_folders f LEFT JOIN users u ON u.id=f.created_by ORDER BY f.name")
        loose = one("SELECT COUNT(*) AS n FROM staff_files WHERE folder_id IS NULL")["n"]
        mod = moderator()
        return jsonify(folders=[{**f, "locked": bool(f["locked"]), "can_add": mod or not f["locked"]} for f in fs], unfiled=loose, can_moderate=mod)

    @app.post("/api/staff/folders")
    @ROOM
    def sr_folder_add():
        if not moderator(): return err("Only the head teacher or an admin can create folders", 403)
        v, m = folder_fields(request.get_json(silent=True) or {}, True)
        if m: return err(m)
        if one("SELECT id FROM staff_folders WHERE LOWER(name)=LOWER(?)", (v["name"],)): return err("A folder with that name already exists", 409)
        fid = db().execute("INSERT INTO staff_folders(name,description,locked,created_by,created_at) VALUES(?,?,?,?,?)",
                           (v["name"], v.get("description"), v["locked"], g.user["id"], c.utc_stamp())).lastrowid
        audit("staff_folder_create", "staff_folder", fid, v["name"] + (" (locked)" if v["locked"] else "")); db().commit()
        return jsonify(id=fid), 201

    @app.patch("/api/staff/folders/<int:fid>")
    @ROOM
    def sr_folder_edit(fid):
        if not moderator(): return err("Only the head teacher or an admin can change folders", 403)
        f = one("SELECT * FROM staff_folders WHERE id=?", (fid,))
        if not f: return err("Folder not found", 404)
        v, m = folder_fields(request.get_json(silent=True) or {}, False)
        if m: return err(m)
        if not v: return err("Nothing to update")
        if "name" in v and one("SELECT id FROM staff_folders WHERE LOWER(name)=LOWER(?) AND id<>?", (v["name"], fid)): return err("A folder with that name already exists", 409)
        db().execute(f"UPDATE staff_folders SET {','.join(k + '=?' for k in v)} WHERE id=?", (*v.values(), fid))
        audit("staff_folder_update", "staff_folder", fid, "; ".join(f"{k}: {f[k]} -> {v[k]}" for k in v if str(f[k]) != str(v[k])) or "no change"); db().commit()
        return jsonify(ok=True)

    @app.delete("/api/staff/folders/<int:fid>")
    @ROOM
    def sr_folder_del(fid):
        if not moderator(): return err("Only the head teacher or an admin can delete folders", 403)
        f = one("SELECT * FROM staff_folders WHERE id=?", (fid,))
        if not f: return err("Folder not found", 404)
        if one("SELECT 1 AS x FROM staff_files WHERE folder_id=? LIMIT 1", (fid,)): return err("Move or delete the files in this folder first", 409)
        db().execute("DELETE FROM staff_folders WHERE id=?", (fid,))
        audit("staff_folder_delete", "staff_folder", fid, f["name"]); db().commit()
        return jsonify(ok=True)

    # ---------- teachers' guide: files ----------
    def folder_ok(fid, mod):
        """None when fid may receive files from this person, else an error response."""
        if fid in (None, "", 0, "0"): return None
        f = one("SELECT locked FROM staff_folders WHERE id=?", (fid,))
        if not f: return err("Folder not found", 404)
        if f["locked"] and not mod: return err("Only the head teacher or an admin can add files to this folder", 403)
        return None

    def as_fid(v):
        try: return int(v) if v not in (None, "", "0", 0) else None
        except (TypeError, ValueError): return -1

    @app.get("/api/staff/files")
    @ROOM
    def sr_files():
        mod, me = moderator(), g.user["id"]
        w, a = [], []
        fid = request.args.get("folder_id")
        if fid == "none": w.append("x.folder_id IS NULL")
        elif fid: w.append("x.folder_id=?"); a.append(as_fid(fid))
        q = (request.args.get("q") or "").strip()[:100]
        if q:
            w.append("(LOWER(x.title) LIKE ? OR LOWER(COALESCE(x.description,'')) LIKE ? OR LOWER(COALESCE(x.file_name,'')) LIKE ?)")
            a += [f"%{q.lower()}%"] * 3
        fs = rows("SELECT x.id,x.folder_id,x.title,x.description,x.kind,x.file_name,x.url,x.uploaded_by,x.created_at,x.updated_at,u.full_name AS uploader,f.name AS folder_name "
                  "FROM staff_files x LEFT JOIN users u ON u.id=x.uploaded_by LEFT JOIN staff_folders f ON f.id=x.folder_id"
                  + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY x.id DESC LIMIT 300", a)
        return jsonify([{**x, "can_edit": mod or x["uploaded_by"] == me} for x in fs])

    @app.post("/api/staff/files")
    @ROOM
    def sr_file_add():
        d, mod = body(), moderator()
        title = (d.get("title") or "").strip()
        if not title: return err("Give the file a title")
        fid = as_fid(d.get("folder_id"))
        if fid == -1: return err("Folder not found", 404)
        e = folder_ok(fid, mod)
        if e: return e
        url, up = (d.get("url") or "").strip(), request.files.get("file")
        if bool(url) == bool(up and up.filename): return err("Add either a file or a link")
        stored = shown = None
        if url:
            if not re.match(r"^https?://\S+$", url): return err("The link must start with http:// or https://")
        else:
            try: stored, shown = save(up)
            except ValueError as x: return err(str(x))
        xid = db().execute("INSERT INTO staff_files(folder_id,title,description,kind,file,file_name,url,uploaded_by,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                           (fid, title[:160], (d.get("description") or "").strip()[:1000] or None, "link" if url else "file", stored, shown, url or None,
                            g.user["id"], c.utc_stamp())).lastrowid
        audit("staff_file_add", "staff_file", xid, title[:160]); db().commit()
        return jsonify(id=xid), 201

    def file_for_change(xid):
        x = one("SELECT * FROM staff_files WHERE id=?", (xid,))
        if not x: return None, err("File not found", 404)
        if x["uploaded_by"] != g.user["id"] and not moderator(): return None, err("Only the person who added it, the head teacher or an admin can change this", 403)
        return x, None

    @app.patch("/api/staff/files/<int:xid>")
    @ROOM
    def sr_file_edit(xid):
        x, e = file_for_change(xid)
        if e: return e
        d, v = request.get_json(silent=True) or {}, {}
        if "title" in d:
            if not (d["title"] or "").strip(): return err("Give the file a title")
            v["title"] = d["title"].strip()[:160]
        if "description" in d: v["description"] = (d["description"] or "").strip()[:1000] or None
        if "folder_id" in d:
            fid = as_fid(d["folder_id"])
            if fid == -1: return err("Folder not found", 404)
            if fid != x["folder_id"]:
                e = folder_ok(fid, moderator())
                if e: return e
            v["folder_id"] = fid
        if not v: return err("Nothing to update")
        db().execute(f"UPDATE staff_files SET {','.join(k + '=?' for k in v)}, updated_at=?, updated_by=? WHERE id=?", (*v.values(), c.utc_stamp(), g.user["id"], xid))
        audit("staff_file_update", "staff_file", xid, "; ".join(f"{k}: {x[k]} -> {v[k]}" for k in v if str(x[k]) != str(v[k])) or "no change"); db().commit()
        return jsonify(ok=True)

    @app.delete("/api/staff/files/<int:xid>")
    @ROOM
    def sr_file_del(xid):
        x, e = file_for_change(xid)
        if e: return e
        db().execute("DELETE FROM staff_files WHERE id=?", (xid,))
        audit("staff_file_delete", "staff_file", xid, f"{x['title']}" + (f" (added by user {x['uploaded_by']})" if x["uploaded_by"] != g.user["id"] else "")); db().commit()
        rm(x["file"])
        return jsonify(ok=True)

    @app.get("/api/staff/files/<int:xid>/file")
    @ROOM
    def sr_file_get(xid):
        x = one("SELECT * FROM staff_files WHERE id=?", (xid,))
        if not x or not x["file"]: return err("File not found", 404)
        return send(x["file"], x["file_name"])
