/* Phase 3 screens: home + Join class, attendance, assignments, progress, materials, classroom (teacher/admin), batches editor.
   Loaded after the main script in index.html and reuses its helpers: API, S, t, esc, $, val, api, field, form, flash, render, signout, onSubmit. */
const mvToday = () => new Date(Date.now() + 5 * 3600e3).toISOString().slice(0, 10);  // Maldives date (UTC+5)
const pct = v => v == null ? "–" : v + "%";
const tag = (txt, cls = "") => `<span class="tag ${cls}">${esc(txt)}</span>`;
const safeUrl = u => /^https?:\/\//i.test(u || "") ? u : "#";
const DAYS7 = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const dayName = d => t("day_" + d);

async function apiForm(path, fd, method = "POST") {
  const r = await fetch(API + "/api" + path, {method, headers: {Authorization: "Bearer " + S.token}, body: fd});
  const j = await r.json().catch(() => ({}));
  if (r.status === 401) { signout(); throw new Error(j.error); }
  if (!r.ok) throw new Error(j.error || "Something went wrong");
  return j;
}
async function download(path, name) {
  const r = await fetch(API + "/api" + path, {headers: {Authorization: "Bearer " + S.token}});
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || t("download_failed"));
  const a = document.createElement("a");
  a.href = URL.createObjectURL(await r.blob()); a.download = name || "file";
  document.body.appendChild(a); a.click(); a.remove();
}

