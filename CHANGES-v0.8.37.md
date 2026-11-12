# v0.8.37: Round 3 (grading, bulk actions, timetable, My files, monthly expenses)

Builds on v0.8.36 (Round 2). Round 3 completes the plan agreed after v0.8.34.

## Before you deploy: one database change (additive)
Run `python migrate_v0837.py` first: it is a **dry run** and shows what it would add. Then:
- SQLite: `python migrate_v0837.py --apply` (it writes a backup copy `portal.db.before-v0.8.37-<time>.bak` next to the database first).
- Hosted PostgreSQL: take the provider's backup or `pg_dump`, then `python migrate_v0837.py --apply --i-have-a-backup`.

It only **adds** columns: `tutorials.max_points` (existing tutorials become "out of 100"), `tutorial_submissions.grade, feedback, graded_by, graded_at` (all empty: nothing is graded until a teacher does it) and `expenses.recurring_id, recurring_month` (empty). It checks that every existing tutorial, answer and expense is unchanged before committing, and stops otherwise. A second run finds nothing to do. Two new empty tables (`recurring_expenses`, `recurring_done`) are created when the new version starts. If you skip the script, starting the new version makes the same additions automatically.

## New
- **Tutorial grading.** When posting a tutorial, a teacher sets **Marks out of** (100 by default; empty = comments only). Under **Answers**, ungraded answers come first with "To grade"; each has a grade and feedback box and **Save grade**. The student gets a notification and sees "Grade 9/10" and the feedback on the tutorial. Same rules as assignments: the poster or an admin grades; once saved, only an admin or a teacher with "Change saved grades" can change it (the first grader is kept; every change is in the activity log). If a student sends a new answer after grading, the teacher sees "answer changed after grading". Teacher Home shows "N tutorial answers to grade". Route: `POST /api/tutorial-submissions/<id>/grade`.
- **Timetable** tab for students, teachers and admins: one week, Monday to Sunday, every batch the person may see (not only the one picked at the top), today marked, cancelled and extra classes shown, Join button when the class is about to start, Previous / Next week. Admins can filter by teacher and course. On a phone the days are one under another; on a computer they are one row. Admins see it if they have Batches or Classroom.
- **My files** tab for students and teachers: every file they can open in one list with a search and a type filter. Students: class materials, worksheets, their own work and tutorial answers, payment slips and receipts. Teachers: materials and worksheets of their batches, tutorials they posted. Each opens through its existing route, which checks access again. Route: `GET /api/my/files`.
- **Bulk actions**: tick rows (or "Select all shown") and act once.
  - Fees → Invoices: **Waive** or **Void** all ticked open invoices with one reason.
  - People: **Make active** / **Make inactive** (your own account cannot be ticked).
  - Admissions (Pending / Waitlist): **Move to waitlist** or **Reject** with one reason.
  Each row goes through the same route as its own button, so checks, reasons and the activity log are as before. You see "Done for N of M", with the reason for any row that was refused. Ticks on rows that are no longer shown (another filter or search) are dropped, so an action never reaches a hidden row.
- **Monthly expenses** (Finance → Monthly expenses): category, amount, day of the month (1 to 28), description, first month, optional last month. On that day each month the expense is entered for you (when Finance is opened, and by the scheduled run), marked "monthly" in the list. If the first month is in the past, the months already due are entered at once (up to 12). Each month is entered once: a month you delete by hand is not entered again. Edit changes the months still to come; Pause / Resume; Delete stops it and keeps the expenses already entered. Routes: `GET/POST /api/recurring-expenses`, `PATCH/DELETE /api/recurring-expenses/<id>` (Finance area). The scheduled run's answer now includes `expenses_written`.

## Fixed
- `tests/e2e_submit.py` sometimes failed: Home also has "Submit work" buttons (since v0.8.35), so the script now waits for the Assignments page itself.

## Checks run
- Unit tests: whole suite, 449 tests, in one run. New `tests/test_session37.py` (7): grading rules (limits, other teacher, student, locked grade, admin change, first grader kept, notification, changed after grading, log), comments-only tutorials, My files (owner opens every path, nobody sees another's answer, admins refused), whole-week timetable, monthly expenses (validation, catch-up, written once, deleted month not rewritten, edit affects future only, pause, delete keeps expenses, permissions), new tabs, and the migration on an old database (dry run changes nothing, apply makes the backup, data unchanged, second run does nothing). Security map and tab lists updated.
- Browser: all 12 `tests/e2e_*.py`; new `e2e_round3.py` (21 checks on a phone screen: grading by the teacher and seen by the student, timetable, My files, bulk waive, bulk inactive, monthly expense).
- Not tested: a real Vercel deployment, PostgreSQL, real phones.
