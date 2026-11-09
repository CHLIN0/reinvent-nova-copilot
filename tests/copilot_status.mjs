// Execute the shipped Copilot script with an offline DOM and deterministic timers.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync(process.argv[2] ?? new URL("../web/copilot.js", import.meta.url), "utf8");
const { status: threeMinutes, sign_in: signInResponse } = process.argv[2]
  ? JSON.parse(readFileSync(0, "utf8"))
  : { status: { signed_in: true, seconds_left: 180, refreshable: false },
    sign_in: { authorization_url: "https://example.invalid/signin" } };
async function page(initial, { scheduleFails = false, briefing = { text: "Offline welcome briefing", trace: [] } } = {}) {
  const created = [], timers = [], calls = [], announced = [];
  let status = initial, assigned;
  class Elem {
    constructor(tag) {
      Object.assign(this, { tag, className: "", textContent: "", children: [], dataset: {}, style: {}, listeners: {} });
      created.push(this);
    }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; }
    get textContent() { return (this.text || "") + this.children.map(e => e.textContent).join(""); }
    set textContent(value) { this.text = value; this.children = []; }
    setAttribute() {}
    addEventListener(type, fn) { this.listeners[type] = fn; }
    focus() {}
  }
  // The Event Atlas page provides the header toggle and the My re:Invent briefing slot.
  const slots = { "copilot-toggle": new Elem("button"), "mine-briefing": Object.assign(new Elem("div"), { hidden: true }) };
  const body = new Elem("body"); const bodyClasses = new Set();
  body.classList = { toggle: (c, on) => (on ? bodyClasses.add(c) : bodyClasses.delete(c)) };
  runInNewContext(source, {
    document: { body, createElement: tag => new Elem(tag), getElementById: id => slots[id] || null,
      createTextNode: text => Object.assign(new Elem("#text"), { textContent: text }), querySelector: () => null },
    window: { dispatchEvent(e) { if (e.type === "atlas:auth-status") announced.push({ ...e.detail }); } }, Event, CustomEvent, Date,
    location: { assign: url => { assigned = url; } },
    setInterval: (fn, ms) => timers.push({ fn, ms }),
    fetch: async (url, init = {}) => {
      calls.push({ url, init });
      if (url === "/api/my-schedule" && scheduleFails) throw Error("schedule_unavailable");
      const data = { "/api/status": status,
        "/api/my-schedule": { signed_in: true, reserved: [], favorites: [] },
        "/api/briefing": briefing,
        "/api/auth/start": signInResponse }[url];
      assert.ok(data, `Unexpected request: ${url}`);
      return { ok: true, json: async () => data };
    },
  });
  await new Promise(resolve => setImmediate(resolve));
  return { banner: created.find(e => e.id === "nc-banner"), calls, timers, page: slots, bodyClasses, announced,
    panel: created.find(e => e.id === "nc-panel"), demo: created.find(e => e.className === "nc-note nc-demo"),
    open: async () => {
      slots["copilot-toggle"].listeners.click();
      await new Promise(resolve => setImmediate(resolve));
    },
    assigned: () => assigned, setStatus: value => { status = value; } };
}

const warning = await page(threeMinutes);
assert.equal(warning.calls.filter(c => c.url === "/api/briefing").length, 1,
  "Signed in, the briefing is requested once on page load, without opening the panel");
assert.equal(warning.page["mine-briefing"].hidden, false);
assert.match(warning.page["mine-briefing"].textContent, /Offline welcome briefing/);
assert.equal(warning.demo.hidden, true);
assert.equal(warning.page["copilot-toggle"].hidden, false);
assert.equal(warning.panel.hidden, true);
assert.match(warning.banner.textContent, /signed in · 3 min left · sign in again soon/);
assert.equal(warning.banner.className, "nc-warn");
await warning.open();
assert.equal(warning.panel.hidden, false, "The header toggle opens the docked panel");
assert.ok(warning.bodyClasses.has("nc-docked"));
assert.equal(warning.calls.filter(c => c.url === "/api/briefing").length, 1,
  "Opening Copilot with three minutes left must not request a second briefing");
