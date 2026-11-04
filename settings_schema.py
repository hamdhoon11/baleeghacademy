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
        S("reminder_template_dv", "longtext", "", "Overdue reminder (Dhivehi)"),
    ]),
]

SETTINGS = {s["key"]: s for _, _, _, items in GROUPS for s in items}
SETTING_KEYS = tuple(SETTINGS)

# Admin permission areas. An admin with permissions = NULL is a full admin (everything, plus managing other admins' permissions).
AREAS = ("admissions", "courses", "batches", "classroom", "people", "enrollments", "fees", "settings", "audit")

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
