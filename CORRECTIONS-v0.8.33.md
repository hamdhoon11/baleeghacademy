# v0.8.33: UI correction sessions 1 to 22

All 22 correction sessions from the plan were done in one pass on v0.8.32. This file gives, per session, what changed, the names
later work must keep, and a 5-line manual test checklist. Section "Checks run" at the end lists the automated tests.

Decisions you left blank (Session 20d, fonts and the login token): **nothing was changed**. Google Fonts stay; the token stays in
sessionStorage. Tell me if you want either changed.

---

## Session 1: Core reliability (index.html, learning.js)
- A failed save or button action no longer redraws the screen: what was typed stays, and the message appears in a `role="alert"` banner right before the form (or the row, table or panel of the button), scrolled into view and focused. `showErr(anchor, msg)`.
- The clicked or submit button is disabled with `aria-busy="true"` while its request runs (`busy(b, on)`); double clicks do nothing.
- `render()` numbers each run (`RSEQ`); an older run that finishes late is thrown away.
- `api()` goes through `send()`: a dropped connection says `network_error`, a request over 20 s is aborted and says `network_timeout` (uploads: 2 minutes, files: 2 minutes).
- A failed `/my/batches` is not remembered as "no courses": an error panel with Retry and Sign out. The same panel replaces the old blank page when `/auth/me` fails.
- `signout()` uses the `API` prefix. Tab clicks reset `eu em ec eb si ti aid sel result tmp` (`TAB_RESET`), never `S.sb`.
- A DO handler returns `false` when it drew what it needed itself; after a redraw the clicked button gets focus back (`S.refocus`).

Keep: `showErr`, `busy`, `send`, `RSEQ`, `TAB_RESET`, the "return false = no redraw" rule.
Test: (1) People, Add person, use an email that exists: message above the form, name still filled. (2) Click Save twice fast: one request. (3) Turn Wi-Fi off, press any button: "Could not reach the server". (4) As a student, make /my/batches fail (offline at sign-in): Retry panel, Retry works when back online. (5) Open a person, click Fees tab: People editor is closed next time.

## Session 2: Dialog component (new static/ui.js)
- `ui.confirm(msg, {danger, okText, title, details})`, `ui.ask(title, {label, required, multiline, value, hint})`, `ui.form(title, fields, {okText, validate})`; also `ui.pick` (quick jump), `ui.show` (help) and `ui.trap(el, {onEscape})` (focus trap for panels).
- Native `<dialog>` + `showModal()`, Tab stays inside, Escape cancels, focus goes back to the opener, danger dialogs start on Cancel, logical CSS, 44 px buttons. Required fields, numbers, whole numbers and min/max are checked inside the dialog.
- Usage: `if (!await ui.confirm(t("confirm_delete"), {danger: true})) return false;` · `const why = await ui.ask(t("fx_void"), {label: t("fx_prompt_reason"), required: true});` · `const v = await ui.form("Pay", [{id: "amount", label: "Amount", type: "number", required: true, min: 1}]);`

Keep: the `ui` names and option names above; CSS classes `dlg`, `dlg-f`, `dlg-b`, `dlg-a`.
Test: (1) Delete a material: red dialog, focus on Cancel. (2) Escape: dialog closes, focus back on Delete. (3) Tab many times: stays in the dialog. (4) Void an invoice with an empty reason: "Fill in: Reason". (5) Works at 640 px wide (buttons wrap, 44 px).

## Session 3: Dialogs in admin.js
- Every `prompt()`, `confirm()` and `sure()` in admin.js is gone (`sure` is deleted).
- Reasons: application reject (required, as the server requires), drop / move / remove from batch (optional, as the server allows), teacher payment void (required), category rename (`ui.ask` with the old name filled).
- `fePay` is one `ui.form`: amount (whole MVR, outstanding pre-filled), method `<select>` cash / bank_transfer / cheque / other with `fx_m_*` labels, reference, note (the note is now sent; the server already stored it).
- Deletes (course, batch, person, enrollment, expense, category, substitution) are danger dialogs that list what is affected from data already loaded: batch name and active/total students, person name/role/login ID with enrolment and taught-batch counts, enrolment student/course/status.

