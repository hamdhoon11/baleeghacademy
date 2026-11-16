/* v0.8.58: Teachers' room (staff only). Three parts:
     Chat          one group chat for teachers and admins: reply, attach a file, edit or delete your own; head teachers and admins pin and remove.
     Teachers' guide   shared files and links to teach from, in folders. Head teachers and admins make folders; a locked folder takes their files only.
     Head teachers (admins only)   tick the teachers who moderate the room.
   The chat checks for new messages every 8 seconds while it is on screen and redraws only the message list, so a half-typed message is never lost.
   Loaded after learning.js (uses tag, mvToday, viewFile, apiForm, DO) and index.html (api, t, esc, $, render, tabs, flash, ui). */
const SR = {tab: "chat", sig: null, reply: null, folder: "", q: "", older: null, timer: null, data: null};
const SR_ACCEPT = ".pdf,.jpg,.jpeg,.png,.docx,.pptx,.xlsx,.mp3,.m4a,.mp4";

// times come from the server in UTC ('YYYY-MM-DD HH:MM:SS'); people read Maldives time
const srTime = s => {
  if (!s) return "";
  const mv = new Date(Date.parse(s.replace(" ", "T") + "Z") + 5 * 3600e3).toISOString(), day = mv.slice(0, 10), hm = mv.slice(11, 16);
  return `<bdi dir="ltr">${day === mvToday() ? hm : day.slice(8, 10) + "/" + day.slice(5, 7) + " " + hm}</bdi>`;
};
const srLinks = s => esc(s).replace(/https?:\/\/[^\s<]+/g, u => `<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`);
const srWho = m => `<b>${esc(m.author)}</b>${m.author_role === "admin" ? " " + tag(t("sr_admin")) : m.author_head ? " " + tag(t("sr_head"), "ok") : ""}`;

function srMsg(m, mod) {
  if (m.deleted_at) return `<li class="srm sr-del" id="srm${m.id}"><span class="hint">${t("sr_removed")} · ${srTime(m.created_at)}</span></li>`;
  const quote = m.reply_to ? `<div class="srq">${m.reply_body == null ? `<span class="hint">${t("sr_removed")}</span>` : `<b>${esc(m.reply_author || "")}</b> ${esc(m.reply_body)}`}</div>` : "";
  const file = m.has_file ? `<p class="m0"><button type="button" class="btn sm" data-do="srMsgFile" data-id="${m.id}" data-name="${esc(m.file_name)}">${t("open")}:&nbsp;<bdi>${esc(m.file_name)}</bdi></button></p>` : "";
  const act = [`<button type="button" data-do="srReply" data-id="${m.id}">${t("sr_reply")}</button>`,
    m.can_edit ? `<button type="button" data-do="srEdit" data-id="${m.id}">${t("edit")}</button>` : "",
    mod ? `<button type="button" data-do="srPin" data-id="${m.id}" data-on="${m.pinned_at ? 0 : 1}">${t(m.pinned_at ? "sr_unpin" : "sr_pin")}</button>` : "",
    m.can_delete ? `<button type="button" class="dg" data-do="srDel" data-id="${m.id}" data-own="${m.mine ? 1 : 0}">${t("delete")}</button>` : ""].join("");
  return `<li class="srm${m.mine ? " sr-me" : ""}${m.pinned_at ? " sr-pin" : ""}" id="srm${m.id}"><div class="srh">${srWho(m)} <span class="hint">${srTime(m.created_at)}${m.edited_at ? " · " + t("sr_edited") : ""}${m.pinned_at ? " · " + t("sr_pinned") : ""}</span></div>`
    + `${quote}${m.body ? `<div class="srb" dir="auto">${srLinks(m.body)}</div>` : ""}${file}<div class="sra">${act}</div></li>`;
}
const srPins = (j) => j.pinned.length ? `<div class="panel srpins"><h2>${t("sr_pinned_h")}</h2><ul class="plain">${j.pinned.map(p => `<li><a href="#srm${p.id}" data-do="srJump" data-id="${p.id}">${srWho(p)}</a> <span class="hint">${srTime(p.pinned_at)}</span><div dir="auto">${srLinks((p.body || p.file_name || "").slice(0, 400))}</div></li>`).join("")}</ul></div>` : "";
const srList = j => (SR.older || []).concat(j.messages).map(m => srMsg(m, j.can_moderate)).join("") || `<li class="hint">${t("sr_empty")}</li>`;
const srNearBottom = el => !el || el.scrollHeight - el.scrollTop - el.clientHeight < 80;