// one delegated handler for buttons (data-do) and selects/inputs (data-ch) so re-rendering never loses them
const DO = {}, CH = {}, CT = {};
document.addEventListener("click", async e => {
  const b = e.target.closest("[data-do]");
  if (!b || !DO[b.dataset.do]) return;
  e.preventDefault();
  let again = true;
  try { again = (await DO[b.dataset.do](b.dataset, b)) !== false; } catch (x) { flash(x.message); }
  if (again) render();
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
  if (a.kind === "test") return tag(t("test"));
  if (a.my.submitted) return tag(t("submitted") + (a.my.is_late ? " · " + t("late_tag") : ""));
  return tag(t("to_do"), "warn");
};

// ---------- home (student and teacher) ----------
views.home = async () => {
  const h = await api("/my/home");
  let html = `<h1>${t("home")}</h1><div class="panel next">${nextCard(h)}</div>`;
  if (S.user.role === "student") {
    html += `<div class="stats">${h.courses.map(c => `<div class="stat"><b>${pct(c.attendance_pct)}</b>${esc(c.course_name)} · ${t("attendance_pct")}<br><small>${t("avg_pct")}: ${pct(c.avg_pct)}</small></div>`).join("")}</div>`;
    html += `<div class="panel"><h2>${t("open_assignments")}</h2>${h.todo.length ? h.todo.map(a => `<div class="cl"><div><b>${esc(a.title)}</b><br>${esc(a.course_name)} · ${a.due_date ? esc(t("due_date")) + " " + esc(a.due_date) : t("no_due")}</div><button class="btn sm" data-do="goA" data-id="${a.id}">${t("open")}</button></div>`).join("") : `<p>${t("empty")}</p>`}</div>`;
  } else {
    html += `<div class="stats"><div class="stat"><b>${h.to_grade}</b>${t("pending_grading")}</div><div class="stat"><b>${h.low_attendance.length}</b>${t("low_att_students")}</div></div>`;
    if (h.low_attendance.length) html += `<div class="panel"><h2>${t("low_att_students")}</h2>${h.low_attendance.map(s => `<div class="cl"><div><b>${esc(s.full_name)}</b><br>${esc(s.course_name)} · ${esc(s.batch_code)}</div>${tag(pct(s.pct), "bad")}</div>`).join("")}</div>`;
  }
  return html + `<div class="panel"><h2>${t("this_week")}</h2>${weekList(h)}</div>`;
};
DO.goA = d => { S.aid = +d.id; S.view = "assignments"; };

// ---------- student: assignments ----------
views.assignments = async () => {
  const list = await api("/assignments");
  const a = list.find(x => x.id === S.aid);
  if (a) {
    const m = a.my;
    const fileLink = m.has_file ? `<button class="btn sm" data-do="dlSub" data-id="${m.submission_id}" data-name="${esc(m.file_name || "file")}">${esc(m.file_name || t("download"))}</button>` : "";
    const done = m.grade != null ? `<div class="msg ok"><b>${t("grade")}: ${m.grade}/${a.max_points}</b>${m.feedback ? "<br>" + esc(m.feedback) : ""}</div>` : "";
    let action;
    if (a.kind === "test") action = `<p>${t("test_note")}</p>`;
    else if (m.grade != null) action = `<p class="hint">${t("graded_locked")}</p>`;
    else action = `${m.submitted ? `<p class="hint">${t("resubmit_note")}</p>` : ""}<label>${t("your_answer")}<textarea id="atext" rows="5">${esc(m.text_answer || "")}</textarea></label><br><label>${t("attach_file")}<input type="file" id="afile" accept=".pdf,.jpg,.jpeg,.png,.docx,.mp3,.m4a,.mp4"></label><br><button class="btn" data-do="submitA" data-id="${a.id}">${t("submit")}</button>`;
    return `<h1>${t("assignments")}</h1><div class="panel"><button class="btn sm alt" data-do="backA">${t("back")}</button><h2>${esc(a.title)} ${statusTag(a)}</h2><p>${esc(a.course_name)} · ${a.due_date ? esc(t("due_date")) + " " + esc(a.due_date) : t("no_due")} · ${a.max_points} pts</p><p class="pre">${esc(a.description || "")}</p>${a.has_attachment ? `<p><button class="btn sm" data-do="dlAtt" data-id="${a.id}" data-name="${esc(a.attachment_name || "file")}">${t("attachment_from_teacher")}: ${esc(a.attachment_name || "")}</button></p>` : ""}${done}${m.submitted ? `<p class="hint">${t("submitted")}${m.is_late ? " · " + t("late_tag") : ""}</p>${m.text_answer ? `<p class="pre">${esc(m.text_answer)}</p>` : ""}${fileLink}` : ""}<div style="margin-top:1rem">${action}</div></div>`;
  }
  return `<h1>${t("assignments")}</h1>` + (list.length ? list.map(x => `<div class="panel cl"><div><b>${esc(x.title)}</b> ${statusTag(x)}<br>${esc(x.course_name)} · ${x.due_date ? esc(t("due_date")) + " " + esc(x.due_date) : t("no_due")}</div><button class="btn sm" data-do="goA" data-id="${x.id}">${t("open")}</button></div>`).join("") : `<p>${t("empty")}</p>`);
};
DO.backA = () => { S.aid = null; };
DO.dlAtt = async d => { await download("/assignments/" + d.id + "/attachment", d.name); return false; };
DO.dlSub = async d => { await download("/submissions/" + d.id + "/file", d.name); return false; };
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
      ${c.items.length ? `<table><thead><tr><th>${t("title")}</th><th>${t("kind")}</th><th>${t("due_date")}</th><th>${t("grade")}</th></tr></thead><tbody>${c.items.map(i => `<tr><td>${esc(i.title)}</td><td>${t(i.kind)}</td><td>${esc(i.due_date || "–")}</td><td>${i.grade != null ? i.grade + "/" + i.max_points : t("not_graded_yet")}${i.feedback ? `<br><small>${esc(i.feedback)}</small>` : ""}</td></tr>`).join("")}</tbody></table>` : `<p>${t("empty")}</p>`}</div>`;
  }).join("") || `<p>${t("empty")}</p>`);
};

// ---------- materials list (student view; teachers manage in classroom) ----------
const matRow = (m, canDelete) => `<div class="cl"><div><b>${esc(m.title)}</b> ${tag(m.kind === "link" ? t("link") : t("file"))}<br>${esc(m.course_name)} · ${esc(m.batch_code)}${m.uploader ? " · " + esc(m.uploader) : ""} · ${esc((m.created_at || "").slice(0, 10))}${m.description ? "<br>" + esc(m.description) : ""}</div><div>${m.kind === "link" ? `<a class="btn sm" href="${esc(safeUrl(m.url))}" target="_blank" rel="noopener noreferrer">${t("open")}</a>` : `<button class="btn sm" data-do="dlMat" data-id="${m.id}" data-name="${esc(m.file_name || "file")}">${t("download")}</button>`}${canDelete ? ` <button class="btn sm alt" data-do="delMat" data-id="${m.id}">${t("delete")}</button>` : ""}</div></div>`;
views.materials = async () => {
  const list = await api("/materials");
  return `<h1>${t("materials")}</h1><div class="panel">${list.map(m => matRow(m, false)).join("") || `<p>${t("empty")}</p>`}</div>`;
};
DO.dlMat = async d => { await download("/materials/" + d.id + "/file", d.name); return false; };
DO.delMat = async d => { if (!confirm(t("confirm_delete"))) return false; await api("/materials/" + d.id, "DELETE"); flash(t("saved"), true); };

// ---------- classroom (teacher: own batches; admin: all batches) ----------
CH.batch = el => { S.cb = +el.value; S.aid = null; S.adate = null; render(); };
CH.adate = el => { S.adate = el.value; render(); };
DO.ctab = d => { S.ct = d.v; S.aid = null; };

views.classroom = async () => {
  const bs = await api("/batches");
  if (!bs.length) return `<h1>${t("classroom")}</h1><div class="panel"><p>${t("empty")}</p></div>`;
  if (!bs.some(b => b.id === S.cb)) S.cb = bs[0].id;
  const tab = CT[S.ct] ? S.ct : "attendance", b = bs.find(x => x.id === S.cb);
  const sel = `<label>${t("select_batch")}<select data-ch="batch">${bs.map(x => `<option value="${x.id}" ${x.id === S.cb ? "selected" : ""}>${esc(x.course_name)} · ${esc(x.code)}${S.user.role === "admin" && x.teacher_name ? " (" + esc(x.teacher_name) + ")" : ""}</option>`).join("")}</select></label>`;
  const tabs = ["attendance", "assignments", "gradebook", "materials", "schedule"];
  return `<h1>${t("classroom")}</h1><div class="panel">${sel}<div class="subtabs">${tabs.map(k => `<button data-do="ctab" data-v="${k}" ${k === tab ? 'aria-current="true"' : ""}>${t(k)}</button>`).join("")}</div></div>` + await CT[tab](b);
};

CT.attendance = async b => {
  const date = S.adate || mvToday();
  const [r, sm] = await Promise.all([api(`/batches/${b.id}/attendance?date=${date}`), api(`/batches/${b.id}/attendance/summary`)]);
  const cancelled = r.session && r.session.status === "cancelled";
  const list = r.students.map(s => `<div class="cl"><b>${esc(s.full_name)}</b><div class="seg" role="radiogroup" aria-label="${esc(s.full_name)}">${["present", "late", "absent", "excused"].map(k => `<label><input type="radio" name="att_${s.id}" value="${k}" ${(s.status || "present") === k ? "checked" : ""}><span>${t(k)}</span></label>`).join("")}</div></div>`).join("");
  return `<div class="panel"><h2>${t("attendance")}</h2><div class="row" style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:end"><label>${t("date")}<input type="date" id="adate" data-ch="adate" value="${date}" max="${mvToday()}"></label><label>${t("topic")}<input id="atopic" value="${esc((r.session && r.session.topic) || "")}"></label></div>
    ${cancelled ? `<div class="msg err">${t("class_cancelled")}</div>` : ""}<p class="hint">${t("high_attendance_note")}</p>${list || `<p>${t("empty")}</p>`}${r.students.length && !cancelled ? `<button class="btn" data-do="saveAtt">${t("save_attendance")}</button>` : ""}</div>
    <div class="panel"><h2>${t("attendance_pct")} (${t("classes_held")}: ${sm.classes_held})</h2><table><thead><tr><th>${t("student")}</th><th>${t("present")}</th><th>${t("late")}</th><th>${t("absent")}</th><th>${t("excused")}</th><th>${t("attendance_pct")}</th></tr></thead><tbody>${sm.students.map(s => `<tr><td>${esc(s.full_name)}</td><td>${s.present}</td><td>${s.late}</td><td>${s.absent}</td><td>${s.excused}</td><td>${pct(s.pct)} ${s.low ? tag(t("low_attendance"), "bad") : ""}</td></tr>`).join("")}</tbody></table></div>`;
};
DO.saveAtt = async () => {
  const recs = [...document.querySelectorAll(".seg input:checked")].map(i => ({student_id: +i.name.slice(4), status: i.value}));
  await api(`/batches/${S.cb}/attendance`, "POST", {date: S.adate || mvToday(), topic: $("#atopic").value.trim() || null, records: recs});
  flash(t("saved"), true);
};

CT.assignments = async b => {
  const list = await api(`/assignments?batch_id=${b.id}`);
  const sel = list.find(x => x.id === S.aid);
  setTimeout(() => {
    $("#am") && ($("#am").value = 100);
    onSubmit("fa", async () => {
      const fd = new FormData(); fd.append("title", val("at")); fd.append("kind", val("ak")); if (val("ad")) fd.append("due_date", val("ad")); fd.append("max_points", val("am")); fd.append("description", $("#adesc").value.trim());
      const file = $("#aatt").files[0]; if (file) fd.append("file", file);
      await apiForm(`/batches/${b.id}/assignments`, fd);
    });
  });
  let html = `<div class="panel"><h2>${t("create_assignment")}</h2>${form("fa", field("at", "title") + field("ak", "kind", "", [["assignment", t("assignment")], ["test", t("test")]]) + field("ad", "due_date", "date") + field("am", "max_points", "number") + `<label style="flex:1 1 100%">${t("description")}<textarea id="adesc" rows="4"></textarea></label><label style="flex:1 1 100%">${t("assignment_file")}<input type="file" id="aatt" accept=".pdf,.jpg,.jpeg,.png,.docx,.pptx,.xlsx,.mp3,.m4a,.mp4"></label><p class="hint" style="flex:1 1 100%;margin:0">${t("assignment_hint")}</p>`, "create_assignment")}</div>`;
  html += `<div class="panel"><table><thead><tr><th>${t("title")}</th><th>${t("kind")}</th><th>${t("due_date")}</th><th>${t("submitted")}</th><th>${t("graded")}</th><th></th></tr></thead><tbody>${list.map(a => `<tr><td>${esc(a.title)}${a.has_attachment ? " " + tag(t("file")) : ""}</td><td>${t(a.kind)}</td><td>${esc(a.due_date || "–")}</td><td>${a.submitted_count}/${a.student_count}</td><td>${a.graded_count}/${a.student_count}</td><td><button class="btn sm" data-do="selA" data-id="${a.id}">${t("submissions")}</button> <button class="btn sm alt" data-do="delA" data-id="${a.id}">${t("delete")}</button></td></tr>`).join("")}</tbody></table>${list.length ? "" : `<p>${t("empty")}</p>`}</div>`;
  if (sel) {
    const s = await api(`/assignments/${sel.id}/submissions`);
    html += `<div class="panel"><h2>${esc(s.assignment.title)} · ${s.assignment.max_points} pts</h2>${s.students.map(r => `<div class="sub"><div><b>${esc(r.full_name)}</b> ${s.assignment.kind === "test" ? "" : r.submitted ? tag(t("submitted") + (r.is_late ? " · " + t("late_tag") : ""), r.is_late ? "warn" : "ok") : tag(t("not_submitted"), "warn")}</div>${r.text_answer ? `<p class="pre">${esc(r.text_answer)}</p>` : ""}${r.has_file ? `<button class="btn sm" data-do="dlSub" data-id="${r.submission_id}" data-name="${esc(r.file_name || "file")}">${esc(r.file_name || t("download"))}</button>` : ""}
      <div class="row" style="display:flex;gap:.5rem;flex-wrap:wrap;align-items:end;margin-top:.4rem"><label style="flex:0 0 110px">${t("grade")} /${s.assignment.max_points}<input type="number" step="0.5" min="0" max="${s.assignment.max_points}" id="g_${r.student_id}" value="${r.grade ?? ""}"></label><label>${t("feedback")}<input id="f_${r.student_id}" value="${esc(r.feedback || "")}"></label><button class="btn sm" data-do="saveG" data-sid="${r.student_id}" data-aid="${sel.id}">${t("save_grade")}</button></div></div>`).join("")}</div>`;
  }
  return html;
};
DO.selA = d => { S.aid = +d.id; };
DO.delA = async d => { if (!confirm(t("confirm_delete"))) return false; await api("/assignments/" + d.id, "DELETE"); if (S.aid === +d.id) S.aid = null; flash(t("saved"), true); };
DO.saveG = async d => { await api(`/assignments/${d.aid}/grades`, "POST", {student_id: +d.sid, grade: $("#g_" + d.sid).value, feedback: $("#f_" + d.sid).value}); flash(t("saved"), true); };

CT.gradebook = async b => {
  const g = await api(`/batches/${b.id}/gradebook`);
  return `<div class="panel"><h2>${t("gradebook")}</h2><table><thead><tr><th>${t("student")}</th><th>${t("graded_items")}</th><th>${t("avg_pct")}</th><th>${t("attendance_pct")}</th></tr></thead><tbody>${g.map(s => `<tr><td>${esc(s.full_name)}</td><td>${s.graded_items}</td><td>${pct(s.avg_pct)}</td><td>${pct(s.attendance_pct)} ${s.low_attendance ? tag(t("low_attendance"), "bad") : ""}</td></tr>`).join("")}</tbody></table>${g.length ? "" : `<p>${t("empty")}</p>`}</div>`;
};

CT.materials = async b => {
  const list = await api(`/materials?batch_id=${b.id}`);
  setTimeout(() => { const f = $("#fm"); if (f) f.onsubmit = async e => { e.preventDefault(); try { const fd = new FormData(); fd.append("title", val("mt")); fd.append("description", val("md")); if (val("mu")) fd.append("url", val("mu")); const file = $("#mf").files[0]; if (file) fd.append("file", file); await apiForm(`/batches/${b.id}/materials`, fd); flash(t("saved"), true); } catch (x) { flash(x.message); } render(); }; });
  return `<div class="panel"><h2>${t("materials")}</h2><form class="row" id="fm">${field("mt", "title")}${field("md", "description")}<label>${t("file")}<input type="file" id="mf" accept=".pdf,.jpg,.jpeg,.png,.docx,.pptx,.xlsx,.mp3,.m4a,.mp4"></label>${field("mu", "url", "url")}<button class="btn alt">${t("upload")}</button></form><p class="hint">${t("file_or_link")}</p></div><div class="panel">${list.map(m => matRow(m, true)).join("") || `<p>${t("empty")}</p>`}</div>`;
};

CT.schedule = async b => {
  const d0 = mvToday(), d1 = new Date(Date.now() + 5 * 3600e3 + 14 * 864e5).toISOString().slice(0, 10);
  const tl = await api(`/timetable?batch_id=${b.id}&from=${d0}&to=${d1}`);
  setTimeout(() => onSubmit("fx", () => api(`/batches/${b.id}/sessions`, "POST", {date: val("xd"), start_time: val("xt") || undefined, topic: val("xp") || undefined})));
  const none = !(b.days && b.start_time);
  return `<div class="panel"><h2>${t("schedule")}</h2><p>${esc(b.days ? b.days.split(",").map(dayName).join(", ") : "–")} · ${esc(b.start_time || "–")}</p>${none ? `<div class="msg err">${t("no_schedule_warn")} ${esc(b.course_name)} ${esc(b.code)}. ${t("set_days_hint")}</div>` : ""}${tl.map(o => `<div class="cl ${o.status === "cancelled" ? "off" : ""}"><div><b>${whenHtml(o)}</b> ${o.status === "cancelled" ? tag(t("class_cancelled"), "bad") : ""}${o.extra ? tag(t("extra")) : ""}${o.topic ? "<br>" + esc(o.topic) : ""}</div><button class="btn sm alt" data-do="setSess" data-date="${o.date}" data-time="${o.start_time}" data-st="${o.status === "cancelled" ? "scheduled" : "cancelled"}">${t(o.status === "cancelled" ? "reinstate" : "cancel_class")}</button></div>`).join("") || `<p>${t("empty")}</p>`}</div>
    <div class="panel"><h2>${t("add_class")}</h2>${form("fx", field("xd", "date", "date") + field("xt", "time", "time") + field("xp", "topic"), "add")}</div>`;
};
DO.setSess = async d => { await api(`/batches/${S.cb}/sessions`, "POST", {date: d.date, start_time: d.time, status: d.st}); flash(t("saved"), true); };

// ---------- admin: batches (adds class days, start date, editing) ----------
const dayBoxes = sel => `<fieldset class="days"><legend>${t("days")}</legend>${DAYS7.map(d => `<label><input type="checkbox" name="bd" value="${d}" ${(sel || "").split(",").includes(d) ? "checked" : ""}><span>${dayName(d)}</span></label>`).join("")}</fieldset>`;
const pickedDays = () => [...document.querySelectorAll('input[name="bd"]:checked')].map(i => i.value).join(",");
DO.editB = d => { S.eb = +d.id; };
DO.closeB = () => { S.eb = null; };
DO.saveB = async () => {
  await api("/batches/" + S.eb, "PATCH", {days: pickedDays(), start_time: val("be_t") || null, start_date: val("be_sd") || null, meet_link: val("be_m"), capacity: val("be_c"), teacher_id: val("be_h") || null, status: val("be_s")});
  S.eb = null; flash(t("saved"), true);
};
views.batches = async () => {
  const [b, c, tc] = await Promise.all([api("/batches"), api("/courses"), api("/users?role=teacher")]);
  const e = b.find(x => x.id === S.eb);
  setTimeout(() => {
    onSubmit("fb", () => api("/batches", "POST", {course_id: val("bc"), code: val("bn"), days: pickedDays(), start_time: val("bt"), start_date: val("bsd") || null, capacity: val("bp"), teacher_id: val("bh") || null, meet_link: val("bm")}));
    if (e) { $("#be_h").value = e.teacher_id || ""; $("#be_s").value = e.status; }
  });
  const teachers = [["", "-"], ...tc.map(x => [x.id, x.full_name])];
  const editor = e ? `<div class="panel"><h2>${esc(e.course_name)} · ${esc(e.code)}</h2>${dayBoxes(e.days)}<div class="row" style="display:flex;flex-wrap:wrap;gap:.6rem;align-items:end"><label>${t("time")}<input type="time" id="be_t" value="${esc(e.start_time || "")}"></label><label>${t("start_date")}<input type="date" id="be_sd" value="${esc(e.start_date || "")}"></label><label>${t("capacity")}<input type="number" id="be_c" value="${e.capacity}"></label>${field("be_h", "teacher", "", teachers)}${field("be_s", "status", "", [["open", "open"], ["running", "running"], ["closed", "closed"]])}<label style="flex:1 1 100%">${t("meet")}<input type="url" id="be_m" value="${esc(e.meet_link || "")}" placeholder="https://meet.google.com/..."></label><button class="btn" data-do="saveB">${t("save")}</button><button class="btn alt" data-do="closeB">${t("cancel")}</button></div></div>` : "";
  return `<h1>${t("batches")}</h1>${editor}<div class="panel">${form("fb", field("bc", "course", "", c.map(x => [x.id, x.name + " " + (x.level || "")])) + field("bn", "code") + field("bt", "time", "time") + field("bsd", "start_date", "date") + field("bp", "capacity", "number") + field("bh", "teacher", "", teachers) + field("bm", "meet", "url") + dayBoxes(""))}</div><div class="panel"><table><thead><tr><th>${t("course")}</th><th>${t("code")}</th><th>${t("days")}</th><th>${t("time")}</th><th>${t("seats")}</th><th>${t("teacher")}</th><th>${t("status")}</th><th></th></tr></thead><tbody>${b.map(x => `<tr><td>${esc(x.course_name)}</td><td>${esc(x.code)}</td><td>${x.days ? esc(x.days.split(",").map(dayName).join(", ")) : tag("–", "warn")}</td><td>${esc(x.start_time || "–")}</td><td>${x.enrolled}/${x.capacity}</td><td>${esc(x.teacher_name || "–")}</td><td>${esc(x.status)}</td><td><button class="btn sm" data-do="editB" data-id="${x.id}">${t("edit")}</button></td></tr>`).join("")}</tbody></table></div>`;
};


// ---------- tutorials (everyone signed in reads and posts; text, a file, a link, or any mix) ----------
DO.dlTut = async d => { await download("/tutorials/" + d.id + "/file", d.name); return false; };
DO.delTut = async d => { if (!confirm(t("confirm_delete"))) return false; await api("/tutorials/" + d.id, "DELETE"); flash(t("saved"), true); };
views.tutorials = async () => {
  const f = S.tf || {}, q = new URLSearchParams();
  if (f.course) q.set("course_id", f.course); if (f.q) q.set("q", f.q);
  const [list, courses] = await Promise.all([api("/tutorials?" + q), api("/courses").catch(() => [])]);
  setTimeout(() => {
    const ff = $("#tff"); if (ff) { $("#tf_c").value = f.course || ""; ff.onsubmit = e => { e.preventDefault(); S.tf = {course: val("tf_c"), q: val("tf_q")}; render(); }; }
    const fp = $("#tfp"); if (fp) fp.onsubmit = async e => {
      e.preventDefault();
      try {
        const fd = new FormData(); fd.append("title", val("tp_t")); fd.append("text", $("#tp_x").value.trim());
        if (val("tp_u")) fd.append("url", val("tp_u")); if (val("tp_c")) fd.append("course_id", val("tp_c"));
        const file = $("#tp_f").files[0]; if (file) fd.append("file", file);
        await apiForm("/tutorials", fd); flash(t("saved"), true);
      } catch (x) { flash(x.message); }
      render();
    };
  });
  const opts = [["", "-"], ...courses.map(c => [c.id, c.name + (c.level ? " " + c.level : "")])];
  const card = x => `<div class="panel"><div class="cl"><div><b>${esc(x.title)}</b><br><span class="hint">${esc(x.uploader)} · ${esc(t(x.uploader_role))} · ${esc((x.created_at || "").slice(0, 10))}${x.course_name ? " · " + esc(x.course_name) : ""}</span></div>${x.can_delete ? `<button class="btn sm alt" data-do="delTut" data-id="${x.id}">${t("delete")}</button>` : ""}</div>
    ${x.text ? `<p class="pre">${esc(x.text)}</p>` : ""}<div class="seg">${x.has_file ? `<button class="btn sm" data-do="dlTut" data-id="${x.id}" data-name="${esc(x.file_name || "file")}">${t("download")}: ${esc(x.file_name || t("file"))}</button>` : ""}${x.url ? `<a class="btn sm" href="${esc(safeUrl(x.url))}" target="_blank" rel="noopener noreferrer">${t("open")} ${t("link")}</a>` : ""}</div></div>`;
  return `<h1>${t("tutorials")}</h1><p class="hint">${t("tutorials_intro")}</p>
    <div class="panel"><h2>${t("share_tutorial")}</h2><form id="tfp" class="row">${field("tp_t", "title")}${field("tp_c", "course_optional", "", opts)}
      <label style="flex:1 1 100%">${t("tutorial_text")}<textarea id="tp_x" rows="5" maxlength="8000"></textarea></label>
      <label>${t("file")}<input type="file" id="tp_f" accept=".pdf,.jpg,.jpeg,.png,.docx,.pptx,.xlsx,.mp3,.m4a,.mp4"></label>${field("tp_u", "url", "url")}
      <p class="hint" style="flex:1 1 100%;margin:0">${t("tutorial_need")}</p><button class="btn alt">${t("post")}</button></form></div>
    <div class="panel"><form id="tff" class="row">${field("tf_c", "course", "", [["", t("all_courses")], ...opts.slice(1)])}<label>${t("search")}<input id="tf_q" value="${esc(f.q || "")}"></label><button class="btn">${t("search")}</button></form></div>
    ${list.length ? list.map(card).join("") : `<div class="panel"><p>${t("empty")}</p></div>`}`;
};
TABS.admin.splice(TABS.admin.indexOf("classroom") + 1, 0, "tutorials");
TABS.teacher.push("tutorials");
TABS.student.splice(TABS.student.indexOf("materials") + 1, 0, "tutorials");
