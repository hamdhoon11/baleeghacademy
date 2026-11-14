import os
# Session 11: the server blocks every route until a temporary password is replaced. The older suites sign in with freshly created accounts and never
# change the password, so they switch that one rule off. tests/test_session11.py runs with it ON (it removes this variable).
os.environ.setdefault("PORTAL_SKIP_FORCED_CHANGE", "1")
# v0.8.49: People -> Add person needs a contact number. The older suites create people without one, so they switch that rule off.
# tests/test_session49.py runs with it ON.
os.environ.setdefault("PORTAL_PHONE_OPTIONAL", "1")