// redraw only the parts that change; keep the reader where they were unless they were at the bottom
function srPaint(j, toBottom) {
  SR.data = j; SR.sig = j.signature;
  const box = $("#sr_list"); if (!box) return;
  const stay = toBottom || srNearBottom(box), y = box.scrollTop;
  box.innerHTML = srList(j);
  const p = $("#sr_pins"); if (p) p.innerHTML = srPins(j);
  const more = $("#sr_more"); if (more) more.hidden = !(SR.older ? SR.olderMore : j.more);
  if (stay) box.scrollTop = box.scrollHeight; else box.scrollTop = y;
}
async function srPoll(force) {
  if (S.view !== "staff_room" || SR.tab !== "chat" || !S.token || (!force && document.visibilityState === "hidden")) return;
  try { const j = await api("/staff/messages"); if (force || j.signature !== SR.sig) srPaint(j, force); } catch (_) { /* a missed check is fine; the next one tries again */ }
}
function srStartPoll() { if (!SR.timer) SR.timer = setInterval(() => srPoll(false), 8000); }
document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") srPoll(false); });

const srReplyBar = () => { const m = SR.reply && (SR.data ? (SR.older || []).concat(SR.data.messages) : []).find(x => x.id === SR.reply);
  return m ? `<div class="srq rowflex"><span>${t("sr_replying")} <b>${esc(m.author)}</b>: ${esc((m.body || m.file_name || "").slice(0, 100))}</span><button type="button" class="btn sm alt" data-do="srNoReply">${t("cancel")}</button></div>` : ""; };

