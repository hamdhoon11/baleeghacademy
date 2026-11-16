# v0.8.59: installable app; "Keep me signed in on this device"

Asked:
- Can the portal be an app people download?
- Chosen: the installable web app (no app store), with "Keep me signed in on this device".

## Database changes
None. One new setting, `remember_days` (Settings → Security), which starts at 30.

## 1. Installable app
- **Android, and Chrome or Edge on a computer:** an **Install app** button appears on the sign-in page and next to Sign out in the menu. It opens the browser's own "Install" box. Once installed, the portal has its own icon and opens full screen, with no address bar.
- **iPhone and iPad:** iPhones have no install box, so **Install app** shows the three steps instead: Share → Add to Home Screen → Add. This works in Safari.
- The button disappears once the app is installed, and it never shows inside the installed app.
- **Icon:** if your logo (Settings → Academy logo) is square and at least 192 × 192 px, it becomes the app icon. Otherwise the built-in teal and gold "ب" is used, so a wide logo is never squashed. Changing the logo later changes the icon for new installs. Phones that already have the app may keep the old icon for a while.
- **App name:** taken from Settings → Academy name. On the home screen it shows as "Baleegh".
- **Offline:** without a connection the app still opens and says it cannot reach the server, with Retry. It does not show the browser's error page.
- **Updates:** nothing extra to do. Every new version you deploy reaches the app the next time it is opened.

## 2. Keep me signed in on this device
- The sign-in page has a new tick box, **Keep me signed in on this device**, with a note to use it only on your own phone or computer.
- **Ticked:** the person stays signed in for 30 days, even after closing the app or the browser.
- **Not ticked:** as before. The sign-in ends when the tab is closed or after "Stay signed in for (hours)".
- In the installed app the box is ticked by default. In a browser tab it is not.
- **Still ends a kept sign-in at once:**
  - Sign out;
  - changing your password (the device you changed it on stays signed in and stays remembered);
  - an admin resetting or setting the password;
  - an admin's Sign out, Suspend or Pause, or deactivating the account.
- **Settings → Security → Keep me signed in on this device (days):** 1–90. **0** hides the tick box for everyone.
- The Activity log notes "kept signed in on this device" on those sign-ins.

## Safety
- The app stores only the page, its scripts, the text and the icons on the phone. **Nothing from `/api/` is ever stored**: fees, grades, messages, files and personal details always come fresh from the server. The browser test checks this.
- A kept sign-in is saved in the browser's storage on that device. Anyone who uses that phone or computer while it is unlocked is signed in as that person, which is why the note says "not a shared one".

## Files
- New: `static/sw.js` (service worker), `static/icons/` (4 icons), `tests/test_v0859.py` (13), `tests/e2e_v0859.py` (browser).
- Changed: `app.py` (manifest, iPhone icon, sw.js headers, kept sign-ins), `branding.py` (logo as app icon), `settings_schema.py`, `static/index.html`, `static/i18n/en.json`, `API.md`, `tests/test_session32.py` (the two new public routes recorded as public by decision).

## Checks run
- Unit tests: whole suite, 581 tests, all pass.
- Browser (`tests/e2e_v0859.py`, Chromium at 390 px and 1280 px, plus an iPhone profile), 27 checks, all pass:
  - the worker registers and controls the page;
  - an unticked sign-in does not survive a new tab, and a ticked one survives closing and reopening;
  - the saved copies hold no `/api/` replies;
  - the app opens offline;
  - Sign out forgets the token;
  - the Install button appears without wiping a half-typed ID, and opens the install box;
  - the iPhone steps show;
  - inside the installed app the box is ticked and there is no Install button.
- **Not tested:** installing on a real Android phone and a real iPhone, and the live Vercel site.
