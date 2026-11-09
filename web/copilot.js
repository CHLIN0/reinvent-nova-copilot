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
  let signedIn = false;

  // The toggle lives in the Event Atlas header; the panel docks on the right and stays open until toggled.
  let toggle = document.getElementById("copilot-toggle");
  if (!toggle) { toggle = el("button", "nc-btn2", "✦ Nova Copilot"); toggle.id = "copilot-toggle"; toggle.type = "button"; document.body.append(toggle); }
  toggle.hidden = false;
  const panel = el("aside"); panel.id = "nc-panel"; panel.hidden = true; panel.setAttribute("aria-label", "Nova Copilot");
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

  const log = bodies.chat;
  const demo = el("div", "nc-note nc-demo", "Demo mode: you are signed out, so Copilot answers from the synthetic demo catalog. Sign in with “登入 AWS Events” on the page for the official catalog and your schedule.");
  demo.hidden = true; log.append(demo);
  log.append(el("div", "nc-empty", "Ask in any language. Nova Pro searches the official catalog, checks travel between venues and plans your day from your hotel."));
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
  document.body.append(panel);
  const setOpen = open => {
    panel.hidden = !open; toggle.setAttribute("aria-pressed", String(open));
    document.body.classList.toggle("nc-docked", open);
    window.dispatchEvent(new Event("resize"));  // Atlas's calendar and map re-measure the narrower page
    if (open) { show("chat"); ta.focus(); }
  };
  toggle.addEventListener("click", () => setOpen(panel.hidden));
  close.addEventListener("click", () => setOpen(false));

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

  // "My plan" (我的安排) lives on the server (/api/plan); Event Atlas re-reads it when told, no page reload.
  const planChanged = () => window.dispatchEvent(new Event("atlas:plan-changed"));
  async function addToAtlas(chosen, msg) {
    const ids = chosen.map(c => c.id).filter(id => typeof id === "string" && id);
    if (!ids.length) { msg.textContent = "No sessions to add."; return; }
    try {
      const r = await api("/api/plan", {action: "add", session_ids: ids});
      planChanged();
      msg.textContent = r.changed ? `Added ${r.changed} session(s) to “我的安排”.` : "These sessions are already in “我的安排”.";
    } catch (e) { msg.textContent = "Could not add to “我的安排”: " + e.message; }
  }

  // Suggested sessions with explicit RSVP / favorite / cancel buttons: the model proposes, the attendee clicks.
  // Each card shows its official state from /api/plan: reserved → reserved + cancel (never RSVP); favorite → favorited + RSVP.
  const SEATS = {available: "Seats available", limited: "Limited seats", veryLimited: "Very few seats left", unavailable: "Full", walkUp: "Walk-up only, no reservation"};
  const FAILURES = {  // the official per-item codes (ReserveSessions / AssociateFavorites), plus CancelReservation's 409/401/429/5xx
    sessionNotReservable: "This session does not take reservations.",
    scheduleConflict: "It overlaps a session already on your schedule.",
    alreadyScheduled: "It is already on your schedule.",
    sessionFull: "The session is full.",
    insufficientAccess: "Your registration does not give access to this session.",
    timePassed: "The session has already started or ended.",
    alreadyFavorited: "It is already in your favorites.",
    notFavorited: "It is not in your favorites.",
    other: "AWS Events refused it without giving a reason.",
    operationClosed: "AWS Events is not accepting this change right now; try again later.",
    not_reported: "AWS Events did not report a result for it; check your schedule in AWS Events.",
    official_sign_in_required: "Your sign-in expired; sign in to AWS Events again.",
    official_rate_limited: "AWS Events is busy; wait a minute and try again.",
    catalog_unavailable: "AWS Events did not answer; check your schedule before trying again.",
  };
  const failureText = (it, codeOf) => {
    const also = it.conflicts_with?.length ? ` (${it.conflicts_with.map(codeOf).join(", ")})` : "";
    const text = FAILURES[it.code];
    return text ? text.replace(/\.$/, also + ".") : `AWS Events refused it (code: ${it.code || "none"})${also}; see AWS Events.`;
  };
  // Every card set re-reads the official state when the plan changes (here or in Atlas); one read serves them all.
  const cardSets = new Set(); let planRead = null;
  const readPlanOnce = () => (planRead ||= api("/api/plan").finally(() => { planRead = null; }));
  window.addEventListener("atlas:plan-changed", () => { for (const read of cardSets) read(); });
  function sessionCards(rows) {
    const box = el("div", "nc-cards"); const cards = [];
    let official = {}, codes = {};
    const when = s => `${(s.start || "").slice(5, 10)} ${hhmm(s.start)}–${hhmm(s.end)}`;
    const named = s => `${s.code || s.id} “${s.title || ""}” (${when(s)})`;
    async function readPlan() {
      try {  // a failed read, or an official read that failed, keeps the last known state (Cancel never turns into RSVP)
        const p = await readPlanOnce(); const status = p.official?.status;
        codes = Object.fromEntries((p.items || []).map(i => [i.session_id, i.code || i.session_id]));
        if (status !== "error") official = Object.fromEntries((p.items || []).filter(i => status === "live" && i.source !== "local").map(i => [i.session_id, i.source]));
      } catch { /* keep the last known state */ }
      for (const render of cards) render();
    }
    for (const s of rows) {
      const c = el("div", "nc-card"); const state = el("div", "nc-sub"); const row = el("div", "nc-actions"); const out = el("div", "nc-sub");
      c.append(el("div", "nc-t", `${when(s)}  ${s.code || ""}`), el("div", null, s.title || ""), el("div", "nc-sub", s.venue || ""));
      if (SEATS[s.seats]) c.append(el("div", "nc-sub", SEATS[s.seats]));
      const act = async (path, b) => {
        const cancel = path === "/api/rsvp/cancel";
        const ask = cancel ? `Cancel your official reservation for ${named(s)}? Your seat is released and may not be available again.`
          : path === "/api/rsvp" ? `Reserve a seat for ${named(s)} in your official AWS Events schedule?` : null;
        if (ask && !confirm(ask)) return;
        b.disabled = true; out.textContent = "Sending to AWS Events…";
        try {
          const r = await api(path, {session_ids: [s.id]}); const it = (r.results || [])[0] || {};
          const verified = cancel ? it.in_schedule_reserved === false : (it.in_schedule_reserved ?? it.in_schedule_favorites);
          out.textContent = it.ok && verified ? (cancel ? (it.already_gone ? "✓ It was already not reserved; verified in your official schedule." : "✓ Cancelled and verified in your official schedule (no longer reserved).")
              : `✓ Done and verified in your official schedule (${path === "/api/rsvp" ? "reserved" : "favorites"}).`)
            : it.ok ? (cancel ? "Cancel accepted, but your schedule read-back still lists it as reserved. Check the AWS Events app." : "Accepted, but not yet visible in your schedule read-back. Check the AWS Events app.")
            : "Not done: " + failureText(it, id => codes[id] || id);
          if (it.ok) { loadOfficial(); await readPlan(); } else b.disabled = false;  // refused: nothing changed, retry stays possible
        } catch (e) { out.textContent = "Not done: " + e.message + (/sign_in/.test(e.message) ? " Sign in to AWS Events first." : ""); b.disabled = false; }
      };
      cards.push(() => {
        const src = official[s.id];
        state.textContent = src === "reserved" ? "✓ Reserved in your official schedule" : src === "favorite" ? "★ In your official favorites" : "";
        const actions = src === "reserved" ? [["Cancel reservation", "/api/rsvp/cancel", "nc-btn2"]]
          : [["RSVP", "/api/rsvp", "nc-btn"], ...(src === "favorite" ? [] : [["☆ Favorite", "/api/favorite", "nc-btn2"]])];
        row.replaceChildren(...actions.map(([label, path, cls]) => { const b = el("button", cls, label); b.type = "button"; b.addEventListener("click", () => act(path, b)); return b; }));
      });
      c.append(state, row, out); box.append(c);
    }
    cardSets.add(readPlan); readPlan();
    return box;
  }

  // Once per page load when signed in: shown inline at the top of My re:Invent and in the Ask tab.
  let briefed = false;
  async function briefing() {
    if (briefed) return; briefed = true;
    const inline = document.getElementById("mine-briefing");
    const waiting = "Welcome back. Nova Pro is checking your official schedule and profile…";
    const a = el("div", "nc-msg nc-bot", waiting); log.append(a);
    const b = inline ? el("div", "nc-msg nc-bot", waiting) : null;
    if (inline) { inline.replaceChildren(el("b", null, "Nova Copilot briefing"), b); inline.hidden = false; }
    try {
      const r = await api("/api/briefing", {});
      const head = r.first_visit ? "Welcome! " : r.schedule_diff ? "Since your last visit: " + ["reserved", "favorites"].map(k => `${k} +${r.schedule_diff[k].added.length}/−${r.schedule_diff[k].removed.length}`).join(", ") + "\n\n" : "";
      for (const box of [a, b].filter(Boolean)) {
        box.textContent = head + r.text; if (r.trace.length) box.append(traceBox(r.trace));
        if ((r.suggested || []).length) box.append(sessionCards(r.suggested));
      }
      if (r.plan) renderPlan(r.plan);
    } catch (e) { for (const box of [a, b].filter(Boolean)) box.textContent = "Briefing unavailable: " + e.message; }
  }

  async function send(text) {
    show("chat"); const q = el("div", "nc-msg nc-user", text); const a = el("div", "nc-msg nc-bot", "Nova Pro is checking the catalog and routes…");
    log.append(q, a); log.scrollTop = log.scrollHeight; sendBtn.disabled = true;
    try {
      const r = await api("/api/chat", {message: text, allow_write: allow.checked});
      a.textContent = r.text; if (r.trace.length) a.append(traceBox(r.trace));
      if ((r.suggested || []).length) a.append(sessionCards(r.suggested));
      if (r.plan) { renderPlan(r.plan); const go = el("button", "nc-btn", "See the route & timeline →"); go.type = "button"; go.style.marginTop = "6px"; go.addEventListener("click", () => show("day")); a.append(go); }
    } catch (e) { a.textContent = "Error: " + e.message; a.classList.add("nc-err"); }
    allow.checked = false; sendBtn.disabled = false; log.scrollTop = log.scrollHeight;
  }
  form.addEventListener("submit", e => { e.preventDefault(); const v = ta.value.trim(); if (v) { ta.value = ""; send(v); } });
  ta.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } });

  // Official schedule: proves the sign-in is real (data comes from AWS Events GetSchedule) and shows RSVPs in Atlas.
  const banner = el("div"); banner.id = "nc-banner"; document.body.append(banner);
  function scheduleList(title, rows) {
    const box = el("div"); box.append(el("div", "nc-t", `${title} (${rows.length})`));
    const ul = el("ul", "nc-tl");
    for (const r of rows) { const li = el("li"); li.append(el("div", "nc-t", `${(r.start || "").slice(5, 10)} ${hhmm(r.start)}–${hhmm(r.end)}  ${r.code || ""}`), el("div", null, r.title || r.id), el("div", "nc-sub", [r.venue_name || r.venue, r.room].filter(Boolean).join(" · "))); ul.append(li); }
    box.append(rows.length ? ul : el("div", "nc-empty", "None")); return box;
  }
  async function loadOfficial(statusOnly = false) {
    let status, s, scheduleError;
    try {
      status = await api("/api/status");
      if (status.signed_in && !statusOnly) {
        try { s = await api("/api/my-schedule"); } catch (e) { scheduleError = e.message; }
        status = await api("/api/status"); // Reading the schedule may have refreshed the token.
      }
    } catch (e) { banner.textContent = "AWS Events: could not check sign-in status (" + e.message + ")"; banner.className = "nc-warn"; return; }
    signedIn = status.signed_in; demo.hidden = signedIn;
    const soon = status.signed_in && status.seconds_left != null && status.seconds_left <= 300;
    // Event Atlas's sign-in button is the only sign-in control; it follows this poll.
    window.dispatchEvent(new CustomEvent("atlas:auth-status", {detail: {signed_in: !!status.signed_in, soon}}));
    banner.textContent = status.signed_in
      ? `✓ AWS Events: signed in${status.seconds_left == null ? "" : ` · ${Math.ceil(status.seconds_left / 60)} min left`}${soon ? " · sign in again soon with “再次登入”" : ""}${status.refreshable ? " · automatic refresh available" : ""}`
      : status.reason === "restarted" ? "The app restarted, please sign in again with “登入 AWS Events”."
      : "AWS Events: please sign in again with “登入 AWS Events”.";
    banner.className = status.signed_in && !soon ? "nc-ok" : "nc-warn";
    if (signedIn) briefing();
    if (scheduleError) { banner.append(document.createTextNode(" · Could not read your official schedule (" + scheduleError + ")")); banner.className = "nc-warn"; }
    if (!status.signed_in || !s?.signed_in) return;
    if (!lastPlan) { const box = bodies.day; box.replaceChildren(el("div", "nc-note", "Your official schedule (AWS Events GetSchedule). Ask Copilot to plan around it."), scheduleList("Reserved", s.reserved), scheduleList("Favorites", s.favorites)); }
    planChanged();  // official reservations and favorites are part of “我的安排”
  }
  loadOfficial();
  setInterval(() => loadOfficial(true), 60000);
})();
