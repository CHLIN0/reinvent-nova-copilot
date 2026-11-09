// Runs the real web/copilot.js against a minimal fake DOM (offline) and checks the suggested session cards:
// a reserved session shows its reserved state and a cancel action, never RSVP; a favorited one shows its
// favorited state; seat words; the confirms name code, title and time; results read in plain words.
// Usage: node tests/copilot_rsvp_cards.mjs <path to web/copilot.js>
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const created = [];
class Elem {
  constructor(tag) {
    Object.assign(this, { tag, className: "", textContent: "", value: "", children: [], dataset: {}, style: {}, listeners: {}, attrs: {}, disabled: false });
    created.push(this);
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  get childElementCount() { return this.children.length; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  setAttribute(k, v) { this.attrs[k] = v; }
  get classList() { return { add: (c) => { this.className += " " + c; }, toggle() {} }; }
  focus() {}
  fire(type) { for (const fn of this.listeners[type] || []) fn({ type, target: this, preventDefault() {} }); }
  click() { this.fire("click"); }
  requestSubmit() { this.fire("submit"); }
}
const texts = (node) => [node.textContent, ...node.children.flatMap(texts)];
const buttons = (node) => [...(node.tag === "button" ? [node] : []), ...node.children.flatMap(buttons)];

const S = (id, code, seats) => ({ id, code, title: "Title " + code, start: "2026-12-02T10:00:00-08:00", end: "2026-12-02T11:00:00-08:00", venue: "venetian", seats });
const suggested = [S("r1", "SYN-RES1", "limited"), S("f1", "SYN-FAV1", "walkUp"), S("n1", "SYN-NEW1", ""), S("n2", "SYN-NEW2", "available")];
const planItem = (id, code, source) => ({ session_id: id, code, source });
let reserved = ["r1", "x9"];
const calls = [];
const asked = [];
const results = {
  "/api/rsvp/cancel": () => { reserved = reserved.filter((i) => i !== "r1"); return { results: [{ session_id: "r1", ok: true, in_schedule_reserved: false }], verified: true }; },
  "/api/rsvp": () => ({ results: [{ session_id: "n1", ok: false, code: "scheduleConflict", conflicts_with: ["x9", "zz"], in_schedule_reserved: false }], verified: true }),
  "/api/favorite": () => ({ results: [{ session_id: "n2", ok: false, code: "brandNewCode", in_schedule_favorites: false }], verified: true }),
};

globalThis.window = new EventTarget();
globalThis.document = {
  body: new Elem("body"),
  createElement: (tag) => new Elem(tag),
  createTextNode: (text) => Object.assign(new Elem("#text"), { textContent: text }),
  querySelector: () => null,
  getElementById: () => null,
};
globalThis.setInterval = () => 0;
globalThis.confirm = (text) => { asked.push(text); return true; };
globalThis.fetch = async (url, init = {}) => {
  const method = init.method || "GET";
  calls.push({ url, method, body: init.body ? JSON.parse(init.body) : null });
  const reply = method === "POST" && results[url] ? results[url]()
    : {
      "/api/status": { signed_in: false },
      "/api/chat": { text: "Try these.", trace: [], suggested, plan: null },
      "/api/plan": { version: 1, official: { status: "live" }, items: [
        ...reserved.map((i) => planItem(i, i === "x9" ? "SYN-KEY02" : "SYN-RES1", "reserved")),
        planItem("f1", "SYN-FAV1", "favorite"), planItem("n2", "SYN-NEW2", "local")] },
    }[url];
  return { ok: !!reply, status: reply ? 200 : 404, json: async () => reply || { error: "not found" } };
};
const settle = () => new Promise((r) => setTimeout(r, 20));

new Function(readFileSync(process.argv[2], "utf8"))();
await settle();
created.find((e) => e.tag === "textarea").value = "Suggest sessions";
created.find((e) => e.className === "nc-form").requestSubmit();
await settle();
const cards = created.filter((e) => e.className === "nc-card");
assert.equal(cards.length, 4);
const card = (code) => cards.find((c) => texts(c).some((t) => t.includes(code)));
const labels = (c) => buttons(c).map((b) => b.textContent);

// Reserved: reserved state + cancel, never RSVP. Favorited: favorited state, RSVP only. Local pick: plain buttons.
assert.deepEqual(labels(card("SYN-RES1")), ["Cancel reservation"]);
assert.ok(texts(card("SYN-RES1")).includes("✓ Reserved in your official schedule"));
assert.deepEqual(labels(card("SYN-FAV1")), ["RSVP"]);
assert.ok(texts(card("SYN-FAV1")).includes("★ In your official favorites"));
assert.deepEqual(labels(card("SYN-NEW1")), ["RSVP", "☆ Favorite"]);
assert.deepEqual(labels(card("SYN-NEW2")), ["RSVP", "☆ Favorite"]);
// Seat words; nothing when the field is empty.
assert.ok(texts(card("SYN-RES1")).includes("Limited seats"));
assert.ok(texts(card("SYN-FAV1")).includes("Walk-up only, no reservation"));
assert.ok(texts(card("SYN-NEW2")).includes("Seats available"));
assert.ok(!texts(card("SYN-NEW1")).some((t) => /seat|Full|Walk-up/i.test(t)));

// Cancel: confirm names code, title and time; POST; read-back line; the card re-reads the plan.
buttons(card("SYN-RES1"))[0].click();
await settle();
assert.match(asked[0], /Cancel your official reservation for SYN-RES1 “Title SYN-RES1” \(12-02 10:00–11:00\)/);
assert.deepEqual(calls.find((c) => c.url === "/api/rsvp/cancel").body, { session_ids: ["r1"] });
assert.ok(texts(card("SYN-RES1")).includes("✓ Cancelled and verified in your official schedule (no longer reserved)."));
assert.deepEqual(labels(card("SYN-RES1")), ["RSVP", "☆ Favorite"]);

// A change made elsewhere (Event Atlas's cancel, or a re-reserve) reaches the cards through the plan event.
reserved = ["r1", "x9"];
const reads = calls.filter((c) => c.url === "/api/plan").length;
window.dispatchEvent(new Event("atlas:plan-changed"));
await settle();
assert.deepEqual(labels(card("SYN-RES1")), ["Cancel reservation"]);
assert.equal(calls.filter((c) => c.url === "/api/plan").length, reads + 1);  // one read serves every card set

// RSVP: confirm names the session; a conflict reads in words with the conflicting session codes.
buttons(card("SYN-NEW1"))[0].click();
await settle();
assert.match(asked[1], /Reserve a seat for SYN-NEW1 “Title SYN-NEW1” \(12-02 10:00–11:00\)/);
assert.ok(texts(card("SYN-NEW1")).includes("Not done: It overlaps a session already on your schedule (SYN-KEY02, zz)."));

// An unknown code shows verbatim plus "see AWS Events".
buttons(card("SYN-NEW2"))[1].click();
await settle();
assert.ok(texts(card("SYN-NEW2")).includes("Not done: AWS Events refused it (code: brandNewCode); see AWS Events."));
assert.equal(asked.length, 2);  // favorites are cheap and reversible: no extra confirm
console.log("copilot rsvp checks passed");
