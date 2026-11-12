/* Phase 3 screens: home + Join class, attendance, assignments, progress, materials, classroom (teacher/admin), batches editor.
   Loaded after the main script and ui.js in index.html and reuses their helpers: API, S, t, esc, $, val, api, field, form, flash, render, signout, onSubmit, mount, go, ui. */
const mvToday = () => new Date(Date.now() + 5 * 3600e3).toISOString().slice(0, 10);  // Maldives date (UTC+5)
const pct = v => v == null ? "–" : v + "%";
const tag = (txt, cls = "") => `<span class="tag ${cls}">${esc(txt)}</span>`;
const safeUrl = u => /^https?:\/\//i.test(u || "") ? u : "#";
const DAYS7 = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const dayName = d => t("day_" + d);

async function apiForm(path, fd, method = "POST") {   // uploads get 2 minutes instead of 20 s
  const r = await send(API + "/api" + path, {method, headers: {Authorization: "Bearer " + S.token}, body: fd}, 120000);
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) { signout(); throw new Error(j.error); }
  if (r.status === 413 && !j.error) throw new Error(t("file_too_large_server"));
  if (!r.ok) throw new Error(j.error || "Something went wrong");
  return j;
}
const download = (path, name) => fetchFile(path, {name});                        // always save
const viewFile = (path, name) => fetchFile(path, {name, preview: true});         // preview PDF/images, save other types

// one delegated handler for buttons (data-do) and selects/inputs (data-ch) so re-rendering never loses them
// Session 1: the button is disabled (aria-busy) while its request runs; on an error the screen is NOT redrawn and the message appears next to the button.
// A handler returns false when it has drawn what it needs itself (or navigated with go()).
const DO = {}, CH = {}, CT = {};
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-do]");
  if (!b || !DO[b.dataset.do]) return;
  e.preventDefault();
  if (b.getAttribute("aria-busy") === "true") return;
  busy(b, true);
  let again = true;
  try { again = (await DO[b.dataset.do](b.dataset, b)) !== false; }
  catch (x) { busy(b, false); if (b.isConnected) showErr(b, x.message); else { flash(x.message); render(); } return; }
  busy(b, false);
  if (again) { staleBadges(); S.refocus = {do: b.dataset.do, id: b.dataset.id}; render(); }
  else if (b.isConnected && (document.activeElement === document.body || !document.activeElement)) b.focus();
});
document.addEventListener("change", e => { const f = CH[e.target.dataset.ch]; if (f) f(e.target); });

// ---------- shared pieces ----------
// dates and times stay left-to-right even inside Dhivehi (right-to-left) text, otherwise 15:56–16:56 reads backwards
const whenHtml = o => `${esc(o.date === mvToday() ? t("today") : dayName(o.weekday))} <bdi dir="ltr">${esc(o.date)} · ${esc(o.start_time)}–${esc(o.end_time)}</bdi>`;
const classRow = o => `<div class="cl ${o.status === "cancelled" ? "off" : ""}"><div><b>${whenHtml(o)}</b> ${o.status === "cancelled" ? tag(t("class_cancelled"), "bad") : ""}${o.extra ? tag(t("extra")) : ""}${o.live ? tag(t("live_now"), "ok") : ""}<br>${esc(o.course_name)} · ${esc(o.batch_code)}${o.topic ? " · " + esc(o.topic) : ""}</div>${o.can_join ? `<a class="btn alt sm" href="${esc(safeUrl(o.meet_link))}" target="_blank" rel="noopener">${t("join")}</a>` : ""}</div>`;

function nextCard(h) {
  const n = h.next_class;
  const warn = h.batches_without_schedule.length ? `<p class="hint">${esc(t("no_schedule_warn"))} ${esc(h.batches_without_schedule.map(b => b.course_name + " " + b.code).join(", "))}. ${esc(t("set_days_hint"))}</p>` : "";
  if (!n) return `<h2>${t("next_class")}</h2><p>${t("no_next_class")}</p>${warn}`;
  const join = n.can_join ? `<a class="btn alt big" href="${esc(safeUrl(n.meet_link))}" target="_blank" rel="noopener">${t("join")}</a>` : n.meet_link ? `<p class="hint">${t("join_early_note")}</p>` : `<p class="hint">${t("no_meet_link")}</p>`;
  return `<h2>${t("next_class")}</h2><p class="bigtime">${whenHtml(n)} ${n.live ? tag(t("live_now"), "ok") : ""}</p><p>${esc(n.course_name)} · ${esc(n.batch_code)}${n.teacher_name ? " · " + esc(n.teacher_name) : ""}${n.topic ? "<br>" + esc(n.topic) : ""}</p>${join}${warn}`;
}
function weekList(h) {
  if (!h.week.length) return `<p>${t("empty")}</p>`;
  return h.week.map(classRow).join("");
}
const statusTag = a => {
  if (a.my.grade != null) return tag(t("graded"), "ok");
  if (a.my.submitted) return tag(t("submitted") + (a.my.is_late ? " · " + t("late_tag") : ""));
  if (a.kind === "test") return tag(t("test"));
  return tag(t("to_do"), "warn");
};