Keep: DO names unchanged (`ecDel delB euDel emDel bUnenrol emSet emMove fePay feVoid fnCatRename ...`); `S.ebInfo`, `S.euInfo`, `S.emInfo`, `S.apInfo` hold the delete-dialog details.
Test: (1) Batches, Edit, Delete: dialog shows "Active students: n". (2) Record teacher payment: method is a list. (3) Void a teacher payment with no reason: refused in the dialog. (4) Drop an enrolment, leave reason empty, OK: dropped. (5) Cancel on any of these does nothing.

## Session 4: Dialogs in fees.js, learning.js, notify.js
- `fxAsk` is now a `ui.ask` with a required reason; void, waive, reopen, reverse and slip reject use it.
- Discount is one `ui.form`: kind (Amount in MVR / Percent), value (whole number, at most 100 for percent), reason. The "10%" typing convention and its key `fx_prompt_discount` are removed.
- Duplicate-slip check uses `ui.confirm` with danger. Deletes in learning.js (material, assignment, recording, tutorial) and the announcement confirm in notify.js use `ui.confirm`.

Test: (1) Invoice, Discount, Percent 150: refused. (2) Discount Amount 50 with reason: saved. (3) Waive with reason: done. (4) Verify a slip whose file was used before: red confirm. (5) Send an announcement: confirm names the audience.

## Session 5: Dead code in index.html
- Fully overridden by later files and deleted from index.html: `dashboard` (by admin.js; fees.js wrapped it but admin.js replaced it), `courses`, `people`, `enrollments`, `settings`, `audit` (all admin.js). `admissions` was the only one still used (wrapped by admin.js) and moved in Session 10. `const views = {}` is all that is left. Helpers `table`, `field`, `form`, `val`, `onSubmit` stay (used in all screen files).
- Views that were defined more than once (v0.8.32, file:line): dashboard index.html:270, fees.js:30, admin.js:392 · admissions index.html:274, admin.js:136 · courses index.html:298, admin.js:13 · people index.html:303, admin.js:65, admin.js:438 · enrollments index.html:309, admin.js:118 · settings index.html:315, admin.js:146 · audit index.html:321, admin.js:242 · batches learning.js:230, admin.js:44, admin.js:268 · finance admin.js:286, admin.js:332 · home learning.js:57, fees.js:20.
- Now: every view is defined once, except `home` (learning.js plus the fees.js wrapper that adds the "fee due" notice for students; intentional, small).

Test: (1)-(5) open every admin tab once: nothing missing (the browser suite does this for all roles at two widths).

## Session 6: One Batches view (admin.js)
- One `views.batches` in admin.js; `batchEditor`, `batchStudents`, `batchSubs` are plain template functions. No `h.replace(...)`. learning.js's batches layer and the substitutes wrapper are deleted; `dayBoxes` became `DAYS_IN(sel, name)` in admin.js.
- Changed on purpose: the students and substitutes panels now sit right under the editor (they were at the very bottom, under the list). The editor's day boxes are named `bde` and the create form's `bd`; before, Save could pick up boxes ticked in the create form.

Keep: `editB closeB saveB delB bEnrol bUnenrol subRemove`, ids `be_*`, `bs_add`, `fsub`, `sb_*`, `fb`.
Test: (1) Edit a batch, tick a day, Save: list shows it. (2) Enrol a student from the panel. (3) Remove one with a reason. (4) Add and end a substitute. (5) Tick a day in the create form, then edit and save another batch: only the editor's days are saved.

## Session 7: mount() hook (learning, fees, notify)
- `mount(fn)` in index.html: queued during a view, run in order right after `root.innerHTML` is set, queue emptied on every render; a failing fn is logged and does not stop the rest.
- Every `setTimeout(...)` wiring in learning.js and fees.js is now `mount(...)` (notify.js had none). The "fetch before the base view" workarounds are gone with the merges (Sessions 6, 8, 10).
- Known limit: if two renders overlap, a slow older view could still queue a function into the newer render's queue (JavaScript cannot tell which render an `await` belongs to). Every queued function only wires elements by id, so the effect is at most a duplicate wiring; not seen in tests.

Keep: `mount`, `MQ`.
Test: (1) Tutorials post form works. (2) Classroom, Assignments, create works. (3) Fees, filter invoices works. (4) Record a payment works. (5) Switch tabs quickly 5 times: the last tab is shown and its forms work.

