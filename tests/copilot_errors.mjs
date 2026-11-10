// Row B3: the Copilot panel shows the server's plain error sentence, never a bare code or exception text.
// Runs the shipped web/copilot.js with a fake DOM: `node tests/copilot_errors.mjs`.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { runInNewContext } from "node:vm";

const source = readFileSync(new URL("../web/copilot.js", import.meta.url), "utf8");
const UNAVAILABLE = { error: "model_unavailable",
  message: "Nova is unavailable right now. Your plan and the official schedule are unaffected; try again shortly." };

async function page(failures) {
  const created = [];
  class Elem {
    constructor(tag) {
      Object.assign(this, { tag, className: "", text: "", value: "", children: [], dataset: {}, style: {}, listeners: {} });
      this.classList = { add: c => { this.className += " " + c; }, toggle() {} };
      created.push(this);
    }
    append(...nodes) { this.children.push(...nodes); }
    replaceChildren(...nodes) { this.children = nodes; }
    get textContent() { return (this.text || "") + this.children.map(e => e.textContent).join(""); }
    set textContent(value) { this.text = value; this.children = []; }
    setAttribute() {}
    addEventListener(type, fn) { this.listeners[type] = fn; }
    requestSubmit() { this.listeners.submit({ preventDefault() {} }); }
    focus() {}
  }
  const slots = { "copilot-toggle": new Elem("button"), "mine-briefing": Object.assign(new Elem("div"), { hidden: true }) };
  const body = new Elem("body");
  body.classList = { toggle() {} };
  runInNewContext(source, {
    document: { body, createElement: tag => new Elem(tag), getElementById: id => slots[id] || null,
      createTextNode: text => Object.assign(new Elem("#text"), { textContent: text }), querySelector: () => null },
    window: { addEventListener() {}, dispatchEvent() {} }, Event, CustomEvent, Date,
    location: { assign() {} }, setInterval() {}, confirm: () => true,
    fetch: async url => {
      if (failures[url]) return { ok: false, status: failures[url].status, json: async () => failures[url].body };
      const data = { "/api/status": { signed_in: true, seconds_left: 3600, refreshable: true },
        "/api/my-schedule": { signed_in: true, reserved: [], favorites: [] },
        "/api/plan": { version: 1, items: [], official: { status: "live" } } }[url];
      assert.ok(data, `Unexpected request: ${url}`);
      return { ok: true, status: 200, json: async () => data };
    },
  });
  const settle = () => new Promise(resolve => setImmediate(resolve));
  await settle();
  return { created, settle };
}

// The welcome briefing fails: both briefing boxes carry the sentence.
{
  const { created, settle } = await page({ "/api/briefing": { status: 503, body: UNAVAILABLE } });
  await settle();
  const boxes = created.filter(e => e.textContent.startsWith("Briefing unavailable"));
  assert.ok(boxes.length >= 1, "a briefing box reports the failure");
  for (const box of boxes) assert.equal(box.textContent, "Briefing unavailable: " + UNAVAILABLE.message);
}

// A chat question fails: the answer bubble shows the sentence, not the code.
{
  const signinExpired = { error: "signin_expired",
    message: "Your AWS Events sign-in has expired. Sign in again from the top of the page." };
  const { created, settle } = await page({ "/api/briefing": { status: 503, body: UNAVAILABLE },
    "/api/chat": { status: 401, body: signinExpired } });
  const textarea = created.find(e => e.tag === "textarea");
  const form = created.find(e => e.tag === "form");
  textarea.value = "What should I attend on Tuesday?";
  form.requestSubmit();
  await settle(); await settle();
  const answer = created.find(e => e.className.includes("nc-err"));
  assert.ok(answer, "the failed answer is marked as an error");
  assert.equal(answer.textContent, "Error: " + signinExpired.message);
  assert.ok(!answer.textContent.includes("signin_expired"));
}

// An error without a sentence still shows its code (fallback).
{
  const { created, settle } = await page({ "/api/briefing": { status: 500, body: { error: "server_error" } } });
  await settle();
  assert.ok(created.some(e => e.textContent === "Briefing unavailable: server_error"));
}

console.log("copilot_errors: ok");