// ---------- home (student and teacher) ----------
views.home = async () => {
  const h = await api("/my/home");
  let html = `<h1>${t("home")}</h1><div class="panel next">${nextCard(h)}</div>`;
  if (S.user.role === "student") {
    html += `<div class="stats">${h.courses.map(c => `<div class="stat"><b>${pct(c.attendance_pct)}</b>${esc(c.course_name)} · ${t("attendance_pct")}<br><small>${t("avg_pct")}: ${pct(c.avg_pct)}</small></div>`).join("")}</div>`;
    html = html.replace(`<h1>${t("home")}</h1>`, `<h1>${t("home")}</h1>` + nextSteps(h));   // v0.8.35: "What to do next" first
  } else {
    html = html.replace(`<h1>${t("home")}</h1>`, `<h1>${t("home")}</h1>` + teacherToday(h));   // v0.8.35: today's classes with Take attendance
    const d = await api("/teacher/dashboard").catch(() => null);   // Session 19: the batch picked in the header (or all batches); same numbers as everywhere else
    if (d) {
      const card = (n, k) => `<div class="stat"><b>${n}</b>${t(k)}</div>`, A = d.assignments, C = d.classes;
      html += `<div class="stats">${card(d.batches.length, "dash_batches")}${card(d.students, "dash_students")}${card(C.held, "dash_held")}${card(C.upcoming, "dash_upcoming")}${card(A.given, "dash_assignments")}${card(A.tests, "dash_tests")}${card(d.tutorials.given, "dash_tutorials")}${card(A.submissions, "dash_submissions")}${card(A.pending_grading, "pending_grading")}${card(A.graded, "dash_graded")}${card(pct(d.attendance.pct), "attendance_pct")}${card(d.attendance.low_students, "low_att_students")}</div>`;
      html += `<div class="panel"><h2>${t("dash_batches")}</h2>${d.batches.map(b => `<div class="cl"><div><b>${esc(b.course_name)}</b> · ${esc(b.code)}<br><span class="hint">${esc(b.days || "")} ${esc(b.start_time || "")} · ${b.students} ${t("dash_students")}</span></div></div>`).join("") || `<p>${t("empty")}</p>`}</div>`;
      if (d.recent_activity.length) html += `<div class="panel"><h2>${t("dash_recent")}</h2>${d.recent_activity.map(r => `<div class="cl"><div>${esc(r.action.replace(/_/g, " "))}${r.detail ? " · " + esc(r.detail) : ""}<br><span class="hint"><bdi dir="ltr">${esc(fmtTime(r.at))}</bdi></span></div></div>`).join("")}</div>`;
    } else html += `<div class="stats"><div class="stat"><b>${h.to_grade}</b>${t("pending_grading")}</div><div class="stat"><b>${h.low_attendance.length}</b>${t("low_att_students")}</div></div>`;
    if (h.low_attendance.length) html += `<div class="panel"><h2>${t("low_att_students")}</h2>${h.low_attendance.map(s => `<div class="cl"><div><b>${esc(s.full_name)}</b><br>${esc(s.course_name)} · ${esc(s.batch_code)}</div>${tag(pct(s.pct), "bad")}</div>`).join("")}</div>`;
  }
  return html + `<div class="panel"><h2>${t("this_week")}</h2>${weekList(h)}</div>`;
};
DO.goA = d => { go({view: "assignments", aid: +d.id}); return false; };
// v0.8.35: the student's "What to do next": work to hand in (late first), new grades, new materials. The fee notice (fees.js) stays above it.
function nextSteps(h) {
  const items = [];
  (h.todo || []).forEach(a => items.push(`<div class="cl"><div><b>${esc(a.title)}</b> ${a.overdue ? tag(t("Late"), "bad") : ""}<br><span class="hint">${esc(a.course_name)} · ${a.due_date ? esc(t("due_date")) + " <bdi dir=\"ltr\">" + esc(a.due_date) + "</bdi>" : esc(t("no_due"))}</span></div><button class="btn sm" data-do="goA" data-id="${a.id}">${t("Hand in")}</button></div>`));
  if ((h.todo_count || 0) > (h.todo || []).length) items.push(`<p class="hint">${esc(t("and_n_more").replace("{n}", h.todo_count - h.todo.length))} <button class="linkbtn" data-do="goTab" data-v="assignments">${t("assignments")}</button></p>`);
  (h.new_grades || []).forEach(g => items.push(`<div class="cl"><div><b>${esc(g.title)}</b> ${tag(t("New grade"), "ok")}<br><span class="hint">${esc(g.course_name)} · ${esc(g.grade)} / ${esc(g.max_points)}</span></div><button class="btn sm alt" data-do="goA" data-id="${g.id}">${t("open")}</button></div>`));
  (h.new_materials || []).forEach(m => items.push(`<div class="cl"><div><b>${esc(m.title)}</b> ${tag(t("New material"))}<br><span class="hint">${esc(m.course_name)} · <bdi dir="ltr">${esc(fmtDate(m.created_at))}</bdi></span></div><button class="btn sm alt" data-do="goTab" data-v="materials">${t("open")}</button></div>`));
  return `<div class="panel" id="nextp"><h2>${t("What to do next")}</h2>${items.join("") || `<p class="msg ok">${esc(t("nothing_to_do"))}</p>`}</div>`;
}
// v0.8.35: the teacher's classes today, each with Take attendance (or Attendance taken), and the grading queue
function teacherToday(h) {
  const rows = (h.today || []).filter(o => o.status !== "cancelled").map(o => `<div class="cl"><div><b>${esc(o.course_name)} · ${esc(o.batch_code)}</b><br><span class="hint"><bdi dir="ltr">${esc(o.start_time)}–${esc(o.end_time)}</bdi></span></div>`
    + (o.attendance_taken ? `<div class="rowflex">${tag("✓ " + t("Attendance taken"), "ok")}<button class="btn sm alt" data-do="takeAtt" data-b="${o.batch_id}">${t("edit")}</button></div>`
      : `<button class="btn sm${o.started ? "" : " alt"}" data-do="takeAtt" data-b="${o.batch_id}">${t("Take attendance")}</button>`) + `</div>`).join("");
  const grade = h.to_grade ? `<div class="cl"><div><b>${h.to_grade}</b> ${esc(t("pending_grading"))}</div><button class="btn sm" data-do="goGrade">${t("open")}</button></div>` : "";
  return `<div class="panel" id="todayp"><h2>${t("Today")}</h2>${rows || `<p class="hint">${esc(t("no_class_today"))}</p>`}${grade}</div>`;
}
DO.goTab = d => { openTab(d.v); return false; };
DO.takeAtt = d => {
  const b = +d.b;
  if ((S.mine || []).some(x => x.id === b)) { S.sb = b; sessionStorage.setItem("sb", b); } else S.cb = b;
  openTab("classroom", {ct: "attendance", adate: null, aid: null}); return false;
};
DO.goGrade = () => { openTab("classroom", {ct: "assignments", aid: null}); return false; };