## Session 8: admin.js wiring and Finance
- All admin.js `setTimeout` wiring is `mount`. One `views.finance`: `fnDashPanel()` (dashboard and revenue), `feEarnPanel()` (teacher earnings), `fnExpensesPanels()` (expenses and categories), loaded together, same order as before. All DO names kept.
- Dashboard: admin.js `views.dashboard` is the only one; the index.html one and the fees.js wrapper (its "Collected this month" cards were never visible since Session 25) are deleted. The fee cards are still on the admin dashboard (from `/admin/dashboard`).

Test: (1) Finance opens with the dashboard, revenue, earnings, expenses. (2) Filter revenue. (3) Add, edit and delete an expense. (4) Calculate a month. (5) Dashboard filters work.

## Session 9: Navigation state
- `go(patch)` sets S keys and pushes a history entry `{view, eu, em, ec, eb, si, ti, aid, sel, back, scroll}`; the URL stays `#tab`. `popstate` restores the keys, so Back closes a detail screen first. `navBack(patch)` (in-app Back) uses `history.back()` when the list is the entry before; `closeDetail(patch)` (after Save/Cancel/Delete) returns to the list without leaving a stale entry.
- `go()` is used for: student and teacher records, the open assignment (student and Classroom), the batch, person, enrollment and course editors, and application review.
- `S.sif S.tif S.al S.pf S.fn` are kept in sessionStorage (`flt`) and come back after a refresh; cleared at sign-out.
- `BAR_PREFS = {student: ["home", "assignments", "fees", "progress"]}`: students get Fees in the phone bar; the sidebar and the More sheet keep the server order.
- A refresh keeps the open detail (it is read back from `history.state`).

Keep: `go`, `navBack`, `closeDetail`, `NAV_KEYS`, `DETAIL_KEY`, `BAR_PREFS`, sessionStorage key `flt`.
Test: (1) People, Edit, browser Back: editor closes, still on People. (2) Back again: previous tab. (3) Student information, search, refresh: search kept. (4) Student on a phone: bar is Home, Assignments, Fees, Progress. (5) Open a person, refresh: editor still open.

## Session 9A: Navigation structure and orientation
- Tabs are `<a href="#tab" class="tab" data-v aria-current="page">`; a plain left click navigates in the page, Ctrl/Cmd-click, middle-click and "open in new tab" are left to the browser.
- Phone top bar: section title next to the mark; on a detail screen a Back arrow (`#topBack`, label "Back") replaces the mark.
- `crumb(items)` / `crumbFor(label, closePatch)`: breadcrumb above the h1 on a computer only, for detail screens; earlier crumbs are links through `go()`/Back. It is a `div role="navigation"` (a `<nav>` picked up the sidebar styles and covered the page; found by the new tests).
- More sheet: focus trap (`ui.trap`), Escape closes and focuses More, closes on scrim click, on navigating, and when the window grows over 880 px.
- Last tab per person in localStorage `lastTab:<user id>`, used when the URL has no #name and only if still allowed.
- Scroll: forward to a new screen starts at the top; Back to a list returns to where you were.
- Admin sidebar: current group highlighted; groups collapse (button in the group title), saved in localStorage `navClosed:<user id>`; the current group cannot be collapsed. On a phone the groups are plain headings.

Keep: `.tab` as `<a>`, `#topBack`, `.crumb`, localStorage keys `lastTab:<id>`, `navClosed:<id>`.
Test: (1) Ctrl-click a tab: new browser tab on that section. (2) Phone, open a person: Back arrow; it returns to the list. (3) Computer: "People › Name" above the heading; People link works. (4) Collapse "System", reload: still collapsed; open Settings: group opens. (5) Scroll a long list, open an item, Back: same scroll position.

## Session 9B: Navigation enhancements
- Badges: Admissions = `pending_applications` and admin Fees = `slips_pending` (only for admins with the Fees area; `/dashboard` sends it only to them), student Assignments = open assignments from `/my/home` `todo`. Fetched after a render, kept 60 s, refreshed when the window gets focus (at most every 5 s) and after any save. Hidden at 0; the count is in the tab's aria-label. No new endpoint was needed. Not done (no endpoint yet): teacher "to grade" on Classroom would need a count endpoint that does not load the whole home screen (`GET /api/teacher/counts` or reuse `/teacher/dashboard`).
- Quick jump: Ctrl/Cmd+K, or "/" outside fields; filter over allowed tabs; admins also get Add course / Add person / Add enrollment, which open the tab, open the collapsed Add panel and put the cursor in it. Arrow keys and Enter. Search button at the top of the sidebar and inside the phone More sheet.
- Alt+1..9 opens the nth tab; "?" opens the shortcuts help; all ignored while typing in an input, textarea or select, and while a dialog is open.
- Skeleton (3 grey panels plus a heading bar) when a screen takes over 300 ms.
- Sub-tabs (Settings, Classroom, Fees) are one horizontally scrollable row that sticks under the phone top bar; the active one is scrolled into view. Classroom's sub-tabs moved out of the panel so sticky works.
- `tests/e2e_navigation.py` extended: 192 → 214 checks.

