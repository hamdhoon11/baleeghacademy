"""Single source of truth for portal settings (what the admin Settings screen shows) and admin permission areas.
Each setting: key, type (text|longtext|email|url|number|bool|select), default (used when the admin leaves it empty), label and hint (English; shown in the UI).
Empty value always means 'use the default'. Validation is generic by type; fees.py adds its own checks for the fee keys."""
import re


def S(key, type="text", default="", label=None, hint="", min=None, max=None, options=None):
    return dict(key=key, type=type, default=default, label=label or key.replace("_", " ").capitalize(), hint=hint, min=min, max=max, options=options)


GROUPS = [
    ("academy", "Academy details", "Shown on the public pages and in messages to students.", [
        S("academy_name", "text", "Baleegh Academy", "Academy name"),
        S("tagline", "text", "", "Tagline", "One short line under the name (optional)."),
        S("contact_phone", "text", "", "Contact phone / WhatsApp", "7-digit Maldives numbers get the 960 prefix automatically for WhatsApp links."),
        S("contact_email", "email", "", "Contact email"),
        S("address", "longtext", "", "Address / how to reach us"),
        S("website_url", "url", "", "Website link", "Must start with https://"),
        S("facebook_url", "url", "", "Facebook page link", "Must start with https://"),
        S("portal_banner", "longtext", "", "Notice on the login page", "For example: holiday dates or a new batch. Leave empty to show nothing."),
    ]),
    ("admissions", "Admissions", "Controls the public application form and approval messages.", [
        S("applications_open", "bool", "1", "Accept new applications", "Turn off to close the public form (for example when all batches are full)."),
        S("applications_closed_message", "longtext", "", "Message when applications are closed", "Shown to people who try to apply."),
        S("minor_age", "number", "18", "Age below which a guardian is required", min=10, max=21),
        S("default_capacity", "number", "20", "Default seats for a new batch", "You can still change the seats on each batch.", min=1, max=500),
        S("welcome_message_template", "longtext", "", "Approval message (WhatsApp)",
          "Placeholders: {name} {ref} {academy} {email} {password}. Leave empty for the standard message."),
    ]),
    ("classes", "Classes and attendance", "", [
        S("join_early_min", "number", "15", "Join class button appears (minutes before start)", min=0, max=120),
        S("low_attendance_pct", "number", "75", "Low attendance warning below (%)", min=0, max=100),
    ]),
    ("security", "Security", "Changes apply to new sign-ins and new passwords.", [
        S("min_password_length", "number", "8", "Minimum password length", min=6, max=64),
        S("session_hours", "number", "8", "Stay signed in for (hours)", "People are asked to sign in again after this long.", min=1, max=72),
    ]),
    ("fees", "Fees and bank details", "Students see the bank details when paying.", [
        S("bank_name", "text", "", "Bank name"),
        S("bank_account_name", "text", "", "Account name"),
        S("bank_account_number", "text", "", "Account number"),
        S("invoice_due_day", "number", "10", "Invoice due day of the month", min=1, max=28),
        S("first_invoice_mode", "select", "full", "First invoice for a new student", "full = charge the whole month; skip = start billing next month.", options=["full", "skip"]),
        S("first_invoice_grace_days", "number", "7", "Grace days before the first invoice is due", min=0, max=60),
        S("receipt_prefix", "text", "BA-R-", "Receipt number prefix", "Up to 12 letters, digits, - _ or /"),
        S("reminder_template_en", "longtext", "", "Overdue reminder (English)"),
    ]),
    ("notifications", "Notifications and reminders", "In-app messages for students, teachers and admins. A daily run (07:30 Maldives time) sends the fee and assignment reminders; 0 turns a reminder off.", [
        S("notify_enabled", "bool", "1", "Notifications on", "Turn off to stop creating any new notification (existing ones stay visible)."),
        S("remind_fee_days_before", "number", "3", "Fee due soon: remind students this many days before the due date", min=0, max=14),
        S("remind_overdue_every_days", "number", "7", "Overdue fee: remind students every this many days", "The first reminder is sent the day after the due date.", min=0, max=60),
        S("remind_assignment_days_before", "number", "1", "Assignment due: remind students this many days before", "Only students who have not handed in yet are reminded.", min=0, max=14),
    ]),
    ("earnings", "Teacher earnings", "How each month's collected fees are split between the teacher and the academy (Finance, Teacher earnings).", [
        S("revenue_share_percent", "number", "50", "Teacher's share of fees collected (percent)", "50 means half of what a batch collected in the month goes to its teacher. A month that is already approved is never changed.", min=0, max=100),
        S("teachers_see_earnings", "bool", "1", "Teachers can see their own approved earnings", "Only approved months are shown, and only to that teacher. Registration fees are never part of teacher earnings."),
    ]),
]

SETTINGS = {s["key"]: s for _, _, _, items in GROUPS for s in items}
SETTING_KEYS = tuple(SETTINGS)