// ---------- student: assignments ----------
views.assignments = async () => {
  const list = await api("/assignments");
  const a = list.find(x => x.id === S.aid);
  if (a) {
    const m = a.my;
    const fileLink = m.has_file ? `<button class="btn sm" data-do="dlSub" data-id="${m.submission_id}" data-name="${esc(m.file_name || "file")}">${esc(m.file_name || t("download"))}</button>` : "";
    const done = m.grade != null ? `<div class="msg ok"><b>${t("grade")}: ${m.grade}/${a.max_points}</b>${m.feedback ? "<br>" + esc(m.feedback) : ""}</div>` : "";
    let action;
    if (m.grade != null) action = `<p class="hint">${t("graded_locked")}</p>`;
    else action = `${a.kind === "test" ? `<p class="hint">${t("test_note")}</p>` : ""}${m.submitted ? `<p class="hint">${t("resubmit_note")}</p>` : ""}<label>${t("your_answer")}<textarea id="atext" rows="5">${esc(m.text_answer || "")}</textarea></label><br><label>${t("attach_file")}<input type="file" id="afile" accept=".pdf,.jpg,.jpeg,.png,.docx,.mp3,.m4a,.mp4"></label><br><button class="btn" data-do="submitA" data-id="${a.id}">${t("submit")}</button>`;
    return `${crumbFor(a.title, {aid: null})}<h1>${t("assignments")}</h1><div class="panel" data-detail><button class="btn sm alt" data-do="backA">${t("back")}</button><h2>${esc(a.title)} ${statusTag(a)}</h2><p>${esc(a.course_name)} · ${a.due_date ? esc(t("due_date")) + " " + esc(a.due_date) : t("no_due")} · ${a.max_points} pts</p><p class="pre">${esc(a.description || "")}</p>${a.has_attachment ? `<p><button class="btn sm" data-do="dlAtt" data-id="${a.id}" data-name="${esc(a.attachment_name || "file")}">${t("attachment_from_teacher")}: ${esc(a.attachment_name || "")}</button></p>` : ""}${done}${m.submitted ? `<p class="hint">${t("submitted")}${m.is_late ? " · " + t("late_tag") : ""}</p>${m.text_answer ? `<p class="pre">${esc(m.text_answer)}</p>` : ""}${fileLink}` : ""}<div class="mt1">${action}</div></div>`;
  }
  return `<h1>${t("assignments")}</h1>` + (list.length ? list.map(x => `<div class="panel cl"><div><b>${esc(x.title)}</b> ${statusTag(x)}<br>${esc(x.course_name)} · ${x.due_date ? esc(t("due_date")) + " " + esc(x.due_date) : t("no_due")}</div><button class="btn sm" data-do="goA" data-id="${x.id}">${t(x.my.grade == null && !x.my.submitted ? "submit_work" : "open")}</button></div>`).join("") : `<p>${t("empty")}</p>`);
};
DO.backA = () => { navBack({aid: null}); return false; };
DO.dlAtt = async d => { await viewFile("/assignments/" + d.id + "/attachment", d.name); return false; };
DO.dlSub = async d => { await viewFile("/submissions/" + d.id + "/file", d.name); return false; };
DO.submitA = async d => {
  const fd = new FormData(); fd.append("text", $("#atext").value);
  const f = $("#afile").files[0]; if (f) fd.append("file", f);
  await apiForm("/assignments/" + d.id + "/submit", fd);
  flash(t("saved"), true);
};

// ---------- student: progress (attendance + grades) ----------
views.progress = async () => {
  const [gr, at] = await Promise.all([api("/my/grades"), api("/my/attendance")]);
  const A = Object.fromEntries(at.map(x => [x.batch_id, x]));
  return `<h1>${t("progress")}</h1>` + (gr.map(c => {
    const a = A[c.batch_id] || {recent: []};
    return `<div class="panel"><h2>${esc(c.course_name)} · ${esc(c.batch_code)}</h2><div class="stats"><div class="stat"><b>${pct(a.pct)}</b>${t("attendance_pct")} ${a.low ? tag(t("low_attendance"), "bad") : ""}</div><div class="stat"><b>${pct(c.avg_pct)}</b>${t("avg_pct")}</div></div>
      <p>${a.recent.map(r => tag(r.date.slice(5) + " " + t(r.status), r.status === "absent" ? "bad" : r.status === "present" ? "ok" : "")).join(" ") || t("empty")}</p>
      ${c.items.length ? `<table><thead><tr><th>${t("title")}</th><th>${t("kind")}</th><th>${t("due_date")}</th><th>${t("status")}</th><th>${t("grade")}</th><th>${t("teacher_comment")}</th></tr></thead><tbody>${c.items.map(i => `<tr><td>${esc(i.title)}</td><td>${t(i.kind)}</td><td>${esc(i.due_date || "–")}</td><td>${tag(t(i.status === "graded" ? "graded" : i.status === "submitted" ? "submitted" : "pending"), i.status === "graded" ? "ok" : i.status === "submitted" ? "" : "warn")}</td><td>${i.grade != null ? i.grade + "/" + i.max_points : "–"}</td><td>${i.feedback ? esc(i.feedback) : "–"}</td></tr>`).join("")}</tbody></table>` : `<p>${t("empty")}</p>`}</div>`;
  }).join("") || `<p>${t("empty")}</p>`);
};

// ---------- materials list (student view; teachers manage in classroom) ----------
const matRow = (m, canDelete) => `<div class="cl"><div><b>${esc(m.title)}</b> ${tag(m.kind === "link" ? t("link") : t("file"))}<br>${esc(m.course_name)} · ${esc(m.batch_code)}${m.uploader ? " · " + esc(m.uploader) : ""} · ${esc((m.created_at || "").slice(0, 10))}${m.description ? "<br>" + esc(m.description) : ""}</div><div>${m.kind === "link" ? `<a class="btn sm" href="${esc(safeUrl(m.url))}" target="_blank" rel="noopener noreferrer">${t("open")}</a>` : `<button class="btn sm" data-do="dlMat" data-id="${m.id}" data-name="${esc(m.file_name || "file")}">${t("download")}</button>`}${canDelete ? ` <button class="btn sm alt" data-do="delMat" data-id="${m.id}">${t("delete")}</button>` : ""}</div></div>`;
views.materials = async () => {
  const list = await api("/materials");
  return `<h1>${t("materials")}</h1><div class="panel">${list.map(m => matRow(m, false)).join("") || `<p>${t("empty")}</p>`}</div>`;
};
DO.dlMat = async d => { await viewFile("/materials/" + d.id + "/file", d.name); return false; };
DO.delMat = async d => { if (!await ui.confirm(t("confirm_delete"), {danger: true})) return false; await api("/materials/" + d.id, "DELETE"); flash(t("saved"), true); };

// ---------- classroom (teacher: own batches; admin: all batches) ----------
CH.batch = async el => {
  if (S.attDirty && !await ui.confirm(t("att_unsaved"), {okText: t("Discard changes")})) { el.value = S.cb; return; }
  S.cb = +el.value; S.aid = null; S.adate = null; render();
};
// Session 14: changing the date with marks not yet saved asks first
CH.adate = async el => {
  if (S.attAsking) return;   // a date field can send "change" twice in a row: ask once
  if (S.attDirty) {
    S.attAsking = true;
    const go_ = await ui.confirm(t("att_unsaved"), {okText: t("Discard changes")}).finally(() => { S.attAsking = false; });
    if (!go_) { el.value = S.adate || mvToday(); return; }
  }
  S.adate = el.value; render();
};
DO.ctab = d => { S.ct = d.v; S.aid = null; };
const ctSelect = async k => { if (S.attDirty && !await ui.confirm(t("att_unsaved"), {okText: t("Discard changes")})) return false; S.ct = k; S.aid = null; };