Keep: `BADGE`, `staleBadges()`, `loadBadges()`, `quickJump()`, `QUICK`, `openAdd` / `data-add` on Add panels.
Test: (1) Submit an application on /apply.html: Admissions badge 1 within a minute or on focus. (2) Ctrl+K, type "fees", Enter. (3) Ctrl+K, "add person": People with the form open, cursor in Name. (4) Alt+3 opens the 3rd tab; inside a field it types instead. (5) Phone: Settings sub-tabs scroll sideways and stay under the top bar.

## Session 10: Admissions and Courses
- One `views.admissions` in admin.js. The review panel and the correction form are above the list; Review uses `go()`, so the page opens at the panel, and has a Back button.
- "Delete ID copies after approving" checkbox is gone; Approve sends `delete_files: false`. "Delete ID copies" is its own red button with a `ui.confirm` (shown also after approval).
- Reject asks the reason with `ui.ask` (required).
- Courses: the create form is a collapsed "Add course" panel. Fee and registration fee (create and edit) are `min=0 step=1 inputmode=numeric` and checked as whole numbers (`wholeNum(id, label)`) before sending.

Keep: ids `ap rj wl df vi vg ab af fa fa_*` (plus DO `apReview apApprove apReject apWait apDelFiles apView apBack`), `addPanel(key, title, inner)`, `wholeNum`, `moneyAttrs`.
Test: (1) Review an application at the bottom of a long list: panel shown at the top. (2) Approve: password panel; ID copies still there. (3) Delete ID copies: confirm, then gone. (4) Add course with fee 350.5: "must be a whole number". (5) Add course panel is closed until clicked.

## Session 11: People and Enrollments
- People: search over name, login ID and email, on the client (`GET /api/users` has no `q`), with the role filter; 30 at a time with "Load more" (`S.pq`, `S.plim`, DO `peMore`). Create form in a collapsed "Add person" panel. The CSV import panel is part of the same view (was a second wrapper).
- Enrollments: student and batch pickers are a filter box plus select (`pickField(id, label, opts)`); students are active ones only, labelled "Name (login ID)", as on the Batches screen (the batch screen picker is the same component now). List search (student, course, batch, status, code) and paging (`S.enq`, `S.enlim`, DO `enMore`). Create form in a collapsed "Add enrollment" panel; empty student or batch is refused before sending.
- Admins limited to a picker area get names only from `/users`; they are treated as active (before, the batch screen showed them nobody).

Test: (1) People search by part of a login ID. (2) Load more appears over 30 people. (3) Enrollments, type part of a name in "Find student": select narrows. (4) Enrol: saved. (5) Search the list by batch code.

## Session 12: Settings and shared tabs
- `tabs({id, items, current, onSelect, label})` in index.html: `role=tablist/tab`, `aria-selected`, roving tabindex, Left/Right (mirrored in RTL), Home/End move focus, Enter/Space opens; `onSelect` may return a Promise and `false` to stay. Focus returns to the selected tab after the redraw.
- Used in Settings, Classroom and Fees (Fees was also a fake tablist).
- Settings: edits are tracked; switching group with unsaved edits asks `ui.confirm`; an "Unsaved changes" tag shows (and is announced) after the first edit.

Keep: `tabs`, `TABSEL`, `data-tabs` / `data-key`; the old DO names `ctab`, `fxTab`, `setTab` still exist (unused by the page).
Test: (1) Settings, change a value, click another group: asked. (2) Cancel: still there with the value. (3) Arrow keys move between sub-tabs; Enter opens. (4) Fees sub-tabs work by keyboard. (5) Screen reader says "tab, selected".

