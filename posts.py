"""v0.8.63: Notice board. Posts and announcements for students (and teachers), with pictures, files, a video link, comments and "Seen by".

Who reads: everyone signed in sees the posts meant for them (no permission needed, like Home):
    everyone  -> all students and all teachers        students -> all students        teachers -> all teachers
    batch     -> the active students of that batch and its teacher
  Admins see every post. A post's author always sees it.
Who writes: area "write_posts" (part of "everything" for admins and teachers; a limited account needs it ticked).
    Admins post to any audience. Teachers post only to a batch they teach.
    The author, or an admin with the area, edits, pins, deletes, adds or removes files and sees who has read it.
Comments: anyone who can see a post can comment when the post allows it. You delete your own; the author and admins delete any.
    The author gets a notification for a comment.
Read: the board marks the posts it shows as read (POST /api/posts/read). "Seen by" lists the people the post is for, read or not.
Video: a YouTube, Google Drive or Vimeo link plays inside the post; any other https link is shown as a link. No video uploads (size limits).
Files: up to 6 per post, sent one at a time (Vercel takes 4 MB per request); pictures show in the post, other files open or download.

  GET    /api/posts?before=ID                 {items, pinned, more, can_post, unread, batches (for the form)}
  POST   /api/posts                           {title, body, video_url, audience, batch_id, allow_comments}
  PATCH  /api/posts/<id>                      same fields
  DELETE /api/posts/<id>
  POST   /api/posts/<id>/pin                  {pinned: true|false}
  POST   /api/posts/<id>/files                multipart {file}
  DELETE /api/posts/<id>/files/<fid>
  GET    /api/posts/<id>/files/<fid>          pictures inline, other files as a download
  POST   /api/posts/read                      {ids: [...]}
  GET    /api/posts/<id>/seen                 {seen: [...], not_seen: [...]}   author / admin
  GET    /api/posts/<id>/comments
  POST   /api/posts/<id>/comments             {body}
  DELETE /api/posts/<id>/comments/<cid>
"""
import datetime as dt, os, re, uuid
from urllib.parse import urlparse, parse_qs

from flask import g, jsonify, request

import common
from learning import ALLOWED_MATERIAL, magic_ok

AREA = "write_posts"
AUDIENCES = ("everyone", "students", "teachers", "batch")
PAGE, MAX_TITLE, MAX_BODY, MAX_FILES, MAX_COMMENT = 20, 150, 5000, 6, 1000
IMAGES = (".jpg", ".jpeg", ".png")
UNREAD_DAYS = 60   # older posts never count as "to read"


def video_embed(url):
    """(embed url or None, error or None). YouTube, Google Drive and Vimeo play in the post; other https links stay plain links."""
    url = (url or "").strip()
    if not url: return None, None
    if not re.match(r"^https://\S+$", url) or len(url) > 500: return None, "The video link must start with https://"
    u = urlparse(url)
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    vid = None
    if host == "youtu.be": vid = u.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "youtube-nocookie.com", "music.youtube.com"):
        if u.path == "/watch": vid = (parse_qs(u.query).get("v") or [""])[0]
        else:
            m = re.match(r"^/(shorts|embed|live|v)/([^/?#]+)", u.path)
            vid = m.group(2) if m else ""   # a channel or search page: not a video
    if vid is not None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", vid or ""): return None, "This YouTube link has no video in it. Copy the link from Share."
        return f"https://www.youtube-nocookie.com/embed/{vid}", None
    if host == "drive.google.com":
        m = re.match(r"^/file/d/([A-Za-z0-9_-]{10,})", u.path) or None
        fid = m.group(1) if m else (parse_qs(u.query).get("id") or [""])[0]
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,}", fid or ""): return None, "This Google Drive link has no file in it. Use Share, then Copy link."
        return f"https://drive.google.com/file/d/{fid}/preview", None
    if host == "vimeo.com":
        m = re.match(r"^/(\d{5,})", u.path)
        if m: return f"https://player.vimeo.com/video/{m.group(1)}", None
    return None, None   # some other site: shown as a link