views.classroom = async () => {
  S.attDirty = false;   // a redraw replaces the attendance marks, so nothing is "unsaved" any more
  const bs = await api("/batches");
  if (!bs.length) return `<h1>${t("classroom")}</h1><div class="panel"><p>${t("empty")}</p></div>`;
  if (S.user.role === "teacher" && bs.some(b => b.id === S.sb)) S.cb = S.sb;   // a teacher works in the batch chosen in the header (Session 15)
  if (!bs.some(b => b.id === S.cb)) S.cb = bs[0].id;
  const tab = CT[S.ct] ? S.ct : "attendance", b = bs.find(x => x.id === S.cb);
  const sel = S.user.role === "teacher" ? `<h2>${esc(b.course_name)} · ${esc(b.code)}</h2>` : `<label>${t("select_batch")}<select data-ch="batch">${bs.map(x => `<option value="${x.id}" ${x.id === S.cb ? "selected" : ""}>${esc(x.course_name)} · ${esc(x.code)}${S.user.role === "admin" && x.teacher_name ? " (" + esc(x.teacher_name) + ")" : ""}</option>`).join("")}</select></label>`;
  const keys = ["attendance", "assignments", "gradebook", "materials", "recordings", "schedule"];
  const body = await CT[tab](b);
  const sa = tab === "assignments" && S.aid ? (S.ctAssign || {}) : null;   // the open assignment's title, for the breadcrumb
  return `${sa && sa.title ? crumb([{label: t("classroom"), patch: {aid: null}}, {label: sa.title}]) : ""}<h1>${t("classroom")}</h1><div class="panel">${sel}</div>${tabs({id: "classroom", items: keys.map(k => [k, t(k)]), current: tab, onSelect: ctSelect, label: t("classroom")})}` + body;
};

CT.attendance = async b => {
  const date = S.adate || mvToday();
  mount(() => { const p = $("#attp"); if (p) p.addEventListener("change", e => { if (e.target.matches(".seg input")) S.attDirty = true; }); });
  const [r, sm] = await Promise.all([api(`/batches/${b.id}/attendance?date=${date}`), api(`/batches/${b.id}/attendance/summary`)]);
  const cancelled = r.session && r.session.status === "cancelled";
  const list = r.students.map(s => `<div class="cl"><b>${esc(s.full_name)}</b><div class="seg" role="radiogroup" aria-label="${esc(s.full_name)}">${["present", "late", "absent", "excused"].map(k => `<label><input type="radio" name="att_${s.id}" value="${k}" ${(s.status || "present") === k ? "checked" : ""}><span>${t(k)}</span></label>`).join("")}</div></div>`).join("");
  return `<div class="panel" id="attp"><h2>${t("attendance")}</h2><div class="rowflex row"><label>${t("date")}<input type="date" id="adate" data-ch="adate" value="${date}" max="${mvToday()}"></label><label>${t("topic")}<input id="atopic" value="${esc((r.session && r.session.topic) || "")}"></label></div>
    ${cancelled ? `<div class="msg err">${t("class_cancelled")}</div>` : ""}<p class="hint">${t("high_attendance_note")}</p>${r.students.length && !cancelled ? `<p><button type="button" class="btn sm alt" data-do="attAllPresent">${t("Mark all present")}</button></p>` : ""}${list || `<p>${t("empty")}</p>`}${r.students.length && !cancelled ? `<button class="btn" data-do="saveAtt">${t("save_attendance")}</button>` : ""}</div>
    <div class="panel"><h2>${t("attendance_pct")} (${t("classes_held")}: ${sm.classes_held})</h2><table><thead><tr><th>${t("student")}</th><th>${t("present")}</th><th>${t("late")}</th><th>${t("absent")}</th><th>${t("excused")}</th><th>${t("attendance_pct")}</th></tr></thead><tbody>${sm.students.map(s => `<tr><td>${esc(s.full_name)}</td><td>${s.present}</td><td>${s.late}</td><td>${s.absent}</td><td>${s.excused}</td><td>${pct(s.pct)} ${s.low ? tag(t("low_attendance"), "bad") : ""}</td></tr>`).join("")}</tbody></table></div>`;
};
DO.saveAtt = async () => {
  const recs = [...document.querySelectorAll(".seg input:checked")].map(i => ({student_id: +i.name.slice(4), status: i.value}));
  await api(`/batches/${S.cb}/attendance`, "POST", {date: S.adate || mvToday(), topic: $("#atopic").value.trim() || null, records: recs});
  S.attDirty = false;
  flash(t("att_saved_n").replace("{n}", recs.length), true);
};
DO.attAllPresent = () => { document.querySelectorAll('#attp .seg input[value="present"]').forEach(i => { i.checked = true; }); S.attDirty = true; announce(t("att_all_present_done")); return false; };