## Session 13: Activity log and time formatting
- Filters keep the "This user" drill-down; the batch drill-down is the Batch box.
- Asks for 51 rows with `offset` (new optional server parameter on `GET /api/audit`, see `tests/test_session33.py`), shows 50; Next is enabled only when row 51 exists.
- 5 columns (Time, Who, Action, Entity, Detail) and a "More" button per row that opens role, login ID, batch, old and new value, IP and the drill-down buttons.
- `fmtTime(utcText)` → "YYYY-MM-DD HH:MM" in Maldives time; used in the log, its summary, and in notify.js (older than a day, and "Last run").
- `feMonth` uses `prevMonth()` (the month before, in Maldives time) instead of "32 days ago".

Test: (1) Filter by action after "This user": still that user. (2) Exactly 50 rows: Next disabled. (3) Times are 5 hours ahead of the stored UTC. (4) More / Less on a row. (5) Finance earnings month defaults to last month on the 1st and 31st.

## Session 14: Classroom
- Grades save in place: no redraw, a "✓ Saved" mark next to the row. For a teacher without "Change saved grades" the row locks itself right after saving (as a redraw would show it) and the cursor moves to the Saved mark. "Save all" saves every changed row and says how many.
- Attendance: "Mark all present"; changing the date or the batch, or opening another sub-tab, with marks not saved asks first (one dialog even if the date field fires twice); the save message says "Attendance saved for N students".

Keep: `saveG` `saveGAll` `attAllPresent` `saveAtt`, `S.attDirty`, ids `gradep`, `gs_<student>`, `attp`, `data-orig` on grade fields.
Test: (1) Grade a student, Save: Saved mark, page does not jump. (2) Change two feedbacks, Save all: "2 grades saved". (3) Mark one absent, change date: asked; Cancel keeps date. (4) Mark all present, Save: count shown. (5) Teacher without permission: saved grade locks.

## Session 15: Notifications front end
- The panel uses `ui.trap`: focus moves in, stays in, Escape closes, focus returns to the bell. The old document-level Escape listener (one more on every open) is gone.
- Links: "tab" or "tab:id". assignments:<id> opens the assignment; fees:<invoice> opens Fees with that invoice highlighted (student) or the Slips tab with it highlighted (admin); classroom:<batch> switches the teacher to that batch (schedule for class-cancelled messages).
- `#bellLive` (polite live region outside the page) says the unread count when it changes.

Test: (1) Open the bell, Tab around: stays inside. (2) Escape: focus on the bell. (3) Open/close 5 times, then Escape once: no errors. (4) Click a grade notification: that assignment opens. (5) Screen reader hears "3 unread notifications" when one arrives.

## Session 16: Notification links (server)
- assignment_new, grade, assignment due → `assignments:<assignment id>`; slip uploaded/verified/rejected and fee reminders → `fees:<invoice id>`; class cancelled/reinstated → students "home", the teacher `classroom:<batch>`; substitute assigned → substitute and original teacher `classroom:<batch>`, students "home"; substitute removed → original teacher `classroom:<batch>`, substitute and students "home". Admin digests stay "fees". Old rows with a plain tab still work.
- `tests/test_session28.py`: two link assertions updated, `test_20a_links_open_the_item` added.

## Session 17: i18n keys
- The script found 214 missing keys; all are in en.json now (sentence keys keep the sentence), plus keys passed through variables the script cannot see (`qa_*`, `network_*`, statuses, `fx_m_cheque`). Script output is now empty.
- Raw snake keys now have labels: all → All, closed → Closed, upcoming → Upcoming, actions → Actions, created → Created, expenses → Expenses, inactive → Inactive (also running).
- Removed as unused: `fx_month_collection` (dead dashboard wrapper), `fx_prompt_discount` (old discount prompt).

## Session 18: Language and direction
- `setLang(code)` sets `<html lang dir>` (rtl for dv/ar) from `S.user.lang`, else `S.info.language`, else "en". Neither exists on the server yet, so the page stays English/LTR until one is added.
- `fmtNum` (Latin digits, grouping) and `fmtDate` (YYYY-MM-DD, Maldives time); "en-US" and `toLocaleDateString` are gone.
- Physical CSS found and fixed in index.html: `.brand` padding, phone `.brand` padding, `.tab::before` radius, `.kv th` text-align and padding, select arrow position (`[dir=rtl]` rule), group chevron, Back arrow. Also fixed: notify.js panel shadow, apply.html honeypot `left:-9999px`. Left as they are (direction-neutral or decorative): the loading bar animation `@keyframes ld`, the skeleton shimmer, `box-shadow` with x = 0.
- `tests/test_phase3` no longer forbids the text "rtl" in the page (it still forbids a language switch and Dhivehi text).

