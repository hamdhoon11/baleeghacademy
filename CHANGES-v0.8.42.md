# v0.8.42: imports checked and corrected (students, teachers, enrolments, courses, batches, expenses, grades)

Builds on v0.8.41. Independent of v0.8.39 (the security fixes). No database change.

Reported: the student import in People is not working; then: check all the import sections and correct them. The live error message was not available, so every import was measured and run in several ways. Four faults were found and fixed.

## What was wrong
1. **Importing students got slower with every student, and ran out of time.** After each new student the portal looked for people still waiting for an ID, with one more database query for every student who has no course yet. 100 students cost about 7,000 queries (71 a row, rising); on the hosted database that is far beyond what one request is allowed, so the import stopped half way with "Something went wrong" and only some rows saved. It is now 12 queries a row, however many students there are. The same slow-down hit People → Add person and approving applications.
2. **Each imported account spent a tenth of a second on its temporary password.** The slow password hash is right for passwords people choose; for 100 imported accounts it added 9 seconds. Temporary passwords (12 random characters, must be changed at first sign-in) now use a quick hash; the password the person then chooses gets the usual slow one.
3. **The enrolment import could only fill half of a batch.** In a real import the seats taken by earlier rows of the file were counted twice (once in the database, once from the file), so a batch of 60 was "full" after 30, although Check file said all would be created. Fixed; the check and the import now agree.
4. **Courses, batches, expenses and grades: a check could really save the rows on a newer Flask.** These imports run each row through the screen's own route. That relied on Flask handing the inner route the same database connection. Flask 3.2 no longer does: "Check file" would save the rows, and "Import" would then refuse them all as already there. `requirements.txt` said `Flask>=3.0`, so a new deployment could pick 3.2 up without anyone choosing it. The inner route is now always given the outer request's connection (works on both), and Flask is held below 3.2 until it has been tested.

## Also changed
- **Long files are sent in parts of 10 rows**, with "Working: 20 of 180 rows done…" on the screen, so no single request runs longer than the host allows. The result is put together as before, including the new-accounts download with every temporary password. Checks sent in parts still find a code, email or student repeated further up in the file.
- **If a part fails**, the screen says exactly where it stopped ("Stopped after 40 of 180 rows…") and lists what was done. Importing the same file again adds the rest; rows already there are refused, never added twice.
- A request the host cuts off now says "The server did not finish in time" instead of "Something went wrong".

## Not changed
- Students and teachers still need an email address in the file (the same rule as People → Add person).
- Imports only add; they never change existing records.

## Checks run
- Unit tests: whole suite in one run, 480 tests, all pass. New `tests/test_session42.py` (9): queries per imported student stay under 20 for 60 students; IDs are given as before (first course decides, migration gives BAL/STU); temporary password quick, chosen password slow, sign-in with the temporary password works; a check and an import in parts of 4, 7, 15 give the same rows and messages as the whole file; courses and batches in parts; enrolment import fills all 6 of 6 seats and check equals import; a check saves nothing with contexts as Flask 3.1 and as Flask 3.2 handle them; exports still work; requirements and page.
- The whole suite also ran with every database row in the PostgreSQL shape: nothing new fails.
- Measured (40 rows each, queries per row): courses 3, batches 6, expenses 5, students 12, teachers 21, enrolments 31.
- Browser: new `tests/e2e_import_parts.py` (11 checks on a phone screen: 45 students in five parts, the accounts download, a part that times out and the retry, 25 courses with a code repeated 22 rows apart); `e2e_excel.py`, `e2e_browser.py`, `e2e_navigation.py`, `e2e_round3.py` pass. The other eleven scripts were not run.
- **Not tested: a real PostgreSQL database, a real Vercel deployment, Flask 3.2 itself** (its behaviour was imitated), Microsoft Excel, real phones.