CT.assignments = async b => {
  const list = await api(`/assignments?batch_id=${b.id}`);
  const sel = list.find(x => x.id === S.aid);
  S.ctAssign = sel || null;
  mount(() => {
    $("#am") && ($("#am").value = 100);
    onSubmit("fa", async () => {
      const fd = new FormData(); fd.append("title", val("at")); fd.append("kind", val("ak")); if (val("ad")) fd.append("due_date", val("ad")); fd.append("max_points", val("am")); fd.append("description", $("#adesc").value.trim());
      const file = $("#aatt").files[0]; if (file) fd.append("file", file);
      await apiForm(`/batches/${b.id}/assignments`, fd);
    });
  });
  let html = `<div class="panel"><h2>${t("create_assignment")}</h2>${form("fa", field("at", "title") + field("ak", "kind", "", [["assignment", t("assignment")], ["test", t("test")]]) + field("ad", "due_date", "date") + field("am", "max_points", "number") + `<label class="full">${t("description")}<textarea id="adesc" rows="4"></textarea></label><label class="full">${t("assignment_file")}<input type="file" id="aatt" accept=".pdf,.jpg,.jpeg,.png,.docx,.pptx,.xlsx,.mp3,.m4a,.mp4"></label><p class="full m0 hint">${t("assignment_hint")}</p>`, "create_assignment")}</div>`;
  html += `<div class="panel"><table><thead><tr><th>${t("title")}</th><th>${t("kind")}</th><th>${t("due_date")}</th><th>${t("submitted")}</th><th>${t("graded")}</th><th></th></tr></thead><tbody>${list.map(a => `<tr><td>${esc(a.title)}${a.has_attachment ? " " + tag(t("file")) : ""}</td><td>${t(a.kind)}</td><td>${esc(a.due_date || "–")}</td><td>${a.submitted_count}/${a.student_count}</td><td>${a.graded_count}/${a.student_count}</td><td><button class="btn sm" data-do="selA" data-id="${a.id}">${t("submissions")}</button> <button class="btn sm alt" data-do="delA" data-id="${a.id}">${t("delete")}</button></td></tr>`).join("")}</tbody></table>${list.length ? "" : `<p>${t("empty")}</p>`}</div>`;
  if (sel) {
    const s = await api(`/assignments/${sel.id}/submissions`);
    const editable = s.students.some(r => !(r.grade != null && !s.can_edit_grades));
    html += `<div class="panel" data-detail id="gradep" data-can-edit="${s.can_edit_grades ? 1 : 0}"><h2>${esc(s.assignment.title)} · ${s.assignment.max_points} pts</h2>${editable ? `<p><button type="button" class="btn alt" data-do="saveGAll" data-aid="${sel.id}">${t("Save all")}</button> <span class="hint">${t("save_all_hint")}</span></p>` : ""}${s.students.map(r => `<div class="sub" data-sid="${r.student_id}" data-name="${esc(r.full_name)}"><div><b>${esc(r.full_name)}</b> ${r.submitted ? tag(t("submitted") + (r.is_late ? " · " + t("late_tag") : ""), r.is_late ? "warn" : "ok") : tag(t("not_submitted"), "warn")}</div>${r.text_answer ? `<p class="pre">${esc(r.text_answer)}</p>` : ""}${r.has_file ? `<button class="btn sm" data-do="dlSub" data-id="${r.submission_id}" data-name="${esc(r.file_name || "file")}">${esc(r.file_name || t("download"))}</button>` : ""}
      <div class="row" style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:end;margin-top:.4rem">${(() => { const lock = r.grade != null && !s.can_edit_grades ? "disabled" : ""; return `<label style="flex:0 0 110px">${t("grade")} /${s.assignment.max_points}<input type="number" step="0.5" min="0" max="${s.assignment.max_points}" id="g_${r.student_id}" value="${r.grade ?? ""}" data-orig="${esc(r.grade ?? "")}" ${lock}></label><label>${t("feedback")}<input id="f_${r.student_id}" value="${esc(r.feedback || "")}" data-orig="${esc(r.feedback || "")}" ${lock}></label>` + (lock ? `<span class="hint">${t("grade_locked_teacher")}</span>` : `<button class="btn sm" data-do="saveG" data-sid="${r.student_id}" data-aid="${sel.id}">${t("save_grade")}</button><span class="saved" id="gs_${r.student_id}" hidden>✓ ${t("saved")}</span>`); })()}</div></div>`).join("")}</div>`;
  }
  return html;
};
DO.selA = d => { go({aid: +d.id}); return false; };
DO.delA = async d => { if (!await ui.confirm(t("confirm_delete"), {danger: true})) return false; await api("/assignments/" + d.id, "DELETE"); if (S.aid === +d.id) closeDetail({aid: null}); flash(t("saved"), true); };
// Session 14: a grade is saved in place: no redraw, the cursor stays where it was, a "Saved" mark appears next to the row
async function saveOneGrade(aid, sid) {
  const g = $("#g_" + sid), f = $("#f_" + sid);
  await api(`/assignments/${aid}/grades`, "POST", {student_id: +sid, grade: g.value, feedback: f.value});
  g.dataset.orig = g.value; f.dataset.orig = f.value;
  const m = $("#gs_" + sid); if (m) m.hidden = false;
  if (g.value !== "" && $("#gradep").dataset.canEdit !== "1") {   // a saved grade is locked for a teacher without "Change saved grades", as a redraw would show it
    g.disabled = f.disabled = true;
    const btn = document.querySelector(`[data-do="saveG"][data-sid="${sid}"]`);
    if (btn) { const had = document.activeElement === btn || document.activeElement === document.body, h = document.createElement("span"); h.className = "hint"; h.textContent = t("grade_locked_teacher"); btn.replaceWith(h); if (had && m) { m.tabIndex = -1; m.focus(); } }   // keep the cursor in this row
  }
}
DO.saveG = async d => { await saveOneGrade(d.aid, d.sid); announce(t("saved")); return false; };
DO.saveGAll = async d => {
  const rows = [...document.querySelectorAll("#gradep .sub[data-sid]")].filter(r => { const g = $("#g_" + r.dataset.sid), f = $("#f_" + r.dataset.sid); return g && !g.disabled && (g.value !== g.dataset.orig || f.value !== f.dataset.orig); });
  let n = 0;
  for (const r of rows) {
    try { await saveOneGrade(d.aid, r.dataset.sid); n++; }
    catch (x) { throw new Error(`${r.dataset.name}: ${x.message}` + (n ? ` (${t("grades_saved_n").replace("{n}", n)})` : "")); }
  }
  announce(n ? t("grades_saved_n").replace("{n}", n) : t("nothing_to_save"));
  const m = document.createElement("span"); m.className = "saved"; m.setAttribute("data-err", ""); m.textContent = " ✓ " + (n ? t("grades_saved_n").replace("{n}", n) : t("nothing_to_save"));
  const old = document.querySelector("#gradep .saved[data-err]"); if (old) old.remove();
  document.querySelector('#gradep [data-do="saveGAll"]').after(m);
  return false;
};

CT.gradebook = async b => {
  const g = await api(`/batches/${b.id}/gradebook`);
  const mine = S.user.role === "teacher" ? (await api(`/my/given-grades?batch_id=${b.id}`)).grades : [];
  const given = mine.length ? `<div class="panel"><h2>${t("grades_i_gave")}</h2><table><thead><tr><th>${t("student")}</th><th>${t("title")}</th><th>${t("grade")}</th><th>${t("feedback")}</th></tr></thead><tbody>${mine.map(x => `<tr><td>${esc(x.full_name)}</td><td>${esc(x.title)}</td><td>${x.grade}/${x.max_points}</td><td>${esc(x.feedback || "–")}</td></tr>`).join("")}</tbody></table></div>` : "";
  return given + `<div class="panel"><h2>${t("gradebook")}</h2><table><thead><tr><th>${t("student")}</th><th>${t("graded_items")}</th><th>${t("avg_pct")}</th><th>${t("attendance_pct")}</th></tr></thead><tbody>${g.map(s => `<tr><td>${esc(s.full_name)}</td><td>${s.graded_items}</td><td>${pct(s.avg_pct)}</td><td>${pct(s.attendance_pct)} ${s.low_attendance ? tag(t("low_attendance"), "bad") : ""}</td></tr>`).join("")}</tbody></table>${g.length ? "" : `<p>${t("empty")}</p>`}</div>`;
};

