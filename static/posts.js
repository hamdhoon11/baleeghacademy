/* v0.8.63: Notice board. Posts and announcements with pictures, files, a video link (YouTube, Google Drive, Vimeo) and comments.
   Everyone reads the posts meant for them. Admins post to anyone; teachers post to the batches they teach (area "write_posts").
   The author and admins see "Seen by": who has read the post and who has not. Showing a post on this screen marks it as read.
   Loaded after learning.js (tag, DO, apiForm, mvToday) and index.html (api, t, esc, $, mount, render, flash, showErr, busy, fetchFile, ui). */
const PO = {older: [], more: false, img: {}, open: {}, data: null};
const PO_ACCEPT = ".jpg,.jpeg,.png,.pdf,.docx,.pptx,.xlsx,.mp3,.m4a,.mp4";
const poTime = s => {
  if (!s) return "";
  const mv = new Date(Date.parse(s.replace(" ", "T") + "Z") + 5 * 3600e3).toISOString(), day = mv.slice(0, 10), hm = mv.slice(11, 16);
  return `<bdi dir="ltr">${day === mvToday() ? t("po_today") + " " + hm : day.slice(8, 10) + "/" + day.slice(5, 7) + "/" + day.slice(0, 4) + " " + hm}</bdi>`;
};
const poLinks = s => esc(s).replace(/https?:\/\/[^\s<]+/g, u => `<a href="${u}" target="_blank" rel="noopener noreferrer">${u}</a>`);
const poWho = p => p.audience === "batch" ? t("po_to_batch").replace("{b}", p.batch_label || "") : t("po_to_" + p.audience);

function poCard(p) {
  const imgs = p.files.filter(f => f.image), docs = p.files.filter(f => !f.image);
  const video = p.video_embed
    ? `<div class="po-video"><iframe src="${esc(p.video_embed)}" title="${esc(t("po_video"))}: ${esc(p.title)}" loading="lazy" allow="encrypted-media; picture-in-picture; fullscreen" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe></div>`
    : p.video_url ? `<p><a class="btn sm alt" href="${esc(p.video_url)}" target="_blank" rel="noopener noreferrer">${t("po_watch")}</a></p>` : "";
  const pics = imgs.length ? `<div class="po-imgs">${imgs.map(f => `<button type="button" class="po-img" data-do="poOpen" data-p="${p.id}" data-f="${f.id}" data-name="${esc(f.name)}" aria-label="${esc(t("open"))}: ${esc(f.name)}"><img data-src="/posts/${p.id}/files/${f.id}" alt="${esc(f.name)}"></button>`).join("")}</div>` : "";
  const files = docs.length ? `<p class="rowflex">${docs.map(f => `<button type="button" class="btn sm alt" data-do="poOpen" data-p="${p.id}" data-f="${f.id}" data-name="${esc(f.name)}">${t("open")}:&nbsp;<bdi>${esc(f.name)}</bdi></button>`).join("")}</p>` : "";
  const seen = p.can_manage ? `<button type="button" class="btn sm alt" data-do="poSeen" data-id="${p.id}">${esc(t("po_seen_n").replace("{n}", p.seen_n ?? 0).replace("{m}", p.audience_n ?? 0))}</button>` : "";
  const manage = p.can_manage ? [   // the rarer actions sit behind one "Manage" button so a phone shows two buttons, not seven
    `<button type="button" class="btn sm alt" data-do="poEdit" data-id="${p.id}">${t("edit")}</button>`,
    `<button type="button" class="btn sm alt" data-do="poPin" data-id="${p.id}" data-on="${p.pinned_at ? 0 : 1}">${t(p.pinned_at ? "po_unpin" : "po_pin")}</button>`,
    `<button type="button" class="btn sm alt" data-do="poAddFile" data-id="${p.id}">${t("po_add_file")}</button>`,
    `<button type="button" class="btn sm danger" data-do="poDel" data-id="${p.id}" data-title="${esc(p.title)}">${t("delete")}</button>`].join("") : "";
  const rmFiles = p.can_manage ? p.files.map(f => `<button type="button" class="btn sm alt" data-do="poRmFile" data-p="${p.id}" data-f="${f.id}" data-name="${esc(f.name)}">${t("Remove")}: <bdi>${esc(f.name)}</bdi></button>`).join("") : "";
  const cm = p.allow_comments || p.comments_n
    ? `<button type="button" class="btn sm alt" data-do="poComments" data-id="${p.id}" aria-expanded="${PO.open[p.id] ? "true" : "false"}" aria-controls="poc${p.id}">${esc(t("po_comments_n").replace("{n}", p.comments_n))}</button>` : "";
  return `<article class="panel po${p.pinned_at ? " po-pin" : ""}${PO.focus === p.id ? " po-hl" : ""}" id="post${p.id}" aria-labelledby="poh${p.id}">`
    + `<p class="hint m0">${p.pinned_at ? tag("📌 " + t("po_pinned"), "ok") + " " : ""}${p.read ? "" : tag(t("po_new"), "warn") + " "}<b>${esc(p.author || t("po_someone"))}</b>`
    + `${p.author_role === "admin" ? " " + tag(t("admin")) : p.author_role === "teacher" ? " " + tag(t("teacher")) : ""} · ${poTime(p.created_at)}${p.edited_at ? " · " + t("po_edited") : ""} · ${esc(poWho(p))}</p>`
    + `<h2 id="poh${p.id}" dir="auto">${esc(p.title)}</h2>${p.body ? `<div class="po-body" dir="auto">${poLinks(p.body)}</div>` : ""}${video}${pics}${files}`
    + `<div class="rowflex po-act">${cm}${seen}</div>${p.can_manage ? `<details class="po-manage"><summary>${t("po_manage")}</summary><div class="rowflex">${manage}${rmFiles}</div></details>` : ""}<div id="poc${p.id}" class="po-cm"${PO.open[p.id] ? "" : " hidden"}></div></article>`;
}

