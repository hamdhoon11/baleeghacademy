"""Baleegh Academy Portal backend. Phase 1 auth/roles/courses/batches, Phase 2 admissions (here), Phase 3 learning tools (learning.py), Phase 4 fees (fees.py, payments.py, receipts.py)."""
import os, re, time, secrets, uuid, datetime as dt
from functools import wraps
import jwt
from flask import Flask, g, jsonify, request, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
import settings_schema as SS
import idcodes
import common, dbx, storage, transfers
import presence

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
        FILE_STORAGE=os.environ.get("FILE_STORAGE", ""),       # v0.8.34: db | s3 | local; empty = S3 if S3_BUCKET is set, the database on Vercel, else a local folder
        ON_VERCEL=ON_VERCEL,
        CORS_ORIGINS=[o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()],
        TOKEN_HOURS=int(os.environ.get("TOKEN_HOURS", "8")),
        JOIN_EARLY_MIN=int(os.environ.get("JOIN_EARLY_MIN", "15")),      # Join class button appears this many minutes before start
        LEARNING_MAX_MB=int(os.environ.get("LEARNING_MAX_MB", "20")),    # max size of submissions and materials
        MAX_CONTENT_LENGTH=25 * 1024 * 1024,
        SKIP_FORCED_CHANGE=os.environ.get("PORTAL_SKIP_FORCED_CHANGE") == "1",   # TESTS ONLY: never set this on a real server
        PHONE_OPTIONAL=os.environ.get("PORTAL_PHONE_OPTIONAL") == "1",           # TESTS ONLY (v0.8.49): Add person without a contact number
        ALLOW_EMAIL_LOGIN=os.environ.get("ALLOW_EMAIL_LOGIN", "1") != "0",   # Session 11: set to 0 once everyone has confirmed they can sign in by ID
    )
    if config:
        app.config.update(config)
    app.config["USE_POSTGRES"] = dbx.is_postgres(app.config["DATABASE_URL"])
    if not app.config["USE_POSTGRES"]:
        os.makedirs(os.path.dirname(app.config["DATABASE_PATH"]), exist_ok=True)
    id_tables = dbx.id_tables_of(dbx.read_schema(BASE))
    DUMMY_HASH = generate_password_hash("not-a-real-password")
    fails = {}  # ip -> [timestamps]; simple in-memory login rate limit

    # ---------- db ----------
    def connect():
        return dbx.Conn(app.config["DATABASE_URL"], app.config["DATABASE_PATH"], id_tables)

    # A warm serverless instance keeps one PostgreSQL connection for the next request instead of opening a new one each time
    # (a new secure connection costs several network round trips). The request that is using it owns it; it is handed back at the end.
    # It is dropped if it is older than WARM_SECONDS idle or looks broken, and a connection that errored is never reused.
    warm = {"conn": None, "at": 0.0}

    def take_conn():
        c, warm["conn"] = warm["conn"], None
        if c is not None:
            raw = c.raw
            if time.time() - warm["at"] > app.config.get("WARM_SECONDS", 25) or raw.closed or raw.broken:
                try: c.close()
                except Exception: pass
                c = None
        return c or connect()

    def db():
        if "db" not in g:
            g.db = take_conn() if app.config["USE_POSTGRES"] else connect()
            g.db.reset_stats()
        return g.db

    @app.teardown_appcontext
    def close_db(exc):
        c = g.pop("db", None)
        if not c:
            return
        if app.config["USE_POSTGRES"] and exc is None:
            try:
                c.rollback()   # ends the open read transaction; committed work is already safe
                if warm["conn"] is None:
                    warm["conn"], warm["at"] = c, time.time()
                    return
            except Exception:
                pass
        try: c.close()
        except Exception: pass

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

    def audit(action, entity=None, entity_id=None, detail=None, *, course_id=None, batch_id=None, old=None, new=None, role=None, login_id=None):
        """Write one activity-log row. The first four arguments are the old signature; the rest are optional (Session 20).
        Who (user, role, login ID) and where from (IP) are filled in automatically. Passwords are never passed in here."""
        u = getattr(g, "user", None) or {}
        if batch_id is not None and course_id is None:
            b = one("SELECT course_id FROM batches WHERE id=?", (batch_id,))
            course_id = b["course_id"] if b else None
        try: ip = request.remote_addr
        except RuntimeError: ip = None   # scheduled runs have no request
        val = lambda x: None if x is None else str(int(x) if isinstance(x, float) and x.is_integer() else x)[:300]   # 6.0 is stored as 6
        db().execute("INSERT INTO audit_log(user_id,action,entity,entity_id,detail,user_role,login_id,course_id,batch_id,old_value,new_value,ip) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                     (u.get("id"), action, entity, entity_id, detail, role or u.get("role"), login_id or u.get("login_id"), course_id, batch_id, val(old), val(new), ip))

    def err(msg, code=400):
        return jsonify(error=msg), code

    def raw_setting(key):
        """Saved value of a setting, or None if never saved. The whole settings table is read once per request (not once per lookup),
        which matters on a hosted database where every query is a network round trip."""
        if "settings_cache" not in g:
            g.settings_cache = {r[0]: r[1] for r in db().execute("SELECT key,value FROM settings").fetchall()}
        return g.settings_cache.get(key)

    def setting(key):
        """Admin-editable setting from the Settings screen; falls back to its default when empty or never saved."""
        v = raw_setting(key) or ""
        return v.strip() or SS.default_of(key)

    def setting_int(key):
        try: return int(setting(key))
        except ValueError: return int(SS.default_of(key))

    def saved_int(key, fallback):
        """Setting the admin has actually saved, else the given fallback (lets an env var such as TOKEN_HOURS act as the starting value)."""
        v = raw_setting(key)
        try: return int(v) if v is not None and str(v).strip() else fallback
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

    def fill_codes():
        """Session 10: give any new student, teacher, enrolment or course its ID code. Call before the commit that stores the row."""
        return idcodes.fill_missing(db(), unenrolled_students=False)

    def fees_hook(name, *a):
        """Phase 4 hooks (invoices start/move when an enrollment becomes active). No-op until fees.register() has run."""
        fn = app.extensions.get("fees", {}).get(name)
        return fn(*a) if fn else None

    # ---------- auth ----------
    def make_token(u):
        exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=saved_int("session_hours", app.config["TOKEN_HOURS"]))
        # v0.8.47: "tv" = the account's token_version when signed in. A full admin raising it (Sign out, Suspend, Pause) ends every open session.
        return jwt.encode({"sub": str(u["id"]), "role": u["role"], "exp": exp, "tv": int(u.get("token_version") or 0)}, app.config["SECRET_KEY"], "HS256")

    def perm_list(u):
        """None for a full admin, else the list of allowed areas."""
        return None if u.get("permissions") is None else [x for x in u["permissions"].split(",") if x]

    def has_perm(u, area):
        pl = perm_list(u)
        if pl is None: return area not in SS.OPT_IN.get(u["role"], ())   # opt-in areas (edit_grades) are never part of "everything"
        return area in pl

    PICKER_AREAS = ("people", "batches", "enrollments", "fees", "classroom", "settings")   # admin screens that need to pick a person or an enrolment

    def can_any(u, *areas):
        return any(has_perm(u, a) for a in areas)

    def public_user(u):
        """What the page needs to know about the signed-in person. `tabs` is decided here, on the server; the page only draws these."""
        pl = perm_list(u)
        pub = {k: u[k] for k in ("id", "login_id", "email", "full_name", "role", "must_change_password")}
        pub["permissions"] = pl
        pub["tabs"] = SS.tabs_for(u["role"], pl)
        pub["is_super"] = is_super(u)   # v0.8.48
        return pub

    def auth(*roles, perm=None):
        """roles: who may call. perm: the area (see settings_schema.AREAS) this call belongs to, or {role: area} when the same call serves
        several roles; anyone whose permissions list lacks it gets 403, whatever their role. permissions = NULL means everything the role has."""
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
                u = one("SELECT id,login_id,email,full_name,role,is_active,must_change_password,permissions,token_version,suspended_at,paused_until,"
                        "last_seen_at,signed_out_at,account_message,is_super FROM users WHERE id=?", (p["sub"],))
                if not u or not u["is_active"]:
                    return err("Account disabled", 403)
                # v0.8.47: signed out, suspended or paused by a full admin. 401 makes the page sign out and show the message.
                stop = presence.blocked(u, utc_stamp()) or (None if int(p.get("tv", 0)) == int(u["token_version"] or 0) else presence.KICKED)
                if stop:
                    return jsonify(error=stop[1], code=stop[0]), 401
                g.user = u
                # "who is online": at most one small write per person every 30 seconds (a full admin's also clears ended pauses)
                app.extensions["presence"]["touch"](db(), u, utc_stamp(), request, is_full_admin(u))
                for col in ("token_version", "suspended_at", "paused_until", "last_seen_at", "signed_out_at", "account_message"): u.pop(col, None)
                # Session 11: until the temporary password is replaced, nothing works except changing it (and asking who I am). Enforced here, not in the page.
                if u["must_change_password"] and not app.config["SKIP_FORCED_CHANGE"] and request.path not in ("/api/auth/change-password", "/api/auth/me"):
                    return jsonify(error="You must change your temporary password first", code="password_change_required"), 403
                if roles and u["role"] not in roles:
                    return err("You do not have access to this", 403)
                area = perm.get(u["role"]) if isinstance(perm, dict) else perm
                if area and not has_perm(u, area):
                    return err("Your account does not have permission for this area", 403)
                return fn(*a, **k)
            wrap.auth_roles, wrap.auth_perm = roles, perm   # Session 32: lets the permissions-matrix test read every route's rule
            return wrap
        return deco

    def need(data, *fields):
        miss = [f for f in fields if not str(data.get(f, "")).strip()]
        return ("Missing: " + ", ".join(miss)) if miss else None

    LOGIN_ID = re.compile(r"^[A-Z0-9][A-Z0-9/._-]{2,39}$")
    EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

    @app.before_request
    def start_timer():
        g.t0 = time.perf_counter()

    @app.after_request
    def headers(resp):
        # Server-Timing shows in the browser's Network tab (Timing): total time here, and how many database queries took how long
        c = g.get("db")
        resp.headers["Server-Timing"] = f"app;dur={(time.perf_counter() - g.get('t0', time.perf_counter())) * 1000:.0f}" + (f", db;dur={c.ms:.0f};desc=\"{c.q} queries\"" if c else "")
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

    def norm_login(v):
        return re.sub(r"\s+", "", str(v or "")).upper()

    def temp_password():
        return secrets.token_urlsafe(9)

    @app.post("/api/auth/login")
    def login():
        ip = request.remote_addr or "?"
        now = time.time()
        d = request.get_json(silent=True) or {}
        who = str(d.get("login") or d.get("login_id") or d.get("email") or "").strip()
        key = "acct:" + who.lower()   # guessing one account's password is limited too, because IDs follow a pattern anyone can guess
        for k in (ip, key):
            fails[k] = [t for t in fails.get(k, []) if now - t < 300]
        if len(fails[ip]) >= 8 or len(fails[key]) >= 8:
            return err("Too many attempts. Try again in a few minutes.", 429)
        if "@" in who:
            u = one("SELECT * FROM users WHERE email=?", (who.lower(),)) if app.config["ALLOW_EMAIL_LOGIN"] else None   # old way, switch off with ALLOW_EMAIL_LOGIN=0
        else:
            u = one("SELECT * FROM users WHERE login_id=?", (norm_login(who),))
        # the password is always checked (against a dummy hash if nobody matched) so the answer time does not reveal whether the ID exists
        ok = check_password_hash(u["password_hash"] if u else DUMMY_HASH, str(d.get("password", "")))
        if not u or not ok or not u["is_active"]:
            fails[ip].append(now); fails[key].append(now)
            presence.log_login(db(), u["id"] if u else None, who, False, "account disabled" if u and ok else ("wrong password" if u else "unknown ID"), utc_stamp(), request)
            audit("failed_login", "user", u["id"] if u else None, "account disabled" if u and ok else ("wrong password" if u else "unknown ID"),
                  role="anonymous", login_id=who[:60] or None); db().commit()   # what was typed as the ID is kept; the password never is
            return err("Wrong ID or password", 401)
        stop = presence.blocked(u, utc_stamp())   # v0.8.47: told only after the right password, so a stranger learns nothing
        if stop:
            presence.log_login(db(), u["id"], who, False, stop[0], utc_stamp(), request)
            audit("login_blocked", "user", u["id"], stop[0], role=u["role"], login_id=u["login_id"]); db().commit()
            return jsonify(error=stop[1], code=stop[0]), 403
        g.user = u
        presence.signed_in(db(), u["id"], utc_stamp(), request)
        presence.log_login(db(), u["id"], who, True, None, utc_stamp(), request)
        audit("login", "user", u["id"]); db().commit()
        return jsonify(token=make_token(u), user=public_user(u))

    @app.post("/api/auth/logout")
    @auth()
    def logout():
        """Tokens are stateless, so this only writes the log row; the browser forgets the token itself."""
        db().execute("UPDATE users SET signed_out_at=? WHERE id=?", (utc_stamp(), g.user["id"]))   # v0.8.47: shows as offline at once
        audit("logout", "user", g.user["id"]); db().commit()
        return jsonify(ok=True)

    @app.get("/api/auth/me")
    @auth()
    def me():
        return jsonify(user=public_user(g.user))

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

    # ---------- users ----------
    STUDENT_FIELDS = ("date_of_birth", "grade", "island", "guardian_name", "guardian_relationship", "guardian_phone")

    def other_full_admins(uid):
        return one("SELECT COUNT(*) n FROM users WHERE role='admin' AND is_active=1 AND permissions IS NULL AND id<>?", (uid,))["n"]

    def is_full_admin(u):
        return u["role"] == "admin" and u["is_active"] and u["permissions"] is None

    # ---------- v0.8.48: the superadmin ----------
    # Only a superadmin clears the portal's data (Settings) and signs out, pauses, suspends or restores accounts (Who's online). Other admins can
    # still SEE who is online. A superadmin is always an active full admin. While no active full admin has is_super=1 (a new or upgraded
    # database, or the last one was turned off by hand), the earliest active full admin counts as the superadmin, so nobody is ever locked out.
    def super_ids():
        ids = [r["id"] for r in rows("SELECT id FROM users WHERE role='admin' AND is_active=1 AND permissions IS NULL AND is_super=1 ORDER BY id")]
        if ids: return ids
        r = one("SELECT MIN(id) AS id FROM users WHERE role='admin' AND is_active=1 AND permissions IS NULL")
        return [r["id"]] if r and r["id"] else []

    def is_super(u):
        if not u or u.get("role") != "admin" or not u.get("is_active", 1) or u.get("permissions") is not None: return False
        return bool(u.get("is_super")) or u["id"] in super_ids()

    def super_only(msg="Only the superadmin can do this"):
        return None if is_super(g.user) else err(msg, 403)

    @app.get("/api/users")
    @auth("admin")
    def users_list():
        # Session 32: contact details, login IDs and permission lists need the People area. An admin who only needs to pick a teacher or student
        # (batches, enrolments, fees...) gets names only; an admin with none of those areas gets nothing.
        full = has_perm(g.user, "people")
        if not full and not can_any(g.user, *PICKER_AREAS): return err("Your account does not have permission for this area", 403)
        role = request.args.get("role")
        sql = ("SELECT id,login_id,email,full_name,role,phone,is_active,created_at,permissions,is_super FROM users" if full
               else "SELECT id,full_name,role,is_active FROM users")
        args = ()
        if role in ("admin", "teacher", "student"):
            sql += " WHERE role=?"; args = (role,)
        out = rows(sql + " ORDER BY id", args)
        sup = set(super_ids()) if full else set()
        for r in out if full else ():
            r["permissions"] = None if r["permissions"] is None else [x for x in r["permissions"].split(",") if x]
            r["is_super"] = r["id"] in sup
        return jsonify(out)

    @app.get("/api/users/<int:uid>")
    @auth("admin", perm="people")
    def users_get(uid):
        u = one("SELECT id,login_id,email,full_name,role,phone,is_active,must_change_password,created_at,permissions FROM users WHERE id=?", (uid,))
        if not u: return err("User not found", 404)
        u["permissions"] = None if u["permissions"] is None else [x for x in u["permissions"].split(",") if x]
        u["is_super"] = uid in super_ids()   # v0.8.48
        if u["role"] == "student":
            u.update(one("SELECT date_of_birth,grade,island,guardian_name,guardian_relationship,guardian_phone FROM students WHERE user_id=?", (uid,)) or {})
        if u["role"] == "teacher":
            u.update(one("SELECT bio FROM teachers WHERE user_id=?", (uid,)) or {})
        u["areas"] = list(SS.ROLE_AREAS[u["role"]])
        u["enrollments"] = one("SELECT COUNT(*) n FROM enrollments WHERE student_id=?", (uid,))["n"]
        u["batches_taught"] = one("SELECT COUNT(*) n FROM batches WHERE teacher_id=?", (uid,))["n"]
        return jsonify(u)

    @app.post("/api/users")
    @auth("admin", perm="people")
    def users_create():
        d = request.get_json(silent=True) or {}
        m = need(d, "email", "full_name", "role")
        if m: return err(m)
        email = d["email"].strip().lower()
        if not EMAIL.match(email): return err("Enter a valid email")
        if d["role"] not in ("admin", "teacher", "student"): return err("Invalid role")
        # v0.8.49: a contact number is required for everyone added in People (WhatsApp reminders and messages need it)
        phone = str(d.get("phone") or "").strip()
        if phone or not app.config.get("PHONE_OPTIONAL"):
            if not phone: return err("Enter a contact number")
            if len(phone) > 30 or not re.fullmatch(r"\+?[\d\s\-()]{7,}", phone) or len(re.sub(r"\D", "", phone)) < 7:
                return err("Enter a valid contact number (at least 7 digits), like 7771234 or +960 7771234")
        d["phone"] = phone or None
        if d["role"] == "admin" and g.user["permissions"] is not None:
            return err("Only a full admin can create another admin", 403)
        generated = not d.get("password")   # no password typed = make a random one and show it once
        pw = temp_password() if generated else str(d["password"])
        if len(pw) < setting_int("min_password_length"): return err(f"Password must be at least {setting_int('min_password_length')} characters")
        if one("SELECT id FROM users WHERE email=?", (email,)): return err("That email is already registered", 409)
        perms = None
        if d.get("permissions") not in (None, "all"):
            if g.user["permissions"] is not None: return err("Only a full admin can set permissions", 403)
            pv = d["permissions"]
            if not isinstance(pv, list) or any(x not in SS.ROLE_AREAS[d["role"]] for x in pv): return err("Unknown permission area for this role")
            perms = ",".join(a for a in SS.ROLE_AREAS[d["role"]] if a in pv)
        cur = db().execute("INSERT INTO users(email,password_hash,full_name,role,phone,must_change_password,permissions) VALUES(?,?,?,?,?,1,?)",
                           (email, generate_password_hash(pw), d["full_name"].strip(), d["role"], d.get("phone"), perms))
        uid = cur.lastrowid
        if d["role"] == "student":
            db().execute("INSERT INTO students(user_id,date_of_birth,grade,island,guardian_name,guardian_relationship,guardian_phone) VALUES(?,?,?,?,?,?,?)",
                         (uid, d.get("date_of_birth"), d.get("grade"), d.get("island"), d.get("guardian_name"),
                          d.get("guardian_relationship"), d.get("guardian_phone")))
        elif d["role"] == "teacher":
            db().execute("INSERT INTO teachers(user_id,bio) VALUES(?,?)", (uid, d.get("bio")))
        fill_codes()
        if d["role"] == "student" and d.get("course_id"): idcodes.assign_student_code(db(), uid, d["course_id"])   # ID right away, from this course
        login_id = idcodes.give_login_id(db(), uid)
        audit("create_user", "user", uid, f"{d['role']} {login_id}"); db().commit()
        out = {"id": uid, "login_id": login_id}
        if generated: out["temporary_password"] = pw   # shown once; only the hash is stored
        resp = jsonify(**out); resp.status_code = 201; resp.headers["Cache-Control"] = "no-store"
        return resp

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
        # v0.8.48: a superadmin's account is changed only by a superadmin (no other admin can take it over, lock it or limit it)
        target_super = uid in super_ids()
        if target_super and not mine and not is_super(g.user): return err("Only the superadmin can change the superadmin's account", 403)
        if "is_super" in d:
            want = bool(d["is_super"]) and d["is_super"] not in ("0", "false")
            if want != target_super:
                if not is_super(g.user): return err("Only the superadmin can choose who is superadmin", 403)
                if want and not (u["role"] == "admin" and u["is_active"] and u["permissions"] is None and d.get("role", "admin") == "admin"
                                 and d.get("permissions", "all") in (None, "all") and d.get("is_active", 1) not in (0, False)):
                    return err("Only an active full admin can be made superadmin. Give them full admin rights first.", 409)
                if not want and len([i for i in super_ids() if i != uid]) == 0: return err("There must always be one superadmin. Make someone else superadmin first.", 409)
        if target_super and not mine and not (d.get("is_super", True) in (0, False, "0", "false")):
            if ("role" in d and d["role"] != "admin") or (d.get("permissions") not in (None, "all") and "permissions" in d):
                return err("Remove superadmin from this account first", 409)
        sets, args, changed = [], [], []
        if "full_name" in d:
            if not str(d["full_name"] or "").strip(): return err("Name cannot be empty")
            sets.append("full_name=?"); args.append(d["full_name"].strip()); changed.append("full_name")
        if "phone" in d: sets.append("phone=?"); args.append(d["phone"] or None); changed.append("phone")
        if "login_id" in d and norm_login(d["login_id"]) != (u["login_id"] or ""):
            nl = norm_login(d["login_id"])
            if not LOGIN_ID.match(nl): return err("Login ID: 3 to 40 letters, digits or / . _ -")
            if one("SELECT id FROM users WHERE login_id=? AND id<>?", (nl, uid)): return err("That login ID is already used", 409)
            sets.append("login_id=?"); args.append(nl); changed.append("login_id")
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
            sets.append("permissions=NULL")   # a new role starts with everything that role has; set permissions again if needed
        if "is_active" in d:
            if not d["is_active"] and is_full_admin(u) and not other_full_admins(uid): return err("This is the only full admin and cannot be disabled", 409)
            sets.append("is_active=?"); args.append(1 if d["is_active"] else 0); changed.append("is_active")
        if "permissions" in d:
            if g.user["permissions"] is not None: return err("Only a full admin can change permissions", 403)
            if mine: return err("You cannot change your own permissions")
            pv = d["permissions"]
            if "role" in d and d["role"] != u["role"] and pv not in (None, "all"):
                return err("Change the role first, then set permissions")
            if pv in (None, "all"):
                sets.append("permissions=NULL")
            else:
                allowed = SS.ROLE_AREAS[new_role]
                if not isinstance(pv, list) or any(x not in allowed for x in pv): return err("Unknown permission area for this role")
                if is_full_admin(u) and not other_full_admins(uid): return err("This is the only full admin; it cannot be restricted", 409)
                sets.append("permissions=?"); args.append(",".join(a for a in allowed if a in pv))
            changed.append("permissions")
        if d.get("password"):
            if len(d["password"]) < setting_int("min_password_length"): return err(f"Password must be at least {setting_int('min_password_length')} characters")
            sets += ["password_hash=?", "must_change_password=1"]; args.append(generate_password_hash(d["password"])); changed.append("password")
        if "must_change_password" in d and not d.get("password"):
            sets.append("must_change_password=?"); args.append(1 if d["must_change_password"] else 0); changed.append("must_change_password")
        prof = {}
        if new_role == "student": prof = {k: d[k] for k in STUDENT_FIELDS if k in d}
        if new_role == "teacher" and "bio" in d: prof = {"bio": d["bio"]}
        if "is_super" in d and (bool(d["is_super"]) and d["is_super"] not in ("0", "false")) != target_super:
            for i in super_ids(): db().execute("UPDATE users SET is_super=1 WHERE id=?", (i,))   # the one counted by default is written down first
            sets.append("is_super=?"); args.append(0 if target_super else 1); changed.append("is_super")
        if not sets and not prof: return err("Nothing to update")
        if sets:
            try: db().execute(f"UPDATE users SET {','.join(sets)} WHERE id=?", (*args, uid))
            except dbx.IntegrityError: return err("That email or login ID is already registered", 409)
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
        fill_codes()
        if "is_super" in changed:
            audit("superadmin_change", "user", uid, u["login_id"] or u["email"], old="yes" if target_super else "no", new="no" if target_super else "yes")
        if "permissions" in changed:
            audit("permission_change", "user", uid, u["login_id"] or u["email"], old=u["permissions"] or "all", new=one("SELECT permissions FROM users WHERE id=?", (uid,))["permissions"] or "all")
        audit("update_user", "user", uid, diff_detail(u, changed, {**d, "role": d.get("role", u["role"]), **({"login_id": norm_login(d["login_id"])} if "login_id" in d else {})}) if "password" not in changed else ",".join(changed))
        db().commit()
        return jsonify(ok=True)

    @app.post("/api/users/<int:uid>/reset-password")
    @auth("admin", perm="people")
    def users_reset_password(uid):
        """New random temporary password, shown once. The old password stops working and the person must choose their own at next sign-in."""
        u = one("SELECT u.id,u.role,u.login_id,u.full_name,u.phone,(SELECT s.guardian_phone FROM students s WHERE s.user_id=u.id) AS guardian_phone FROM users u WHERE u.id=?", (uid,))
        if not u: return err("User not found", 404)
        if uid == g.user["id"]: return err("Use Change password for your own account")
        if u["role"] == "admin" and g.user["permissions"] is not None: return err("Only a full admin can reset an admin's password", 403)
        if uid in super_ids() and not is_super(g.user): return err("Only the superadmin can reset the superadmin's password", 403)
        pw = temp_password()
        db().execute("UPDATE users SET password_hash=?, must_change_password=1 WHERE id=?", (generate_password_hash(pw), uid))
        ph = app.extensions.get("passhelp")
        if ph: ph["close_for"](uid)   # v0.8.35: a "Forgot password" request from this person is now handled
        audit("reset_password", "user", uid, u["login_id"] or ""); db().commit()
        msg = (f"Assalaamu alaikum {u['full_name']}. Your new password for the {raw_setting('academy_name') or 'Baleegh Academy'} portal:\n"
               f"Login ID: {u['login_id']}\nTemporary password: {pw}\nSign in at {request.host_url} and choose your own password.")
        link = ph["wa_link"](u["phone"] or u["guardian_phone"], msg) if ph else None
        resp = jsonify(login_id=u["login_id"], temporary_password=pw, name=u["full_name"], whatsapp_link=link)
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.delete("/api/users/<int:uid>")
    @auth("admin", perm="people")
    def users_delete(uid):
        """Delete an account made by mistake. Anyone with enrollments, grades, invoices or other records must be disabled instead."""
        u = one("SELECT * FROM users WHERE id=?", (uid,))
        if not u: return err("User not found", 404)
        if uid == g.user["id"]: return err("You cannot delete your own account")
        if u["role"] == "admin" and g.user["permissions"] is not None: return err("Only a full admin can delete an admin", 403)
        if is_full_admin(u) and not other_full_admins(uid): return err("This is the only full admin and cannot be deleted", 409)
        if uid in super_ids():
            if not is_super(g.user): return err("Only the superadmin can delete the superadmin's account", 403)
            if not [i for i in super_ids() if i != uid]: return err("There must always be one superadmin. Make someone else superadmin first.", 409)
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
    COURSE_FIELDS = ("name", "level", "description", "textbook", "monthly_fee_mvr", "registration_fee_mvr", "days_per_week", "minutes_per_class", "status", "kind", "code", "is_active")

    @app.get("/api/public/courses")
    def public_courses():  # no login; for the public website
        return jsonify(rows("SELECT id,name,level,description,textbook,monthly_fee_mvr,days_per_week,minutes_per_class,status "
                            "FROM courses WHERE status IN ('open','upcoming') AND is_active=1 ORDER BY id"))

    @app.get("/api/courses")
    @auth()
    def courses_list():
        """?active=1 leaves out inactive courses (dropdowns for new enrolments, batches, applications). Without it everything is listed, so reports and the admin list keep them."""
        if request.args.get("active") == "1": return jsonify(rows("SELECT * FROM courses WHERE is_active=1 ORDER BY id"))
        return jsonify(rows("SELECT * FROM courses ORDER BY id"))

    def course_problem(d, creating=False):
        """Validate and normalise course fields in place."""
        if "name" in d and not str(d["name"] or "").strip(): return "Course name cannot be empty"
        if "name" in d: d["name"] = d["name"].strip()
        if "status" in d and d["status"] not in ("open", "upcoming", "closed"): return "Invalid status"
        if "kind" in d and d["kind"] not in idcodes.KINDS: return "Type must be course or tuition"
        if "code" in d:
            if d["code"] in (None, ""): d.pop("code")
            else:
                d["code"] = idcodes.norm_course_code(d["code"])
                if not d["code"]: return "Code must be 2 to 8 letters or digits, for example AL1 or G8M"
        if "is_active" in d: d["is_active"] = 1 if d["is_active"] in (True, 1, "1", "true") else 0
        if "monthly_fee_mvr" in d or creating:
            try: d["monthly_fee_mvr"] = int(d.get("monthly_fee_mvr") or 0)
            except (ValueError, TypeError): return "Fee must be a whole number"
            if d["monthly_fee_mvr"] < 0: return "Fee cannot be negative"
        if "registration_fee_mvr" in d or creating:
            try: d["registration_fee_mvr"] = int(d.get("registration_fee_mvr") or 0)
            except (ValueError, TypeError): return "Registration fee must be a whole number"
            if d["registration_fee_mvr"] < 0: return "Registration fee cannot be negative"
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
        code = d.get("code") or idcodes.course_code_for(db(), d["name"], d.get("level"))
        try:
            cur = db().execute("INSERT INTO courses(name,level,description,textbook,monthly_fee_mvr,registration_fee_mvr,days_per_week,minutes_per_class,status,kind,code,is_active) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                               (d["name"], d.get("level"), d.get("description"), d.get("textbook"), d["monthly_fee_mvr"], d["registration_fee_mvr"],
                                d.get("days_per_week"), d.get("minutes_per_class"), d.get("status", "upcoming"), d.get("kind", "course"), code,
                                d.get("is_active", 0 if d.get("status") == "closed" else 1)))
        except dbx.IntegrityError:
            db().rollback()
            return err("That course code is already used", 409)
        audit("create_course", "course", cur.lastrowid, d["name"], course_id=cur.lastrowid); db().commit()
        warn = {"warning": "fee_zero", "message": "Monthly fee is 0, so students enrolled in this course will not be invoiced. Set a fee on the course."} if d["monthly_fee_mvr"] <= 0 else {}
        return jsonify(id=cur.lastrowid, **warn), 201

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
        f = [k for k in f if k in d]   # an empty code was dropped by course_problem
        if not f: return err("Nothing to update")
        try: db().execute(f"UPDATE courses SET {','.join(k + '=?' for k in f)} WHERE id=?", (*[d[k] for k in f], cid))
        except dbx.IntegrityError:
            db().rollback()
            return err("That course code is already used", 409)
        audit("update_course", "course", cid, diff_detail(old, f, d), course_id=cid)
        billed = None
        if "monthly_fee_mvr" in d and old["monthly_fee_mvr"] <= 0 < d["monthly_fee_mvr"]:   # fee just set: bill the enrolments that were skipped while it was 0
            r = fees_hook("catch_up", (g.user or {}).get("id"), "course fee set")
            billed = r["created"] if r else None
        db().commit()
        return jsonify(ok=True, **({"invoices_created": billed} if billed is not None else {}))

    @app.delete("/api/courses/<int:cid>")
    @auth("admin", perm="courses")
    def courses_delete(cid):
        c = one("SELECT name FROM courses WHERE id=?", (cid,))
        if not c: return err("Course not found", 404)
        try:
            db().execute("DELETE FROM courses WHERE id=?", (cid,))
            audit("delete_course", "course", cid, c["name"], course_id=cid); db().commit()
        except dbx.IntegrityError:
            db().rollback()
            return err("This course has batches, applications or other records. Set its status to Closed instead.", 409)
        return jsonify(ok=True)

    # ---------- batches ----------
    BATCH_SQL = ("SELECT b.*, c.name AS course_name, c.kind AS course_kind, c.is_active AS course_active, u.full_name AS teacher_name, "
                 "(SELECT COUNT(*) FROM enrollments e WHERE e.batch_id=b.id AND e.status='active') AS enrolled "
                 "FROM batches b JOIN courses c ON c.id=b.course_id LEFT JOIN users u ON u.id=b.teacher_id")

    @app.get("/api/batches")
    @auth()
    def batches_list():
        u = g.user
        if u["role"] == "admin":
            return jsonify(rows(BATCH_SQL + " ORDER BY b.id"))
        if u["role"] == "teacher":
            ids = sorted(app.extensions["teacher_batches"](u["id"]))   # the one "batches this teacher may use" rule, in learning.py
            return jsonify(rows(BATCH_SQL + f" WHERE b.id IN ({','.join('?' * len(ids))}) ORDER BY b.id", ids) if ids else [])
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
        co = one("SELECT is_active FROM courses WHERE id=?", (d["course_id"],))
        if not co: return err("Course not found", 404)
        if not co["is_active"]: return err("This course or tuition class is inactive. Make it active before adding a batch.", 409)
        try:
            cur = db().execute("INSERT INTO batches(course_id,code,days,start_time,start_date,capacity,teacher_id,meet_link,status) VALUES(?,?,?,?,?,?,?,?,?)",
                               (d["course_id"], d["code"], d.get("days"), d.get("start_time"), d.get("start_date"),
                                d["capacity"], d.get("teacher_id"), d.get("meet_link"), d.get("status", "open")))
        except dbx.IntegrityError:
            return err("That batch code already exists for this course", 409)
        audit("create_batch", "batch", cur.lastrowid, d["code"], batch_id=cur.lastrowid)
        if d.get("teacher_id"): audit("assign_teacher", "batch", cur.lastrowid, d["code"], batch_id=cur.lastrowid, new=d["teacher_id"])
        db().commit()
        return jsonify(id=cur.lastrowid), 201

    @app.patch("/api/batches/<int:bid>")
    @auth("admin", perm="batches")
    def batches_update(bid):
        d = request.get_json(silent=True) or {}
        f = [k for k in ("course_id", "code", "days", "start_time", "start_date", "capacity", "teacher_id", "meet_link", "status") if k in d]   # the Batches screen no longer sends meet_link (Session 12); the API still accepts it
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
        audit("update_batch", "batch", bid, diff_detail(old, f, d), batch_id=bid)
        if "teacher_id" in d and str(old["teacher_id"]) != str(d["teacher_id"]): audit("assign_teacher", "batch", bid, old["code"], batch_id=bid, old=old["teacher_id"], new=d["teacher_id"])
        db().commit()
        return jsonify(ok=True)

    @app.delete("/api/batches/<int:bid>")
    @auth("admin", perm="batches")
    def batches_delete(bid):
        b = one("SELECT code FROM batches WHERE id=?", (bid,))
        if not b: return err("Batch not found", 404)
        try:
            db().execute("DELETE FROM batches WHERE id=?", (bid,))
            audit("delete_batch", "batch", bid, b["code"], batch_id=bid); db().commit()
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
        if g.user["role"] == "admin" and not can_any(g.user, *PICKER_AREAS): return err("Your account does not have permission for this area", 403)   # Session 32
        return jsonify(rows("SELECT u.id,u.full_name,u.phone,e.status,e.id AS enrollment_id FROM enrollments e JOIN users u ON u.id=e.student_id "
                            "WHERE e.batch_id=? AND e.status IN ('active','waitlist') ORDER BY u.full_name", (bid,)))

    # ---------- enrollments ----------
    @app.get("/api/enrollments")
    @auth()
    def enroll_list():
        sql = ("SELECT e.*, u.full_name AS student_name, c.name AS course_name, b.code AS batch_code FROM enrollments e "
               "JOIN users u ON u.id=e.student_id JOIN batches b ON b.id=e.batch_id JOIN courses c ON c.id=b.course_id")
        if g.user["role"] == "admin":
            if not can_any(g.user, *PICKER_AREAS): return err("Your account does not have permission for this area", 403)   # Session 32
            return jsonify(rows(sql + " ORDER BY e.id DESC"))
        if g.user["role"] == "student":
            return jsonify(rows(sql + " WHERE e.student_id=? ORDER BY e.id DESC", (g.user["id"],)))
        return err("You do not have access to this", 403)

    def start_stamp(v):
        """v0.8.43/44: a start date 'YYYY-MM-DD' (Maldives) -> the stored UTC enrolled_at, or None for today. Raises ValueError with a message."""
        try: sd = dt.date.fromisoformat(str(v).strip())
        except ValueError: raise ValueError("Start date must look like 2026-04-01")
        t = fees_hook("today") or dt.date.today()
        if sd > t: raise ValueError("The start date cannot be in the future")
        if sd < t - dt.timedelta(days=731): raise ValueError("The start date can be at most two years back")
        return None if sd == t else (dt.datetime.combine(sd, dt.time(0, 0)) - dt.timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")

    @app.post("/api/enrollments/<int:eid>/start-date")
    @auth("admin", perm="enrollments")
    def enroll_start_date(eid):
        """v0.8.44: change when an enrolment started (students added this month who really began earlier). Moving it earlier bills the
        months in between; moving it later removes nothing, it only reports the invoices now dated before the start (void them in Fees)."""
        d = request.get_json(silent=True) or {}
        e = one("SELECT * FROM enrollments WHERE id=?", (eid,))
        if not e: return err("Enrollment not found", 404)
        if not d.get("start_date"): return err("Choose the start date")
        try: at = start_stamp(d["start_date"]) or utc_stamp()
        except ValueError as x: return err(str(x))
        db().execute("UPDATE enrollments SET enrolled_at=? WHERE id=?", (at, eid))
        audit("enrollment_start", "enrollment", eid, f"start date {d['start_date']}", batch_id=e["batch_id"], old=e["enrolled_at"], new=at)
        made = (fees_hook("back_bill", eid) or 0) if e["status"] == "active" else 0
        first = d["start_date"][:7]
        before = one("SELECT COUNT(*) n FROM invoices WHERE enrollment_id=? AND kind='monthly' AND period<? AND status NOT IN ('void','waived')", (eid, first))["n"]
        db().commit()
        return jsonify(ok=True, enrolled_at=at, earlier_invoices=made, invoices_before_start=before)

    @app.post("/api/enrollments")
    @auth("admin", perm="enrollments")
    def enroll_create():
        d = request.get_json(silent=True) or {}
        m = need(d, "student_id", "batch_id")
        if m: return err(m)
        if not one("SELECT id FROM users WHERE id=? AND role='student'", (d["student_id"],)): return err("Student not found", 404)
        b = one("SELECT b.id,b.capacity,c.is_active FROM batches b JOIN courses c ON c.id=b.course_id WHERE b.id=?", (d["batch_id"],))
        if not b: return err("Batch not found", 404)
        if not b["is_active"]: return err("This course or tuition class is inactive, so no new students can be enrolled.", 409)
        ex = one("SELECT id,status FROM enrollments WHERE student_id=? AND batch_id=?", (d["student_id"], d["batch_id"]))
        if ex and ex["status"] in ("active", "waitlist"): return err("Student is already in this batch", 409)
        # v0.8.43: optional start date in the past (students who began before they were added to the portal); earlier months are billed too
        at = utc_stamp()
        if d.get("start_date"):
            try: at = start_stamp(d["start_date"]) or at
            except ValueError as x: return err(str(x))
        n = one("SELECT COUNT(*) n FROM enrollments WHERE batch_id=? AND status='active'", (b["id"],))["n"]
        status = "active" if n < b["capacity"] else "waitlist"
        if ex:
            db().execute("UPDATE enrollments SET status=?, enrolled_at=? WHERE id=?", (status, at, ex["id"])); eid = ex["id"]
        else:
            eid = db().execute("INSERT INTO enrollments(student_id,batch_id,status,enrolled_at) VALUES(?,?,?,?)", (d["student_id"], b["id"], status, at)).lastrowid
        fill_codes()
        audit("enroll", "enrollment", eid, status + (f", started {d['start_date']}" if d.get("start_date") else ""), batch_id=b["id"], old=ex["status"] if ex else None, new=status)
        res = fees_hook("first_invoice_result", eid) or {}
        back = (fees_hook("back_bill", eid) or 0) if status == "active" else 0
        db().commit()
        return jsonify(id=eid, status=status, invoice_id=res.get("invoice_id"), invoice_skipped=res.get("reason"), invoice_message=res.get("message"), earlier_invoices=back), 201

    @app.patch("/api/enrollments/<int:eid>")
    @auth("admin", perm="enrollments")
    def enroll_update(eid):
        d = request.get_json(silent=True) or {}
        e = one("SELECT * FROM enrollments WHERE id=?", (eid,))
        if not e: return err("Enrollment not found", 404)
        try: eff = transfers.clean_date(d.get("effective_date"), utc_stamp()[:10])
        except ValueError as x: return err(str(x))
        if d.get("transfer_to_batch_id"):  # move student to another batch
            nb = one("SELECT b.id,b.capacity,c.is_active FROM batches b JOIN courses c ON c.id=b.course_id WHERE b.id=?", (d["transfer_to_batch_id"],))
            if not nb: return err("Target batch not found", 404)
            if not nb["is_active"]: return err("The target course or tuition class is inactive", 409)
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
            fill_codes()
            audit("transfer", "enrollment", eid, f"to batch {nb['id']}", batch_id=e["batch_id"], old=e["batch_id"], new=nb["id"])
            transfers.record_event(db(), e["student_id"], e["batch_id"], nb["id"], "transfer", eff, d.get("reason"), g.user["id"], utc_stamp())
            fees_hook("on_transfer", eid, new)
            db().commit()
            return jsonify(id=new)
        if d.get("status") not in ("active", "waitlist", "dropped", "completed"): return err("Invalid status")
        db().execute("UPDATE enrollments SET status=? WHERE id=?", (d["status"], eid))
        audit("enrollment_status", "enrollment", eid, d["status"], batch_id=e["batch_id"], old=e["status"], new=d["status"])
        if d["status"] == "dropped" and e["status"] != "dropped":   # a withdrawal: history kept, content access ends at once
            transfers.record_event(db(), e["student_id"], e["batch_id"], None, "withdrawal", eff, d.get("reason"), g.user["id"], utc_stamp())
        if d["status"] == "active" and e["status"] != "active": fees_hook("first_invoice", eid)
        db().commit()
        return jsonify(ok=True)

    # ---------- admissions (Phase 2) ----------
    UPLOADS = os.path.join(os.path.dirname(app.config["DATABASE_PATH"]), "uploads")   # used only when files are kept on local disk
    store = storage.make(app.config, UPLOADS, conn=db)   # on Vercel without a bucket the files go into the database (v0.8.34)
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
                       minor_age=int(g_("minor_age")),
                       # Session 21 (v0.8.33): the real upload limits, so the forms can check a file before sending it (on Vercel both are 4 MB)
                       upload_max_mb=MAX_FILE // (1024 * 1024), learning_max_mb=common.cap_mb(int(app.config.get("LEARNING_MAX_MB", 20))),
                       logo_url=app.extensions["branding"]["logo_url"]())   # v0.8.48

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
        if not a: return err("Application not found", 404)
        out = dict(a); out["duplicates"] = same_person(a)
        return jsonify(out)

    def same_person(a):
        """v0.8.36: earlier applications or existing accounts that look like the same person: same phone (digits), same email, or same name and
        date of birth. Shown as a warning on the review panel; nothing is blocked."""
        ph, em = digits_intl(a["phone"] or ""), (a["email"] or "").strip().lower()
        name, dob = (a["full_name"] or "").strip().lower(), a["date_of_birth"]
        seen, out = set(), []
        for r in rows("SELECT id, ref, full_name, phone, email, date_of_birth, status, created_at FROM applications WHERE id<>? ORDER BY id DESC LIMIT 2000", (a["id"],)):
            why = [w for w, hit in (("phone", ph and len(ph) >= 7 and digits_intl(r["phone"] or "") == ph), ("email", em and (r["email"] or "").strip().lower() == em),
                                    ("name and date of birth", name and dob and (r["full_name"] or "").strip().lower() == name and r["date_of_birth"] == dob)) if hit]
            if why: out.append({"kind": "application", "id": r["id"], "label": f"{r['full_name']} ({r['ref']}, {r['status']})", "why": why, "at": r["created_at"]})
        for r in rows("SELECT u.id, u.full_name, u.login_id, u.phone, u.email, u.role, u.is_active FROM users u WHERE LOWER(u.email)=? OR u.phone IS NOT NULL", (em,)):
            if r["id"] in seen: continue
            why = [w for w, hit in (("phone", ph and len(ph) >= 7 and digits_intl(r["phone"] or "") == ph), ("email", em and (r["email"] or "").strip().lower() == em)) if hit]
            if why: seen.add(r["id"]); out.append({"kind": "account", "id": r["id"], "label": f"{r['full_name']} ({r['login_id'] or r['role']}{'' if r['is_active'] else ', inactive'})", "why": why})
        return out[:20]

    @app.get("/api/applications/<int:aid>/file/<which>")
    @auth("admin", perm="admissions")
    def apps_file(aid, which):
        col = {"id": "id_file", "guardian_id": "guardian_id_file"}.get(which)
        a = one("SELECT id_file,guardian_id_file FROM applications WHERE id=?", (aid,))
        if not col or not a or not a[col]: return err("File not found", 404)
        audit("view_id_file", "application", aid, which); db().commit()
        ext = os.path.splitext(a[col])[1] or ""
        want_download = request.args.get("download") == "1"
        return common.file_headers(store.send("ids", a[col]), f"{which.replace('_', '-')}-copy-{aid}{ext}", attachment=want_download)

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
        fill_codes()
        login_id = idcodes.give_login_id(db(), uid)
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
            vals = {"name": a["full_name"], "ref": a["ref"], "academy": academy, "email": a["email"], "login_id": login_id, "password": temp}
            msg = re.sub(r"\{(\w+)\}", lambda m_: str(vals.get(m_.group(1), m_.group(0))), tpl)
        else:
            msg = (f"Assalaamu alaikum {a['full_name']}, your application to {academy} (ref {a['ref']}) is approved. "
                   f"Login ID: {login_id} | Temporary password: {temp} (you will be asked to change it). Sign in at {request.host_url}")
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
            audit("delete_enrollment", "enrollment", eid, f"student {e['student_id']} batch {e['batch_id']}", batch_id=e["batch_id"], old=e["status"]); db().commit()
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
        extra = app.extensions.get("fees", {}).get("dashboard")
        n = one("SELECT (SELECT COUNT(*) FROM users WHERE role='student' AND is_active=1) AS students,"
                " (SELECT COUNT(*) FROM users WHERE role='teacher' AND is_active=1) AS teachers,"
                " (SELECT COUNT(*) FROM courses WHERE status='open') AS courses_open,"
                " (SELECT COUNT(*) FROM batches WHERE status IN ('open','running')) AS batches_active,"
                " (SELECT COUNT(*) FROM enrollments WHERE status='active') AS active_enrollments,"
                " (SELECT COUNT(*) FROM enrollments WHERE status='waitlist') AS waitlisted,"
                " (SELECT COUNT(*) FROM applications WHERE status='pending') AS pending_applications")
        ph = app.extensions.get("passhelp")
        more = {"password_help": ph["pending"]()} if ph and has_perm(g.user, "people") else {}   # v0.8.35: People badge
        return jsonify(**(extra() if extra and has_perm(g.user, "fees") else {}), **n, **more)   # Session 32: money figures only for admins who have the Fees area

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
        g.pop("settings_cache", None)
        audit("update_settings", "settings", None, ",".join(changed) or "no change"); db().commit()
        return jsonify(ok=True)

    # ---------- Phase 3: learning tools (timetable, attendance, assignments, grades, materials) ----------
    from types import SimpleNamespace
    import learning
    ns = SimpleNamespace(db=db, rows=rows, one=one, raw_setting=raw_setting, audit=audit, err=err, auth=auth, need=need, UPLOADS=UPLOADS, store=store, has_perm=has_perm)
    ns.is_full_admin, ns.utc_stamp = is_full_admin, utc_stamp
    ns.is_super, ns.super_ids, ns.super_only = is_super, super_ids, super_only   # v0.8.48
    import branding, reportpdf   # v0.8.48: the academy logo; one PDF builder for every report
    branding.register(app, ns)

    def pdf_response(title, blocks, filename, subtitle="", landscape=True):
        n = app.config["NOW"]() if app.config.get("NOW") else dt.datetime.now(MVT)
        pdf = reportpdf.build(title, blocks, academy=setting("academy_name"), subtitle=subtitle, logo=app.extensions["branding"]["logo_bytes"](),
                              landscape=landscape, generated=n.astimezone(MVT).strftime("%d %b %Y, %H:%M"))
        return reportpdf.send(pdf, filename)
    app.extensions["pdf"] = pdf_response
    presence.register(app, ns)   # v0.8.47: who is online; sign out, pause, suspend (full admins only)
    import notify
    notify.register(app, ns, lambda: app.config["NOW"]() if app.config.get("NOW") else dt.datetime.now(MVT))   # Session 28: notifications (must come first: the modules below call ns.notify)
    learning.register(app, ns)
    import filecheck
    filecheck.register(app, ns)
    import resetdata   # v0.8.41: "Clear portal data" (full admins, Settings): deletes everything entered and keeps the admins
    resetdata.register(app, ns, dbx.read_schema(BASE),
                       lambda uid, pw: check_password_hash(one("SELECT password_hash FROM users WHERE id=?", (uid,))["password_hash"], pw))
    import passhelp
    passhelp.register(app, ns)   # v0.8.35: "Forgot password" requests go to admins (no email needed)
    import todo
    todo.register(app, ns)       # v0.8.35: Dashboard "To do today"   # v0.8.34: storage health and the list of records whose file is gone
    import whatsapp
    whatsapp.register(app, ns, lambda: app.config["NOW"]() if app.config.get("NOW") else dt.datetime.now(MVT))   # Session 29: WhatsApp click-to-chat by phone number

    # ---------- scheduler (not role-based: it is called by Vercel Cron with the CRON_SECRET) ----------
    @app.route("/api/cron/generate-invoices", methods=["GET", "POST"])
    def cron_generate_invoices():
        """Vercel Cron sends 'Authorization: Bearer <CRON_SECRET>'. The secret is never accepted in the URL. Without CRON_SECRET the endpoint is closed
        (always 401, which does not reveal whether a secret is set)."""
        import hmac
        secret = app.config.get("CRON_SECRET") or os.environ.get("CRON_SECRET") or ""
        got = request.headers.get("Authorization") or ""
        if not secret or not got.startswith("Bearer ") or not hmac.compare_digest(got[7:].encode(), secret.encode()):
            return err("Not allowed", 401)
        r = fees_hook("catch_up", None, "scheduled run")
        written = app.extensions["recurring"]("scheduled run") if "recurring" in app.extensions else 0   # v0.8.37: monthly expenses due today
        return jsonify(expenses_written=written, period=r["period"], created=r["created"], skipped_total=r["skipped_total"], skipped=r["skipped"])

    # ---------- Phase 4: fees and payments (invoices, slips, receipts, reminders, reports) ----------
    import fees
    fees.register(app, ns)
    import feereminders   # v0.8.48: reminders per person (total and months): Fees -> Reminders (WhatsApp), the student's Home, the daily notices
    feereminders.register(app, ns, lambda: app.config["NOW"]() if app.config.get("NOW") else dt.datetime.now(MVT))
    transfers.register(app, ns)   # Session 13: transfer / withdrawal report
    import substitutions
    substitutions.register(app, ns, lambda: (app.config["NOW"]() if app.config.get("NOW") else dt.datetime.now(MVT)).date(), utc_stamp)   # Session 22
    import finance, earnings
    earnings.register(app, ns, lambda: (app.config["NOW"]() if app.config.get("NOW") else dt.datetime.now(MVT)).date())   # Session 30: teacher earnings
    finance.register(app, ns, lambda: (app.config["NOW"]() if app.config.get("NOW") else dt.datetime.now(MVT)).date())   # Session 23: expenses
    import recurring
    recurring.register(app, ns, lambda: (app.config["NOW"]() if app.config.get("NOW") else dt.datetime.now(MVT)).date())   # v0.8.37: monthly expenses
    import admindash
    admindash.register(app, ns, lambda: (app.config["NOW"]() if app.config.get("NOW") else dt.datetime.now(MVT)).date())   # Session 25: admin dashboard
    import payreports
    payreports.register(app, ns, lambda: (app.config["NOW"]() if app.config.get("NOW") else dt.datetime.now(MVT)).date())   # Session 26: payment reports
    import portio
    portio.register(app, ns)   # Session 27: exports and imports
    import sheets
    sheets.register(app, ns, lambda: (app.config["NOW"]() if app.config.get("NOW") else dt.datetime.now(MVT)).date())   # v0.8.38: Excel exports and imports
    import auditview
    auditview.register(app, ns)   # Session 21: activity log viewer (the old /api/audit route lives there now)

    # ---------- errors: the API always answers in JSON ----------
    # Without this, Flask answers 404 / 405 / 413 / 500 with an HTML page and the browser fails with "Unexpected token < ... is not valid JSON".
    from werkzeug.exceptions import HTTPException

    def api_error(msg, code):
        return jsonify(error=msg), code

    @app.errorhandler(FileNotFoundError)
    def _file_missing(e):
        return api_error("The file could not be found on the server. It may have been removed, or lost before storage was fixed: ask the person to upload it again.", 404)

    @app.errorhandler(HTTPException)
    def _http_error(e):
        if not request.path.startswith("/api/"): return e
        if e.code == 413:
            mb = common.VERCEL_MAX_MB if ON_VERCEL else int(app.config.get("MAX_CONTENT_LENGTH") or 0) // (1024 * 1024)
            return api_error(f"The upload is too large ({mb} MB max). Choose a smaller file." if mb else "The upload is too large.", 413)
        msgs = {404: "Not found", 405: "Method not allowed", 400: "Bad request"}
        return api_error(msgs.get(e.code) or e.description or "Request failed", e.code or 500)

    def record_error(e):
        """v0.8.49: write the error down on a connection of its own (the request's may be in a failed transaction). Returns its reference."""
        import traceback
        ref = secrets.token_hex(3).upper()
        try:
            tb = traceback.extract_tb(e.__traceback__)
            here = [f for f in tb if BASE in (f.filename or "") and "site-packages" not in f.filename] or tb
            lines = "\n".join(f"{os.path.basename(f.filename)}:{f.lineno} in {f.name}: {(f.line or '').strip()[:200]}" for f in here[-8:])
            u = g.get("user") or {}
            c = connect()
            try:
                c.execute("INSERT INTO server_errors(ref,at,method,path,user_id,error_type,message,trace) VALUES(?,?,?,?,?,?,?,?)",
                          (ref, dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), request.method, request.path[:200], u.get("id"),
                           type(e).__name__, str(e)[:1000], lines[:4000]))
                c.execute("DELETE FROM server_errors WHERE id NOT IN (SELECT id FROM server_errors ORDER BY id DESC LIMIT 500)")
                c.commit()
            finally: c.close()
        except Exception:
            app.logger.exception("Could not record the server error")
        return ref

    @app.errorhandler(Exception)
    def _server_error(e):
        if not request.path.startswith("/api/"): raise e
        app.logger.exception("Unhandled error on %s", request.path)
        ref = record_error(e)
        u = g.get("user") or {}
        # admins see the reason (it names a code line, never data from other people); everyone gets the reference to pass on
        why = f" ({type(e).__name__}: {str(e)[:160]})" if u.get("role") == "admin" else ""
        r = jsonify(error=f"Something went wrong on the server. Please try again. If it happens again, send this reference to support: {ref}{why}", ref=ref)
        return r, 500

    @app.get("/api/admin/server-errors")
    @auth("admin")
    def server_errors_list():
        if g.user["permissions"] is not None: return err("Only a full admin can see server errors", 403)
        return jsonify(rows("SELECT e.*, u.full_name AS user_name FROM server_errors e LEFT JOIN users u ON u.id=e.user_id ORDER BY e.id DESC LIMIT 100"))

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
