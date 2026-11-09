// Nova Copilot panel injected into Event Atlas: AI advice + route planning + one-click "add to my Atlas plan".
(() => {
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const api = async (path, body) => {
    const r = await fetch(path, body === undefined ? {cache: "no-store"} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
    const j = await r.json(); if (!r.ok) throw new Error(j.error || r.status); return j;
  };
  const hhmm = iso => (iso || "").slice(11, 16);
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
  for (const [k, label] of [["chat", "Ask"]]) {
    const b = el("button", null, label); b.type = "button"; b.dataset.k = k; tabs.append(b);
    bodies[k] = el("div", "nc-body"); bodies[k].hidden = true;
  }
  const show = k => { for (const b of tabs.children) b.setAttribute("aria-selected", String(b.dataset.k === k)); for (const [n, d] of Object.entries(bodies)) d.hidden = n !== k; };
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

  panel.append(head, tabs, bodies.chat, form, opt);
  document.body.append(panel);
  const setOpen = open => {
    panel.hidden = !open; toggle.setAttribute("aria-pressed", String(open));
    document.body.classList.toggle("nc-docked", open);
    window.dispatchEvent(new Event("resize"));  // Atlas's calendar and map re-measure the narrower page
    if (open) { show("chat"); ta.focus(); }
  };
  toggle.addEventListener("click", () => setOpen(panel.hidden));
  close.addEventListener("click", () => setOpen(false));

  function traceBox(trace) {
    const d = el("details", "nc-trace"); d.append(el("summary", null, `${trace.length} tool call(s): ${trace.map(t => t.name).join(", ")}`));
    for (const t of trace) d.append(el("pre", null, `${t.ok ? "✓" : "✕"} ${t.name}${t.confirmed === false ? " (not confirmed, nothing saved)" : ""}\ninput: ${JSON.stringify(t.input)}\nresult: ${typeof t.result === "string" ? t.result : JSON.stringify(t.result)}`));
    return d;
  }

  // "My plan" (我的安排) lives on the server (/api/plan); Event Atlas re-reads it when told, no page reload.
  const planChanged = () => window.dispatchEvent(new Event("atlas:plan-changed"));
  function planButton(p, box) {
    const add = el("button", "nc-btn", "Add these sessions to my Event Atlas plan"); add.type = "button"; add.style.marginTop = "6px";
    const msg = el("div", "nc-note"); add.addEventListener("click", () => addToAtlas((p.plan || {}).chosen || [], msg)); box.append(add, msg);
  }
  async function addToAtlas(chosen, msg) {
    const ids = chosen.map(c => c.id).filter(id => typeof id === "string" && id);
    if (!ids.length) { msg.textContent = "No sessions to add."; return; }
    try {
      const r = await api("/api/plan", {action: "add", session_ids: ids});
      planChanged();
      msg.textContent = r.changed ? `Added ${r.changed} session(s) to “我的安排”.` : "These sessions are already in “我的安排”.";
    } catch (e) { msg.textContent = "Could not add to “我的安排”: " + e.message; }
  }

  // Suggested sessions with explicit RSVP / favorite buttons: the model proposes, the attendee clicks.
  function sessionCards(rows) {
    const box = el("div", "nc-cards");
    for (const s of rows) {
      const c = el("div", "nc-card");
      c.append(el("div", "nc-t", `${(s.start || "").slice(5, 10)} ${hhmm(s.start)}–${hhmm(s.end)}  ${s.code || ""}`), el("div", null, s.title || ""), el("div", "nc-sub", s.venue || ""));
      const row = el("div", "nc-actions"); const out = el("div", "nc-sub");
      for (const [label, path] of [["RSVP", "/api/rsvp"], ["☆ Favorite", "/api/favorite"]]) {
        const b = el("button", label === "RSVP" ? "nc-btn" : "nc-btn2", label); b.type = "button";
        b.addEventListener("click", async () => {
          if (label === "RSVP" && !confirm(`Reserve a seat for ${s.code || s.title} in your official AWS Events schedule?`)) return;
          b.disabled = true; out.textContent = "Sending to AWS Events…";
          try {
            const r = await api(path, {session_ids: [s.id]}); const it = (r.results || [])[0] || {};
            const inSched = it.in_schedule_reserved ?? it.in_schedule_favorites;
            out.textContent = it.ok && inSched ? `✓ Done and verified in your official schedule (${label === "RSVP" ? "reserved" : "favorites"}).`
              : it.ok ? "Accepted, but not yet visible in your schedule read-back. Check the AWS Events app."
              : `Not done: ${it.code || "rejected"}${it.conflicts_with ? " (conflicts with " + it.conflicts_with.join(", ") + ")" : ""}.`;
            if (it.ok) loadOfficial();
          } catch (e) { out.textContent = "Not done: " + e.message + (/sign_in/.test(e.message) ? " Sign in to AWS Events first." : ""); b.disabled = false; }
        });
        row.append(b);
      }
      c.append(row, out); box.append(c);
    }
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
      const cd = r.catalog_diff, n = (k, word) => `${k} ${word}${k === 1 ? "" : "s"}`;
      const catalog = cd ? [cd.new && n(cd.new, "new session"), cd.moved.length && n(cd.moved.length, "reservation") + " moved",
        cd.cancelled.length && n(cd.cancelled.length, "reservation") + " cancelled"].filter(Boolean).join(", ") : "";
      const since = [r.schedule_diff && ["reserved", "favorites"].map(k => `${k} +${r.schedule_diff[k].added.length}/−${r.schedule_diff[k].removed.length}`).join(", "), catalog].filter(Boolean);
      const head = r.first_visit ? "Welcome! " : since.length ? "Since your last visit: " + since.join("; ") + "\n\n" : "";
      for (const box of [a, b].filter(Boolean)) {
        box.textContent = head + r.text; if (r.trace.length) box.append(traceBox(r.trace));
        if ((r.suggested || []).length) box.append(sessionCards(r.suggested));
        if (r.plan) planButton(r.plan, box);
      }
    } catch (e) { for (const box of [a, b].filter(Boolean)) box.textContent = "Briefing unavailable: " + e.message; }
  }

  async function send(text) {
    show("chat"); const q = el("div", "nc-msg nc-user", text); const a = el("div", "nc-msg nc-bot", "Nova Pro is checking the catalog and routes…");
    log.append(q, a); log.scrollTop = log.scrollHeight; sendBtn.disabled = true;
    try {
      const r = await api("/api/chat", {message: text, allow_write: allow.checked});
      a.textContent = r.text; if (r.trace.length) a.append(traceBox(r.trace));
      if ((r.suggested || []).length) a.append(sessionCards(r.suggested));
      if (r.plan) planButton(r.plan, a);
    } catch (e) { a.textContent = "Error: " + e.message; a.classList.add("nc-err"); }
    allow.checked = false; sendBtn.disabled = false; log.scrollTop = log.scrollHeight;
  }
  form.addEventListener("submit", e => { e.preventDefault(); const v = ta.value.trim(); if (v) { ta.value = ""; send(v); } });
  ta.addEventListener("keydown", e => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); } });

  // Official schedule: proves the sign-in is real (data comes from AWS Events GetSchedule) and shows RSVPs in Atlas.
  const banner = el("div"); banner.id = "nc-banner"; document.body.append(banner);
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
    planChanged();  // official reservations and favorites are part of “我的安排”
  }
  loadOfficial();
  setInterval(() => loadOfficial(true), 60000);
})();
