# v0.8.58: batch end time; Teachers' room (staff chat, teachers' guide, head teacher)

Asked:
- On Batches, choose when the class ends as well as when it starts.
- A place for teachers to talk and share their own teaching files, like a teachers' guide.
- A head teacher with more rights than other teachers in that chat and section.

## Database changes (added on their own when the new version starts)
Nothing existing is changed:
- `batches.end_time` (empty for every existing batch).
- `teachers.is_head` (0 for everyone).
- Three new empty tables: `staff_messages`, `staff_folders`, `staff_files`.

## 1. Batch end time
- **Batches** has an **End time** next to Start time, both when you add a batch and in the batch editor.
- The list shows the class as `16:00–17:30`.
- The end must come after the start. A class cannot run past midnight.
- If you set an end time, the class length comes from start to end. If you leave it empty, the course's "minutes per class" is used, as before.
- The class length is used in these places:
  - Timetable and Home (the "16:00–17:30" shown to students and teachers);
  - when the Join button disappears;
  - weekly hours in Teacher information.
- Classroom, My information, the teacher dashboard and the public application form show the end time too.
- Batch Excel import, template and export have an `end_time` column.
- Changing the end time is in the activity log.

## 2. Teachers' room (new tab)
Teachers find it under the Teaching group, next to Tutorials. Admins see it in the same group. Students never see it, and every route refuses them.

**Chat**
- One group chat for teachers and admins.
- Each message shows who wrote it, with an "Admin" or "Head teacher" tag.
- Members can:
  - reply to a message;
  - attach a file (PDF, picture, Word, PowerPoint, Excel, audio or video, with the same checks as class materials);
  - edit or delete their own messages.
- New messages appear on their own every 8 seconds. A half-typed message is kept.
- Pinned messages stay at the top.
- Links in messages can be clicked.

**Teachers' guide**
- Shared files and links to teach from, such as lesson plans, answer keys and notes.
- Files can sit in folders, and there is a search.
- Anyone in the room can add a file or link, and can change or delete their own.
- A **locked** folder takes files only from head teachers and admins. Use it for official guides.

**Head teachers** (admins only)
- Press **Make head teacher** next to a teacher. You can choose more than one.
- That teacher gets a notification.

| | Teacher | Head teacher | Admin |
|---|---|---|---|
| Read, post, reply, attach | ✓ | ✓ | ✓ |
| Edit or delete own messages and files | ✓ | ✓ | ✓ |
| Add files to unlocked folders | ✓ | ✓ | ✓ |
| Pin messages (everyone else in the room is notified) | | ✓ | ✓ |
| Remove anyone's message | | ✓ | ✓ |
| Make, rename, lock or delete folders; add files to locked folders | | ✓ | ✓ |
| Edit, move or delete anyone's guide file | | ✓ | ✓ |
| Choose head teachers | | | ✓ |

- Removing the head-teacher role takes these rights away at once.
- The activity log records:
  - removing someone else's message, with what it said;
  - pins;
  - head-teacher changes;
  - guide files and folders.
- Ordinary chat messages are not logged.

**Permissions:** new area "Teachers' room". It is part of "everything" for teachers and for full admins. A teacher or admin whose permissions are **limited** does not get it until you tick it in People.

**Files:** files are private and open only through the room's own routes. Settings → Files and storage → "Check for missing files" covers them. Clear data deletes them.

## Checks run
- Unit tests: **568, all pass**.
- New `tests/test_v0858.py` (9 tests):
  - end time saved, used, cleared and checked;
  - teacher views and weekly hours;
  - Excel columns;
  - who gets into the room;
  - chat edit, delete and reply;
  - attachments, including wrong and fake files;
  - head-teacher rights, and losing them;
  - folders and locked folders.
- Updated tests:
  - `test_session32`: security map lists the 16 new routes; students and limited accounts are refused on all of them;
  - `test_permissions`: tab lists.
- Browser: new `tests/e2e_v0858.py`, at 390 px and 1280 px, **21 checks, all pass**:
  - batch end time in the form, list, editor, error message and timetable;
  - the admin makes a head teacher;
  - a teacher sends a message with an attachment;
  - a new message appears without a reload, and a half-typed message is kept;
  - the head teacher pins a message, the teacher is notified, and the head teacher makes a locked folder.
- Not tested: a real PostgreSQL database, a real Vercel deployment, real phones.
