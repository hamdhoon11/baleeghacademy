"""Seed demo data. Run: python seed.py   (set ADMIN_EMAIL / ADMIN_PASSWORD to choose your own admin login)."""
import os
from werkzeug.security import generate_password_hash
import dbx, idcodes
from app import create_app

app = create_app()
db = dbx.connect(app.config, os.path.dirname(os.path.abspath(__file__)))
# Demo teacher/student accounts have passwords that are written in the README, so on a real hosted database they are NOT created
# unless you ask for them (SEED_DEMO=1). On a local SQLite file they are created as before (SEED_DEMO=0 turns them off).
DEMO = os.environ.get("SEED_DEMO", "0" if app.config["USE_POSTGRES"] else "1") == "1"

def user(email, pw, name, role):
    r = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if r: return r[0]
    uid = db.execute("INSERT INTO users(email,password_hash,full_name,role,must_change_password) VALUES(?,?,?,?,1)",
                     (email, generate_password_hash(pw), name, role)).lastrowid
    if role == "teacher": db.execute("INSERT INTO teachers(user_id) VALUES(?)", (uid,))
    if role == "student": db.execute("INSERT INTO students(user_id) VALUES(?)", (uid,))
    return uid

admin_email = os.environ.get("ADMIN_EMAIL", "admin@baleegh.test")
admin_pw = os.environ.get("ADMIN_PASSWORD", "ChangeMe-Admin1")
user(admin_email, admin_pw, "Academy Admin", "admin")
t = user("teacher@baleegh.test", "ChangeMe-Teach1", "Demo Teacher", "teacher") if DEMO else None
s = user("student@baleegh.test", "ChangeMe-Stud1", "Demo Student", "student") if DEMO else None

if not db.execute("SELECT 1 FROM courses").fetchone():
    ar = db.execute("INSERT INTO courses(name,level,textbook,monthly_fee_mvr,days_per_week,minutes_per_class,status) VALUES('Arabic','Level 1','Madinah Arabic Reader Book 1',350,3,60,'open')").lastrowid
    db.execute("INSERT INTO courses(name,level,status) VALUES('Islam Basic for GCE O Level','O Level','upcoming')")
    db.execute("INSERT INTO courses(name,level,status) VALUES('English for Adults','Level 1','upcoming')")
    # days / Meet links are not on the website: set them in the admin panel (TODO)
    db.execute("INSERT INTO batches(course_id,code,start_time,capacity,teacher_id,status) VALUES(?,?,?,?,?,'running')", (ar, "004", "16:00", 20, t))
    db.execute("INSERT INTO batches(course_id,code,start_time,capacity,teacher_id,status) VALUES(?,?,?,?,?,'running')", (ar, "005", "21:00", 20, t))
    if s: db.execute("INSERT INTO enrollments(student_id,batch_id) VALUES(?,1)", (s,))
for k, v in {"academy_name": "Baleegh Academy", "contact_phone": "725-0901"}.items():
    db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
idcodes.fill_missing(db)   # Session 10: course, student, teacher and enrolment codes
db.commit()
db.reset_sequences()
print("Seeded. Admin:", admin_email, "| Demo accounts:", "created, CHANGE THEIR PASSWORDS before going live" if DEMO else "not created")