function poForm(j) {
  if (!j.can_post) return "";
  const admin = j.is_admin, bs = j.batches || [];
  const aud = (admin ? [["everyone", t("po_to_everyone")], ["students", t("po_to_students")], ["teachers", t("po_to_teachers")]] : []).concat(bs.length ? [["batch", t("po_one_batch")]] : []);
  if (!aud.length) return `<p class="hint">${esc(t("po_no_batches"))}</p>`;
  return `<details class="panel" id="po_new"${PO.formOpen ? " open" : ""}><summary><b>${t("po_new_post")}</b></summary><form id="po_f" class="po-form">`
    + `<label>${t("Title")} <span class="req" aria-hidden="true">*</span><input id="po_title" maxlength="150" required dir="auto"></label>`
    + `<label>${t("po_text")}<textarea id="po_body" rows="5" maxlength="5000" dir="auto"></textarea></label>`
    + `<label>${t("po_video_link")}<input id="po_video" type="url" inputmode="url" placeholder="https://youtu.be/..." aria-describedby="po_video_h"><span class="hint" id="po_video_h">${t("po_video_hint")}</span></label>`
    + `<label>${t("po_files")}<input id="po_files" type="file" multiple accept="${PO_ACCEPT}" aria-describedby="po_files_h"><span class="hint" id="po_files_h">${t("po_files_hint")}</span></label>`
    + `<label>${t("Send to")}<select id="po_aud">${aud.map(a => `<option value="${a[0]}">${esc(a[1])}</option>`).join("")}</select></label>`
    + `<label id="po_bl"${aud[0][0] === "batch" ? "" : " hidden"}>${t("Batch")}<select id="po_batch">${bs.map(b => `<option value="${b.id}">${esc(b.course_name + " · " + b.code)}</option>`).join("")}</select></label>`
    + `<label class="inl"><input id="po_cm" type="checkbox" checked> ${t("po_allow_comments")}</label>`
    + `<p class="hint">${t("po_notify_hint")}</p><button class="btn">${t("po_publish")}</button></form></details>`;
}

async function poUpload(pid, files) {
  const bad = [];
  for (const f of files) {
    try { const fd = new FormData(); fd.append("file", f); await apiForm(`/posts/${pid}/files`, fd); }
    catch (x) { bad.push(`${f.name}: ${x.message}`); }
  }
  return bad;
}

