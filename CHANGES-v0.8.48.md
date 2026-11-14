# v0.8.48: fee reminders by total and month, PDF for every report, monthly report by batch with charts, superadmin, academy logo

Builds on v0.8.47. **Database change: additive only** (one new column `users.is_super`, added automatically on start; no row is changed, nothing to run).

Asked:
1. Overdue reminders should be based on the student's total amount due and the months; a reminder 5 days before the due date to settle the payment, on WhatsApp and on the portal dashboard, showing within those 5 days.
2. Every report should have a PDF download, the monthly ones too; the monthly report better, batch by batch, with charts.
3. A superadmin who alone can erase the data and sign out (kick) and ban people in Who's online; other admins can still see who is online.
4. The Baleegh logo can be put in the portal from Settings.

## 1. Fee reminders by total and month
- **One reminder per student**, not one per invoice: "MVR 1,500 for Aug 2026, Sep 2026 and Oct 2026 is overdue (3 unpaid months, the oldest 96 days late)".
- **5 days before the due date** (Settings → Notifications, "Fee due soon", now 5 by default): "MVR 300 for Nov 2026 is due on 17 Nov 2026. Please settle the payment before the due date."
- **Student's Home (dashboard):** a red "Fees overdue" banner with the total and the months, and a yellow "Payment reminder" banner that shows only in the 5 days before the due date (it goes away when paid; after the date the month moves into the overdue banner).
- **Portal notice (bell):** the daily run (07:30) sends each student one notice with the total and the months. Overdue: the day after the due date, then every 7 days, and at once when another month becomes overdue. Due soon: once per due date. The admins' daily line now also says how many people are waiting for a WhatsApp reminder.
- **WhatsApp:** new tab **Fees → Fee reminders (WhatsApp)**. Two lists, *Overdue* and *Due in the next 5 days*: each person with the total, the months, each line, the last reminder, and buttons **WhatsApp** (and **WhatsApp · guardian** when a guardian number is saved) and **See message**. WhatsApp opens with the message written; it is recorded on each invoice in the message. **Remind next on WhatsApp** steps through everyone not reminded today. Download PDF of both lists.
- The two WhatsApp messages can be changed in **Settings → Fees** ("Overdue fees message", "Fee due soon message") with {name} {amount} {months} {count} {due_date} {days_left} {days_overdue} {details} {academy} {guardian}.
- A month with a payment slip waiting to be checked is left out of the amount (the student has paid); such people are listed under "Slips waiting".
- **Not automatic on WhatsApp:** a normal WhatsApp number cannot send by itself (only the paid WhatsApp Business API can, with a registered business number and approved templates). The portal notice and the Home banner reach students automatically; WhatsApp is one tap per person.
- The old per-invoice tab is now called **Overdue invoices** and is unchanged.

## 2. PDF for every report
"Download PDF" next to CSV/Excel on: **Fees → Monthly report**, **Fees → Payment report** (with its filters), **Fees → Fee reminders**, **Finance** (revenue by month/type/course/batch, expenses by category, 12-month chart), **Finance → Teacher earnings**, **Enrollments → Transfers and withdrawals**, **Activity log** (with its filters; newest 2,000 rows), and in **Classroom**: **Gradebook PDF** and **Attendance PDF** (month). Receipts, invoices and statements were already PDFs.
Each PDF uses the same rows as the screen, CSV and Excel; A4 landscape; academy name and logo at the top; page numbers and the time made (Maldives time) at the bottom; Arabic and Dhivehi names drawn with the portal's font. Every PDF download is in the activity log.

## Monthly report, batch by batch with charts
On screen and in the PDF:
- Cards: invoiced, collected, outstanding, **collection rate**, overdue.
- **By batch** chart (collected in blue, still to pay in orange) and table: course, batch, teacher, students, invoiced, collected, outstanding, %, paid, overdue (hand-made invoices with no batch are one "No batch" row).
- **Last 6 months** chart (collected and still to pay per month).
- Invoices this month: paid / part paid / unpaid / overdue.
- By course, by revenue type and who still has to pay, as before.