CT.materials = async b => {
  const list = await api(`/materials?batch_id=${b.id}`);
  mount(() => onSubmit("fm", async () => { const fd = new FormData(); fd.append("title", val("mt")); fd.append("description", val("md")); if (val("mu")) fd.append("url", val("mu")); const file = $("#mf").files[0]; if (file) fd.append("file", file); await apiForm(`/batches/${b.id}/materials`, fd); }));
  return `<div class="panel"><h2>${t("materials")}</h2><form class="row" id="fm">${field("mt", "title")}${field("md", "description")}<label>${t("file")}<input type="file" id="mf" accept=".pdf,.jpg,.jpeg,.png,.docx,.pptx,.xlsx,.mp3,.m4a,.mp4"></label>${field("mu", "url", "url")}<button class="btn alt">${t("upload")}</button></form><p class="hint">${t("file_or_link")}</p></div><div class="panel">${list.map(m => matRow(m, true)).join("") || `<p>${t("empty")}</p>`}</div>`;
};

CT.schedule = async b => {
  const d0 = mvToday(), d1 = new Date(Date.now() + 5 * 3600e3 + 14 * 864e5).toISOString().slice(0, 10);
  const tl = await api(`/timetable?batch_id=${b.id}&from=${d0}&to=${d1}`);
  const canLinks = S.user.permissions == null || S.user.permissions.includes("class_links");   // the server checks it too
  mount(() => onSubmit("fx", () => api(`/batches/${b.id}/sessions`, "POST", {date: val("xd"), start_time: val("xt") || undefined, topic: val("xp") || undefined, ...(canLinks && val("xm") ? {meet_link: val("xm")} : {})})));
  const none = !(b.days && b.start_time);
  const linkPanel = `<div class="panel"><h2>${t("class_link")}</h2>${b.meet_link ? `<p><a href="${esc(safeUrl(b.meet_link))}" target="_blank" rel="noopener noreferrer">${esc(b.meet_link)}</a></p>` : `<p class="hint">${t("no_meet_link")}</p>`}
    ${canLinks ? `<div class="rowflex row"><label class="full">${t("meet")}<input type="url" id="ml" value="${esc(b.meet_link || "")}" placeholder="https://meet.google.com/..."></label><button class="btn" data-do="saveLink">${t("save")}</button></div><p class="hint">${t("class_link_hint")}</p>` : `<p class="hint">${t("class_link_locked")}</p>`}</div>`;
  return `${linkPanel}<div class="panel"><h2>${t("schedule")}</h2><p>${esc(b.days ? b.days.split(",").map(dayName).join(", ") : "–")} · ${esc(b.start_time || "–")}</p>${none ? `<div class="msg err">${t("no_schedule_warn")} ${esc(b.course_name)} ${esc(b.code)}. ${t("set_days_hint")}</div>` : ""}${tl.map(o => `<div class="cl ${o.status === "cancelled" ? "off" : ""}"><div><b>${whenHtml(o)}</b> ${o.status === "cancelled" ? tag(t("class_cancelled"), "bad") : ""}${o.extra ? tag(t("extra")) : ""}${o.own_link ? tag(t("own_link")) : ""}${o.topic ? "<br>" + esc(o.topic) : ""}</div><div>${canLinks && o.own_link ? `<button class="btn sm" data-do="rmOneLink" data-date="${o.date}" data-time="${o.start_time}">${t("remove_class_link")}</button> ` : ""}<button class="btn sm alt" data-do="setSess" data-date="${o.date}" data-time="${o.start_time}" data-st="${o.status === "cancelled" ? "scheduled" : "cancelled"}">${t(o.status === "cancelled" ? "reinstate" : "cancel_class")}</button></div></div>`).join("") || `<p>${t("empty")}</p>`}</div>
    <div class="panel"><h2>${t("add_class")}</h2>${form("fx", field("xd", "date", "date") + field("xt", "time", "time") + field("xp", "topic") + (canLinks ? field("xm", "one_off_link", "url") + `<p class="full m0 hint">${t("one_off_link_hint")}</p>` : ""), "add")}</div>`;
};
DO.saveLink = async () => { await api(`/batches/${S.cb}/meet-link`, "PUT", {meet_link: val("ml")}); flash(t("saved"), true); };
DO.rmOneLink = async d => { await api(`/batches/${S.cb}/sessions`, "POST", {date: d.date, start_time: d.time, meet_link: ""}); flash(t("saved"), true); };
DO.setSess = async d => { await api(`/batches/${S.cb}/sessions`, "POST", {date: d.date, start_time: d.time, status: d.st}); flash(t("saved"), true); };

// ---------- recordings (Session 5): teachers add a Google Drive link per batch; students of that batch open it ----------
const recRow = (r, canDelete) => `<div class="cl"><div><b>${esc(r.title)}</b><br><bdi dir="ltr">${esc(r.recorded_on)}</bdi> · ${esc(r.course_name)} · ${esc(r.batch_code)}${r.added_by ? " · " + esc(r.added_by) : ""}</div><div><a class="btn sm" href="${esc(safeUrl(r.url))}" target="_blank" rel="noopener noreferrer">${t("open")}</a>${r.download_url ? ` <a class="btn sm alt" href="${esc(safeUrl(r.download_url))}" target="_blank" rel="noopener noreferrer">${t("download")}</a>` : ""}${canDelete ? ` <button class="btn sm alt" data-do="delRec" data-id="${r.id}">${t("delete")}</button>` : ""}</div></div>`;
views.recordings = async () => {
  const list = await api("/recordings");
  return `<h1>${t("recordings")}</h1><p class="hint">${t("recordings_student_hint")}</p><div class="panel">${list.map(r => recRow(r, false)).join("") || `<p>${t("empty")}</p>`}</div>`;
};
CT.recordings = async b => {
  const list = await api(`/recordings?batch_id=${b.id}`);
  const canAdd = S.user.permissions == null || S.user.permissions.includes("add_recordings");   // the server checks it too
  mount(() => onSubmit("fr", () => api(`/batches/${b.id}/recordings`, "POST", {title: val("rt"), recorded_on: val("rd"), url: val("ru")})));
  return `${canAdd ? `<div class="panel"><h2>${t("add_recording")}</h2>${form("fr", field("rt", "title") + field("rd", "class_date", "date") + field("ru", "drive_link", "url") + `<p class="full m0 hint">${t("recording_hint")}</p>`, "add")}</div>` : `<div class="panel"><p class="hint">${t("recording_locked")}</p></div>`}
    <div class="panel"><h2>${t("recordings")}</h2>${list.map(r => recRow(r, canAdd)).join("") || `<p>${t("empty")}</p>`}</div>`;
};
DO.delRec = async d => { if (!await ui.confirm(t("confirm_delete"), {danger: true})) return false; await api("/recordings/" + d.id, "DELETE"); flash(t("saved"), true); };

