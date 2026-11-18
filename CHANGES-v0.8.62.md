# v0.8.62: Removing a person: say clearly whose password to type

Reported: "Still can't remove them. It tells me to write their password before deletion, and when I set a new password for them and paste it, it still says the password is wrong."

**Why it failed:** the password step in People → Delete asks for **the admin's own password** (the one you sign in with), not the password of the person being removed. The dialog only said "Your password", so it read like "their password". Resetting the student's password and pasting it can never work.

## Changed
- The password box now says **"Your own password (you are signed in as <your login ID>)"**, and the hint says not to type or reset the other person's password.
- If you type **the removed person's password** by mistake, the portal now says exactly that: "That is <name>'s password. Type YOUR OWN password instead: the one you sign in with as <login ID>." Nothing is removed.
- Any other wrong password says "Wrong password. Type your own password … Not the password of the person being removed."
- Password boxes in dialogs no longer trim spaces, so a password is checked exactly as typed (same as sign-in).
- Activity log: `delete_user_refused` says "their password typed" when that was the mistake.
- App cache version bumped (sw.js) so phones load the new screen.

## Routes
- `GET /api/users/<id>/removal`: also returns `you` (the signed-in admin's login ID).
- `DELETE /api/users/<id>`: a wrong password is still 403, now with `code: "their_password"` or `"wrong_password"`.

## Checks run
- Unit tests: whole suite, **593, all pass**. New `test_v0861.py::test_02b`: the student's password gives `their_password` and removes nothing; a random one gives `wrong_password`; the admin's password removes them.
- Not tested: the live Vercel site.
