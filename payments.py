"""Payment layer for invoices. Everything that changes what an invoice has been paid goes through here, so that a future
online gateway only has to call `record(...)` with method='gateway' and its own reference; nothing else needs rewriting.

Money is whole MVR integers. Receipt numbers come from the `counters` table and are never reused."""
import datetime as dt

METHODS = ("bank_transfer", "cash", "other", "gateway")


class PayError(Exception):
    def __init__(self, msg, code=400, extra=None):
        super().__init__(msg)
        self.msg, self.code, self.extra = msg, code, extra or {}


def as_int(v, what="Amount"):
    """Strict whole-number parse: rejects floats, booleans, blanks, negatives and zero."""
    if isinstance(v, bool) or v is None:
        raise PayError(f"{what} must be a whole number of MVR")
    if isinstance(v, float):
        if v != int(v): raise PayError(f"{what} must be a whole number of MVR")
        v = int(v)
    s = str(v).strip()
    if not s.lstrip("+").isdigit():
        raise PayError(f"{what} must be a whole number of MVR")
    n = int(s)
    if n <= 0: raise PayError(f"{what} must be more than 0")
    if n > 10_000_000: raise PayError(f"{what} is too large")
    return n


class Payments:
    def __init__(self, c, now, setting):
        self.c, self.now, self.setting = c, now, setting   # now() -> aware datetime, setting(key, default) -> str

    # ---- reading ----
    def invoice(self, invoice_id):
        return self.c.one("SELECT * FROM invoices WHERE id=?", (invoice_id,))

    @staticmethod
    def balance(inv):
        if inv["status"] == "void": return 0
        return max(inv["amount_due_mvr"] - inv["waived_mvr"] - inv["paid_mvr"], 0)

    # ---- the one place an invoice's paid amount and status are worked out ----
    def recompute(self, invoice_id):
        inv = self.invoice(invoice_id)
        paid = self.c.one("SELECT COALESCE(SUM(amount_mvr),0) n FROM payments WHERE invoice_id=? AND reversed_at IS NULL", (invoice_id,))["n"]
        status, reason = inv["status"], inv["status_reason"]
        if status not in ("void", "waived"):
            if inv["amount_due_mvr"] == 0:
                status, reason = "waived", reason or "Fully discounted"
            elif paid >= inv["amount_due_mvr"]:
                status = "paid"
            elif self.c.one("SELECT 1 x FROM payment_slips WHERE invoice_id=? AND status='pending'", (invoice_id,)):
                status = "slip_submitted"
            else:
                status = "unpaid"
        self.c.db().execute("UPDATE invoices SET paid_mvr=?, status=?, status_reason=? WHERE id=?", (paid, status, reason, invoice_id))
        return self.invoice(invoice_id)

    def next_receipt(self):
        """Allocate the next receipt number. The UPDATE takes the write lock first, so two requests cannot get the same number."""
        db = self.c.db()
        db.execute("UPDATE counters SET value = value + 1 WHERE name='receipt'")
        seq = self.c.one("SELECT value FROM counters WHERE name='receipt'")["value"]
        prefix = self.setting("receipt_prefix", "") or "BA-R-"
        return seq, f"{prefix}{seq:04d}"

    # ---- writing ----
    def record(self, invoice_id, amount, method, paid_on=None, reference=None, note=None, slip_id=None, user_id=None):
        """Record money received against an invoice. Returns the new payment row. Raises PayError."""
        inv = self.invoice(invoice_id)
        if not inv: raise PayError("Invoice not found", 404)
        if method not in METHODS: raise PayError("Choose a payment method")
        amount = as_int(amount)
        if inv["status"] in ("void", "waived"):
            raise PayError(f"This invoice is {inv['status']}; reopen it before recording a payment", 409)
        bal = self.balance(inv)
        if amount > bal:
            raise PayError(f"That is more than the balance of MVR {bal}. Enter MVR {bal} or less.", 400, {"balance": bal})
        today = self.now().date()
        try:
            d = dt.date.fromisoformat(str(paid_on)) if paid_on else today
        except ValueError:
            raise PayError("Enter a real payment date")
        if d > today: raise PayError("The payment date cannot be in the future")
        seq, no = self.next_receipt()
        pid = self.c.db().execute(
            "INSERT INTO payments(invoice_id,student_id,amount_mvr,method,paid_on,reference,note,slip_id,receipt_seq,receipt_no,recorded_by,created_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (invoice_id, inv["student_id"], amount, method, d.isoformat(), (reference or "").strip()[:80] or None, (note or "").strip()[:300] or None,
             slip_id, seq, no, user_id, self.now().isoformat(timespec="seconds"))).lastrowid
        self.recompute(invoice_id)
        return self.c.one("SELECT * FROM payments WHERE id=?", (pid,))

    def reverse(self, payment_id, reason, user_id):
        """Cancel a payment that was recorded by mistake. The row and its receipt number stay (marked reversed); the balance reopens."""
        reason = (reason or "").strip()
        if not reason: raise PayError("Give a reason for reversing this payment")
        p = self.c.one("SELECT * FROM payments WHERE id=?", (payment_id,))
        if not p: raise PayError("Payment not found", 404)
        inv = self.invoice(p["invoice_id"])
        if inv["status"] == "waived":
            raise PayError("This invoice was waived. Reopen it before reversing a payment.", 409)
        cur = self.c.db().execute("UPDATE payments SET reversed_at=?, reversed_by=?, reverse_reason=? WHERE id=? AND reversed_at IS NULL",
                                  (self.now().isoformat(timespec="seconds"), user_id, reason[:300], payment_id))
        if not cur.rowcount: raise PayError("This payment was already reversed", 409)
        if p["slip_id"]:
            self.c.db().execute("UPDATE payment_slips SET status='reversed' WHERE id=? AND status='verified'", (p["slip_id"],))
        self.recompute(p["invoice_id"])
        return p
