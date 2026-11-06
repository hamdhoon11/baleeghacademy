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
]

SETTINGS = {s["key"]: s for _, _, _, items in GROUPS for s in items}
SETTING_KEYS = tuple(SETTINGS)

# Permission areas. Every user has a role (admin, teacher, student) and the role decides which areas exist for that person.
# permissions = NULL on a user means "everything their role has" (a full admin for admins). A list means only those areas.
# The server uses this list to decide which tabs a person sees AND to refuse every request outside it.
AREAS = ("admissions", "courses", "batches", "classroom", "people", "enrollments", "fees", "settings", "audit", "tutorials",
         "assignments", "progress", "materials", "create_tutorials", "submit_tutorial_work", "class_links", "recordings", "add_recordings", "student_information", "teacher_information")
ROLE_AREAS = {
    "admin": ("admissions", "courses", "batches", "classroom", "people", "enrollments", "fees", "settings", "audit", "tutorials", "create_tutorials", "class_links", "add_recordings", "student_information", "teacher_information"),
    "teacher": ("classroom", "tutorials", "create_tutorials", "class_links", "add_recordings"),
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
# Tabs in the order they are shown. Home and Dashboard need no permission.
ROLE_TABS = {
    "admin": ("dashboard", "admissions", "courses", "batches", "classroom", "tutorials", "people", "student_information", "teacher_information", "enrollments", "fees", "settings", "audit"),
    "teacher": ("home", "classroom", "tutorials"),
    "student": ("home", "assignments", "progress", "materials", "recordings", "fees", "tutorials"),
}
TAB_AREA = {a: a for a in AREAS}   # every tab that is not home/dashboard is guarded by the area of the same name


def tabs_for(role, perms):
    """Tabs a person may see. perms is None (everything their role has) or a list of areas."""
    return [t for t in ROLE_TABS.get(role, ()) if t not in TAB_AREA or perms is None or TAB_AREA[t] in perms]


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