// pictures come through the API with the sign-in token, so they are fetched and shown from memory
async function poImages() {
  for (const im of document.querySelectorAll(".po img[data-src]")) {
    const src = im.dataset.src; im.removeAttribute("data-src");
    try {
      if (!PO.img[src]) {
        const r = await send(API + "/api" + src, {headers: {Authorization: "Bearer " + S.token}}, 60000);
        if (!r.ok) throw new Error();
        PO.img[src] = URL.createObjectURL(await r.blob());
      }
      im.src = PO.img[src];
    } catch (_) { im.alt = t("po_img_failed"); }
  }
}

async function poMarkRead(list) {
  const ids = list.filter(p => !p.read).map(p => p.id);
  if (!ids.length) return;
  try { await api("/posts/read", "POST", {ids}); list.forEach(p => { p.read = true; }); if (window.bellRefresh) window.bellRefresh(); } catch (_) { /* tried again next time */ }
}

views.posts = async () => {
  const j = await api("/posts"); PO.data = j; PO.older = []; PO.more = j.more;
  const focus = S.post ? +S.post : null; S.post = null; PO.focus = focus;
  const all = j.pinned.concat(j.items);
  mount(() => {
    const f = $("#po_f");
    if (f) {
      $("#po_aud").onchange = () => { $("#po_bl").hidden = $("#po_aud").value !== "batch"; };
      $("#po_new").addEventListener("toggle", e => { PO.formOpen = e.target.open; });
      f.onsubmit = async e => {
        e.preventDefault(); if (f.getAttribute("aria-busy") === "true") return;
        const b = f.querySelector("button.btn"), aud = $("#po_aud").value, files = [...$("#po_files").files];
        const body = {title: $("#po_title").value.trim(), body: $("#po_body").value, video_url: $("#po_video").value.trim(), audience: aud, allow_comments: $("#po_cm").checked};
        if (aud === "batch") body.batch_id = +$("#po_batch").value;
        if (files.length > 6) return showErr(f, t("po_max_files"));
        const who = $("#po_aud").selectedOptions[0].text + (aud === "batch" ? ": " + $("#po_batch").selectedOptions[0].text : "");
        if (!await ui.confirm(t("po_confirm").replace("{who}", who), {okText: t("po_publish"), details: [body.title]})) return;
        busy(b, true); f.setAttribute("aria-busy", "true");
        try {
          const r = await api("/posts", "POST", body);
          const bad = files.length ? await poUpload(r.id, files) : [];
          PO.formOpen = false;
          flash(bad.length ? t("po_posted_files_failed") + " " + bad.join("; ") : t("po_posted").replace("{n}", r.notified), !bad.length);
          render();
        } catch (x) { showErr(f, x.message); }
        finally { busy(b, false); f.removeAttribute("aria-busy"); }
      };
    }
    poImages();
    if (focus) { const el = $("#post" + focus); if (el) { el.scrollIntoView({block: "start"}); el.focus && el.setAttribute("tabindex", "-1"); el.focus({preventScroll: true}); } }
    setTimeout(() => poMarkRead(all), 1500);   // shown on the screen = read (the "New" tag stays until the next visit)
    Object.keys(PO.open).forEach(id => poLoadComments(+id));
  });
  const unread = j.unread ? ` ${tag(t("po_unread_n").replace("{n}", j.unread), "warn")}` : "";
  const pinned = j.pinned.length ? j.pinned.map(poCard).join("") : "";
  const list = j.items.map(poCard).join("");
  return `<h1>${t("posts")}${unread}</h1><p class="hint">${t(j.can_post ? "po_intro_staff" : "po_intro")}</p>${poForm(j)}${pinned}`
    + `<div id="po_list">${list || (pinned ? "" : `<div class="panel"><p class="hint">${t("po_empty")}</p></div>`)}</div>`
    + (j.more ? `<p><button type="button" class="btn alt" data-do="poMore">${t("Older")}</button></p>` : "");
};

const poFind = id => { const d = PO.data; return d ? d.pinned.concat(d.items, PO.older).find(p => p.id === +id) : null; };

