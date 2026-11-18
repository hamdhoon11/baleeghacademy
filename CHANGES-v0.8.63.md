# v0.8.63: Notice board, a to-do list for everyone, and more notifications

Asked: "For notifications include more, like showing if anything is done or needs to be read; this should be user based. Also include somewhere we can post things for students to see, like posts and videos, or announcements."

**Choices made (asked):**
- A personal to-do list, more notifications, and "Seen by" on posts.
- Admins and teachers post. Teachers post only to their own batches.
- Videos are added as YouTube, Google Drive or Vimeo links. No video uploads, because Vercel limits uploads to 4 MB.
- Posts can be pinned, can have pictures and files, and students can comment.

No migration script is needed. The four new tables are created by `schema.sql` when the app starts.

## New: Notice board (new tab for everyone)
**Reading:** everyone sees the posts meant for them. You don't need a permission to read.
- **Everyone:** all students and all teachers.
- **All students** or **All teachers**.
- **One batch:** its active students and its teacher.
- Admins see every post.

**Posting** (People area "Write posts on the Notice board"):
- Admins and teachers get this area by default. A limited account needs it ticked.
- Admins post to any audience. Teachers post only to a batch they teach.

**A post** has:
- a title and text;
- a video link, which plays inside the post;
- up to 6 pictures or files. Pictures show in the post; PDF, Word, PowerPoint, Excel and audio files open or download.

Everyone the post is for gets a notification that opens the post.

**New and read:**
- Unread posts are tagged **New**, and the tab heading shows how many are new.
- A post counts as read once it has been shown on the screen.

**Seen by:**
- The author and admins see "Seen by 3 of 12".
- Pressing it lists who has seen the post, and when, and who hasn't yet.

**Comments:**
- Anyone who can see a post can comment, unless the author turned comments off.
- You delete your own comments. The author and admins delete any comment, and that is written to the activity log.
- The author gets a notification for each comment.

**Manage post** (author and admins):
- Edit, pin (pinned posts stay at the top), add or remove files, and delete.
- Deleting removes the post's files, comments and read marks. The activity log records it.

## Notifications: To-do tab, and New/Read in words
The bell panel now has two tabs.

**Notifications:**
- Each line says **New** or **Read**, not only bold text.
- New option: **Only new**.

**To do:** each person's own list, in three parts (To do, Waiting, Done). Tapping a line opens the right screen.
- **Student:**
  - work to hand in, with the due date, marked when late;
  - work handed in, with the grade once given;
  - tutorials from the last 30 days, answered or not;
  - fees to pay, a slip waiting to be checked, or "No fees to pay";
  - new posts to read.
- **Teacher:**
  - today's classes: take attendance, attendance taken, or later today;
  - work waiting for a grade, per assignment;
  - tutorial answers to grade;
  - new posts.
- **Admin:**
  - the same items as the Dashboard's "To do today";
  - new posts.

**New notifications:**

| Event | Who is told | Opens |
|---|---|---|
| New post | everyone it is for | the post |
| Comment on your post | the author | the post |
| New material | the batch's students | Materials |
| New class recording | the batch's students | Recordings |
| New tutorial | students of that course (all students if it has no course) | Tutorials |
| Marked absent | the student, once per class | Progress |
| New invoice to pay (monthly, registration or manual) | the student | Fees, at that invoice |

## Other changes
- A batch with posts cannot be deleted. Close it instead, as with other records.
- Removing a person (v0.8.61):
  - their comments and read marks go with them;
  - posts they wrote move to the admin who removes them, like tutorials.
- **Clear portal data** also deletes posts and their files.
- **Check for missing files** includes Notice board files.
- Admin phone bar: Dashboard, Notice board, Admissions, Interest list. Students' phone bar is unchanged (Home, Assignments, Fees, Progress); the Notice board is under More.

## Routes
- `GET /api/posts?before=ID`
- `POST /api/posts`, `PATCH /api/posts/<id>`, `DELETE /api/posts/<id>`, `POST /api/posts/<id>/pin`
- `POST /api/posts/<id>/files`, `DELETE /api/posts/<id>/files/<fid>`, `GET /api/posts/<id>/files/<fid>`
- `POST /api/posts/read`, `GET /api/posts/<id>/seen`
- `GET|POST /api/posts/<id>/comments`, `DELETE /api/posts/<id>/comments/<cid>`
- `GET /api/my/todo`: every role, own list only.

## How it works (for the next session)
- **Server:**
  - `posts.py` (new): the visible-posts rule is `visible(u)`, the audience is `audience_ids(p)`, and the video link parser is `video_embed(url)`.
  - `todo.py`: `/api/my/todo`. Student and teacher items come from `learning.py` (`app.extensions["my_todo"]`), new-post counts from `posts.py` (`app.extensions["posts_unread"]`).
  - `fees.py`: `tell_invoice()`.
- **Tables:** `posts`, `post_files`, `post_reads`, `post_comments`. They are in `removeperson.PLAN`, `resetdata.LABELS` and `filecheck.REFS`.
- **Front end:** `static/posts.js` (new). `static/notify.js` holds the bell's To-do tab. The `sw.js` version is bumped.

## Checks run
- **Unit tests:** whole suite, **603, all pass**.
- **New `tests/test_v0863.py`** (10 tests):
  - who sees what, and who is notified;
  - who may post;
  - read and Seen by;
  - comments;
  - video links;
  - files, pin, edit and delete;
  - a teacher manages their own post;
  - the new notifications (an absence is notified only once);
  - everyone's to-do list;
  - removing people.
- **Updated tests:** `test_session32` (security map lists the new routes), `test_permissions` (tab lists), `e2e_permissions` (student tab list).
- **Browser: new `tests/e2e_v0863.py`**, at 390 px and 1280 px, **26 checks, all pass**:
  - posting with a picture and a video;
  - New and Read in the bell;
  - To-do tab;
  - a notification opens the post;
  - a shown post counts as read;
  - comment;
  - Seen by.
- Also re-run and passing: `e2e_permissions`, `e2e_navigation`, `e2e_v0858`, `e2e_v0861`.
- **Not tested:**
  - a real PostgreSQL database;
  - the live Vercel site;
  - files in a bucket;
  - videos actually playing (the test machine has no internet; the right YouTube player address is checked).