## Session 19: Accessibility sweep
- One persistent `#live` region (outside `#root`) updated by `flash()`/`announce()`; the visible note no longer carries `role=status`.
- `table(cols, data, extra, caption)`: visually hidden caption, `th scope="col"`; `labelTables` adds `scope="col"` to every header cell and keeps a cell's own `data-label`.
- Focus: to the error banner on failure; to the first panel (`[data-detail]`) when a detail opens inside a section; to `main` on a new section.
- Icon-only buttons: checked in the browser for every tab, 3 roles, 2 widths: none without an accessible name.
- Remaining findings (not fixed): hand-built tables other than the log have no caption; status tags rely on colour plus text (fine) but "✓/✗" in People needed hidden text (added) and may exist elsewhere; the notification panel is a div with `role=dialog`, not a `<dialog>`; the phone bottom bar has no landmark name distinct from the sidebar (same `nav`); fixed headings order (h1 → h3) in a few panels.

## Session 20: CSS cleanup and fonts
- Utility classes in index.html: `.full .m0 .mt1 .mb1 .bk .scrollx .rowflex label.inl`.
- `tools/codemod_styles.py` (dry run by default, `--write` to apply, safe to repeat). It has been run: 36 tags changed, inline styles in the JS went from about 50 to 9 one-offs.
- `.btn.sm` is 32 px high on a computer with a mouse (`pointer:fine` and over 880 px); 44 px on touch screens.
- Fonts and token: not changed (your decision line was empty).

## Session 21: Public apply form and file checks
- `checkFile(input, maxMb, types)` in index.html; every file input in the portal is checked when a file is picked (a document-level change listener; `data-max` overrides the limit). Wrong type, empty or too big: the file is cleared and a message appears under it. apply.html has the same function.
- `/api/public/info` now also returns `upload_max_mb` (ID copies, slips, receipts: 5, or 4 on Vercel) and `learning_max_mb`. The apply form shows the real limit (the "5 MB" text was wrong on Vercel), falls back to 4 MB.
- Failure to load courses, batches or info shows a message with "Try again"; Submit stays off until loaded. Replies that are not JSON (a Vercel 413) give a readable message. The honeypot field is kept.

Test: (1) Apply with a 6 MB file: message under the field, nothing sent. (2) A .docx as ID: "Use PDF, JPG, PNG". (3) Block /api/public/courses: "Try again" works. (4) Student slip of 10 MB: refused at once. (5) Teacher material of 15 MB: allowed on own server (20 MB), refused on Vercel (4 MB).

## Session 22: Tests
- Stale e2e scripts fixed: one `e2e_shim.login()` (clears the forced first password change for accounts made during the script, handles the course chooser, email or login ID), `e2e_shim.subtab()`, `e2e_shim.dialog()` (answers ui.js dialogs), `e2e_shim.preview_bytes()` (PDFs open in a tab since Session 8). Selectors updated for grouped Settings, the Classroom link moving to Classroom, the Session 9 catch-up invoice, Session 18 tutorial visibility.
- `test_warm_connection` is isolated (environment patched only inside it, `seed.py` executed for its own database): the whole suite now passes in one run.
- New `tests/e2e_ui.py` (27 checks) for Sessions 1, 2, 9A, 14; `tests/test_session33.py` (audit offset, upload limits).

---

## Checks run
- Unit tests, whole suite in one run: **418 tests, all pass** (including `test_warm_connection`).
- Browser (Chromium, phone 390 px and computer 1366 px): e2e_navigation 214, e2e_ui 27, e2e_browser 42, e2e_tutorials 19, e2e_links 10, e2e_recordings 9, e2e_student_info 8, e2e_permissions 7, e2e_teacher_info 7, e2e_submit 6: 349 checks, all pass, no script errors. Before this work only e2e_navigation and e2e_submit ran at all.
- Not done: a real PostgreSQL run, a real phone (iOS Safari: `<dialog>` needs iOS 15.4+), a screen reader pass (only checked by markup), RTL with real Dhivehi text.