async function srChat() {
  const j = await api("/staff/messages"); SR.data = j; SR.sig = j.signature;
  srStartPoll();
  mount(() => {
    const box = $("#sr_list"); if (box) box.scrollTop = box.scrollHeight;
    const f = $("#sr_f"), ta = $("#sr_text");
    if (ta) ta.addEventListener("keydown", e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); f.requestSubmit(); } });
    if (f) f.onsubmit = async e => {
      e.preventDefault(); if (f.getAttribute("aria-busy") === "true") return;
      const b = f.querySelector("button[type=submit]"), file = $("#sr_file").files[0];
      busy(b, true); f.setAttribute("aria-busy", "true");
      try {
        if (file) { const fd = new FormData(); fd.append("body", ta.value); fd.append("file", file); if (SR.reply) fd.append("reply_to", SR.reply); await apiForm("/staff/messages", fd); }
        else await api("/staff/messages", "POST", {body: ta.value, reply_to: SR.reply || undefined});
        ta.value = ""; $("#sr_file").value = ""; SR.reply = null; $("#sr_rbar").innerHTML = "";
        await srPoll(true); ta.focus();
      } catch (x) { showErr(f, x.message); }
      finally { busy(b, false); f.removeAttribute("aria-busy"); }
    };
  });
  return `<div id="sr_pins">${srPins(j)}</div>
    <div class="panel srchat"><p class="m0"><button type="button" class="btn sm alt" id="sr_more" data-do="srOlder"${j.more ? "" : " hidden"}>${t("sr_older")}</button></p>
    <ul class="srl" id="sr_list" aria-live="polite" aria-relevant="additions" aria-label="${esc(t("sr_chat"))}">${srList(j)}</ul>
    <form id="sr_f" class="srf"><div id="sr_rbar">${srReplyBar()}</div>
    <label for="sr_text" class="sr-only">${t("sr_message")}</label><textarea id="sr_text" rows="2" maxlength="4000" dir="auto" placeholder="${esc(t("sr_placeholder"))}"></textarea>
    <div class="rowflex"><label class="inl">${t("sr_attach")} <input id="sr_file" type="file" accept="${SR_ACCEPT}"></label><button type="submit" class="btn">${t("sr_send")}</button></div>
    <p class="hint m0">${t("sr_chat_hint")}</p></form></div>`;
}
DO.srReply = d => { SR.reply = +d.id; const r = $("#sr_rbar"); if (r) r.innerHTML = srReplyBar(); const ta = $("#sr_text"); if (ta) ta.focus(); return false; };
DO.srNoReply = () => { SR.reply = null; const r = $("#sr_rbar"); if (r) r.innerHTML = ""; return false; };
DO.srMsgFile = async d => { await viewFile(`/staff/messages/${d.id}/file`, d.name); return false; };
DO.srJump = d => { const el = document.getElementById("srm" + d.id); if (el) { el.scrollIntoView({block: "center"}); el.classList.add("sr-hl"); setTimeout(() => el.classList.remove("sr-hl"), 1600); } return false; };
DO.srOlder = async () => {
  const all = (SR.older || []).concat(SR.data.messages), first = all[0];
  if (!first) return false;
  const j = await api(`/staff/messages?before=${first.id}`), box = $("#sr_list"), h = box.scrollHeight;
  SR.older = j.messages.concat(SR.older || []); SR.olderMore = j.more;
  box.innerHTML = srList(SR.data); box.scrollTop = box.scrollHeight - h;
  $("#sr_more").hidden = !j.more; return false;
};
DO.srEdit = async d => {
  const m = (SR.older || []).concat(SR.data.messages).find(x => x.id === +d.id); if (!m) return false;
  const v = await ui.ask(t("sr_edit_title"), {label: t("sr_message"), multiline: true, value: m.body || "", required: !m.has_file});
  if (v == null) return false;
  await api(`/staff/messages/${d.id}`, "PATCH", {body: v}); await srPoll(false); return false;
};
DO.srDel = async d => {
  if (!await ui.confirm(t(d.own === "1" ? "sr_del_own_q" : "sr_del_other_q"), {danger: true, okText: t("delete")})) return false;
  await api(`/staff/messages/${d.id}`, "DELETE"); SR.older = SR.older && SR.older.map(m => m.id === +d.id ? {...m, deleted_at: "x", body: null, has_file: false} : m);
  await srPoll(false); return false;
};
DO.srPin = async d => { await api(`/staff/messages/${d.id}/pin`, "POST", {pinned: d.on === "1"}); flash(t(d.on === "1" ? "sr_pinned_ok" : "saved"), true); await srPoll(false); return false; };

