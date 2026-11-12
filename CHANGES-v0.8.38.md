# v0.8.38: Excel imports (with templates) and Excel exports

Builds on v0.8.37 (Round 3). No database change.

## Imports: every import takes Excel (.xlsx) or CSV, and has a template
The same steps everywhere: **Download template (Excel)** → fill in the **Data** sheet in Excel → **Check file** (nothing is saved; every row is checked and any problem is listed with its row number and reason) → **Import**. One bad row never stops the others.

Each template has:
- a **Data** sheet with the column names (required ones in red) and drop-down lists where a column has fixed choices;
- an **Instructions** sheet saying what to write in each column, with an example;
- a **Lists** sheet, where it helps, showing what already exists (course codes, batch codes, teachers, expense categories), which the drop-downs use.

Code and phone columns are set to text, so 0771234 keeps its 0. Excel dates and times are read correctly. Old .xls files get a clear message to save as .xlsx.

| Import | Where | What it creates |
|---|---|---|
| Students, Teachers, Enrolments | People (bottom) | as before, now from Excel too |
| **Courses** (new) | Courses | courses and tuition classes |
| **Batches** (new) | Batches | batches of existing courses, with teacher, days, time, seats |
| **Expenses** (new) | Finance | past expenses into existing categories |
| **Grades** (new) | Classroom → Assignments → open one | grades and feedback for that assignment or test; the template is the class list already filled in |

The new imports send every row through the same route as the screen, so each row gets exactly the same checks, rules and activity-log line as typing it in. For example, a saved grade still needs "Change saved grades" to be changed, and a course code cannot be used twice. A check goes through those routes too and then undoes everything, so it reports exactly what Import will do (also a code used twice inside the same file) and sends no notifications.

## Exports: Excel wherever there is a list
New: **Invoices** (Fees → Invoices, with the filter on screen), **Expenses** (Finance, with the filter and a total row), **Applications** (Admissions, for the status shown; no ID copies), **Courses** and **Batches** (the same columns as their imports, so a file can go out, be edited and come back as new rows), **Gradebook** (Classroom → Gradebook: one column per assignment or test, average and attendance), **Attendance register** (Classroom → Gradebook: choose the month; P/L/A/E per class date with totals).
Excel added next to CSV: **Activity log**, **Fees monthly report**, **Transfers and withdrawals**, **Enrolments** (Student information).
Already had Excel: student and teacher information, payment report, teacher earnings.

Exports read the same route the screen uses, with the same filters and permission check, and every download is in the activity log. Text that a spreadsheet would run as a formula is saved as plain text.

## Fixed
- After **Check file**, the page forgot the chosen file, so **Import** asked for it again. It is now kept and shown ("Chosen: students.xlsx").

## Not done (on purpose)
- No import for payments or invoices: money needs receipts and the slip checks, so it stays on the Fees screens.
- Imports never update existing records; they only add. A row for something that exists is refused with the reason.

## Checks run
- Unit tests: whole suite, 456 tests. New `tests/test_session38.py` (7): every template (sheets, empty Data sheet, drop-downs, lists, text columns, permissions); students from Excel (dates, leading 0, check saves nothing, .xls refused); courses and batches (duplicate in the same file caught by the check, same log lines, teacher by ID or email, times like 9:00); expenses (unknown category, future date); grades (class-list template, other teacher refused, skip empty, check sends no notification, saved grade locked); list exports match the screen, permissions, logged; formula text stays text.
- Browser: all 13 `tests/e2e_*.py`; new `e2e_excel.py` (17 checks on a phone screen: template → fill → check → import for students, courses, expenses and grades; downloads of courses, expenses, invoices, gradebook and attendance).
- Templates were opened in LibreOffice to make sure they load. Not tested: Microsoft Excel itself, real phones.
