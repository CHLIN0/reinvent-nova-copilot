// Runs the real web/copilot.js against a minimal fake DOM (offline, no browser) and checks that
// "Add these sessions to my Event Atlas plan" posts to /api/plan and tells Event Atlas to refresh
// through the `atlas:plan-changed` window event, without reloading the page.
// Usage: node tests/copilot_plan_event.mjs <path to web/copilot.js>   (prints a JSON report)
import { readFileSync } from "node:fs";

const created = [];
class Elem {
  constructor(tag) {
    Object.assign(this, { tag, className: "", textContent: "", value: "", children: [], dataset: {}, style: {}, listeners: {}, attrs: {} });
    created.push(this);
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  get childElementCount() { return this.children.length; }
  addEventListener(type, fn) { (this.listeners[type] ||= []).push(fn); }
  setAttribute(k, v) { this.attrs[k] = v; }
  get classList() { return { add: (c) => { this.className += " " + c; } }; }
  focus() {}
  fire(type) { for (const fn of this.listeners[type] || []) fn({ type, target: this, preventDefault() {} }); }
  click() { this.fire("click"); }
  requestSubmit() { this.fire("submit"); }
}

const calls = [];
const events = [];
globalThis.window = new EventTarget();
window.addEventListener("atlas:plan-changed", (e) => events.push(e.type));
globalThis.document = {
  body: new Elem("body"),
  createElement: (tag) => new Elem(tag),
  createTextNode: (text) => Object.assign(new Elem("#text"), { textContent: text }),
  querySelector: () => null,
  getElementById: () => null,
};
globalThis.setInterval = () => 0;
globalThis.location = { reload: () => events.push("page-reload") };
globalThis.fetch = async (url, init = {}) => {
  calls.push({ url, method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null });
  const reply = {
    "/api/my-schedule": { signed_in: false },
    "/api/chat": { text: "plan", trace: [], suggested: [], plan: { plan: { chosen: [{ id: "syn-0001", code: "SYN-AI101", title: "t", start: "", end: "" }] } } },
    "/api/plan": { version: 1, items: [], counts: { reserved: 0, favorite: 0, local: 1 }, changed: 1 },
  }[url];
  return { ok: !!reply, status: reply ? 200 : 404, json: async () => reply || { error: "not found" } };
};
const settle = () => new Promise((r) => setTimeout(r, 20));

new Function(readFileSync(process.argv[2], "utf8"))();
await settle();
const form = created.find((e) => e.className === "nc-form");
created.find((e) => e.tag === "textarea").value = "Plan my Monday";
form.requestSubmit();
await settle();
const add = created.find((e) => e.textContent === "Add these sessions to my Event Atlas plan");
add.click();
await settle();
const post = calls.find((c) => c.url === "/api/plan" && c.method === "POST");
const message = add && created[created.indexOf(add) + 1]?.textContent;
const tabs = created.find((e) => e.className === "nc-tabs").children.map((b) => b.textContent);
console.log(JSON.stringify({ post: post?.body ?? null, events, message, tabs }));
