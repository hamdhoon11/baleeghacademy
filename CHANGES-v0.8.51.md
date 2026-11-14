# v0.8.51: teacher salaries by fee month, pay-day approval, late collections accrued, salaries entered as expenses

Builds on v0.8.50. **Database change: additive only**, done automatically on start:
- new columns `teacher_earnings.seq` and `booked_month`, `expenses.teacher_id` and `teacher_payments.expense_id`;
- the unique index on teacher earnings becomes (batch, month, seq).

No row is changed.

Asked: salaries must be worked out from which month's fees were collected, not the date they were entered. Teachers are paid around the 15th of each month from what was collected for that month's fees. A fee for that month paid after the teacher was paid goes to that month as an accrued amount. Salaries will be entered as expenses.

## How it works now
1. **By fee month.** "Calculate" for November counts every payment on **November's fee invoices**, whatever day it was paid or entered. October fees entered in November count for October.
2. **Pay day (around the 15th).** Press Calculate, then **Approve month**. The current month can now be approved (before, only finished months could). The approved figures are locked and never change.
3. **Collected after approval (accrued).** When a student pays that month's fee later, the month's screen says "MVR X for this month was collected after approval and is not counted yet: press Calculate".
   - Calculate adds it as a **"Collected late (accrued)"** row for that month, tagged with the month it was found. Press **Approve late collections** to make it payable.
   - The teacher's "Owed" goes up by their share.
   - A refund or reversal after approval comes in the same way, as a negative row.
4. **Salaries as expenses.**
   - **Finance → Add expense** has a new **"Salary paid to teacher"** choice. An expense with a teacher counts as paid to that teacher, so their "Owed" goes down. Changing or deleting the expense keeps it in step.
   - **Record payment** on the Teacher earnings screen also adds the expense, in the category "Teacher salaries" (made automatically). Voiding it removes the expense.
   - Either way, each salary is entered once and shows in both expenses and teacher payments. The expense list tags it "Salary: name".
5. Calculate's message box explains the result: fees for the month collected so far, what is still unpaid, money not shared (registration, no batch), and batches with no teacher.

Reports (screen, CSV, Excel, PDF) show late rows as "approved (collected late, 2026-11)".

## Checks run
- Unit tests: whole suite **544, all pass**.
  - New `tests/test_session51.py` (4): October fees entered in November count for October; approve on the 15th, a later payment becomes one late row (not doubled on re-calculate), approved row untouched, approving makes it payable, report label; salary expense ↔ teacher payment (create, change amount, un-mark, delete, unknown teacher); a payment on the earnings screen creates and its void removes the expense.
  - Updated for the new rule: test_session30, 31, 40, 49.
- PostgreSQL 16 (local): upgrade of old databases, the whole flow above, reports.
- Browser: e2e_earnings (updated: Calculate stays on for an approved month), e2e_v0849, e2e_navigation pass.
- Your current data: nothing was approved yet, so the next Calculate simply redoes October and November by fee month.
