/* Session 2: one dialog component for the whole portal (replaces prompt(), confirm() and the old fxAsk/sure helpers).
   Loaded in index.html after the main script and before learning.js. Uses t() and esc() from index.html.

     ui.confirm(msg, {danger, okText, title, details})          -> Promise<boolean>
     ui.ask(title, {label, required, multiline, value, hint})   -> Promise<string|null>   (null = cancelled)
     ui.form(title, fields, {okText, hint, validate})           -> Promise<object|null>
         fields: [{id, label, type, options, required, value, min, max, step, inputmode, hint, maxlength}]
     ui.pick(title, items, {placeholder})                       -> Promise<item|null>     (filter list, used by quick jump)
     ui.show(title, html)                                       -> Promise<void>          (information only)
     ui.trap(el, {onEscape})                                    -> release()              (focus trap for panels that are not <dialog>s)

   Every dialog is a native <dialog> opened with showModal(): Tab stays inside, Escape cancels, focus goes back to whatever opened it. */
const ui = (() => {
  const FOCUSABLE = 'a[href],button:not([disabled]),input:not([disabled]):not([type=hidden]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])';
  const visible = x => !!(x.offsetWidth || x.offsetHeight || x.getClientRects().length);
  const focusables = el => [...el.querySelectorAll(FOCUSABLE)].filter(visible);
  let seq = 0;

  // Keeps Tab and Shift+Tab inside `el`. Escape calls onEscape. The listener lives on `el`, so it goes away with it (no leak).
  function trap(el, {onEscape} = {}) {
    const key = e => {
      if (e.key === "Escape" && onEscape) { e.preventDefault(); e.stopPropagation(); onEscape(e); return; }
      if (e.key !== "Tab") return;
      const f = focusables(el); if (!f.length) { e.preventDefault(); return; }
      const first = f[0], last = f[f.length - 1], a = document.activeElement;
      if (e.shiftKey && (a === first || !el.contains(a))) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && (a === last || !el.contains(a))) { e.preventDefault(); first.focus(); }
    };
    el.addEventListener("keydown", key);
    return () => el.removeEventListener("keydown", key);
  }

  // Base: builds the dialog, waits for OK or Cancel, cleans up and returns focus to the opener.
  // collect(form) returns the value for OK, or throws an Error whose message is shown inside the dialog.
  function open({title, body, okText, cancelText, danger, collect, init, focusCancel, noCancel, wide, view}) {
    const opener = document.activeElement, id = "dlg" + (++seq);
    const d = document.createElement("dialog");
    d.className = "dlg" + (danger ? " danger" : "") + (wide ? " wide" : "") + (view ? " view" : "");
    d.setAttribute("aria-labelledby", id + "_t");
    d.innerHTML = `<form class="dlg-f" method="dialog" novalidate><h2 id="${id}_t">${esc(title)}</h2><div class="dlg-b">${body || ""}</div>`
      + `<p class="msg err" role="alert" hidden></p><div class="dlg-a">`
      + (noCancel ? "" : `<button type="button" class="btn alt" value="cancel">${esc(cancelText || t("Cancel"))}</button>`)
      + `<button type="submit" class="btn${danger ? " danger" : ""}" value="ok">${esc(okText || t("OK"))}</button></div></form>`;
    document.body.appendChild(d);
    const f = d.querySelector("form"), errBox = d.querySelector(".dlg-f>.msg"), release = trap(d);
    return new Promise(resolve => {
      let done = false;
      const finish = v => {
        if (done) return; done = true; release();
        if (d.open) d.close();
        d.remove();
        if (opener && opener.isConnected && typeof opener.focus === "function") opener.focus();
        resolve(v);
      };
      d.addEventListener("cancel", e => { e.preventDefault(); finish(null); });      // Escape
      d.addEventListener("click", e => { if (e.target === d) finish(null); });      // a click on the backdrop
      const cancel = d.querySelector('button[value="cancel"]'); if (cancel) cancel.onclick = () => finish(null);
      f.onsubmit = e => {
        e.preventDefault();
        try { const v = collect ? collect(f, id) : true; finish(v); }
        catch (x) { errBox.textContent = x.message; errBox.hidden = false; const bad = f.querySelector("[aria-invalid=true]"); (bad || errBox).focus && (bad || errBox).focus(); }
      };
      d.showModal();
      if (init) init(d, id, finish);
      const first = focusCancel && cancel ? cancel : (f.querySelector(".dlg-b input,.dlg-b select,.dlg-b textarea") || f.querySelector('button[value="ok"]'));
      if (first) first.focus();
    });
  }

  // one form control inside a dialog; ids are prefixed so they never clash with ids on the page
  function control(px, fl) {
    const id = px + "_" + fl.id, req = fl.required ? " required" : "", v = fl.value ?? "";
    const attrs = ["min", "max", "step", "inputmode", "maxlength", "placeholder", "autocomplete"].filter(k => fl[k] != null).map(k => ` ${k}="${esc(fl[k])}"`).join("");
    const hint = fl.hint ? `<span class="hint" id="${id}_h">${esc(fl.hint)}</span>` : "";
    const desc = fl.hint ? ` aria-describedby="${id}_h"` : "";
    let ctl;
    if (fl.type === "select") ctl = `<select id="${id}"${req}${desc}>${(fl.options || []).map(o => `<option value="${esc(o[0])}" ${String(o[0]) === String(v) ? "selected" : ""}>${esc(o[1])}</option>`).join("")}</select>`;
    else if (fl.type === "textarea") ctl = `<textarea id="${id}" rows="${fl.rows || 4}"${req}${attrs}${desc}>${esc(v)}</textarea>`;
    else if (fl.type === "file") ctl = `<input id="${id}" type="file"${fl.accept ? ` accept="${esc(fl.accept)}"` : ""}${req}${desc}>`;   // v0.8.43
    else if (fl.type === "checkbox") return `<label for="${id}" class="inl"><input id="${id}" type="checkbox"${fl.value ? " checked" : ""}${desc}> ${esc(fl.label)}${hint}</label>`;
    else ctl = `<input id="${id}" type="${esc(fl.type || "text")}" value="${esc(v)}"${req}${attrs}${desc}>`;
    return `<label for="${id}">${esc(fl.label)}${fl.required ? ` <span class="req" aria-hidden="true">*</span>` : ""}${ctl}${hint}</label>`;
  }
  function read(f, px, fields) {
    const out = {};
    f.querySelectorAll("[aria-invalid]").forEach(x => x.removeAttribute("aria-invalid"));
    for (const fl of fields) {
      const el = f.querySelector("#" + px + "_" + fl.id);
      if (fl.type === "checkbox") { out[fl.id] = el.checked; continue; }
      if (fl.type === "file") { const file = el.files[0] || null; if (fl.required && !file) { el.setAttribute("aria-invalid", "true"); el.focus(); throw new Error(t("dlg_required").replace("{f}", fl.label)); } out[fl.id] = file; continue; }
      const v = el.value.trim();
      const bad = msg => { el.setAttribute("aria-invalid", "true"); el.focus(); throw new Error(msg); };
      if (fl.required && !v) bad(t("dlg_required").replace("{f}", fl.label));
      if (fl.type === "number" && v !== "") {
        const n = Number(v);
        if (!isFinite(n)) bad(t("dlg_number").replace("{f}", fl.label));
        if ((fl.step == null || +fl.step === 1) && !Number.isInteger(n)) bad(t("whole_number").replace("{f}", fl.label));
        if (fl.min != null && n < +fl.min) bad(t("dlg_min").replace("{f}", fl.label).replace("{n}", fl.min));
        if (fl.max != null && n > +fl.max) bad(t("dlg_max").replace("{f}", fl.label).replace("{n}", fl.max));
      }
      out[fl.id] = v;
    }
    return out;
  }

  function confirm(msg, {danger, okText, title, details} = {}) {
    const list = details && details.length ? `<ul class="dlg-list">${details.map(x => `<li>${esc(x)}</li>`).join("")}</ul>` : "";
    return open({title: title || (danger ? t("dlg_are_you_sure") : t("dlg_confirm")), body: `<p class="pre">${esc(msg)}</p>${list}`, okText: okText || (danger ? t("delete") : t("OK")), danger, focusCancel: !!danger})
      .then(v => v === true);
  }
  function ask(title, {label, required, multiline, value, hint, okText, danger, maxlength} = {}) {
    const fl = {id: "v", label: label || title, required, type: multiline ? "textarea" : "text", value, hint, maxlength: maxlength || 300};
    return open({title, okText, danger, body: control("a" + (seq + 1), fl), collect: (f, id) => read(f, "a" + id.slice(3), [fl]).v})
      .then(v => v == null ? null : v);
  }
  function form(title, fields, {okText, hint, validate, danger} = {}) {
    const px = "f" + (seq + 1);
    const body = (hint ? `<p class="hint">${esc(hint)}</p>` : "") + fields.map(fl => control(px, fl)).join("");
    return open({title, okText, danger, body, collect: f => { const v = read(f, px, fields); const e = validate && validate(v); if (e) throw new Error(e); return v; }});
  }
  function show(title, html) { return open({title, body: html, okText: t("Close"), noCancel: true, wide: true}).then(() => undefined); }

  // A filter box over a list (combobox + listbox). Arrow keys move, Enter picks, a click picks. items: [{label, hint, ...}]
  function pick(title, items, {placeholder} = {}) {
    let chosen = null, shown = items, act = 0;
    const px = "p" + (seq + 1);
    const body = `<label for="${px}_q" class="sr-only">${esc(title)}</label><input id="${px}_q" type="search" role="combobox" aria-expanded="true" aria-controls="${px}_l" aria-autocomplete="list" autocomplete="off" placeholder="${esc(placeholder || t("qj_placeholder"))}">`
      + `<ul class="pick-l" id="${px}_l" role="listbox" aria-label="${esc(title)}"></ul><p class="hint">${esc(t("qj_hint"))}</p>`;
    return open({title, body, okText: t("qj_go"), collect: () => { if (!shown[act]) throw new Error(t("qj_none")); return shown[act]; },
      init: d => {
        const q = d.querySelector("#" + px + "_q"), ul = d.querySelector("#" + px + "_l");
        const draw = () => {
          ul.innerHTML = shown.map((x, i) => `<li role="option" id="${px}_o${i}" aria-selected="${i === act}" data-i="${i}">${x.icon || ""}<span>${esc(x.label)}${x.hint ? ` <small class="hint">${esc(x.hint)}</small>` : ""}</span></li>`).join("") || `<li class="hint" aria-disabled="true">${esc(t("qj_none"))}</li>`;
          if (shown[act]) { q.setAttribute("aria-activedescendant", px + "_o" + act); const li = ul.querySelector("#" + px + "_o" + act); if (li) li.scrollIntoView({block: "nearest"}); } else q.removeAttribute("aria-activedescendant");
        };
        q.addEventListener("input", () => { const s = q.value.trim().toLowerCase(); shown = items.filter(x => (x.label + " " + (x.hint || "") + " " + (x.keys || "")).toLowerCase().includes(s)); act = 0; draw(); });
        q.addEventListener("keydown", e => {
          if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); if (!shown.length) return; act = (act + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length; draw(); }
          else if (e.key === "Home" && e.ctrlKey) { act = 0; draw(); } else if (e.key === "End" && e.ctrlKey) { act = shown.length - 1; draw(); }
        });
        ul.addEventListener("click", e => { const li = e.target.closest("li[data-i]"); if (li) { act = +li.dataset.i; d.querySelector("form").requestSubmit(); } });
        draw();
      }}).then(v => (chosen = v || null));
  }

  // v0.8.34: a file viewer inside the page. Images always show; PDFs show where the browser can display them (navigator.pdfViewerEnabled);
  // otherwise (most Android phones) the dialog says so and offers Download. Download and Open in a new tab are always there.
  // v0.8.36: extra (HTML under the file), okText/cancelText, collect and init turn it into a check dialog (the slip check); its value is returned
  function viewer({name, url, type, size, title, extra, okText, cancelText, collect, init}) {
    const isImg = /^image\//.test(type), isPdf = type === "application/pdf";
    const canPdf = isPdf && navigator.pdfViewerEnabled !== false && !/Android/i.test(navigator.userAgent);
    const kb = size ? (size > 1048576 ? (size / 1048576).toFixed(1) + " MB" : Math.max(1, Math.round(size / 1024)) + " KB") : "";
    const view = isImg ? `<img class="fv-img" src="${esc(url)}" alt="${esc(name)}">`
      : canPdf ? `<iframe class="fv-pdf" src="${esc(url)}" title="${esc(name)}"></iframe>`
      : `<p class="hint">${esc(t("viewer_no_pdf"))}</p>`;
    const body = `<div class="fv">${view}</div><p class="fv-meta hint"><bdi>${esc(name)}</bdi>${kb ? " · " + esc(kb) : ""}</p>`
      + `<div class="fv-act"><a class="btn" href="${esc(url)}" download="${esc(name)}">${esc(t("download"))}</a>`
      + `<a class="btn alt" href="${esc(url)}" target="_blank" rel="noopener">${esc(t("open_new_tab"))}</a></div>`;
    if (extra != null) return open({title: title || name, body: body + extra, okText, cancelText: cancelText || t("Close"), collect, init, wide: true, view: true});
    return open({title: name, body, okText: t("Close"), noCancel: true, wide: true, view: true}).then(() => undefined);
  }

  return {confirm, ask, form, pick, show, trap, viewer};
})();
