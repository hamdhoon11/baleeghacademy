"""Baleegh Academy Portal backend. Phase 1 auth/roles/courses/batches, Phase 2 admissions (here), Phase 3 learning tools (learning.py), Phase 4 fees (fees.py, payments.py, receipts.py)."""
import os, re, time, secrets, uuid, datetime as dt
from functools import wraps
import jwt
from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
import settings_schema as SS
import common, dbx, storage

BASE = os.path.dirname(os.path.abspath(__file__))
ON_VERCEL = bool(os.environ.get("VERCEL"))
# Vercel's filesystem is read-only except /tmp, so the default data folder moves there when running on Vercel.
DEFAULT_DB = "/tmp/baleegh/portal.db" if ON_VERCEL else os.path.join(BASE, "instance", "portal.db")


def create_app(config=None):
    app = Flask(__name__, static_folder="static", static_url_path="")
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE_PATH=os.environ.get("DATABASE_PATH", DEFAULT_DB),
        DATABASE_URL=os.environ.get("DATABASE_URL", ""),   # set it to use hosted PostgreSQL; empty = SQLite file
        S3_BUCKET=os.environ.get("S3_BUCKET", ""),          # set it to keep uploads in a bucket; empty = local folder
        S3_ENDPOINT_URL=os.environ.get("S3_ENDPOINT_URL", ""), S3_REGION=os.environ.get("S3_REGION", ""),
        S3_ACCESS_KEY_ID=os.environ.get("S3_ACCESS_KEY_ID", ""), S3_SECRET_ACCESS_KEY=os.environ.get("S3_SECRET_ACCESS_KEY", ""),
        S3_PREFIX=os.environ.get("S3_PREFIX", ""),
        CORS_ORIGINS=[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()],
        TOKEN_HOURS=int(os.environ.get("TOKEN_HOURS", "8")),
        JOIN_EARLY_MIN=int(os.environ.get("JOIN_EARLY_MIN", "15")),      # Join class button appears this many minutes before start
        LEARNING_MAX_MB=int(os.environ.get("LEARNING_MAX_MB", "20")),    # max size of submissions and materials
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,
    )
    if config:
        app.config.update(config)
    app.config["USE_POSTGRES"] = dbx.is_postgres(app.config["DATABASE_URL"])
    if not app.config["USE_POSTGRES"]:
        os.makedirs(os.path.dirname(app.config["DATABASE_PATH"]), exist_ok=True)
    id_tables = dbx.id_tables_of(dbx.read_schema(BASE))
    fails = {}  # ip -> [timestamps]; simple in-memory login rate limit

    # ---------- db ----------
    def connect():
        return dbx.Conn(app.config["DATABASE_URL"], app.config["DATABASE_PATH"], id_tables)

    def db():
        if "db" not in g:
            g.db = connect()
        return g.db

    @app.teardown_appcontext
    def close_db(_):
        c = g.pop("db", None)
        if c:
            c.close()

    def init_db():
        c = connect()
        try: dbx.init_schema(c, BASE)
        finally: c.close()

    app.init_db = init_db
    init_db()

    def rows(sql, args=()):
        return [dict(r) for r in db().execute(sql, args).fetchall()]

    def one(sql, args=()):
        r = db().execute(sql, args).fetchone()
        return dict(r) if r else None

    def audit(action, entity=None, entity_id=None, detail=None):
        uid = getattr(g, "user", {}).get("id")
        db().execute("INSERT INTO audit_log(user_id,action,entity,entity_id,detail) VALUES(?,?,?,?,?)",
                     (uid, action, entity, entity_id, detail))

    def err(msg, code=400):
        return jsonify(error=msg), code

    def setting(key):
        """Admin-editable setting from the Settings screen; falls back to its default when empty or never saved."""
        r = db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        v = (r[0] if r else "") or ""
        return v.strip() or SS.default_of(key)

    def setting_int(key):
        try: return int(setting(key))
        except ValueError: return int(SS.default_of(key))

    def saved_int(key, fallback):
        """Setting the admin has actually saved, else the given fallback (lets an env var such as TOKEN_HOURS act as the starting value)."""
        r = db().execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        try: return int(r[0]) if r and str(r[0]).strip() else fallback
        except ValueError: return fallback

    def diff_detail(before, after_fields, d):
        """'field: old -> new' for the fields that really changed (passwords never shown)."""
        out = []
        for f in after_fields:
            if f in ("password", "password_hash"): out.append("password reset"); continue
            if str(before.get(f)) != str(d.get(f)): out.append(f"{f}: {before.get(f)!s:.40} -> {d.get(f)!s:.40}")
        return "; ".join(out) or "no change"

    MVT = dt.timezone(dt.timedelta(hours=5))   # Maldives time, no daylight saving

    def utc_stamp():
        """Current time as UTC 'YYYY-MM-DD HH:MM:SS' (same format as SQLite's datetime('now')), honouring an injected test clock."""
        fn = app.config.get("NOW")
        n = fn() if fn else dt.datetime.now(MVT)
        return n.astimezone(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def fees_hook(name, *a):
        """Phase 4 hooks (invoices start/move when an enrollment becomes active). No-op until fees.register() has run."""
        fn = app.extensions.get("fees", {}).get(name)
        return fn(*a) if fn else None

    # ---------- auth ----------
    def make_token(u):
        exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=saved_int("session_hours", app.config["TOKEN_HOURS"]))
        return jwt.encode({"sub": str(u["id"]), "role": u["role"], "exp": exp}, app.config["SECRET_KEY"], "HS256")

    def perm_list(u):
        """None for a full admin, else the list of allowed areas."""
        return None if u.get("permissions") is None else [x for x in u["permissions"].split(",") if x]

    def has_perm(u, area):
        pl = perm_list(u)
        return pl is None or area in pl

    def auth(*roles, perm=None):
        """roles: who may call. perm: admin area (see settings_schema.AREAS); an admin whose permissions list lacks it gets 403.
        Admins with permissions = NULL are full admins."""
        def deco(fn):
            @wraps(fn)
            def wrap(*a, **k):
                h = request.headers.get("Authorization", "")
                if not h.startswith("Bearer "):
                    return err("Sign in required", 401)
                try:
                    p = jwt.decode(h[7:], app.config["SECRET_KEY"], algorithms=["HS256"])
                except jwt.PyJWTError:
                    return err("Session expired. Sign in again.", 401)
                u = one("SELECT id,email,full_name,role,lang,is_active,must_change_password,permissions FROM users WHERE id=?", (p["sub"],))
                if not u or not u["is_active"]:
                    return err("Account disabled", 403)
                g.user = u
                if roles and u["role"] not in roles:
                    return err("You do not have access to this", 403)
                if perm and u["role"] == "admin" and not has_perm(u, perm):
                    return err("Your admin account does not have permission for this area", 403)
                return fn(*a, **k)
            return wrap
        return deco

    def need(data, *fields):
        miss = [f for f in fields if not str(data.get(f, "")).strip()]
        return ("Missing: " + ", ".join(miss)) if miss else None

    EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @app.after_request
    def headers(resp):
        origin = request.headers.get("Origin")
        if origin and origin in app.config["CORS_ORIGINS"]:
            resp.headers["Access-Control-Allow-Origin"] = origin
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PATCH,PUT,DELETE,OPTIONS"
            resp.headers["Vary"] = "Origin"
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        return resp

    @app.route("/api/<path:_>", methods=["OPTIONS"])
    def preflight(_):
        return "", 204

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/api/health")
    def health():
        return jsonify(ok=True)

    @app.post("/api/auth/login")
    def login():
        ip = request.remote_addr or "?"
        now = time.time()
        fails[ip] = [t for t in fails.get(ip, []) if now - t < 300]
        if len(fails[ip]) >= 8:
            return err("Too many attempts. Try again in a few minutes.", 429)
        d = request.get_json(silent=True) or {}
        u = one("SELECT * FROM users WHERE email=?", (str(d.get("email", "")).strip().lower(),))
        if not u or not u["is_active"] or not check_password_hash(u["password_hash"], str(d.get("password", ""))):
            fails[ip].append(now)
            return err("Wrong email or password", 401)
        g.user = u
        audit("login", "user", u["id"]); db().commit()
        pub = {k: u[k] for k in ("id", "email", "full_name", "role", "lang", "must_change_password")}
        pub["permissions"] = perm_list(u)
        return jsonify(token=make_token(u), user=pub)

    @app.get("/api/auth/me")
    @auth()
    def me():
        return jsonify(user={**{k: v for k, v in g.user.items() if k != "permissions"}, "permissions": perm_list(g.user)})

    @app.post("/api/auth/change-password")
    @auth()
    def change_password():
        d = request.get_json(silent=True) or {}
        u = one("SELECT password_hash FROM users WHERE id=?", (g.user["id"],))
        if not check_password_hash(u["password_hash"], str(d.get("current_password", ""))):
            return err("Current password is wrong", 400)
        new = str(d.get("new_password", ""))
        if len(new) < setting_int("min_password_length"):
            return err(f"New password must be at least {setting_int('min_password_length')} characters")
        db().execute("UPDATE users SET password_hash=?, must_change_password=0 WHERE id=?",
                     (generate_password_hash(new), g.user["id"]))
        audit("change_password", "user", g.user["id"]); db().commit()
        return jsonify(ok=True)

    @app.patch("/api/auth/language")
    @auth()
    def set_lang():
        lang = (request.get_json(silent=True) or {}).get("lang")
        if lang not in ("en", "dv"):
            return err("lang must be en or dv")
        db().execute("UPDATE users SET lang=? WHERE id=?", (lang, g.user["id"])); db().commit()
        return jsonify(ok=True)

    # ---------- users ----------
    STUDENT_FIELDS = ("date_of_birth", "grade", "island", "guardian_name", "guardian_relationship", "guardian_phone")

    def other_full_admins(uid):
        return one("SELECT COUNT(*) n FROM users WHERE role='admin' AND is_active=1 AND permissions IS NULL AND id<>?", (uid,))["n"]

    def is_full_admin(u):
        return u["role"] == "admin" and u["is_active"] and u["permissions"] is None

    @app.get("/api/users")
    @auth("admin")
    def users_list():
        role = request.args.get("role")
        sql = "SELECT id,email,full_name,role,phone,is_active,created_at,permissions FROM users"
        args = ()
        if role in ("admin", "teacher", "student"):
            sql += " WHERE role=?"; args = (role,)
        out = rows(sql + " ORDER BY id", args)
        for r in out:
            r["permissions"] = None if r["permissions"] is None else [x for x in r["permissions"].split(",") if x]
        return jsonify(out)

    @app.get("/api/users/<int:uid>")
    @auth("admin", perm="people")
    def users_get(uid):
        u = one("SELECT id,email,full_name,role,phone,lang,is_active,must_change_password,created_at,permissions FROM users WHERE id=?", (uid,))
        if not u: return err("User not found", 404)
        u["permissions"] = None if u["permissions"] is None else [x for x in u["permissions"].split(",") if x]
        if u["role"] == "student":
            u.update(one("SELECT date_of_birth,grade,island,guardian_name,guardian_relationship,guardian_phone FROM students WHERE user_id=?", (uid,)) or {})
        if u["role"] == "teacher":
            u.update(one("SELECT bio FROM teachers WHERE user_id=?", (uid,)) or {})
        u["enrollments"] = one("SELECT COUNT(*) n FROM enrollments WHERE student_id=?", (uid,))["n"]
        u["batches_taught"] = one("SELECT COUNT(*) n FROM batches WHERE teacher_id=?", (uid,))["n"]
        return jsonify(u)

    @app.post("/api/users")
    @auth("admin", perm="people")
    def users_create():
        d = request.get_json(silent=True) or {}
        m = need(d, "email", "password", "full_name", "role")
        if m: return err(m)
        email = d["email"].strip().lower()
        if not EMAIL.match(email): return err("Enter a valid email")
        if d["role"] not in ("admin", "teacher", "student"): return err("Invalid role")
        if d["role"] == "admin" and g.user["permissions"] is not None:
            return err("Only a full admin can create another admin", 403)
        if len(d["password"]) < setting_int("min_password_length"): return err(f"Password must be at least {setting_int('min_password_length')} characters")
        if one("SELECT id FROM users WHERE email=?", (email,)): return err("That email is already registered", 409)
        cur = db().execute("INSERT INTO users(email,password_hash,full_name,role,phone,must_change_password) VALUES(?,?,?,?,?,1)",
                           (email, generate_password_hash(d["password"]), d["full_name"].strip(), d["role"], d.get("phone")))
        uid = cur.lastrowid
        if d["role"] == "student":
            db().execute("INSERT INTO students(user_id,date_of_birth,grade,island,guardian_name,guardian_relationship,guardian_phone) VALUES(?,?,?,?,?,?,?)",
                         (uid, d.get("date_of_birth"), d.get("grade"), d.get("island"), d.get("guardian_name"),
                          d.get("guardian_relationship"), d.get("guardian_phone")))
        elif d["role"] == "teacher":
            db().execute("INSERT INTO teachers(user_id,bio) VALUES(?,?)", (uid, d.get("bio")))
        audit("create_user", "user", uid, d["role"]); db().commit()
        return jsonify(id=uid), 201

    @app.patch("/api/users/<int:uid>")
    @auth("admin", perm="people")
    def users_update(uid):
        """Correct anything about a person: name, email, phone, role, profile details, permissions, active, password."""
        d = request.get_json(silent=True) or {}
        u = one("SELECT * FROM users WHERE id=?", (uid,))
        if not u: return err("User not found", 404)
        mine = uid == g.user["id"]
        if mine and d.get("is_active") in (0, False):
            return err("You cannot disable your own account")
        sets, args, changed = [], [], []
        if "full_name" in d:
            if not str(d["full_name"] or "").strip(): return err("Name cannot be empty")
            sets.append("full_name=?"); args.append(d["full_name"].strip()); changed.append("full_name")
        if "phone" in d: sets.append("phone=?"); args.append(d["phone"] or None); changed.append("phone")
        if "email" in d:
            email = str(d["email"] or "").strip().lower()
            if not EMAIL.match(email): return err("Enter a valid email")
            if email != u["email"]:
                if one("SELECT id FROM users WHERE email=? AND id<>?", (email, uid)): return err("That email is already registered", 409)
                sets.append("email=?"); args.append(email); changed.append("email")
        new_role = d.get("role", u["role"])
        if "role" in d and d["role"] != u["role"]:
            if d["role"] not in ("admin", "teacher", "student"): return err("Invalid role")
            if mine: return err("You cannot change your own role")
            if g.user["permissions"] is not None and "admin" in (d["role"], u["role"]): return err("Only a full admin can change admin roles", 403)
            if is_full_admin(u) and not other_full_admins(uid): return err("This is the only full admin. Make someone else a full admin first.", 409)
            if one("SELECT 1 FROM enrollments WHERE student_id=?", (uid,)) or one("SELECT 1 FROM batches WHERE teacher_id=?", (uid,)):
                return err("This person has enrollments or batches. Move them first, or create a new account for the new role.", 409)
            sets.append("role=?"); args.append(d["role"]); changed.append("role")
            if d["role"] != "admin": sets.append("permissions=NULL")
        if "is_active" in d:
            if not d["is_active"] and is_full_admin(u) and not other_full_admins(uid): return err("This is the only full admin and cannot be disabled", 409)
            sets.append("is_active=?"); args.append(1 if d["is_active"] else 0); changed.append("is_active")
        if "permissions" in d:
            if g.user["permissions"] is not None: return err("Only a full admin can change admin permissions", 403)
            if mine: return err("You cannot change your own permissions")
            if new_role != "admin": return err("Permissions apply to admin accounts only")
            pv = d["permissions"]
            if pv in (None, "all"):
                sets.append("permissions=NULL")
            else:
                if not isinstance(pv, list) or any(x not in SS.AREAS for x in pv): return err("Unknown permission area")
                if is_full_admin(u) and not other_full_admins(uid): return err("This is the only full admin; it cannot be restricted", 409)
                sets.append("permissions=?"); args.append(",".join(a for a in SS.AREAS if a in pv))
            changed.append("permissions")
        if d.get("password"):
            if len(d["password"]) < setting_int("min_password_length"): return err(f"Password must be at least {setting_int('min_password_length')} characters")
            sets += ["password_hash=?", "must_change_password=1"]; args.append(generate_password_hash(d["password"])); changed.append("password")
        if "must_change_password" in d and not d.get("password"):
            sets.append("must_change_password=?"); args.append(1 if d["must_change_password"] else 0); changed.append("must_change_password")
        prof = {}
        if new_role == "student": prof = {k: d[k] for k in STUDENT_FIELDS if k in d}
        if new_role == "teacher" and "bio" in d: prof = {"bio": d["bio"]}
        if not sets and not prof: return err("Nothing to update")
        if sets:
            try: db().execute(f"UPDATE users SET {','.join(sets)} WHERE id=?", (*args, uid))
            except dbx.IntegrityError: return err("That email is already registered", 409)
        if "role" in d and d["role"] != u["role"]:
            if u["role"] == "student": db().execute("DELETE FROM students WHERE user_id=?", (uid,))
            if u["role"] == "teacher": db().execute("DELETE FROM teachers WHERE user_id=?", (uid,))
            if d["role"] == "student": db().execute("INSERT OR IGNORE INTO students(user_id) VALUES(?)", (uid,))
            if d["role"] == "teacher": db().execute("INSERT OR IGNORE INTO teachers(user_id) VALUES(?)", (uid,))
        if prof:
            tbl = "students" if new_role == "student" else "teachers"
            db().execute(f"INSERT OR IGNORE INTO {tbl}(user_id) VALUES(?)", (uid,))
            db().execute(f"UPDATE {tbl} SET {','.join(k + '=?' for k in prof)} WHERE user_id=?", (*prof.values(), uid))
            changed += list(prof)
        audit("update_user", "user", uid, diff_detail(u, changed, {**d, "role": d.get("role", u["role"])}) if "password" not in changed else ",".join(changed))
        db().commit()
        return jsonify(ok=True)

    @app.delete("/api/users/<int:uid>")
    @auth("admin", perm="people")
    def users_delete(uid):
        """Delete an account made by mistake. Anyone with enrollments, grades, invoices or other records must be disabled instead."""
        u = one("SELECT * FROM users WHERE id=?", (uid,))
        if not u: return err("User not found", 404)
        if uid == g.user["id"]: return err("You cannot delete your own account")
        if u["role"] == "admin" and g.user["permissions"] is not None: return err("Only a full admin can delete an admin", 403)
        if is_full_admin(u) and not other_full_admins(uid): return err("This is the only full admin and cannot be deleted", 409)
        try:
            db().execute("DELETE FROM students WHERE user_id=?", (uid,))
            db().execute("DELETE FROM teachers WHERE user_id=?", (uid,))
            db().execute("DELETE FROM users WHERE id=?", (uid,))
            audit("delete_user", "user", uid, f"{u['role']} {u['email']}")
            db().commit()
        except dbx.IntegrityError:
            db().rollback()
            return err("This person already has records (enrollments, grades, invoices or decisions). Disable the account instead.", 409)
        return jsonify(ok=True)

    # ---------- courses ----------
    COURSE_FIELDS = ("name", "level", "description", "textbook", "monthly_fee_mvr", "days_per_week", "minutes_per_class", "status")

    @app.get("/api/public/courses")
    def public_courses():  # no login; for the public website
        return jsonify(rows("SELECT id,name,level,description,textbook,monthly_fee_mvr,days_per_week,minutes_per_class,status "
                            "FROM courses WHERE status IN ('open','upcoming') ORDER BY id"))

    @app.get("/api/courses")
    @auth()
    def courses_list():
        return jsonify(rows("SELECT * FROM courses ORDER BY id"))

    def course_problem(d, creating=False):
        """Validate and normalise course fields in place."""
        if "name" in d and not str(d["name"] or "").strip(): return "Course name cannot be empty"
        if "name" in d: d["name"] = d["name"].strip()
        if "status" in d and d["status"] not in ("open", "upcoming", "closed"): return "Invalid status"
        if "monthly_fee_mvr" in d or creating:
            try: d["monthly_fee_mvr"] = int(d.get("monthly_fee_mvr") or 0)
            except (ValueError, TypeError): return "Fee must be a whole number"
            if d["monthly_fee_mvr"] < 0: return "Fee cannot be negative"
        for k in ("days_per_week", "minutes_per_class"):
            if k in d:
                if d[k] in (None, ""): d[k] = None
                else:
                    try: d[k] = int(d[k])
                    except (ValueError, TypeError): return k.replace("_", " ").capitalize() + " must be a number"
                    if d[k] <= 0 or d[k] > (7 if k == "days_per_week" else 600): return k.replace("_", " ").capitalize() + " is out of range"
        return None

    @app.post("/api/courses")
    @auth("admin", perm="courses")
    def courses_create():
        d = request.get_json(silent=True) or {}
        m = need(d, "name")
        if m: return err(m)
        m = course_problem(d, True)
        if m: return err(m)
        cur = db().execute("INSERT INTO courses(name,level,description,textbook,monthly_fee_mvr,days_per_week,minutes_per_class,status) VALUES(?,?,?,?,?,?,?,?)",
                           (d["name"], d.get("level"), d.get("description"), d.get("textbook"), d["monthly_fee_mvr"],
                            d.get("days_per_week"), d.get("minutes_per_class"), d.get("status", "upcoming")))
        audit("create_course", "course", cur.lastrowid, d["name"]); db().commit()
        return jsonify(id=cur.lastrowid), 201

    @app.patch("/api/courses/<int:cid>")
    @auth("admin", perm="courses")
    def courses_update(cid):
        d = request.get_json(silent=True) or {}
        f = [k for k in COURSE_FIELDS if k in d]
        if not f: return err("Nothing to update")
        old = one("SELECT * FROM courses WHERE id=?", (cid,))
        if not old: return err("Course not found", 404)
        m = course_problem(d)
        if m: return err(m)
        db().execute(f"UPDATE courses SET {','.join(k + '=?' for k in f)} WHERE id=?", (*[d[k] for k in f], cid))
        audit("update_course", "course", cid, diff_detail(old, f, d)); db().commit()
        return jsonify(ok=True)

    @app.delete("/api/courses/<int:cid>")
    @auth("admin", perm="courses")
    def courses_delete(cid):
        c = one("SELECT name FROM courses WHERE id=?", (cid,))
        if not c: return err("Course not found", 404)
        try:
            db().execute("DELETE FROM courses WHERE id=?", (cid,))
            audit("delete_course", "course", cid, c["name"]); db().commit()
        except dbx.IntegrityError:
            db().rollback()
            return err("This course has batches, applications or other records. Set its status to Closed instead.", 409)
        return jsonify(ok=True)

    # ---------- batches ----------
    BATCH_SQL = ("SELECT b.*, c.name AS course_name, u.full_name AS teacher_name, "
                 "(SELECT COUNT(*) FROM enrollments e WHERE e.batch_id=b.id AND e.status='active') AS enrolled "
                 "FROM batches b JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=b.teacher_id")

    @app.get("/api/batches")
    @auth()
    def batches_list():
        u = g.user
        if u["role"] == "admin":
            return jsonify(rows(BATCH_SQL + " ORDER BY b.id"))
        if u["role"] == "teacher":
            return jsonify(rows(BATCH_SQL + " WHERE b.teacher_id=? ORDER BY b.id", (u["id"],)))
        return jsonify(rows(BATCH_SQL + " WHERE b.id IN (SELECT batch_id FROM enrollments WHERE student_id=? AND status IN ('active','waitlist')) ORDER BY b.id", (u["id"],)))

    DAYNAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

    def batch_problem(d):
        """Validate days ('Sun,Tue,Thu'), start_time ('HH:MM') and meet_link. Normalises d['days'] in place."""
        if d.get("days"):
            parts = [p.strip()[:3].title() for p in str(d["days"]).split(",") if p.strip()]
            if not parts or any(p not in DAYNAMES for p in parts): return "Days must be a list like Sun,Tue,Thu"
            d["days"] = ",".join(sorted(set(parts), key=DAYNAMES.index))
        elif "days" in d:
            d["days"] = None
        if d.get("start_time") and not re.match(r"^([01]\d|2[0-3]):[0-5]\d$", str(d["start_time"])): return "Start time must look like 16:00"
        if d.get("meet_link") and not re.match(r"^https://\S+$", str(d["meet_link"])): return "The Meet link must start with https://"
        if "meet_link" in d and not d["meet_link"]: d["meet_link"] = None
        return None

    def batch_fields_problem(d, bid=None):
        if "code" in d and not str(d["code"] or "").strip(): return "Batch name/code cannot be empty"
        if "code" in d: d["code"] = d["code"].strip()
        if "status" in d and d["status"] not in ("open", "running", "closed"): return "Invalid status"
        if "capacity" in d:
            try: d["capacity"] = int(d["capacity"])
            except (ValueError, TypeError): return "Seats must be a whole number"
            if not 1 <= d["capacity"] <= 500: return "Seats must be between 1 and 500"
            if bid:
                n = one("SELECT COUNT(*) n FROM enrollments WHERE batch_id=? AND status='active'", (bid,))["n"]
                if d["capacity"] < n: return f"{n} students are already enrolled. Move or drop some before lowering the seats to {d['capacity']}."
        if d.get("teacher_id") and not one("SELECT id FROM users WHERE id=? AND role='teacher'", (d["teacher_id"],)): return "Teacher not found"
        if "teacher_id" in d and not d["teacher_id"]: d["teacher_id"] = None
        if d.get("start_date"):
            try: dt.date.fromisoformat(str(d["start_date"]))
            except ValueError: return "Start date must look like 2026-12-01"
        elif "start_date" in d: d["start_date"] = None
        return None

    @app.post("/api/batches")
    @auth("admin", perm="batches")
    def batches_create():
        d = request.get_json(silent=True) or {}
        m = need(d, "course_id", "code")
        if m: return err(m)
        if not d.get("capacity"): d["capacity"] = setting_int("default_capacity")
        m = batch_problem(d) or batch_fields_problem(d)
        if m: return err(m)
        if not one("SELECT id FROM courses WHERE id=?", (d["course_id"],)): return err("Course not found", 404)
        try:
            cur = db().execute("INSERT INTO batches(course_id,code,days,start_time,start_date,capacity,teacher_id,meet_link,status) VALUES(?,?,?,?,?,?,?,?,?)",
                               (d["course_id"], d["code"], d.get("days"), d.get("start_time"), d.get("start_date"),
                                d["capacity"], d.get("teacher_id"), d.get("meet_link"), d.get("status", "open")))
        except dbx.IntegrityError:
            return err("That batch code already exists for this course", 409)
        audit("create_batch", "batch", cur.lastrowid, d["code"]); db().commit()
        return jsonify(id=cur.lastrowid), 201

    @app.patch("/api/batches/<int:bid>")
    @auth("admin", perm="batches")
    def batches_update(bid):
        d = request.get_json(silent=True) or {}
        f = [k for k in ("course_id", "code", "days", "start_time", "start_date", "capacity", "teacher_id", "meet_link", "status") if k in d]
        if not f: return err("Nothing to update")
        old = one("SELECT * FROM batches WHERE id=?", (bid,))
        if not old: return err("Batch not found", 404)
        m = batch_problem(d) or batch_fields_problem(d, bid)
        if m: return err(m)
        if "course_id" in d:
            if not one("SELECT id FROM courses WHERE id=?", (d["course_id"],)): return err("Course not found", 404)
            if int(d["course_id"]) != old["course_id"] and one("SELECT 1 FROM enrollments WHERE batch_id=?", (bid,)):
                return err("This batch already has students. Create a new batch under the other course instead of moving this one.", 409)
        try:
            db().execute(f"UPDATE batches SET {','.join(k + '=?' for k in f)} WHERE id=?", (*[d[k] for k in f], bid))
        except dbx.IntegrityError:
            return err("That batch code already exists for this course", 409)
        audit("update_batch", "batch", bid, diff_detail(old, f, d)); db().commit()
        return jsonify(ok=True)

    @app.delete("/api/batches/<int:bid>")
    @auth("admin", perm="batches")
    def batches_delete(bid):
        b = one("SELECT code FROM batches WHERE id=?", (bid,))
        if not b: return err("Batch not found", 404)
        try:
            db().execute("DELETE FROM batches WHERE id=?", (bid,))
            audit("delete_batch", "batch", bid, b["code"]); db().commit()
        except dbx.IntegrityError:
            db().rollback()
            return err("This batch has students, classes, assignments or applications. Set its status to Closed instead.", 409)
        return jsonify(ok=True)

    @app.get("/api/batches/<int:bid>/students")
    @auth("admin", "teacher")
    def batch_students(bid):
        b = one("SELECT teacher_id FROM batches WHERE id=?", (bid,))
        if not b: return err("Batch not found", 404)
        if g.user["role"] == "teacher" and b["teacher_id"] != g.user["id"]:
            return err("This is not your batch", 403)
        return jsonify(rows("SELECT u.id,u.full_name,u.phone,e.status FROM enrollments e JOIN users u ON u.id=e.student_id "
                            "WHERE e.batch_id=? AND e.status IN ('active','waitlist') ORDER BY u.full_name", (bid,)))

    # ---------- enrollments ----------
    @app.get("/api/enrollments")
    @auth()
    def enroll_list():
        sql = ("SELECT e.*, u.full_name AS student_name, c.name AS course_name, b.code AS batch_code FROM enrollments e "
               "JOIN users u ON u.id=e.student_id JOIN batches b ON b.id=e.batch_id JOIN courses c ON c.id=b.course_id")
        if g.user["role"] == "admin":
            return jsonify(rows(sql + " ORDER BY e.id DESC"))
        if g.user["role"] == "student":
            return jsonify(rows(sql + " WHERE e.student_id=? ORDER BY e.id DESC", (g.user["id"],)))
        return err("You do not have access to this", 403)

    @app.post("/api/enrollments")
    @auth("admin", perm="enrollments")
    def enroll_create():
        d = request.get_json(silent=True) or {}
        m = need(d, "student_id", "batch_id")
        if m: return err(m)
        if not one("SELECT id FROM users WHERE id=? AND role='student'", (d["student_id"],)): return err("Student not found", 404)
        b = one("SELECT id,capacity FROM batches WHERE id=?", (d["batch_id"],))
        if not b: return err("Batch not found", 404)
        ex = one("SELECT id,status FROM enrollments WHERE student_id=? AND batch_id=?", (d["student_id"], d["batch_id"]))
        if ex and ex["status"] in ("active", "waitlist"): return err("Student is already in this batch", 409)
        n = one("SELECT COUNT(*) n FROM enrollments WHERE batch_id=? AND status='active'", (b["id"],))["n"]
        status = "active" if n < b["capacity"] else "waitlist"
        if ex:
            db().execute("UPDATE enrollments SET status=?, enrolled_at=? WHERE id=?", (status, utc_stamp(), ex["id"])); eid = ex["id"]
        else:
            eid = db().execute("INSERT INTO enrollments(student_id,batch_id,status,enrolled_at) VALUES(?,?,?,?)", (d["student_id"], b["id"], status, utc_stamp())).lastrowid
        audit("enroll", "enrollment", eid, status)
        if status == "active": fees_hook("first_invoice", eid)
        db().commit()
        return jsonify(id=eid, status=status), 201

    @app.patch("/api/enrollments/<int:eid>")
    @auth("admin", perm="enrollments")
    def enroll_update(eid):
        d = request.get_json(silent=True) or {}
        e = one("SELECT * FROM enrollments WHERE id=?", (eid,))
        if not e: return err("Enrollment not found", 404)
        if d.get("transfer_to_batch_id"):  # move student to another batch
            nb = one("SELECT id,capacity FROM batches WHERE id=?", (d["transfer_to_batch_id"],))
            if not nb: return err("Target batch not found", 404)
            if one("SELECT id FROM enrollments WHERE student_id=? AND batch_id=? AND status IN ('active','waitlist')", (e["student_id"], nb["id"])):
                return err("Student is already in that batch", 409)
            n = one("SELECT COUNT(*) n FROM enrollments WHERE batch_id=? AND status='active'", (nb["id"],))["n"]
            if n >= nb["capacity"]: return err("Target batch is full", 409)
            db().execute("UPDATE enrollments SET status='dropped' WHERE id=?", (eid,))
            # reuse an old (dropped/completed) row for the target batch instead of REPLACE-ing it: invoices point at enrollment ids
            back = one("SELECT id FROM enrollments WHERE student_id=? AND batch_id=?", (e["student_id"], nb["id"]))
            if back:
                db().execute("UPDATE enrollments SET status='active', enrolled_at=? WHERE id=?", (utc_stamp(), back["id"])); new = back["id"]
            else:
                new = db().execute("INSERT INTO enrollments(student_id,batch_id,status,enrolled_at) VALUES(?,?,'active',?)", (e["student_id"], nb["id"], utc_stamp())).lastrowid
            audit("transfer", "enrollment", eid, f"to batch {nb['id']}")
            fees_hook("on_transfer", eid, new)
            db().commit()
            return jsonify(id=new)
        if d.get("status") not in ("active", "waitlist", "dropped", "completed"): return err("Invalid status")
        db().execute("UPDATE enrollments SET status=? WHERE id=?", (d["status"], eid))
        audit("enrollment_status", "enrollment", eid, d["status"])
        if d["status"] == "active" and e["status"] != "active": fees_hook("first_invoice", eid)
        db().commit()
        return jsonify(ok=True)

    # ---------- admissions (Phase 2) ----------
    UPLOADS = os.path.join(os.path.dirname(app.config["DATABASE_PATH"]), "uploads")   # used only when files are kept on local disk
    store = storage.make(app.config, UPLOADS)
    app.extensions["store"] = store
    apply_hits = {}
    MAGIC = {".pdf": b"%PDF", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff", ".png": b"\x89PNG"}
    MAX_FILE = common.MAX_FILE

    def digits_intl(phone):  # Maldives: 7-digit local numbers get the 960 prefix
        d = re.sub(r"\D", "", phone or "")
        return "960" + d if len(d) == 7 else d

    def age_from(dob):
        b = dt.date.fromisoformat(dob)
        t = dt.date.today()
        return t.year - b.year - ((t.month, t.day) < (b.month, b.day))

    def save_upload(f):
        """Validate (type, size, real content) and store privately. Returns stored filename or raises ValueError."""
        if not f or not f.filename:
            raise ValueError("A file is required")
        ext = os.path.splitext(f.filename.lower())[1]
        if ext not in MAGIC:
            raise ValueError("Upload a PDF, JPG or PNG file")
        data = f.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise ValueError(f"File is too large ({MAX_FILE // (1024 * 1024)} MB max)")
        if not data.startswith(MAGIC[ext]):
            raise ValueError("File content does not match its type")
        name = uuid.uuid4().hex + (".jpg" if ext == ".jpeg" else ext)
        store.put("ids", name, data)
        return name

    def rm_file(name):
        if name: store.delete("ids", name)

    @app.get("/api/public/info")
    def public_info():
        s = {r["key"]: r["value"] for r in rows("SELECT key,value FROM settings")}
        g_ = lambda k: (s.get(k) or "").strip() or SS.default_of(k)
        return jsonify(academy_name=g_("academy_name"), contact_phone=s.get("contact_phone", ""),
                       whatsapp=digits_intl(s.get("contact_phone", "")), tagline=g_("tagline"), contact_email=g_("contact_email"),
                       address=g_("address"), website_url=g_("website_url"), facebook_url=g_("facebook_url"), banner=g_("portal_banner"),
                       applications_open=g_("applications_open") != "0", applications_closed_message=g_("applications_closed_message"),
                       minor_age=int(g_("minor_age")))

    @app.get("/api/public/batches")
    def public_batches():
        return jsonify(rows("SELECT b.id,b.course_id,b.code,b.start_time,b.days,b.status,"
                            "b.capacity-(SELECT COUNT(*) FROM enrollments e WHERE e.batch_id=b.id AND e.status='active') AS spots "
                            "FROM batches b JOIN courses c ON c.id=b.course_id WHERE b.status IN ('open','running') AND c.status='open' ORDER BY b.id"))

    @app.post("/api/public/apply")
    def apply():
        ip = request.remote_addr or "?"
        now = time.time()
        apply_hits[ip] = [x for x in apply_hits.get(ip, []) if now - x < 3600]
        if len(apply_hits[ip]) >= app.config.get("APPLY_LIMIT", 5):
            return err("Too many applications from this connection. Try again later or contact us on WhatsApp.", 429)
        if setting("applications_open") == "0":
            return err(setting("applications_closed_message") or "Applications are closed at the moment. Please contact us on WhatsApp.", 403)
        f = request.form
        if f.get("website"):  # honeypot: real people never fill this hidden field
            return jsonify(ref="BA-000000"), 201
        m = need(f, "full_name", "date_of_birth", "phone", "email", "course_id")
        if m: return err(m)
        email = f["email"].strip().lower()
        if not EMAIL.match(email): return err("Enter a valid email")
        try:
            age = age_from(f["date_of_birth"])
        except ValueError:
            return err("Enter a valid date of birth")
        if not 3 <= age <= 100: return err("Check the date of birth")
        course = one("SELECT id,status FROM courses WHERE id=?", (f["course_id"],))
        if not course or course["status"] != "open": return err("This course is not open for applications")
        batch_id = f.get("batch_id") or None
        if batch_id and not one("SELECT id FROM batches WHERE id=? AND course_id=?", (batch_id, course["id"])):
            return err("Choose a batch that belongs to the course")
        minor_age = setting_int("minor_age")
        minor = age < minor_age
        if minor:
            m = need(f, "guardian_name", "guardian_relationship", "guardian_phone")
            if m: return err(f"Applicants under {minor_age} need a guardian. " + m)
            if "guardian_id" not in request.files: return err(f"Applicants under {minor_age} need a copy of the guardian's ID")
        saved = []
        try:
            id_file = save_upload(request.files.get("id_card")); saved.append(id_file)
            g_file = None
            if minor:
                g_file = save_upload(request.files.get("guardian_id")); saved.append(g_file)
        except ValueError as e:
            for s in saved: rm_file(s)
            return err(str(e))
        ref = "BA-" + secrets.token_hex(3).upper()
        db().execute("INSERT INTO applications(ref,full_name,date_of_birth,is_minor,grade,phone,email,island,course_id,batch_id,id_file,"
                     "guardian_name,guardian_relationship,guardian_phone,guardian_id_file) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (ref, f["full_name"].strip(), f["date_of_birth"], int(minor), f.get("grade"), f["phone"].strip(), email, f.get("island"),
                      course["id"], batch_id, id_file, f.get("guardian_name"), f.get("guardian_relationship"), f.get("guardian_phone"), g_file))
        db().commit()
        apply_hits[ip].append(now)
        return jsonify(ref=ref, is_minor=minor), 201

    @app.post("/api/public/apply/status")
    def apply_status():  # reference + phone must match; reveals status only
        d = request.get_json(silent=True) or {}
        a = one("SELECT status,reject_reason,phone FROM applications WHERE ref=?", (str(d.get("ref", "")).strip().upper(),))
        if not a or re.sub(r"\D", "", a["phone"]) != re.sub(r"\D", "", str(d.get("phone", ""))):
            return err("No application matches that reference and phone number", 404)
        return jsonify(status=a["status"], reason=a["reject_reason"] if a["status"] == "rejected" else None)

    APP_SQL = ("SELECT a.id,a.ref,a.full_name,a.date_of_birth,a.is_minor,a.grade,a.phone,a.email,a.island,a.course_id,a.batch_id,"
               "a.guardian_name,a.guardian_relationship,a.guardian_phone,a.status,a.reject_reason,a.student_user_id,a.created_at,a.decided_at,"
               "(a.id_file IS NOT NULL) AS has_id,(a.guardian_id_file IS NOT NULL) AS has_guardian_id,"
               "c.name AS course_name,b.code AS batch_code FROM applications a JOIN courses c ON c.id=a.course_id LEFT JOIN batches b ON b.id=a.batch_id")

    @app.get("/api/applications")
    @auth("admin", perm="admissions")
    def apps_list():
        st = request.args.get("status")
        if st in ("pending", "approved", "rejected", "waitlist"):
            return jsonify(rows(APP_SQL + " WHERE a.status=? ORDER BY a.id DESC", (st,)))
        return jsonify(rows(APP_SQL + " ORDER BY a.id DESC"))

    @app.get("/api/applications/<int:aid>")
    @auth("admin", perm="admissions")
    def apps_get(aid):
        a = one(APP_SQL + " WHERE a.id=?", (aid,))
        return jsonify(a) if a else err("Application not found", 404)

    @app.get("/api/applications/<int:aid>/file/<which>")
    @auth("admin", perm="admissions")
    def apps_file(aid, which):
        col = {"id": "id_file", "guardian_id": "guardian_id_file"}.get(which)
        a = one("SELECT id_file,guardian_id_file FROM applications WHERE id=?", (aid,))
        if not col or not a or not a[col]: return err("File not found", 404)
        audit("view_id_file", "application", aid, which); db().commit()
        resp = store.send("ids", a[col])
        resp.headers["Cache-Control"] = "private, no-store"
        return resp

    def decide(aid, status, reason=None, student=None):
        db().execute("UPDATE applications SET status=?,reject_reason=?,student_user_id=COALESCE(?,student_user_id),decided_by=?,decided_at=datetime('now') WHERE id=?",
                     (status, reason, student, g.user["id"], aid))
        audit("application_" + status, "application", aid, reason)

    @app.post("/api/applications/<int:aid>/approve")
    @auth("admin", perm="admissions")
    def apps_approve(aid):
        d = request.get_json(silent=True) or {}
        a = one("SELECT * FROM applications WHERE id=?", (aid,))
        if not a: return err("Application not found", 404)
        if a["status"] not in ("pending", "waitlist"): return err("This application was already decided", 409)
        bid = d.get("batch_id") or a["batch_id"]
        b = one("SELECT id,capacity,code FROM batches WHERE id=?", (bid,)) if bid else None
        if not b: return err("Choose a batch for this student")
        if one("SELECT id FROM users WHERE email=?", (a["email"],)): return err("An account with this email already exists", 409)
        temp = secrets.token_urlsafe(9)
        uid = db().execute("INSERT INTO users(email,password_hash,full_name,role,phone,must_change_password) VALUES(?,?,?,'student',?,1)",
                           (a["email"], generate_password_hash(temp), a["full_name"], a["phone"])).lastrowid
        db().execute("INSERT INTO students(user_id,date_of_birth,grade,island,guardian_name,guardian_relationship,guardian_phone) VALUES(?,?,?,?,?,?,?)",
                     (uid, a["date_of_birth"], a["grade"], a["island"], a["guardian_name"], a["guardian_relationship"], a["guardian_phone"]))
        n = one("SELECT COUNT(*) n FROM enrollments WHERE batch_id=? AND status='active'", (b["id"],))["n"]
        est = "active" if n < b["capacity"] else "waitlist"
        eid = db().execute("INSERT INTO enrollments(student_id,batch_id,status,enrolled_at) VALUES(?,?,?,?)", (uid, b["id"], est, utc_stamp())).lastrowid
        decide(aid, "approved", None, uid)
        if est == "active": fees_hook("first_invoice", eid)
        if d.get("delete_files"):
            rm_file(a["id_file"]); rm_file(a["guardian_id_file"])
            db().execute("UPDATE applications SET id_file=NULL,guardian_id_file=NULL WHERE id=?", (aid,))
            audit("delete_id_files", "application", aid)
        db().commit()
        s = {r["key"]: r["value"] for r in rows("SELECT key,value FROM settings")}
        tpl = setting("welcome_message_template")
        academy = s.get("academy_name") or "Baleegh Academy"
        if tpl:
            vals = {"name": a["full_name"], "ref": a["ref"], "academy": academy, "email": a["email"], "password": temp}
            msg = re.sub(r"\{(\w+)\}", lambda m_: str(vals.get(m_.group(1), m_.group(0))), tpl)
        else:
            msg = (f"Assalaamu alaikum {a['full_name']}, your application to {academy} (ref {a['ref']}) is approved. "
                   f"Login email: {a['email']} | Temporary password: {temp} (you will be asked to change it).")
        if est == "waitlist": msg += " You are on the batch waitlist and we will confirm your seat."
        from urllib.parse import quote
        return jsonify(user_id=uid, email=a["email"], temp_password=temp, enrollment_status=est, message=msg,
                       whatsapp_link=f"https://wa.me/{digits_intl(a['phone'])}?text={quote(msg)}")

    @app.post("/api/applications/<int:aid>/reject")
    @auth("admin", perm="admissions")
    def apps_reject(aid):
        reason = str((request.get_json(silent=True) or {}).get("reason", "")).strip()
        if not reason: return err("Give a reason so the applicant knows why")
        a = one("SELECT status FROM applications WHERE id=?", (aid,))
        if not a: return err("Application not found", 404)
        if a["status"] not in ("pending", "waitlist"): return err("This application was already decided", 409)
        decide(aid, "rejected", reason); db().commit()
        return jsonify(ok=True)

    @app.post("/api/applications/<int:aid>/waitlist")
    @auth("admin", perm="admissions")
    def apps_waitlist(aid):
        a = one("SELECT status FROM applications WHERE id=?", (aid,))
        if not a: return err("Application not found", 404)
        if a["status"] != "pending": return err("Only pending applications can be waitlisted", 409)
        decide(aid, "waitlist"); db().commit()
        return jsonify(ok=True)

    @app.delete("/api/applications/<int:aid>/files")
    @auth("admin", perm="admissions")
    def apps_delete_files(aid):
        a = one("SELECT id_file,guardian_id_file FROM applications WHERE id=?", (aid,))
        if not a: return err("Application not found", 404)
        rm_file(a["id_file"]); rm_file(a["guardian_id_file"])
        db().execute("UPDATE applications SET id_file=NULL,guardian_id_file=NULL WHERE id=?", (aid,))
        audit("delete_id_files", "application", aid); db().commit()
        return jsonify(ok=True)

    @app.delete("/api/enrollments/<int:eid>")
    @auth("admin", perm="enrollments")
    def enroll_delete(eid):
        """Remove an enrollment made by mistake. If it already has invoices or attendance, use 'dropped' instead (keeps the history)."""
        e = one("SELECT * FROM enrollments WHERE id=?", (eid,))
        if not e: return err("Enrollment not found", 404)
        try:
            db().execute("DELETE FROM enrollments WHERE id=?", (eid,))
            audit("delete_enrollment", "enrollment", eid, f"student {e['student_id']} batch {e['batch_id']}"); db().commit()
        except dbx.IntegrityError:
            db().rollback()
            return err("This enrollment already has invoices or payments. Set it to Dropped instead so the history is kept.", 409)
        return jsonify(ok=True)

    APP_EDIT = ("full_name", "date_of_birth", "grade", "phone", "email", "island", "course_id", "batch_id",
                "guardian_name", "guardian_relationship", "guardian_phone")

    @app.patch("/api/applications/<int:aid>")
    @auth("admin", perm="admissions")
    def apps_edit(aid):
        """Correct typing mistakes in an application before it is decided."""
        d = request.get_json(silent=True) or {}
        a = one("SELECT * FROM applications WHERE id=?", (aid,))
        if not a: return err("Application not found", 404)
        if a["status"] not in ("pending", "waitlist"): return err("Only pending or waitlisted applications can be edited", 409)
        f = [k for k in APP_EDIT if k in d]
        if not f: return err("Nothing to update")
        for k in ("full_name", "phone"):
            if k in d and not str(d[k] or "").strip(): return err("Name and phone cannot be empty")
        if "email" in d:
            d["email"] = str(d["email"] or "").strip().lower()
            if not EMAIL.match(d["email"]): return err("Enter a valid email")
        extra = {}
        if "date_of_birth" in d:
            try: age = age_from(d["date_of_birth"])
            except (ValueError, TypeError): return err("Enter a valid date of birth")
            if not 3 <= age <= 100: return err("Check the date of birth")
            extra["is_minor"] = int(age < setting_int("minor_age"))
        cid = d.get("course_id", a["course_id"])
        if "course_id" in d and not one("SELECT id FROM courses WHERE id=?", (cid,)): return err("Course not found", 404)
        bid = d.get("batch_id", a["batch_id"]) or None
        if bid and not one("SELECT id FROM batches WHERE id=? AND course_id=?", (bid, cid)): return err("Choose a batch that belongs to the course")
        if "batch_id" in d or "course_id" in d: d["batch_id"] = bid; f = list(dict.fromkeys(f + ["batch_id"]))
        cols = f + list(extra)
        vals = [d[k] for k in f] + list(extra.values())
        db().execute(f"UPDATE applications SET {','.join(k + '=?' for k in cols)} WHERE id=?", (*vals, aid))
        audit("edit_application", "application", aid, diff_detail(a, f, d)); db().commit()
        return jsonify(ok=True)

    # ---------- admin ----------
    @app.get("/api/dashboard")
    @auth("admin")
    def dashboard():
        c = lambda sql: one(sql)["n"]
        extra = app.extensions.get("fees", {}).get("dashboard")
        return jsonify(**(extra() if extra else {}),
            students=c("SELECT COUNT(*) n FROM users WHERE role='student' AND is_active=1"),
            teachers=c("SELECT COUNT(*) n FROM users WHERE role='teacher' AND is_active=1"),
            courses_open=c("SELECT COUNT(*) n FROM courses WHERE status='open'"),
            batches_active=c("SELECT COUNT(*) n FROM batches WHERE status IN ('open','running')"),
            active_enrollments=c("SELECT COUNT(*) n FROM enrollments WHERE status='active'"),
            waitlisted=c("SELECT COUNT(*) n FROM enrollments WHERE status='waitlist'"),
            pending_applications=c("SELECT COUNT(*) n FROM applications WHERE status='pending'"),
        )

    SETTING_KEYS = SS.SETTING_KEYS

    @app.get("/api/settings")
    @auth("admin", perm="settings")
    def settings_get():
        s = {r["key"]: r["value"] for r in rows("SELECT key,value FROM settings")}
        return jsonify({k: s.get(k, "") for k in SETTING_KEYS})

    @app.get("/api/settings/schema")
    @auth("admin", perm="settings")
    def settings_schema():
        """Grouped description of every setting plus the current value, for the Settings screen."""
        s = {r["key"]: r["value"] for r in rows("SELECT key,value FROM settings")}
        groups = [{"id": gid, "title": title, "hint": hint, "items": [{**it, "value": s.get(it["key"], "")} for it in items]}
                  for gid, title, hint, items in SS.GROUPS]
        return jsonify(groups=groups, areas=list(SS.AREAS))

    @app.put("/api/settings")
    @auth("admin", perm="settings")
    def settings_put():
        d = request.get_json(silent=True) or {}
        check = app.extensions.get("fees", {}).get("validate_setting")
        for k in SETTING_KEYS:
            if k in d:
                e = SS.validate(k, d[k]) or (check(k, d[k]) if check else None)
                if e: return err(e)
        s = {r["key"]: r["value"] for r in rows("SELECT key,value FROM settings")}
        changed = []
        for k in SETTING_KEYS:
            if k in d:
                v = "" if d[k] is None else str(d[k]).strip()
                if s.get(k, "") != v: changed.append(k)
                db().execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, v))
        audit("update_settings", "settings", None, ",".join(changed) or "no change"); db().commit()
        return jsonify(ok=True)

    @app.get("/api/audit")
    @auth("admin", perm="audit")
    def audit_list():
        return jsonify(rows("SELECT a.*, u.full_name AS user_name FROM audit_log a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 200"))

    # ---------- Phase 3: learning tools (timetable, attendance, assignments, grades, materials) ----------
    from types import SimpleNamespace
    import learning
    ns = SimpleNamespace(db=db, rows=rows, one=one, audit=audit, err=err, auth=auth, need=need, UPLOADS=UPLOADS, store=store)
    learning.register(app, ns)

    # ---------- Phase 4: fees and payments (invoices, slips, receipts, reminders, reports) ----------
    import fees
    fees.register(app, ns)

    return app


# Top-level Flask instance: this is what Vercel (and `gunicorn app:app`) looks for.
app = create_app()
if ON_VERCEL:
    # A fresh database (first start, or Vercel's temporary /tmp one) has no users, so create the admin (and demo data for SQLite) once so login works.
    _c = dbx.Conn(app.config["DATABASE_URL"], app.config["DATABASE_PATH"], ())
    try: _empty = not _c.execute("SELECT 1 FROM users LIMIT 1").fetchone()
    finally: _c.close()
    if _empty:
        try:
            import seed  # seed.py seeds the database when imported
        except dbx.IntegrityError:
            pass  # another instance seeded at the same moment


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
