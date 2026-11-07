// Nova Copilot panel injected into Event Atlas: AI advice + route planning + one-click "add to my Atlas plan".
(() => {
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const api = async (path, body) => {
    const r = await fetch(path, body === undefined ? {cache: "no-store"} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json(); if (!r.ok) throw new Error(j.error || r.status); return j;
  };
  const hhmm = iso => (iso || "").slice(11, 16);
  const FIELDS = [["hotel", "Hotel / 飯店"], ["max_steps_per_day", "Max steps per day / 每日步數上限"], ["transport", "Transport (walk, shuttle, monorail, rideshare)"], ["interests", "Interests (comma separated)"], ["role", "Role"], ["diet", "Diet"], ["mobility", "Mobility"], ["fixed_commitments", "Fixed commitments (comma separated)"], ["special_arrangements", "Special arrangements (comma separated)"]];
  const LISTS = new Set(["transport", "interests", "fixed_commitments", "special_arrangements"]);
  let lastPlan = null;

  const fab = el("button", null, "✦ Nova Copilot"); fab.id = "nc-fab"; fab.type = "button";
  const panel = el("aside"); panel.id = "nc-panel"; panel.hidden = true;
  const head = el("div", "nc-head"); const title = el("b", null, "Nova Copilot");
  title.append(el("small", null, "Amazon Nova Pro · official API/MCP · route planning"));
  const close = el("button", "nc-x", "×"); close.type = "button"; head.append(title, close);
  const tabs = el("div", "nc-tabs"); const bodies = {};
  for (const [k, label] of [["chat", "Ask"], ["day", "Your day"], ["profile", "Profile"]]) {
    const b = el("button", null, label); b.type = "button"; b.dataset.k = k; tabs.append(b);
    bodies[k] = el("div", "nc-body"); bodies[k].hidden = true;
  }
  const show = k => { for (const b of tabs.children) b.setAttribute("aria-selected", String(b.dataset.k === k)); for (const [n, d] of Object.entries(bodies)) d.hidden = n !== k; if (k === "profile") loadProfile(); };
  tabs.addEventListener("click", e => { if (e.target.dataset.k) show(e.target.dataset.k); });

  const log = bodies.chat; log.append(el("div", "nc-empty", "Ask in any language. Nova Pro searches the official catalog, checks travel between venues and plans your day from your hotel."));
  const chips = el("div", "nc-chips");
  for (const q of ["Plan my Tuesday around AI agents and security, at most 8000 steps a day.", "我住 Park MGM，每天最多走 8000 步，幫我排週二的議程。", "How do I get from Wynn to Mandalay Bay at 10:00 on Tuesday with the fewest steps?", "What is on my schedule right now?"]) {
    const c = el("button", null, q); c.type = "button"; c.addEventListener("click", () => send(q)); chips.append(c);
  }
  log.append(chips);
  const form = el("form", "nc-form"); const ta = el("textarea"); ta.rows = 2; ta.placeholder = "Ask Nova Copilot…";
  const sendBtn = el("button", "nc-btn", "Send"); sendBtn.type = "submit"; form.append(ta, sendBtn);
  const opt = el("label", "nc-opt"); const allow = el("input"); allow.type = "checkbox";
  opt.append(allow, document.createTextNode(" Allow saving favorites to my official schedule for the next message"));
  bodies.day.append(el("div", "nc-empty", "Ask for a plan; it appears here with travel from and back to your hotel."));
  const pform = el("form"); const psave = el("button", "nc-btn", "Save profile"); psave.type = "submit"; const phome = el("div", "nc-note");
  bodies.profile.append(el("div", "nc-note", "Stored only on this machine. Nova Pro uses it to plan from your hotel and around your commitments."), pform, phome, psave);
  psave.addEventListener("click", e => { e.preventDefault(); pform.requestSubmit(); });

  panel.append(head, tabs, bodies.chat, bodies.day, bodies.profile, form, opt);
  document.body.append(fab, panel);
  fab.addEventListener("click", () => { panel.hidden = false; fab.hidden = true; show("chat"); ta.focus(); });
  document.querySelector(".copilot-link")?.addEventListener("click", e => { e.preventDefault(); fab.click(); });
  close.addEventListener("click", () => { panel.hidden = true; fab.hidden = false; });

  async function loadProfile() {
    const p = await api("/api/profile"); pform.replaceChildren();
    for (const [k, label] of FIELDS) { const i = el("input"); i.name = k; const v = p.fields[k]; i.value = Array.isArray(v) ? v.map(x => typeof x === "object" ? JSON.stringify(x) : x).join(", ") : (v && typeof v === "object" ? JSON.stringify(v) : (v ?? "")); pform.append(el("label", null, label), i); }
    phome.textContent = p.home_base ? (p.home_base.venue ? `Home base for routing: ${p.home_base.venue}${p.home_base.exact ? "" : " (nearest venue, approximation)"}` : p.home_base.note) : "";
  }
  pform.addEventListener("submit", async e => {
    e.preventDefault(); const updates = {};
    for (const [k] of FIELDS) { const v = pform.elements[k].value.trim(); updates[k] = LISTS.has(k) ? (v ? v.split(",").map(x => x.trim()).filter(Boolean) : []) : v; }
    try { await api("/api/profile", {updates}); await loadProfile(); } catch (err) { alert(err.message); }
  });

  function traceBox(trace) {
    const d = el("details", "nc-trace"); d.append(el("summary", null, `${trace.length} tool call(s): ${trace.map(t => t.name).join(", ")}`));
    for (const t of trace) d.append(el("pre", null, `${t.ok ? "✓" : "✕"} ${t.name}${t.confirmed === false ? " (not confirmed, nothing saved)" : ""}\ninput: ${JSON.stringify(t.input)}\nresult: ${typeof t.result === "string" ? t.result : JSON.stringify(t.result)}`));
    return d;
  }

  function renderPlan(p) {
    lastPlan = p; const box = bodies.day; box.replaceChildren();
    const plan = p.plan || {}; const hb = p.home_base_travel || {}; const ul = el("ul", "nc-tl");
    if (hb.to_first) { const li = el("li", "mv"); li.append(el("div", "nc-t", "Leave hotel by " + hhmm(hb.to_first.leave_hotel_by)), el("div", "nc-sub", `${Math.round(hb.to_first.minutes)} min · ${hb.to_first.steps} steps · ${hb.to_first.modes.join(" + ")} (estimate)`)); ul.append(li); }
    const trans = {}; for (const t of plan.transitions || []) trans[t.from] = t;
    for (const s of plan.chosen || []) {
      const li = el("li"); li.append(el("div", "nc-t", `${hhmm(s.start)}–${hhmm(s.end)}  ${s.code || ""}`), el("div", null, s.title), el("div", "nc-sub", [s.venue, s.room].filter(Boolean).join(" · "))); ul.append(li);
      const t = trans[s.code] || trans[s.id];
      if (t) { const m = el("li", "mv"); m.append(el("div", "nc-sub", `${Math.round(t.travel_minutes ?? 0)} min ${(t.modes || []).join(" + ")} · slack ${Math.round(t.slack_minutes ?? 0)} min · ${t.status}`)); ul.append(m); }
    }
    if (hb.back_to_hotel) { const li = el("li", "mv"); li.append(el("div", "nc-t", "Back to hotel"), el("div", "nc-sub", `${Math.round(hb.back_to_hotel.minutes)} min · ${hb.back_to_hotel.modes.join(" + ")} (estimate)`)); ul.append(li); }
    box.append(ul.childElementCount ? ul : el("div", "nc-empty", "No feasible sessions."));
    if ((plan.dropped || []).length) { const d = el("details", "nc-trace"); d.append(el("summary", null, `Dropped (${plan.dropped.length}) and why`)); for (const x of plan.dropped) d.append(el("div", null, `${x.code || x.id}: ${x.reason}`)); box.append(d); }
    if (hb.note) box.append(el("div", "nc-note", hb.note));
    const add = el("button", "nc-btn", "Add these sessions to my Event Atlas plan"); add.type = "button"; add.style.marginTop = "10px";
    const msg = el("div", "nc-note"); add.addEventListener("click", () => addToAtlas(plan.chosen || [], msg)); box.append(add, msg);
  }

  // Writes into Event Atlas's own local plan (IndexedDB "reinvent.local-plan.v2"), using the item format of Atlas's makePlanItem.
  async function addToAtlas(chosen, msg) {
    try {
      const cat = await api("/api/catalog");
      const byId = new Map((cat.sessions || []).map(s => [s.session_id, s]));
      const items = [];
      for (const c of chosen) {
        const s = byId.get(c.id); if (!s) continue;
        items.push({placement: JSON.stringify([s.source, s.session_id, s.start_local, s.end_local]), key: JSON.stringify([s.source, s.session_id]),
          code: String(s.code || ""), title: String(s.title || ""), start: String(s.start_local || ""), end: String(s.end_local || ""), location: String(s.location || ""), addedAt: new Date().toISOString()});
      }
      if (!items.length) { msg.textContent = "These sessions are not in the official catalog loaded in Event Atlas (demo sessions, or not signed in). Sign in to plan with real sessions."; return; }
      const db = await new Promise((res, rej) => { const r = indexedDB.open("reinvent.local-plan.v2", 1); r.onupgradeneeded = () => { if (!r.result.objectStoreNames.contains("plan")) r.result.createObjectStore("plan"); }; r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error); });
      await new Promise((res, rej) => {
        const tx = db.transaction("plan", "readwrite"); const st = tx.objectStore("plan"); const g = st.get("current");
        g.onsuccess = () => { const cur = (g.result && Array.isArray(g.result.items)) ? g.result.items : []; const merged = cur.concat(items.filter(i => !cur.some(p => p.placement === i.placement))); st.put({version: 1, items: merged}, "current"); };
        tx.oncomplete = res; tx.onerror = () => rej(tx.error); tx.onabort = () => rej(tx.error);
      });
      db.close();
      msg.textContent = `Added ${items.length} session(s) to your Event Atlas plan. Reloading the calendar…`;
      setTimeout(() => location.reload(), 900);
    } catch (e) { msg.textContent = "Could not add to the Atlas plan: " + e.message; }
  }

  async function send(text) {
    show("chat"); const q = el("div", "nc-msg nc-user", text); const a = el("div", "nc-msg nc-bot", "Nova Pro is checking the catalog and routes…");
    log.append(q, a); log.scrollTop = log.scrollHeight; sendBtn.disabled = true;
    try {
      const r = await api("/api/chat", {message: text, allow_write: allow.checked});
      a.textContent = r.text; if (r.trace.length) a.append(traceBox(r.trace));
      if (r.plan) { renderPlan(r.plan); const go = el("button", "nc-btn", "See the route & timeline →"); go.type = "button"; go.style.marginTop = "6px"; go.addEventListener("click", () => show("day")); a.append(go); }
    } catch (e) { a.textContent = "Error: " + e.message; a.classList.add("nc-err"); }
    allow.checked = false; sendBtn.disabled = false; log.scrollTop = log.scrollHeight;
  }
  form.addEventListener("submit", e => { e.preventDefault(); const v = ta.value.trim(); if (v) { ta.value = ""; send(v); } });
  ta.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } });
})();