def register(app, c):
    db, rows, one, audit, err, auth, store = c.db, c.rows, c.one, c.audit, c.err, c.auth, c.store

    def tb(uid):
        f = app.extensions.get("teacher_batches")
        return sorted(f(uid)) if f else [r["id"] for r in rows("SELECT id FROM batches WHERE teacher_id=?", (uid,))]

    def marks(n): return ",".join("?" * max(n, 1))

    def can_write(u=None):
        u = u or g.user
        return u["role"] in ("admin", "teacher") and c.has_perm(u, AREA)

    def visible(u, alias="p"):
        """SQL condition and arguments: the posts this person may see."""
        if u["role"] == "admin": return "1=1", []
        if u["role"] == "teacher":
            bs = tb(u["id"]) or [0]
            return (f"({alias}.author_id=? OR {alias}.audience IN ('everyone','teachers') OR ({alias}.audience='batch' AND {alias}.batch_id IN ({marks(len(bs))})))",
                    [u["id"], *bs])
        return (f"({alias}.author_id=? OR {alias}.audience IN ('everyone','students') OR ({alias}.audience='batch' AND {alias}.batch_id IN "
                f"(SELECT batch_id FROM enrollments WHERE student_id=? AND status='active')))", [u["id"], u["id"]])

    def get_visible(pid):
        w, a = visible(g.user)
        return one(f"SELECT p.* FROM posts p WHERE p.id=? AND {w}", (pid, *a))

    def manages(p):
        return p["author_id"] == g.user["id"] or (g.user["role"] == "admin" and can_write())

    def audience_ids(p):
        """Everyone the post is for (active accounts), not counting its author."""
        act = lambda role: [r["id"] for r in rows("SELECT id FROM users WHERE role=? AND is_active=1", (role,))]
        a = p["audience"]
        if a == "everyone": ids = act("student") + act("teacher")
        elif a == "students": ids = act("student")
        elif a == "teachers": ids = act("teacher")
        else:
            b = one("SELECT teacher_id FROM batches WHERE id=?", (p["batch_id"],))
            ids = c.notify_students_of(p["batch_id"]) + ([b["teacher_id"]] if b and b["teacher_id"] else [])
        return [i for i in dict.fromkeys(ids) if i != p["author_id"]]

    def since():   # same text form as utc_stamp(); plain Python so SQLite and PostgreSQL agree
        return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=UNREAD_DAYS)).strftime("%Y-%m-%d %H:%M:%S")

    def unread_count(u):
        w, a = visible(u)
        return one(f"SELECT COUNT(*) n FROM posts p WHERE {w} AND p.author_id<>? AND p.created_at>=? "
                   "AND NOT EXISTS (SELECT 1 FROM post_reads r WHERE r.post_id=p.id AND r.user_id=?)", (*a, u["id"], since(), u["id"]))["n"]

    app.extensions["posts_unread"] = unread_count

    # ---------- reading ----------
    PQ = ("SELECT p.*, u.full_name AS author, u.role AS author_role, b.code AS batch_code, c.name AS course_name, "
          "(SELECT COUNT(*) FROM post_comments x WHERE x.post_id=p.id AND x.deleted_at IS NULL) AS comments_n, "
          "(SELECT 1 FROM post_reads r WHERE r.post_id=p.id AND r.user_id=?) AS is_read "
          "FROM posts p LEFT JOIN users u ON u.id=p.author_id LEFT JOIN batches b ON b.id=p.batch_id LEFT JOIN courses c ON c.id=b.course_id")

    def shape(p):
        x = {k: p[k] for k in ("id", "title", "body", "video_url", "audience", "batch_id", "author_id", "author", "author_role", "created_at", "edited_at", "pinned_at", "comments_n")}
        x["batch_label"] = f"{p['course_name'] or ''} {p['batch_code'] or ''}".strip() if p["audience"] == "batch" else None
        x["video_embed"] = video_embed(p["video_url"])[0] if p["video_url"] else None
        x["allow_comments"] = bool(p["allow_comments"])
        x["read"] = bool(p["is_read"]) or p["author_id"] == g.user["id"]
        x["mine"] = p["author_id"] == g.user["id"]
        x["can_manage"] = manages(p)
        x["files"] = [{"id": f["id"], "name": f["file_name"], "image": f["kind"] == "image"} for f in rows("SELECT id,file_name,kind FROM post_files WHERE post_id=? ORDER BY id", (p["id"],))]
        if x["can_manage"]:
            ids = audience_ids(p)
            x["audience_n"] = len(ids)
            x["seen_n"] = one(f"SELECT COUNT(*) n FROM post_reads WHERE post_id=? AND user_id IN ({marks(len(ids))})", (p["id"], *(ids or [0])))["n"] if ids else 0
        return x

    def form_batches():
        if not can_write(): return []
        if g.user["role"] == "admin":
            return rows("SELECT b.id, b.code, c.name AS course_name FROM batches b JOIN courses c ON c.id=b.course_id WHERE b.status<>'closed' ORDER BY c.name, b.code")
        bs = tb(g.user["id"]) or [0]
        return rows(f"SELECT b.id, b.code, c.name AS course_name FROM batches b JOIN courses c ON c.id=b.course_id WHERE b.id IN ({marks(len(bs))}) ORDER BY c.name, b.code", bs)

    @app.get("/api/posts")
    @auth()
    def posts_list():
        w, a = visible(g.user)
        before = request.args.get("before", type=int)
        cond = f" WHERE {w} AND p.pinned_at IS NULL" + (" AND p.id<?" if before else "")
        items = rows(PQ + cond + " ORDER BY p.id DESC LIMIT ?", (g.user["id"], *a, *([before] if before else []), PAGE + 1))
        more = len(items) > PAGE
        pinned = [] if before else rows(PQ + f" WHERE {w} AND p.pinned_at IS NOT NULL ORDER BY p.pinned_at DESC LIMIT 20", (g.user["id"], *a))
        resp = jsonify(items=[shape(p) for p in items[:PAGE]], pinned=[shape(p) for p in pinned], more=more, can_post=can_write(),
                       is_admin=g.user["role"] == "admin", unread=unread_count(g.user), batches=form_batches() if not before else [])
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    @app.post("/api/posts/read")
    @auth()
    def posts_read():
        ids = (request.get_json(silent=True) or {}).get("ids") or []
        try: ids = sorted({int(i) for i in ids})[:100]
        except (TypeError, ValueError): return err("ids must be numbers")
        if not ids: return jsonify(ok=True, marked=0, unread=unread_count(g.user))
        w, a = visible(g.user)
        ok = [r["id"] for r in rows(f"SELECT p.id FROM posts p WHERE p.id IN ({marks(len(ids))}) AND {w}", (*ids, *a))]
        n = 0
        for pid in ok:
            cur = db().execute("INSERT INTO post_reads(post_id,user_id,read_at) VALUES(?,?,?) ON CONFLICT (post_id, user_id) DO NOTHING", (pid, g.user["id"], c.utc_stamp()))
            n += 1 if cur.rowcount and cur.rowcount > 0 else 0
        db().commit()
        return jsonify(ok=True, marked=n, unread=unread_count(g.user))

    # ---------- writing ----------
    def fields(d, old=None):
        """(values, error). old = the post being edited (missing fields keep their value)."""
        get = lambda k, dflt=None: d[k] if k in d else (old[k] if old is not None else dflt)
        title = str(get("title") or "").strip()
        if not title: return None, "Write a title"
        if len(title) > MAX_TITLE: return None, f"The title can be up to {MAX_TITLE} characters"
        body = str(get("body") or "").strip()
        if len(body) > MAX_BODY: return None, f"The text can be up to {MAX_BODY} characters"
        video = str(get("video_url") or "").strip()
        _, e = video_embed(video)
        if e: return None, e
        aud = get("audience", "everyone")
        if aud not in AUDIENCES: return None, "Choose who the post is for"
        bid = None
        if aud == "batch":
            try: bid = int(get("batch_id"))
            except (TypeError, ValueError): return None, "Choose a batch"
            if not one("SELECT id FROM batches WHERE id=?", (bid,)): return None, "Batch not found"
        if g.user["role"] == "teacher" and (aud != "batch" or bid not in tb(g.user["id"])):
            return None, "Teachers can post only to a batch they teach"
        ac = get("allow_comments", 1)
        return {"title": title, "body": body or None, "video_url": video or None, "audience": aud, "batch_id": bid,
                "allow_comments": 0 if ac in (False, 0, "0", "false", "off") else 1}, None

    def who_label(v):
        if v["audience"] != "batch": return v["audience"]
        b = one("SELECT b.code, c.name FROM batches b JOIN courses c ON c.id=b.course_id WHERE b.id=?", (v["batch_id"],))
        return f"batch {b['name']} {b['code']}" if b else "batch"

    @app.post("/api/posts")
    @auth("admin", "teacher", perm=AREA)
    def posts_create():
        v, e = fields(request.get_json(silent=True) or {})
        if e: return err(e, 403 if e.startswith("Teachers can") else 400)
        pid = db().execute("INSERT INTO posts(author_id,title,body,video_url,audience,batch_id,allow_comments,created_at) VALUES(?,?,?,?,?,?,?,?)",
                           (g.user["id"], v["title"], v["body"], v["video_url"], v["audience"], v["batch_id"], v["allow_comments"], c.utc_stamp())).lastrowid
        p = one("SELECT * FROM posts WHERE id=?", (pid,))
        sent = c.notify(audience_ids(p), "post", f"New post from {g.user['full_name']}", v["title"], f"posts:{pid}", f"post:{pid}")
        audit("post_create", "post", pid, f"{v['title'][:120]} -> {who_label(v)}", batch_id=v["batch_id"])
        db().commit()
        return jsonify(id=pid, notified=sent), 201

    def managed(pid):
        p = one("SELECT * FROM posts WHERE id=?", (pid,))
        if not p: return None, err("Post not found", 404)
        if not get_visible(pid): return None, err("Post not found", 404)   # a post you cannot see does not exist for you
        if not manages(p): return None, err("Only the person who posted it or an admin can change this post", 403)
        return p, None

    @app.patch("/api/posts/<int:pid>")
    @auth("admin", "teacher")
    def posts_edit(pid):
        p, e = managed(pid)
        if e: return e
        v, m = fields(request.get_json(silent=True) or {}, p)
        if m: return err(m, 403 if m.startswith("Teachers can") else 400)
        changed = [k for k in v if (p[k] or None) != (v[k] or None) and str(p[k]) != str(v[k])]
        if not changed: return jsonify(ok=True, changed=False)
        db().execute(f"UPDATE posts SET {','.join(k + '=?' for k in v)}, edited_at=? WHERE id=?", (*v.values(), c.utc_stamp(), pid))
        audit("post_edit", "post", pid, f"{v['title'][:120]}: changed {', '.join(changed)}", batch_id=v["batch_id"])
        db().commit()
        return jsonify(ok=True, changed=True)

    @app.delete("/api/posts/<int:pid>")
    @auth("admin", "teacher")
    def posts_delete(pid):
        p, e = managed(pid)
        if e: return e
        files = [f["file"] for f in rows("SELECT file FROM post_files WHERE post_id=?", (pid,))]
        for t in ("post_comments", "post_reads", "post_files"): db().execute(f"DELETE FROM {t} WHERE post_id=?", (pid,))
        db().execute("DELETE FROM posts WHERE id=?", (pid,))
        audit("post_delete", "post", pid, p["title"][:200] + ("" if p["author_id"] == g.user["id"] else f" (posted by user {p['author_id']})"), batch_id=p["batch_id"])
        db().commit()
        for f in files:
            try: store.delete("learning", f)
            except Exception: pass   # the post is gone; a left-over file is unreachable
        return jsonify(ok=True)

    @app.post("/api/posts/<int:pid>/pin")
    @auth("admin", "teacher")
    def posts_pin(pid):
        p, e = managed(pid)
        if e: return e
        on = (request.get_json(silent=True) or {}).get("pinned", True) in (True, 1, "1", "true")
        if bool(p["pinned_at"]) == on: return jsonify(ok=True, changed=False)
        db().execute("UPDATE posts SET pinned_at=?, pinned_by=? WHERE id=?", (c.utc_stamp() if on else None, g.user["id"] if on else None, pid))
        audit("post_pin" if on else "post_unpin", "post", pid, p["title"][:200], batch_id=p["batch_id"]); db().commit()
        return jsonify(ok=True, changed=True)

    # ---------- files ----------
    @app.post("/api/posts/<int:pid>/files")
    @auth("admin", "teacher")
    def posts_file_add(pid):
        p, e = managed(pid)
        if e: return e
        if one("SELECT COUNT(*) n FROM post_files WHERE post_id=?", (pid,))["n"] >= MAX_FILES: return err(f"A post can have up to {MAX_FILES} files")
        f = request.files.get("file")
        if not f or not f.filename: return err("Choose a file")
        ext = os.path.splitext(f.filename.lower())[1]
        if ext not in ALLOWED_MATERIAL: return err("This file type is not allowed. Allowed: " + ", ".join(ALLOWED_MATERIAL))
        mb = common.cap_mb(int(app.config.get("LEARNING_MAX_MB", 20)))
        data = f.read(mb * 1024 * 1024 + 1)
        if len(data) > mb * 1024 * 1024: return err(f"File is too large ({mb} MB max)")
        if not magic_ok(ext, data[:16]): return err("File content does not match its type")
        name = uuid.uuid4().hex + ext
        store.put("learning", name, data)
        fid = db().execute("INSERT INTO post_files(post_id,file,file_name,kind,created_at) VALUES(?,?,?,?,?)",
                           (pid, name, common.shown_name(f.filename), "image" if ext in IMAGES else "file", c.utc_stamp())).lastrowid
        db().commit()
        return jsonify(id=fid), 201

    @app.delete("/api/posts/<int:pid>/files/<int:fid>")
    @auth("admin", "teacher")
    def posts_file_del(pid, fid):
        p, e = managed(pid)
        if e: return e
        f = one("SELECT * FROM post_files WHERE id=? AND post_id=?", (fid, pid))
        if not f: return err("File not found", 404)
        db().execute("DELETE FROM post_files WHERE id=?", (fid,)); db().commit()
        try: store.delete("learning", f["file"])
        except Exception: pass
        return jsonify(ok=True)

    @app.get("/api/posts/<int:pid>/files/<int:fid>")
    @auth()
    def posts_file_get(pid, fid):
        if not get_visible(pid): return err("File not found", 404)
        f = one("SELECT * FROM post_files WHERE id=? AND post_id=?", (fid, pid))
        if not f: return err("File not found", 404)
        img = f["kind"] == "image"
        return common.file_headers(store.send("learning", f["file"], f["file_name"], as_attachment=not img), f["file_name"], attachment=not img)

    # ---------- seen by ----------
    @app.get("/api/posts/<int:pid>/seen")
    @auth("admin", "teacher")
    def posts_seen(pid):
        p, e = managed(pid)
        if e: return e
        ids = audience_ids(p)
        if not ids: return jsonify(seen=[], not_seen=[])
        people = rows(f"SELECT u.id,u.full_name,u.role,u.login_id,r.read_at FROM users u LEFT JOIN post_reads r ON r.user_id=u.id AND r.post_id=? "
                      f"WHERE u.id IN ({marks(len(ids))}) ORDER BY u.role, u.full_name", (pid, *ids))
        return jsonify(seen=sorted([x for x in people if x["read_at"]], key=lambda x: x["read_at"], reverse=True), not_seen=[x for x in people if not x["read_at"]])

    # ---------- comments ----------
    @app.get("/api/posts/<int:pid>/comments")
    @auth()
    def posts_comments(pid):
        p = get_visible(pid)
        if not p: return err("Post not found", 404)
        mod = manages(p)
        cs = rows("SELECT x.id,x.user_id,x.body,x.created_at,u.full_name AS author,u.role AS author_role FROM post_comments x LEFT JOIN users u ON u.id=x.user_id "
                  "WHERE x.post_id=? AND x.deleted_at IS NULL ORDER BY x.id LIMIT 500", (pid,))
        return jsonify([{**x, "can_delete": mod or x["user_id"] == g.user["id"]} for x in cs])

    @app.post("/api/posts/<int:pid>/comments")
    @auth()
    def posts_comment_add(pid):
        p = get_visible(pid)
        if not p: return err("Post not found", 404)
        if not p["allow_comments"]: return err("Comments are turned off for this post", 403)
        text = str((request.get_json(silent=True) or {}).get("body") or "").strip()
        if not text: return err("Write a comment")
        if len(text) > MAX_COMMENT: return err(f"A comment can be up to {MAX_COMMENT} characters")
        cid = db().execute("INSERT INTO post_comments(post_id,user_id,body,created_at) VALUES(?,?,?,?)", (pid, g.user["id"], text, c.utc_stamp())).lastrowid
        if p["author_id"] and p["author_id"] != g.user["id"]:
            c.notify([p["author_id"]], "post_comment", f"{g.user['full_name']} commented on your post", f"{p['title'][:60]}: {text[:200]}", f"posts:{pid}")
        db().commit()
        return jsonify(id=cid), 201

    @app.delete("/api/posts/<int:pid>/comments/<int:cid>")
    @auth()
    def posts_comment_del(pid, cid):
        p = get_visible(pid)
        x = one("SELECT * FROM post_comments WHERE id=? AND post_id=? AND deleted_at IS NULL", (cid, pid)) if p else None
        if not x: return err("Comment not found", 404)
        own = x["user_id"] == g.user["id"]
        if not own and not manages(p): return err("You can delete only your own comments", 403)
        db().execute("UPDATE post_comments SET body=NULL, deleted_at=?, deleted_by=? WHERE id=?", (c.utc_stamp(), g.user["id"], cid))
        if not own: audit("post_comment_remove", "post", pid, f"comment by user {x['user_id']}: {(x['body'] or '')[:200]}", batch_id=p["batch_id"])
        db().commit()
        return jsonify(ok=True)