// ---------- tutorials: teachers and admins post; students read, download and send an answer; the poster and admins read the answers ----------
DO.dlTut = async d => { await viewFile("/tutorials/" + d.id + "/file", d.name); return false; };
DO.readTut = async d => { S.tfull = S.tfull || {}; S.tfull[d.id] = (await api("/tutorials/" + d.id)).text; };
DO.moreTut = () => { S.tlimit = (S.tlimit || 30) + 30; };
DO.delTut = async d => { if (!await ui.confirm(t("confirm_delete"), {danger: true})) return false; await api("/tutorials/" + d.id, "DELETE"); if (S.topen === +d.id) S.topen = null; flash(t("saved"), true); };
DO.openT = d => { S.topen = S.topen === +d.id ? null : +d.id; };   // opens or closes the answer box (student) or the answers list (teacher/admin) under one tutorial
DO.dlTAns = async d => { await viewFile("/tutorial-submissions/" + d.id + "/file", d.name); return false; };
DO.sendTAns = async d => {
  const text = $("#tans_x").value.trim(), file = $("#tans_f").files[0];
  if (!text && !file) throw new Error(t("tutorial_answer_need"));   // an error keeps what the student typed (Session 1)
  const fd = new FormData(); fd.append("text", text); if (file) fd.append("file", file);
  await apiForm("/tutorials/" + d.id + "/submission", fd);
  flash(t("answer_sent"), true);
};
const answerBox = (x, mine) => `<div class="sub"><h3>${t("your_answer")}</h3>
  ${mine ? `<p class="hint">${t("answered")} · <bdi dir="ltr">${esc((mine.submitted_at || "").slice(0, 16))}</bdi></p>` : ""}
  <p class="hint">${t("tutorial_answer_hint")}</p>
  <label>${t("your_answer")}<textarea id="tans_x" rows="5" maxlength="10000">${esc((mine && mine.text_answer) || "")}</textarea></label>
  ${mine && mine.has_file ? `<p>${t("your_file")}: <button class="btn sm" data-do="dlTAns" data-id="${mine.id}" data-name="${esc(mine.file_name || "file")}">${esc(mine.file_name || t("download"))}</button></p>` : ""}
  <label>${t("attach_file")}<input type="file" id="tans_f" accept=".pdf,.jpg,.jpeg,.png,.docx,.mp3,.m4a,.mp4"></label>
  <p><button class="btn" data-do="sendTAns" data-id="${x.id}">${t(mine ? "send_answer_again" : "send_answer")}</button></p></div>`;
const answersList = (r) => `<div class="sub"><h3>${t("tutorial_answers")} (${r.submissions.length})</h3>${r.submissions.map(a => `<div class="bk cl"><b>${esc(a.full_name)}</b> <span class="hint"><bdi dir="ltr">${esc((a.submitted_at || "").slice(0, 16))}</bdi></span>${a.text_answer ? `<p class="pre">${esc(a.text_answer)}</p>` : ""}${a.has_file ? `<p><button class="btn sm" data-do="dlTAns" data-id="${a.id}" data-name="${esc(a.file_name || "file")}">${t("download")}: ${esc(a.file_name || t("file"))}</button></p>` : ""}</div>`).join("") || `<p>${t("no_answers_yet")}</p>`}</div>`;

