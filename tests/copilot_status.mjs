// Execute the shipped Copilot script with an offline DOM and deterministic timers.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync(process.argv[2], "utf8");
const { status: threeMinutes, sign_in: signInResponse } = JSON.parse(readFileSync(0, "utf8"));
async function page(initial, { scheduleFails = false } = {}) {
  const created = [], timers = [], calls = [];
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
  }
  runInNewContext(source, {
    document: { body: new Elem("body"), createElement: tag => new Elem(tag),
      createTextNode: text => Object.assign(new Elem("#text"), { textContent: text }), querySelector: () => null },
    window: { dispatchEvent() {} }, Event, Date,
    location: { assign: url => { assigned = url; } },
    setInterval: (fn, ms) => timers.push({ fn, ms }),
    fetch: async (url, init = {}) => {
      calls.push({ url, init });
      if (url === "/api/my-schedule" && scheduleFails) throw Error("schedule_unavailable");
      const data = { "/api/status": status,
        "/api/my-schedule": { signed_in: true, reserved: [], favorites: [] },
        "/api/auth/start": signInResponse }[url];
      assert.ok(data, `Unexpected request: ${url}`);
      return { ok: true, json: async () => data };
    },
  });
  await new Promise(resolve => setImmediate(resolve));
  return { banner: created.find(e => e.id === "nc-banner"), calls, timers,
    assigned: () => assigned, setStatus: value => { status = value; } };
}

const warning = await page(threeMinutes);
assert.match(warning.banner.textContent, /signed in · 3 min left · sign in again soon/);
assert.equal(warning.banner.className, "nc-warn");
const button = warning.banner.children.find(e => e.tag === "button");
assert.ok(button);
assert.equal(warning.calls.filter(c => c.url === "/api/auth/start").length, 0);
await button.listeners.click();
assert.equal(warning.assigned(), "https://example.invalid/signin");
assert.equal(warning.calls.at(-1).url, "/api/auth/start");
assert.equal(warning.calls.at(-1).init.method, "POST");

for (const seconds of [300, 0]) {
  const p = await page({ ...threeMinutes, seconds_left: seconds, refreshable: true });
  assert.match(p.banner.textContent, /sign in again soon/);
  assert.match(p.banner.textContent, /automatic refresh available/);
  assert.ok(p.banner.children.find(e => e.tag === "button"));
}
const healthy = await page({ ...threeMinutes, seconds_left: 2520 });
assert.match(healthy.banner.textContent, /signed in · 42 min left/);
assert.equal(healthy.banner.className, "nc-ok");
assert.equal(healthy.banner.children.filter(e => e.tag === "button").length, 0);
assert.equal(healthy.timers.length, 1);
assert.equal(healthy.timers[0].ms, 60000);
const before = healthy.calls.length;
healthy.setStatus(threeMinutes);
await healthy.timers[0].fn();
assert.match(healthy.banner.textContent, /sign in again soon/);
assert.equal(healthy.calls.length, before + 1);
assert.equal(healthy.calls.at(-1).url, "/api/status");
healthy.setStatus({ signed_in: false, reason: "restarted", seconds_left: null });
await healthy.timers[0].fn();
assert.match(healthy.banner.textContent, /app restarted, please sign in again/);
assert.doesNotMatch(healthy.banner.textContent, /demo/);
const restarted = await page({ signed_in: false, reason: "restarted", seconds_left: null });
assert.deepEqual(restarted.calls.map(c => c.url), ["/api/status"]);
const expired = await page({ signed_in: false, reason: "sign_in_required", seconds_left: null });
assert.match(expired.banner.textContent, /please sign in again/);
assert.doesNotMatch(expired.banner.textContent, /restarted/);
const failed = await page(threeMinutes, { scheduleFails: true });
assert.match(failed.banner.textContent, /sign in again soon/);
assert.match(failed.banner.textContent, /Could not read your official schedule/);
console.log("banner status checks passed");
