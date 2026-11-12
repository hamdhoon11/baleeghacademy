// Session 28: notification bell and inbox (everyone), announcements and the reminder run (admin). Uses api(), S, esc(), t(), $, go(), fmtTime() from index.html and ui from ui.js.
// Session 15: the panel behaves like the ui.js dialogs: focus moves in, stays in (ui.trap), and goes back to the bell; Escape closes it; no listener is left behind.
(function () {
  let timer = null, release = null, last = null;
  const css = document.createElement("style");
  css.textContent = "#bell{position:relative}#bell .n{background:var(--coral);color:#fff;border-radius:10px;font-size:.75rem;padding:0 .4rem;margin-inline-start:.3rem}" +
    "#nov{position:fixed;inset:0;background:rgba(16,38,43,.45);z-index:50;display:flex;justify-content:flex-end}" +
    "#npanel{background:#fff;color:var(--ink);width:min(26rem,100%);height:100%;overflow-y:auto;padding:1rem;box-shadow:-4px 0 16px rgba(0,0,0,.2)}[dir=rtl] #npanel{box-shadow:4px 0 16px rgba(0,0,0,.2)}" +
    "#npanel .it{display:block;width:100%;text-align:start;background:none;border:0;border-bottom:1px solid var(--line);padding:.7rem .3rem;cursor:pointer;color:inherit;font:inherit}" +
    "#npanel .it.un{background:var(--mist);font-weight:600}#npanel .it small{display:block;color:#51696e;font-weight:400}#npanel .row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center;margin:.5rem 0}" +
    "#npanel label{display:block;margin:.5rem 0}#npanel input,#npanel select,#npanel textarea{width:100%;box-sizing:border-box;padding:.5rem}";
  document.head.appendChild(css);

  function when(ts) {                       // server time is UTC text, 'YYYY-MM-DD HH:MM:SS'
    const d = new Date(String(ts).replace(" ", "T") + "Z"), m = Math.round((Date.now() - d) / 60000);
    if (m < 1) return t("just now");
    if (m < 60) return m + " " + t("min ago");
    if (m < 1440) return Math.round(m / 60) + " " + t("h ago");
    return fmtTime(ts);                     // older than a day: the date and time in Maldives time (Session 13)
  }
  const setCount = n => {
    const b = $("#bellN"); if (b) { b.textContent = n > 0 ? (n > 99 ? "99+" : n) : ""; b.hidden = !(n > 0); }
    const bt = $("#bell"); if (bt) bt.setAttribute("aria-label", t("Notifications") + (n > 0 ? " (" + n + " " + t("unread") + ")" : ""));
    if (last !== null && n !== last) { const l = $("#bellLive"); if (l) l.textContent = n > 0 ? t("unread_count").replace("{n}", n) : t("no_unread"); }   // Session 15: said once, only when the number changes
    last = n;
  };
  async function refreshCount() { try { setCount((await api("/notifications/unread-count")).unread); } catch (x) { /* the bell must never break the page */ } }
  function close(refocus = true) {
    const o = $("#nov"); if (!o) return;
    if (release) { release(); release = null; }
    o.remove(); refreshCount();
    if (refocus) { const b = $("#bell"); if (b) b.focus(); }
  }
  function open(html) {
    close(false);
    const o = document.createElement("div"); o.id = "nov";
    o.innerHTML = `<div id="npanel" role="dialog" aria-modal="true" aria-labelledby="nTitle" tabindex="-1">${html}</div>`;
    o.addEventListener("click", e => { if (e.target === o) close(); });
    document.body.appendChild(o);
    const p = $("#npanel");
    release = ui.trap(p, {onEscape: () => close()});   // the listener is on the panel, so it disappears with it
    p.focus();
    return p;
  }
  // focus the first thing inside the panel each time its content is replaced
  const focusIn = () => { const p = $("#npanel"); if (!p) return; const f = p.querySelector("h2[tabindex], button, input, select, textarea"); (f || p).focus(); };
  // Session 15: a link is "tab" or "tab:id". Old plain-tab links keep working.
  function openLink(link, kind) {
    const [tab, raw] = String(link || "").split(":"), id = +raw || null;
    if (!tab || !S.user || !(S.user.tabs || []).includes(tab)) return;
    const extra = {};
    if (tab === "assignments" && id) extra.aid = id;
    if (tab === "people" && id) extra.eu = id;   // v0.8.35: password help request: open that person
    if (tab === "fees" && id) { S.fxhl = id; if (S.user.role === "admin") S.fxt = "slips"; }
    if (tab === "classroom" && id) {
      if (S.user.role === "teacher" && (S.mine || []).some(b => b.id === id)) { S.sb = id; sessionStorage.setItem("sb", id); }
      else S.cb = id;
      S.ct = /^class_/.test(kind || "") ? "schedule" : "attendance";
    }
    openTab(tab, extra);
  }

  async function inbox(before) {
    const j = await api("/notifications?limit=20" + (before ? "&before=" + before : ""));
    return j;
  }
  function itemsHtml(items) {
    return items.map(i => `<button class="it ${i.read_at ? "" : "un"}" data-id="${i.id}" data-link="${esc(i.link || "")}" data-kind="${esc(i.kind || "")}">${esc(i.title)}${i.body ? `<small>${esc(i.body)}</small>` : ""}<small>${esc(when(i.created_at))}</small></button>`).join("");
  }
  async function panel() {
    const p = open(`<h2 id="nTitle">${esc(t("Notifications"))}</h2><p class="hint">${esc(t("Loading..."))}</p>`);
    let j; try { j = await inbox(); } catch (x) { p.innerHTML = `<h2 id="nTitle">${esc(t("Notifications"))}</h2><div class="msg err" role="alert">${esc(x.message)}</div><button class="btn alt" id="nx">${esc(t("Close"))}</button>`; $("#nx").onclick = () => close(); focusIn(); return; }
    if (!$("#npanel")) return;   // closed while loading
    const admin = S.user && S.user.role === "admin";
    p.innerHTML = `<div class="row"><h2 id="nTitle" style="margin:0;flex:1">${esc(t("Notifications"))}</h2><button class="btn alt" id="nx">${esc(t("Close"))}</button></div>` +
      `<div class="row"><button class="btn alt" id="nra">${esc(t("Mark all as read"))}</button>${admin ? `<button class="btn alt" id="nan">${esc(t("Send announcement"))}</button><button class="btn alt" id="nrm">${esc(t("Reminders"))}</button><button class="btn alt" id="nwa">${esc(t("WhatsApp"))}</button>` : ""}</div>` +
      `<div id="nl">${j.items.length ? itemsHtml(j.items) : `<p class="hint">${esc(t("Nothing here yet."))}</p>`}</div>` +
      (j.items.length === 20 ? `<p><button class="btn alt" id="nmore">${esc(t("Older"))}</button></p>` : "");
    $("#nx").onclick = () => close();
    focusIn();
    $("#nra").onclick = async () => { await api("/notifications/read-all", "POST"); panel(); };
    if (admin) { $("#nan").onclick = announceForm; $("#nrm").onclick = remindersPanel; $("#nwa").onclick = waForm; }
    const wire = () => document.querySelectorAll("#nl .it").forEach(b => b.onclick = async () => {
      try { await api("/notifications/" + b.dataset.id + "/read", "POST"); } catch (x) { /* already gone */ }
      const l = b.dataset.link; close(false);
      if (l) openLink(l, b.dataset.kind); else { const bell = $("#bell"); if (bell) bell.focus(); }
    });
    wire();
    if ($("#nmore")) $("#nmore").onclick = async () => {
      const last = document.querySelectorAll("#nl .it"); const id = last[last.length - 1].dataset.id;
      const m = await inbox(id); $("#nl").insertAdjacentHTML("beforeend", itemsHtml(m.items)); wire();
      if (m.items.length < 20) $("#nmore").remove();
    };
  }

  async function announceForm() {
    const p = $("#npanel"); let batches = []; try { batches = await api("/batches"); } catch (x) { /* batch choice is optional */ }
    p.innerHTML = `<h2 id="nTitle">${esc(t("Send announcement"))}</h2><form id="naf">` +
      `<label>${esc(t("Send to"))}<select id="nau"><option value="students">${esc(t("All students"))}</option><option value="teachers">${esc(t("All teachers"))}</option><option value="everyone">${esc(t("Everyone"))}</option><option value="batch">${esc(t("One batch (its students and teacher)"))}</option></select></label>` +
      `<label id="nbl" hidden>${esc(t("Batch"))}<select id="nab">${batches.map(b => `<option value="${b.id}">${esc((b.course_name ? b.course_name + " · " : "") + b.code)}</option>`).join("")}</select></label>` +
      `<label>${esc(t("Title"))}<input id="nat" maxlength="100" required></label><label>${esc(t("Message (optional)"))}<textarea id="nam" maxlength="500" rows="4"></textarea></label>` +
      `<div class="row"><button class="btn">${esc(t("Send"))}</button><button type="button" class="btn alt" id="nab2">${esc(t("Back"))}</button></div><div id="nmsg" role="status"></div></form>`;
    $("#nau").onchange = () => { $("#nbl").hidden = $("#nau").value !== "batch"; };
    $("#nab2").onclick = panel; focusIn();
    $("#naf").onsubmit = async e => {
      e.preventDefault();
      const aud = $("#nau").value, body = {audience: aud, title: $("#nat").value, message: $("#nam").value};
      if (aud === "batch") body.batch_id = +$("#nab").value;
      const who = $("#nau").selectedOptions[0].text + (aud === "batch" ? ": " + $("#nab").selectedOptions[0].text : "");
      // the panel's own trap is paused while the dialog is open, then put back (Session 4 + 15)
      if (release) { release(); release = null; }
      const ok = await ui.confirm(t("Send this to") + " " + who + "?", {okText: t("Send"), details: [body.title]});
      const pn = $("#npanel"); if (pn) release = ui.trap(pn, {onEscape: () => close()});
      if (!ok) return;
      try { const r = await api("/announcements", "POST", body); $("#nmsg").innerHTML = `<div class="msg ok">${esc(t("Sent to"))} ${r.sent} ${esc(t("people"))}</div>`; $("#nat").value = ""; $("#nam").value = ""; }
      catch (x) { $("#nmsg").innerHTML = `<div class="msg err">${esc(x.message)}</div>`; }
    };
  }

  async function remindersPanel() {
    const p = $("#npanel");
    const draw = async out => {
      let s; try { s = await api("/notifications/status"); } catch (x) { p.innerHTML = `<h2 id="nTitle">${esc(t("Reminders"))}</h2><div class="msg err" role="alert">${esc(x.message)}</div><button class="btn alt" id="nb">${esc(t("Back"))}</button>`; $("#nb").onclick = panel; focusIn(); return; }
      const line = (k, v) => `<tr><td>${esc(t(k))}</td><td>${v}</td></tr>`;
      p.innerHTML = `<h2 id="nTitle">${esc(t("Reminders"))}</h2>` +
        (s.enabled ? "" : `<div class="msg err">${esc(t("Notifications are turned off in Settings."))}</div>`) +
        (s.cron_secret_set ? "" : `<div class="msg err">${esc(t("CRON_SECRET is not set, so the daily run cannot start by itself. You can still run it by hand here."))}</div>`) +
        `<table>${line("Last run", s.last_run ? `<bdi dir="ltr">${esc(fmtTime(s.last_run))}</bdi>` : esc(t("never")))}${line("Fee due soon", s.fee_days_before ? s.fee_days_before + " " + esc(t("days before")) : esc(t("off")))}` +
        `${line("Overdue fee", s.overdue_every_days ? esc(t("every")) + " " + s.overdue_every_days + " " + esc(t("days")) : esc(t("off")))}${line("Assignment due", s.assignment_days_before ? s.assignment_days_before + " " + esc(t("days before")) : esc(t("off")))}</table>` +
        `<p class="hint">${esc(t("Change these under Settings, Notifications and reminders."))}</p>` +
        `<div class="row"><button class="btn alt" id="nprev">${esc(t("Preview (sends nothing)"))}</button><button class="btn" id="nrun">${esc(t("Run now"))}</button><button class="btn alt" id="nb">${esc(t("Back"))}</button></div><div id="nout" role="status">${out || ""}</div>`;
      $("#nb").onclick = panel; focusIn();
      const run = dry => async () => {
        try {
          const r = await api("/notifications/run?dry_run=" + (dry ? 1 : 0), "POST");
          const txt = r.skipped ? esc(r.skipped) : `${esc(t(dry ? "Would send" : "Sent"))}: ${r.fee_due_soon} ${esc(t("fee due soon"))}, ${r.fee_overdue} ${esc(t("overdue"))}, ${r.assignment_due} ${esc(t("assignment"))}, ${r.admin_digest} ${esc(t("for admins"))}.`;
          if (dry) $("#nout").innerHTML = `<div class="msg ok">${txt}</div>`; else draw(`<div class="msg ok">${txt}</div>`);
        } catch (x) { $("#nout").innerHTML = `<div class="msg err">${esc(x.message)}</div>`; }
      };
      $("#nprev").onclick = run(true); $("#nrun").onclick = run(false);
    };
    draw();
  }

  // Session 29: WhatsApp from the academy's own WhatsApp. The server prepares one link per person; the admin taps each and presses Send in WhatsApp.
  async function waForm(prev) {
    const p = $("#npanel"); let batches = [], students = [];
    try { batches = await api("/batches"); } catch (x) { /* optional */ }
    try { students = await api("/users?role=student"); } catch (x) { /* optional */ }
    p.innerHTML = `<h2 id="nTitle">${esc(t("WhatsApp"))}</h2><p class="hint">${esc(t("Opens WhatsApp with the message ready for each person. You press Send there."))}</p><form id="waf">` +
      `<label>${esc(t("Send to"))}<select id="wau"><option value="batch">${esc(t("One batch (its students and teacher)"))}</option><option value="student">${esc(t("One student"))}</option><option value="students">${esc(t("All students"))}</option><option value="teachers">${esc(t("All teachers"))}</option><option value="everyone">${esc(t("Everyone"))}</option></select></label>` +
      `<label id="wab">${esc(t("Batch"))}<select id="wabs">${batches.map(b => `<option value="${b.id}">${esc((b.course_name ? b.course_name + " · " : "") + b.code)}</option>`).join("")}</select></label>` +
      `<label id="was" hidden>${esc(t("Student"))}<select id="wass">${(Array.isArray(students) ? students : students.items || []).map(u => `<option value="${u.id}">${esc(u.full_name)}</option>`).join("")}</select></label>` +
      `<label><input type="checkbox" id="wag" style="width:auto"> ${esc(t("Also message the guardian"))}</label>` +
      `<label>${esc(t("Message"))}<textarea id="wam" maxlength="1000" rows="5" required>${esc((prev && prev.message) || "")}</textarea></label><p class="hint">{name} {student} {academy}</p>` +
      `<div class="row"><button class="btn">${esc(t("Prepare"))}</button><button type="button" class="btn alt" id="wab2">${esc(t("Back"))}</button></div><div id="wamsg" role="status"></div></form><div id="wal"></div>`;
    const sync = () => { const v = $("#wau").value; $("#wab").hidden = v !== "batch"; $("#was").hidden = v !== "student"; };
    $("#wau").onchange = sync; sync(); $("#wab2").onclick = panel; focusIn();
    $("#waf").onsubmit = async e => {
      e.preventDefault(); const v = $("#wau").value;
      const body = {audience: v, message: $("#wam").value, guardians: $("#wag").checked};
      if (v === "batch") body.batch_id = +$("#wabs").value; if (v === "student") body.student_id = +$("#wass").value;
      try {
        const r = await api("/whatsapp/prepare", "POST", body);
        $("#wamsg").innerHTML = `<div class="msg ok">${r.count} ${esc(t("chats ready"))}${r.missing.length ? ", " + r.missing.length + " " + esc(t("without a valid number")) + ": " + esc(r.missing.map(m => m.name).join(", ")) : ""}</div>`;
        $("#wal").innerHTML = r.items.map((i, n) => `<div class="row"><span style="flex:1">${esc(i.name)}${i.to === "guardian" ? " <small>(" + esc(t("guardian")) + ")</small>" : ""}<small class="bk">${esc(i.phone)}</small></span>` +
          `<button class="btn ${i.sent_today ? "alt" : ""}" data-n="${n}">${esc(t(i.sent_today ? "Sent today, open again" : "Open WhatsApp"))}</button></div>`).join("");
        document.querySelectorAll("#wal [data-n]").forEach(b => b.onclick = async () => {
          const i = r.items[+b.dataset.n];
          window.open(i.url, "_blank", "noopener");       // opened first, inside the tap, so a pop-up blocker lets it through
          try { await api("/whatsapp/sent", "POST", {user_id: i.user_id, to: i.to, preview: $("#wam").value}); b.textContent = t("Sent today, open again"); b.classList.add("alt"); } catch (x) { $("#wamsg").innerHTML = `<div class="msg err">${esc(x.message)}</div>`; }
        });
      } catch (x) { $("#wamsg").innerHTML = `<div class="msg err">${esc(x.message)}</div>`; }
    };
  }

  window.initBell = function () {
    const b = $("#bell"); if (!b) return;
    b.onclick = panel; refreshCount();
    clearInterval(timer);
    timer = setInterval(() => { if (!document.hidden && S.token) refreshCount(); }, 60000);
  };
})();