views.tutorials = async () => {
  const f = S.tf || {}, q = new URLSearchParams();
  const tch = S.user.role === "teacher";   // Session 18: a teacher has no course selector; the header batch decides (the server limits the list to their own batches)
  if (f.course && !tch) q.set("course_id", f.course); if (f.q) q.set("q", f.q);
  const lim = S.tlimit || 30; q.set("limit", lim);
  const [list, courses] = await Promise.all([api("/tutorials?" + q), S.courses ? S.courses : api("/courses").then(c => (S.courses = c)).catch(() => [])]);
  // the one tutorial that is open: load its answer (student) or all its answers (teacher/admin)
  const open = list.find(x => x.id === S.topen && (x.can_submit || x.can_view_answers));
  let panel = "";
  if (open && open.can_submit) panel = answerBox(open, (await api("/tutorials/" + open.id + "/submission")).submission);
  else if (open && open.can_view_answers) panel = answersList(await api("/tutorials/" + open.id + "/submissions"));
  mount(() => {
    const ff = $("#tff"); if (ff) { if ($("#tf_c")) $("#tf_c").value = f.course || ""; ff.onsubmit = e => { e.preventDefault(); S.tf = {course: $("#tf_c") ? val("tf_c") : "", q: val("tf_q")}; S.tlimit = 30; render(); }; }
    onSubmit("tfp", async () => {
      const fd = new FormData(); fd.append("title", val("tp_t")); fd.append("text", $("#tp_x").value.trim());
      if (val("tp_u")) fd.append("url", val("tp_u")); const pc = tch ? ((S.mine || []).find(b => b.id === S.sb) || {}).course_id : val("tp_c"); if (pc) fd.append("course_id", pc);
      const file = $("#tp_f").files[0]; if (file) fd.append("file", file);
      await apiForm("/tutorials", fd);
    });
  });
  const opts = [["", "-"], ...courses.map(c => [c.id, c.name + (c.level ? " " + c.level : "")])];
  const card = x => {
    const isOpen = open && open.id === x.id;
    const status = x.can_submit ? (x.my_submission ? tag(t("answered"), "ok") : tag(t("not_answered"), "warn")) : "";
    const act = x.can_submit ? `<button class="btn sm alt" data-do="openT" data-id="${x.id}">${isOpen ? t("close") : t(x.my_submission ? "edit_answer" : "answer_tutorial")}</button>`
      : x.can_view_answers ? `<button class="btn sm alt" data-do="openT" data-id="${x.id}">${isOpen ? t("close") : t("tutorial_answers") + " (" + (x.answer_count || 0) + ")"}</button>` : "";
    return `<div class="panel"><div class="cl"><div><b>${esc(x.title)}</b> ${status}${!x.accepts_answers ? tag(t("older_post")) : ""}<br><span class="hint">${esc(x.uploader)} · ${esc(t(x.uploader_role))} · ${esc((x.created_at || "").slice(0, 10))}${x.course_name ? " · " + esc(x.course_name) : ""}</span></div>${x.can_delete ? `<button class="btn sm alt" data-do="delTut" data-id="${x.id}">${t("delete")}</button>` : ""}</div>
    ${x.text ? `<p class="pre">${esc((S.tfull || {})[x.id] ?? x.text)}${x.text_truncated && (S.tfull || {})[x.id] == null ? `… <button class="btn sm" data-do="readTut" data-id="${x.id}">${t("read_more")}</button>` : ""}</p>` : ""}<div class="seg">${x.has_file ? `<button class="btn sm" data-do="dlTut" data-id="${x.id}" data-name="${esc(x.file_name || "file")}">${t("download")}: ${esc(x.file_name || t("file"))}</button>` : ""}${x.url ? `<a class="btn sm" href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener noreferrer">${t("open")} ${t("link")}</a>` : ""}${act}</div>${isOpen ? panel : ""}</div>`;
  };
  const canPost = S.user && ["admin", "teacher"].includes(S.user.role) && (S.user.permissions == null || S.user.permissions.includes("create_tutorials"));
  return `<h1>${t("tutorials")}</h1><p class="hint">${t("tutorials_intro")}</p>
    ${canPost ? `<div class="panel"><h2>${t("share_tutorial")}</h2><form id="tfp" class="row">${field("tp_t", "title")}${tch ? "" : field("tp_c", "course_optional", "", opts)}
      <label class="full">${t("tutorial_text")}<textarea id="tp_x" rows="5" maxlength="8000"></textarea></label>
      <label>${t("file")}<input type="file" id="tp_f" accept=".pdf,.jpg,.jpeg,.png,.docx,.pptx,.xlsx,.mp3,.m4a,.mp4"></label>${field("tp_u", "url", "url")}
      <p class="full m0 hint">${t("tutorial_need")}</p><button class="btn alt">${t("post")}</button></form></div>` : ""}
    <div class="panel"><form id="tff" class="row">${tch ? "" : field("tf_c", "course", "", [["", t("all_courses")], ...opts.slice(1)])}<label>${t("search")}<input id="tf_q" value="${esc(f.q || "")}"></label><button class="btn">${t("search")}</button></form></div>
    ${list.length ? list.map(card).join("") : `<div class="panel"><p>${t("empty")}</p></div>`}${list.length >= lim ? `<p><button class="btn" data-do="moreTut">${t("load_more")}</button></p>` : ""}`;
};

// ---------- my information (Session 16): read-only page for the signed-in student or teacher ----------
views.my_information = async () => {
  const r = await api("/my/information"), p = r.profile, st = r.role === "student";
  const row = (k, v) => v ? `<tr><th scope="row">${esc(t(k))}</th><td>${esc(v)}</td></tr>` : "";
  const who = [row("my_id", st ? p.student_code : p.teacher_code), row("login_id", p.login_id), row("full_name", p.full_name), row("email", p.email), row("phone", p.phone)];
  if (st) who.push(row("date_of_birth", p.date_of_birth), row("grade", p.grade), row("island", p.island), row("guardian_name", p.guardian_name), row("guardian_relationship", p.guardian_relationship), row("guardian_phone", p.guardian_phone));
  else who.push(row("bio", p.bio));
  const bl = r.batches.map(b => `<div class="cl"><div><b>${esc(b.course_name)}</b> ${b.course_kind === "tuition" ? tag(t("tuition")) : ""}<br>${esc(b.code)}${b.days ? " · " + esc(b.days) : ""}${b.start_time ? " " + esc(b.start_time) : ""}${b.teacher_name ? " · " + esc(b.teacher_name) : ""}${b.enrol_code ? " · " + esc(b.enrol_code) : ""}</div></div>`).join("");
  return `<h1>${t("my_information")}</h1><p class="hint">${t("my_info_hint")}</p><div class="panel"><table class="kv">${who.join("")}</table></div><div class="panel"><h2>${t(st ? "my_batches" : "my_teaching_batches")}</h2>${bl || `<p>${t("empty")}</p>`}</div>`;
};

// ---------- my earnings (Session 31): a teacher's own approved earnings ----------
views.my_earnings = async () => {
  let r;
  try { r = await api("/my/earnings"); } catch (e) { return `<h1>${t("my_earnings")}</h1><p>${esc(e.message || "")}</p>`; }
  const money = n => `<bdi dir="ltr">MVR ${esc(n)}</bdi>`;
  const body = r.items.map(x => `<tr><td>${esc(x.period)}</td><td>${esc(x.course_name)} ${esc(x.batch_code)}</td><td>${money(x.collected_mvr)}</td><td>${x.share_percent}%</td><td>${money(x.teacher_share_mvr)}</td></tr>`).join("");
  const pays = r.payments.map(x => `<tr><td>${esc(x.paid_on)}</td><td>${money(x.amount_mvr)}</td><td>${esc(x.method)} ${esc(x.reference || "")}</td></tr>`).join("");
  return `<h1>${t("my_earnings")}</h1><p class="hint">${esc(r.note)}</p><div class="stats"><div class="stat"><b>${money(r.earned_mvr)}</b>${t("Earned")}</div><div class="stat"><b>${money(r.paid_mvr)}</b>${t("Paid")}</div><div class="stat"><b>${money(r.outstanding_mvr)}</b>${t("Outstanding")}</div></div>
    <div class="panel">${body ? `<div class="scrollx"><table><thead><tr><th>${t("Month")}</th><th>${t("batch")}</th><th>${t("Collected")}</th><th>${t("Share")}</th><th>${t("Your share")}</th></tr></thead><tbody>${body}</tbody></table></div>` : `<p>${t("empty")}</p>`}</div>
    <div class="panel"><h2>${t("Payments received")}</h2>${pays ? `<table><thead><tr><th>${t("Date")}</th><th>${t("Amount")}</th><th>${t("Method")}</th></tr></thead><tbody>${pays}</tbody></table>` : `<p>${t("empty")}</p>`}</div>`;
};