// ---------- teachers' guide ----------
async function srGuide() {
  const fq = SR.folder ? `folder_id=${encodeURIComponent(SR.folder)}` : "", qq = SR.q ? `q=${encodeURIComponent(SR.q)}` : "";
  const [fs, files] = await Promise.all([api("/staff/folders"), api("/staff/files" + (fq || qq ? "?" + [fq, qq].filter(Boolean).join("&") : ""))]);
  const mod = fs.can_moderate, cur = fs.folders.find(f => String(f.id) === String(SR.folder));
  mount(() => {
    const sf = $("#srg_f"); if (sf) sf.onsubmit = e => { e.preventDefault(); SR.q = val("srg_q"); render(); };
    const fsel = $("#srg_folder"); if (fsel) { fsel.value = SR.folder; fsel.onchange = () => { SR.folder = fsel.value; render(); }; }
  });
  const folderOpts = [["", t("sr_all_files")], ...fs.folders.map(f => [String(f.id), f.name + (f.locked ? " 🔒" : "") + ` (${f.files})`]), ...(fs.unfiled ? [["none", t("sr_unfiled") + ` (${fs.unfiled})`]] : [])];
  const folders = `<div class="panel"><div class="rowflex row">${field("srg_folder", "sr_folder", "", folderOpts)}
    <form id="srg_f" class="rowflex"><label>${t("search")}<input id="srg_q" value="${esc(SR.q)}"></label><button class="btn alt">${t("search")}</button></form></div>
    ${cur ? `<p class="hint">${cur.locked ? tag(t("sr_locked"), "warn") + " " + t("sr_locked_hint") : ""}${cur.description ? " " + esc(cur.description) : ""}</p>` : ""}
    <div class="rowflex"><button type="button" class="btn" data-do="srAddFile">${t("sr_add_file")}</button>${mod ? `<button type="button" class="btn alt" data-do="srNewFolder">${t("sr_new_folder")}</button>` : ""}
    ${mod && cur ? `<button type="button" class="btn alt" data-do="srEditFolder" data-id="${cur.id}">${t("sr_edit_folder")}</button><button type="button" class="btn danger" data-do="srDelFolder" data-id="${cur.id}" data-name="${esc(cur.name)}">${t("sr_del_folder")}</button>` : ""}</div></div>`;
  const row = x => `<div class="cl"><div><b>${esc(x.title)}</b> ${tag(t(x.kind === "link" ? "link" : "file"))}${!SR.folder && x.folder_name ? " " + tag(x.folder_name) : ""}${x.description ? `<br><span dir="auto">${esc(x.description)}</span>` : ""}
    <br><span class="hint">${esc(x.uploader || "")} · ${srTime(x.created_at)}${x.file_name ? ` · <bdi>${esc(x.file_name)}</bdi>` : ""}</span></div>
    <div class="rowflex">${x.kind === "link" ? `<a class="btn sm" href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener noreferrer">${t("open")}</a>` : `<button type="button" class="btn sm" data-do="srOpenFile" data-id="${x.id}" data-name="${esc(x.file_name || "file")}">${t("open")}</button>`}
    ${x.can_edit ? `<button type="button" class="btn sm alt" data-do="srEditFile" data-id="${x.id}">${t("edit")}</button><button type="button" class="btn sm danger" data-do="srDelFile" data-id="${x.id}" data-name="${esc(x.title)}">${t("delete")}</button>` : ""}</div></div>`;
  SR.files = files; SR.folders = fs.folders;
  return `${folders}<div class="panel"><p class="hint">${t("sr_guide_hint")}</p>${files.map(row).join("") || `<p>${t("empty")}</p>`}</div>`;
}
const srFolderChoices = (forAdd) => [["", t("sr_no_folder")], ...(SR.folders || []).filter(f => !forAdd || f.can_add).map(f => [String(f.id), f.name + (f.locked ? " 🔒" : "")])];
DO.srOpenFile = async d => { await viewFile(`/staff/files/${d.id}/file`, d.name); return false; };
DO.srAddFile = async () => {
  const cur = (SR.folders || []).find(f => String(f.id) === String(SR.folder) && f.can_add);
  const v = await ui.form(t("sr_add_file"), [
    {id: "title", label: t("title"), required: true, maxlength: 160}, {id: "description", label: t("description"), type: "textarea", rows: 3},
    {id: "folder_id", label: t("sr_folder"), type: "select", options: srFolderChoices(true), value: cur ? String(cur.id) : ""},
    {id: "file", label: t("file"), type: "file", accept: SR_ACCEPT}, {id: "url", label: t("sr_or_link"), type: "url", placeholder: "https://"}],
    {okText: t("save"), validate: x => (!!x.file === !!x.url) ? t("sr_file_or_link") : null});
  if (!v) return false;
  const fd = new FormData(); ["title", "description", "folder_id", "url"].forEach(k => fd.append(k, v[k] || "")); if (v.file) fd.append("file", v.file);
  await apiForm("/staff/files", fd); flash(t("saved"), true);
};
DO.srEditFile = async d => {
  const x = (SR.files || []).find(f => f.id === +d.id); if (!x) return false;
  const v = await ui.form(t("edit"), [{id: "title", label: t("title"), required: true, value: x.title, maxlength: 160}, {id: "description", label: t("description"), type: "textarea", rows: 3, value: x.description || ""},
    {id: "folder_id", label: t("sr_folder"), type: "select", options: srFolderChoices(false), value: x.folder_id ? String(x.folder_id) : ""}], {okText: t("save")});
  if (!v) return false;
  await api(`/staff/files/${d.id}`, "PATCH", {title: v.title, description: v.description, folder_id: v.folder_id || null}); flash(t("saved"), true);
};
DO.srDelFile = async d => { if (!await ui.confirm(t("sr_del_file_q"), {danger: true, okText: t("delete"), details: [d.name || ""]})) return false; await api(`/staff/files/${d.id}`, "DELETE"); };
const srFolderForm = (f = {}) => ui.form(f.id ? t("sr_edit_folder") : t("sr_new_folder"), [{id: "name", label: t("name"), required: true, maxlength: 80, value: f.name || ""},
  {id: "description", label: t("description"), type: "textarea", rows: 2, value: f.description || ""}, {id: "locked", label: t("sr_lock_label"), type: "checkbox", value: !!f.locked}], {okText: t("save")});
DO.srNewFolder = async () => { const v = await srFolderForm(); if (!v) return false; const r = await api("/staff/folders", "POST", v); SR.folder = String(r.id); flash(t("saved"), true); };
DO.srEditFolder = async d => { const f = (SR.folders || []).find(x => x.id === +d.id); const v = await srFolderForm(f); if (!v) return false; await api(`/staff/folders/${d.id}`, "PATCH", v); flash(t("saved"), true); };
DO.srDelFolder = async d => { if (!await ui.confirm(t("sr_del_folder_q"), {danger: true, okText: t("delete"), details: [d.name || ""]})) return false; await api(`/staff/folders/${d.id}`, "DELETE"); SR.folder = ""; };

// ---------- head teachers (admins) ----------
async function srHeads(room) {
  const rows = room.teachers.map(x => `<div class="cl"><div><b>${esc(x.full_name)}</b> ${x.is_head ? tag(t("sr_head"), "ok") : ""}</div>
    <button type="button" class="btn sm${x.is_head ? " alt" : ""}" data-do="srHead" data-id="${x.id}" data-on="${x.is_head ? 0 : 1}" data-name="${esc(x.full_name)}">${t(x.is_head ? "sr_unmake_head" : "sr_make_head")}</button></div>`).join("");
  return `<div class="panel"><h2>${t("sr_heads")}</h2><p class="hint">${t("sr_heads_hint")}</p>${rows || `<p>${t("empty")}</p>`}</div>`;
}
DO.srHead = async d => {
  if (d.on === "1" && !await ui.confirm(t("sr_make_head_q"), {okText: t("sr_make_head"), details: [d.name || "", t("sr_heads_hint")]})) return false;
  await api("/staff/head", "POST", {user_id: +d.id, is_head: d.on === "1"}); flash(t("saved"), true);
};

views.staff_room = async () => {
  const room = await api("/staff/room"), adm = room.me.is_admin;
  const items = [["chat", t("sr_chat")], ["guide", t("sr_guide")], ...(adm ? [["heads", t("sr_heads")]] : [])];
  if (!items.some(i => i[0] === SR.tab)) SR.tab = "chat";
  if (SR.tab !== "chat") SR.older = null;
  const heads = room.members.filter(m => m.is_head).map(m => esc(m.full_name)).join(", ");
  const top = `<h1>${t("staff_room")}</h1><p class="hint">${t("sr_intro")} ${heads ? t("sr_head_is").replace("{n}", heads) : adm ? t("sr_no_head") : ""}${room.me.is_head ? " " + tag(t("sr_you_head"), "ok") : ""}</p>`
    + tabs({id: "sr", items, current: SR.tab, label: t("staff_room"), onSelect: k => { SR.tab = k; SR.older = null; }});
  const body = SR.tab === "guide" ? await srGuide() : SR.tab === "heads" ? await srHeads(room) : await srChat();
  return top + body;
};
