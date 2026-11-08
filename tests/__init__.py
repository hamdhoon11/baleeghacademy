import os
# Session 11: the server blocks every route until a temporary password is replaced. The older suites sign in with freshly created accounts and never
# change the password, so they switch that one rule off. tests/test_session11.py runs with it ON (it removes this variable).
os.environ.setdefault("PORTAL_SKIP_FORCED_CHANGE", "1")