DO.poMore = async (d, b) => {
  const all = PO.data.items.concat(PO.older), last = all[all.length - 1];
  const j = await api("/posts?before=" + last.id);
  PO.older = PO.older.concat(j.items);
  $("#po_list").insertAdjacentHTML("beforeend", j.items.map(poCard).join(""));
  if (!j.more) b.remove();
  poImages(); setTimeout(() => poMarkRead(j.items), 1500);
  return false;
};
DO.poOpen = async d => { await fetchFile(`/posts/${d.p}/files/${d.f}`, {preview: true, name: d.name}); return false; };
DO.poSeen = async d => {
  const j = await api(`/posts/${d.id}/seen`);
  const li = (x, on) => `<li><b>${esc(x.full_name)}</b> <span class="hint">${esc(t(x.role))}${x.login_id ? " · " + esc(x.login_id) : ""}${on ? " · " + poTime(x.read_at) : ""}</span></li>`;
  await ui.show(t("po_seen_title"), `<h3>✓ ${esc(t("po_seen"))} (${j.seen.length})</h3>${j.seen.length ? `<ul>${j.seen.map(x => li(x, true)).join("")}</ul>` : `<p class="hint">${t("po_nobody_yet")}</p>`}`
    + `<h3>${esc(t("po_not_seen"))} (${j.not_seen.length})</h3>${j.not_seen.length ? `<ul>${j.not_seen.map(x => li(x, false)).join("")}</ul>` : `<p class="hint">${t("po_everyone_seen")}</p>`}`);
  return false;
};
DO.poEdit = async d => {
  const p = poFind(d.id); if (!p) return;
  const v = await ui.form(t("po_edit_title"), [
    {id: "title", label: t("Title"), required: true, value: p.title, maxlength: 150},
    {id: "body", label: t("po_text"), type: "textarea", rows: 6, value: p.body || "", maxlength: 5000},
    {id: "video_url", label: t("po_video_link"), value: p.video_url || "", hint: t("po_video_hint")},
    {id: "allow_comments", label: t("po_allow_comments"), type: "checkbox", value: p.allow_comments}], {okText: t("save")});
  if (!v) return false;
  await api(`/posts/${d.id}`, "PATCH", v); flash(t("saved"), true);
};
DO.poPin = async d => { await api(`/posts/${d.id}/pin`, "POST", {pinned: d.on === "1"}); flash(t(d.on === "1" ? "po_pinned_done" : "po_unpinned_done"), true); };
DO.poDel = async d => {
  if (!await ui.confirm(t("po_delete_q"), {danger: true, details: [d.title || ""]})) return false;
  await api(`/posts/${d.id}`, "DELETE"); flash(t("po_deleted"), true);
};
DO.poAddFile = async d => {
  const v = await ui.form(t("po_add_file"), [{id: "file", label: t("po_files"), type: "file", accept: PO_ACCEPT, required: true, hint: t("po_files_hint")}], {okText: t("upload")});
  if (!v) return false;
  const bad = await poUpload(d.id, [v.file]);
  if (bad.length) throw new Error(bad.join("; "));
  flash(t("saved"), true);
};
DO.poRmFile = async d => {
  if (!await ui.confirm(t("po_remove_file_q"), {danger: true, details: [d.name || ""]})) return false;
  await api(`/posts/${d.p}/files/${d.f}`, "DELETE"); flash(t("saved"), true);
};

