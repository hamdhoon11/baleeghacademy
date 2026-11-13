# v0.8.45: manual invoices (students and people not in the portal), revenue types, editable invoice amounts

Builds on v0.8.44. **Database change (automatic, loosening only):** see "Database" below.

Asked: a way to add invoices by hand, for existing students and for people not in the portal (cash customers, by name); revenue grouped by category (for now registration fees and monthly fees, with more addable); invoice amounts editable, to enter old payments.

## New
- **Fees → New invoice** (new tab):
  - Bill to **a student in the portal** (optionally tied to one of their course/batches) or **someone not in the portal** (name and phone).
  - Revenue type, description (empty = the type's name), amount, invoice date (its month is the invoice's month in reports, so April payments land in April), due date.
  - **Already paid**: records the payment in the same step: amount (empty = all), method, date paid, reference, the WhatsApp slip, and "Tell the student". Leave it unticked to create an unpaid invoice that appears in Invoices and Overdue.
- **Revenue types** (same tab): Monthly fees and Registration fees are built in, and generated invoices use them. **Add** more (e.g. Books, Exam fee), **rename** any, **turn off** added ones. The count of invoices of each type is shown.
- **Edit** on every invoice that is not void: amount, revenue type, description, due date (and name and phone for someone not in the portal). Changing the amount needs a reason; it cannot go below what is already paid. The invoice's status is worked out again (e.g. raising the amount of a paid invoice makes it part-paid). Every edit is in the Activity log (`invoice_edit`).
- **Invoices list**: filter by revenue type; each row shows its type; people not in the portal are tagged "Not in portal". Search also finds customer names and descriptions. The Excel export has `revenue_type` and `description` columns at the end.
- **Finance → Revenue**: a **By revenue type** table and a revenue type filter. Money from invoices without a course shows as "Other (no course)".

## Rules
- Teacher earnings count a manual invoice only when it is tied to a batch **and** its type is Monthly fees (the same as generated monthly invoices). Registration and other types never count.
- Automatic reminders (fee due soon / overdue notices) go to students only; people not in the portal appear in Fees → Overdue with a WhatsApp link when a phone was given.
- Receipts, invoice PDFs and slips work for people not in the portal. They are never visible to any student.
- Generated monthly and registration invoices keep working exactly as before; a manual invoice never blocks or doubles a generated one.

## Database (done automatically when the new version starts; nothing to run)
- New table `revenue_types` (filled with the two built-in types).
- `invoices`: new columns `customer_name`, `customer_phone`, `revenue_type_id`; `enrollment_id`, `student_id`, `course_id`, `batch_id` may now be empty.
- `payments.student_id` and `payment_slips.student_id` may now be empty.
- Only rules are loosened; no existing row is changed. PostgreSQL: `ALTER COLUMN ... DROP NOT NULL`. SQLite: the stored table definition is edited in place, then an integrity check is run.
- `migrate_to_hosted.py` copies the revenue types over the built-in ones.
- Taking a backup in your database provider before deploying is still sensible.

## Also fixed
- `schema.sql` defined `substitutions` (which refers to `sessions`) before `sessions`, so a brand-new empty PostgreSQL database could not be set up. The table is now defined after `sessions`. Checked: the whole schema builds on an empty PostgreSQL 16 database (39 tables). Existing databases are not affected.

## Checks run
- Unit tests: whole suite, 506 tests, all pass. New `tests/test_session45.py` (10): revenue types (built-in, add, duplicate, rename, built-ins cannot be turned off, a turned-off type cannot be used, rights); a walk-in invoice paid with a slip (receipt, invoice PDF, slip, not visible to a student, payments list, search, type filter); a student invoice tied to a batch (student sees it; both statements); 11 refusals that save nothing; part paid then mark paid; editing amounts (reason, not below paid, status worked out again, type/description/due date, rights, activity log); editing a walk-in's name; revenue by type adds up to the total; month report and Excel; overdue WhatsApp link for a walk-in; the daily reminder run; teacher earnings rules; **upgrade of an older database** (NOT NULL loosened, rows unchanged, integrity ok, second run changes nothing). `test_session32` security map has the new routes.
- **PostgreSQL 16** (a real server here): an old-format database upgraded with the same statements; the new queries (invoice list, revenue by type, revenue type counts, earnings) run and give the right results.
- Browser (390 px phone): new `tests/e2e_manual_invoice.py` (12 checks); `e2e_mark_paid.py`, `e2e_browser.py`, `e2e_ui.py`, `e2e_round2.py` pass.
- **Not tested: the real hosted database and Vercel deployment, real phones.**