## 3. Superadmin
- **Only the superadmin** can: clear the portal's data (Settings → Clear portal data), and sign out, pause, suspend (ban), restore, bulk-act and "sign out everyone" in Who's online.
- **Every admin** (full or limited) now sees **Who's online** (the list, the Dashboard card and the sign-in history) but without the buttons; the page says only the superadmin can act.
- **Who is superadmin:** to start with, the earliest active full admin (in your portal: the first admin account). The superadmin can make another full admin superadmin, or take it away, in **People → edit → Superadmin** (there must always be one). Shown as a "Superadmin" tag in People and Who's online.
- **Protected:** no other admin can edit, disable, limit, reset the password of, or delete a superadmin's account. Pause-ended notices go to the superadmin.
- Activity log: `superadmin_change`.

## 4. Academy logo
- **Settings → Academy details → Academy logo:** upload a PNG or JPG (up to 1 MB), change it or remove it.
- Shown in the menu bar, on the sign-in page, on the public application form, as the browser tab icon, and at the top of receipts, invoices, statements and every report PDF.
- Clearing the portal's data keeps the logo (like the settings). Activity log: `logo_change`.

## Routes (new)
`GET /api/fees/reminders`, `POST /api/fees/reminders/sent`, `GET /api/fees/reminders.pdf` (Fees area); `GET /api/fees/report.pdf`, `GET /api/fees/payment-report.pdf` (Fees); `GET /api/finance/report.pdf`, `GET /api/earnings/report.pdf` (Finance); `GET /api/enrollment-events.pdf` (Enrollments); `GET /api/audit.pdf` (Audit); `GET /api/batches/<id>/gradebook.pdf`, `GET /api/batches/<id>/attendance.pdf` (admin or the batch's teacher, Classroom); `POST|DELETE /api/settings/logo` (Settings); `GET /api/public/logo` (public). `/api/my/fees/summary` has `reminder`; `/api/fees/report` has `by_batch`, `status_counts`, `trend`, `totals.rate`; `/api/public/info` has `logo_url`; `/api/auth/me` has `user.is_super`; `PATCH /api/users/<id>` takes `is_super`.

## How it works (for the next session)
- `feereminders.py` (new): `dues(t, student_id, days)` is the one place that adds up overdue / due-soon per person; used by the WhatsApp list, `/my/fees/summary` and notify.py's daily run (`app.extensions["feedue"]`).
- `reportpdf.py` (new): `build(title, blocks, ...)` with blocks stats / heading / note / table / bars / columns; `app.extensions["pdf"](title, blocks, filename, subtitle)` adds academy name, logo and clock.
- `branding.py` (new): logo in file storage area `branding`, metadata in the hidden setting `_logo`; `app.extensions["branding"]["logo_bytes"]()`.
- Superadmin: `app.is_super(u)` / `super_ids()` / `super_only()` (on `ns`); `users.is_super` in `dbx.V0847_USER_COLUMNS`. While nobody has the flag, the earliest active full admin counts (no lock-out on upgrade). `settings_schema.FULL_ONLY` is now empty.

## Checks run
- Unit tests: whole suite, **533 tests, all pass**. New `tests/test_session48.py` (11): superadmin rules (who may look, who may act, protected account, hand-over, never zero); reminders per person with total and months, WhatsApp link, sent recording; due-soon at 6 / 5 days before and after the date; daily notices once per student; slip waiting left out; monthly report by batch, status counts, 6-month trend; every PDF route (status, type, rights, bad month); PDF text holds the numbers; logo upload/refuse/serve/remove and on PDFs; new column. Updated pinned tests: test_session28 (notice wording, default 5 days), test_session47 and test_permissions (limited admins see Who's online), test_session32 security map, test_phase4 tab list.
- Browser: new `tests/e2e_v0848.py` at 390 px and 1280 px (31 checks, all pass): logo upload and shown in menu, tab icon and sign-in page; reminder cards with totals and months; WhatsApp opens with the number and message and is recorded; monthly report charts and no sideways scrolling; PDF button; student Home overdue and "settle before the due date" banners; second admin sees no action buttons and no Clear data. Also pass: e2e_presence (updated), e2e_reset, e2e_browser, e2e_mark_paid, e2e_manual_invoice, e2e_navigation, e2e_ui, e2e_permissions, e2e_earnings, e2e_round2.
- Not tested: the hosted PostgreSQL database and Vercel, real phones, a real WhatsApp send.