assert.equal(warning.banner.className, "nc-warn");
await warning.open();
assert.equal(warning.panel.hidden, true, "The same toggle closes it");
assert.ok(!warning.bodyClasses.has("nc-docked"));
assert.equal(warning.calls.filter(c => c.url === "/api/briefing").length, 1);
// One sign-in control (Codex T3 finding 3): the banner never has its own button; it tells Event Atlas,
// whose "再次登入" / "登入 AWS Events" button follows every poll.
assert.equal(warning.banner.children.filter(e => e.tag === "button").length, 0);
assert.match(warning.banner.textContent, /“再次登入”/);
assert.deepEqual(warning.announced.at(-1), { signed_in: true, soon: true });
assert.equal(warning.calls.filter(c => c.url === "/api/auth/start").length, 0);

for (const seconds of [300, 0]) {
  const p = await page({ ...threeMinutes, seconds_left: seconds, refreshable: true });
  assert.match(p.banner.textContent, /sign in again soon/);
  assert.match(p.banner.textContent, /automatic refresh available/);
  assert.equal(p.banner.children.filter(e => e.tag === "button").length, 0);
  assert.deepEqual(p.announced.at(-1), { signed_in: true, soon: true });
}
const healthy = await page({ ...threeMinutes, seconds_left: 2520 });
assert.match(healthy.banner.textContent, /signed in · 42 min left/);
assert.equal(healthy.banner.className, "nc-ok");
assert.equal(healthy.banner.children.filter(e => e.tag === "button").length, 0);
assert.deepEqual(healthy.announced.at(-1), { signed_in: true, soon: false });
await healthy.open();
assert.equal(healthy.calls.filter(c => c.url === "/api/briefing").length, 1);
assert.equal(healthy.timers.length, 1);
assert.equal(healthy.timers[0].ms, 60000);
const before = healthy.calls.length;
healthy.setStatus(threeMinutes);
await healthy.timers[0].fn();
assert.match(healthy.banner.textContent, /sign in again soon/);
assert.deepEqual(healthy.announced.at(-1), { signed_in: true, soon: true }, "the 60 s poll announces too");
assert.equal(healthy.calls.length, before + 1);
assert.equal(healthy.calls.at(-1).url, "/api/status");
healthy.setStatus({ signed_in: false, reason: "restarted", seconds_left: null });
await healthy.timers[0].fn();
assert.match(healthy.banner.textContent, /app restarted, please sign in again/);
assert.deepEqual(healthy.announced.at(-1), { signed_in: false, soon: false },
  "expiry after the warning still reaches Atlas, which re-enables its sign-in button");
assert.doesNotMatch(healthy.banner.textContent, /demo/);
const restarted = await page({ signed_in: false, reason: "restarted", seconds_left: null });
assert.equal(restarted.banner.children.filter(e => e.tag === "button").length, 0,
  "Signed out, Event Atlas's sign-in button is the only sign-in control");
assert.equal(restarted.demo.hidden, false, "Signed out, the panel says Copilot answers from demo data");
assert.equal(restarted.page["mine-briefing"].hidden, true);
await restarted.open();
assert.deepEqual(restarted.calls.map(c => c.url), ["/api/status"]);
const expired = await page({ signed_in: false, reason: "sign_in_required", seconds_left: null });
assert.match(expired.banner.textContent, /please sign in again/);
assert.doesNotMatch(expired.banner.textContent, /restarted/);
assert.equal(expired.banner.children.filter(e => e.tag === "button").length, 0);
await expired.open();
assert.equal(expired.calls.filter(c => c.url === "/api/briefing").length, 0);
const failed = await page(threeMinutes, { scheduleFails: true });
assert.match(failed.banner.textContent, /sign in again soon/);
assert.match(failed.banner.textContent, /Could not read your official schedule/);
await failed.open();
assert.equal(failed.calls.filter(c => c.url === "/api/briefing").length, 1);
// T6: the briefing head adds one clause for catalog changes since the last visit.
const changed = await page(threeMinutes, { briefing: { text: "Offline welcome briefing", trace: [],
  schedule_diff: { reserved: { added: [], removed: [] }, favorites: { added: [], removed: [] } },
  catalog_diff: { new: 2, moved: [{ id: "syn-0007", code: "SYN-AI407" }], cancelled: [], recommended: ["SYN-SEC999"] } } });
assert.match(changed.page["mine-briefing"].textContent,
  /Since your last visit: reserved \+0\/−0, favorites \+0\/−0; 2 new sessions, 1 reservation moved\n\nOffline welcome briefing/);
console.log("banner status checks passed");