// ---------- comments (drawn inside the post; the rest of the page is not redrawn, so nothing typed is lost) ----------
async function poLoadComments(id) {
  const box = $("#poc" + id); if (!box) return;
  const p = poFind(id);
  let cs; try { cs = await api(`/posts/${id}/comments`); } catch (x) { box.innerHTML = `<div class="msg err" role="alert">${esc(x.message)}</div>`; return; }
  const list = cs.map(c => `<li id="pocm${c.id}"><b>${esc(c.author || t("po_someone"))}</b> <span class="hint">${poTime(c.created_at)}</span>`
    + `${c.can_delete ? ` <button type="button" class="linkbtn" data-do="poCmDel" data-p="${id}" data-id="${c.id}">${t("delete")}</button>` : ""}<div dir="auto" class="po-body">${poLinks(c.body || "")}</div></li>`).join("");
  const form = p && p.allow_comments ? `<form class="po-cf" data-p="${id}"><label class="sr-only" for="pocx${id}">${t("po_write_comment")}</label><textarea id="pocx${id}" rows="2" maxlength="1000" dir="auto" placeholder="${esc(t("po_write_comment"))}"></textarea><button class="btn sm">${t("Send")}</button></form>`
    : `<p class="hint">${t("po_comments_off")}</p>`;
  box.innerHTML = `<ul class="plain po-cl">${list || `<li class="hint">${t("po_no_comments")}</li>`}</ul>${form}`;
  const f = box.querySelector("form");
  if (f) f.onsubmit = async e => {
    e.preventDefault();
    const ta = f.querySelector("textarea"), b = f.querySelector("button");
    if (!ta.value.trim()) { ta.focus(); return; }
    busy(b, true);
    try { await api(`/posts/${id}/comments`, "POST", {body: ta.value}); if (p) p.comments_n++; await poLoadComments(id); poCountLabel(id); const nt = $("#pocx" + id); if (nt) nt.focus(); }
    catch (x) { showErr(f, x.message); }
    finally { busy(b, false); }
  };
}
function poCountLabel(id) {
  const p = poFind(id), b = document.querySelector(`[data-do="poComments"][data-id="${id}"]`);
  if (p && b) b.textContent = t("po_comments_n").replace("{n}", p.comments_n);
}
DO.poComments = async (d, b) => {
  const box = $("#poc" + d.id); if (!box) return false;
  const on = box.hidden; box.hidden = !on; b.setAttribute("aria-expanded", on ? "true" : "false");
  if (on) { PO.open[d.id] = true; await poLoadComments(+d.id); } else delete PO.open[d.id];
  return false;
};
DO.poCmDel = async d => {
  if (!await ui.confirm(t("po_delete_comment_q"), {danger: true})) return false;
  await api(`/posts/${d.p}/comments/${d.id}`, "DELETE");
  const p = poFind(d.p); if (p) p.comments_n = Math.max(0, p.comments_n - 1);
  await poLoadComments(+d.p); poCountLabel(+d.p);
  return false;
};

(function () {
  const css = document.createElement("style");
  css.textContent = ".po h2{margin:.3rem 0}.po-body{white-space:pre-wrap;overflow-wrap:anywhere}.po-pin{border-inline-start:4px solid var(--teal,#1b7f79)}"
    + ".po-hl{outline:3px solid var(--coral,#e36b4f);outline-offset:2px}.po-video{position:relative;aspect-ratio:16/9;max-width:40rem;margin:.6rem 0;background:#000;border-radius:8px;overflow:hidden}"
    + ".po-video iframe{position:absolute;inset:0;width:100%;height:100%;border:0}.po-imgs{display:grid;grid-template-columns:repeat(auto-fill,minmax(9rem,1fr));gap:.4rem;margin:.6rem 0}"
    + ".po-img{padding:0;border:1px solid var(--line,#ddd);border-radius:8px;overflow:hidden;background:var(--mist,#f3f6f6);cursor:zoom-in;min-height:6rem}"
    + ".po-img img{display:block;width:100%;height:100%;max-height:16rem;object-fit:cover}.po-imgs:has(.po-img:only-child){grid-template-columns:1fr}"
    + ".po-imgs{max-width:40rem}.po-imgs .po-img:only-child img{max-height:22rem;object-fit:contain}.po-manage{margin-top:.4rem}.po-manage summary{cursor:pointer;color:var(--teal,#1b7f79);font-weight:600}.po-manage .rowflex{margin-top:.4rem}.po-act{margin-top:.5rem}.po-cm{margin-top:.6rem;border-top:1px solid var(--line,#ddd);padding-top:.5rem}"
    + ".po-cl li{padding:.35rem 0;border-bottom:1px solid var(--line,#eee)}.po-cf{display:flex;gap:.4rem;align-items:flex-end;margin-top:.4rem}.po-cf textarea{flex:1}"
    + ".po-form label{display:block;margin:.5rem 0}.po-form input:not([type=checkbox]),.po-form textarea,.po-form select{width:100%;box-sizing:border-box}";
  document.head.appendChild(css);
})();