# Permission areas. Every user has a role (admin, teacher, student) and the role decides which areas exist for that person.
# permissions = NULL on a user means "everything their role has" (a full admin for admins). A list means only those areas.
# The server uses this list to decide which tabs a person sees AND to refuse every request outside it.
AREAS = ("admissions", "courses", "batches", "classroom", "people", "enrollments", "fees", "settings", "audit", "tutorials",
         "assignments", "progress", "materials", "create_tutorials", "submit_tutorial_work", "class_links", "recordings", "add_recordings", "student_information", "teacher_information", "edit_grades", "cancel_class", "finance")
ROLE_AREAS = {
    "admin": ("admissions", "courses", "batches", "classroom", "people", "enrollments", "fees", "settings", "audit", "tutorials", "create_tutorials", "class_links", "add_recordings", "student_information", "teacher_information", "finance"),
    "teacher": ("classroom", "tutorials", "create_tutorials", "class_links", "add_recordings", "edit_grades", "cancel_class"),
    "student": ("assignments", "progress", "materials", "recordings", "fees", "tutorials", "submit_tutorial_work"),
}
# "tutorials" lets a person open the Tutorials tab and read. "create_tutorials" (teachers, admins) lets them post tutorials and see the
# answers; "submit_tutorial_work" (students) lets them send an answer. These two are abilities, not tabs.
# "class_links" (teachers, admins) lets a person set the Meet link of a batch they manage and add a one-off link for a single class.
# "recordings" (students) opens the Recordings tab and lets them open the Drive links of their own batches. "add_recordings" (teachers, admins)
# lets a person add and delete recordings of a batch they manage; they see them in Classroom.
# "student_information" (admins) opens the Student information directory: one student's profile, batches, attendance, grades and fees together.
# The fees part is shown only to an admin who also has "fees". Nobody has it until a full admin ticks it (no automatic grant).
# "teacher_information" (admins) opens the Teacher information directory: one teacher's profile, batches taught, students and workload. Not granted automatically.
# "edit_grades" (teachers) lets a teacher CHANGE a grade that is already saved. Giving a first grade needs only "classroom". It is opt-in:
# a teacher with "everything a teacher has" (permissions NULL) does NOT get it; an admin must tick it for that teacher. Admins can always change grades.
# "cancel_class" (teachers) lets a teacher mark a class of their batch as cancelled. Opt-in in the same way; reinstating a class needs only "classroom".
# "finance" (admins) opens the Finance tab: expenses, categories and receipts (Session 23; later revenue and the financial dashboard).
# It is part of a full admin's "everything" (otherwise nobody could ever grant it); a limited admin has it only when ticked.
OPT_IN = {"teacher": ("edit_grades", "cancel_class")}
# Tabs in the order they are shown. Home, Dashboard and my_information (Session 16, read-only, own data only) need no permission.
ROLE_TABS = {
    "admin": ("dashboard", "admissions", "courses", "batches", "timetable", "classroom", "tutorials", "people", "student_information", "teacher_information", "enrollments", "fees", "finance", "settings", "audit"),
    "teacher": ("home", "timetable", "classroom", "tutorials", "my_files", "my_earnings", "my_information"),
    "student": ("home", "timetable", "assignments", "progress", "materials", "recordings", "fees", "tutorials", "my_files", "my_information"),
}
TAB_AREA = {a: a for a in AREAS}   # every tab that is not home/dashboard is guarded by the area of the same name


# v0.8.37: tabs shown when the person has ANY of these areas (a limited account without them does not get an empty page)
TAB_ANY = {("admin", "timetable"): ("batches", "classroom"), ("student", "my_files"): ("materials", "assignments", "tutorials", "fees"),
           ("teacher", "my_files"): ("classroom", "tutorials")}


def tabs_for(role, perms):
    """Tabs a person may see. perms is None (everything their role has) or a list of areas."""
    def ok(t):
        if perms is None: return True
        if (role, t) in TAB_ANY: return any(a in perms for a in TAB_ANY[(role, t)])
        return t not in TAB_AREA or TAB_AREA[t] in perms
    return [t for t in ROLE_TABS.get(role, ()) if ok(t)]


_URL = re.compile(r"^https://\S+$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def default_of(key):
    return SETTINGS[key]["default"]


def validate(key, v):
    """Error message or None. Empty means 'use the default'."""
    s = SETTINGS.get(key)
    if not s: return "Unknown setting"
    v = "" if v is None else str(v).strip()
    if not v: return None
    t, label = s["type"], s["label"]
    if t == "number":
        if not re.fullmatch(r"\d{1,6}", v): return f"{label}: enter a whole number"
        if s["min"] is not None and int(v) < s["min"] or s["max"] is not None and int(v) > s["max"]:
            return f"{label}: must be between {s['min']} and {s['max']}"
    elif t == "bool":
        if v not in ("0", "1"): return f"{label}: must be on or off"
    elif t == "select":
        if v not in s["options"]: return f"{label}: choose one of {', '.join(s['options'])}"
    elif t == "url":
        if not _URL.match(v): return f"{label}: must start with https://"
    elif t == "email":
        if not _EMAIL.match(v): return f"{label}: enter a valid email"
    if len(v) > (2000 if t == "longtext" else 300): return f"{label}: too long"
    return None
