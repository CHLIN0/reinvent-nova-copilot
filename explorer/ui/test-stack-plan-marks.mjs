import { test } from "node:test";
import assert from "node:assert/strict";
import { prepare } from "./src/model.mjs";

// Minimal DOM double for createStackCalendar: elements, class selectors, dialogs, events.
class Elem {
  constructor(tag) {
    Object.assign(this, {
      tag,
      className: "",
      children: [],
      parent: null,
      dataset: {},
      attrs: {},
      listeners: {},
      open: false,
      scrollTop: 0,
      scrollLeft: 0,
      tabIndex: -1,
    });
    this._text = "";
    this.style = { setProperty() {} };
  }
  get textContent() {
    return this._text + this.children.map((c) => c.textContent).join("");
  }
  set textContent(v) {
    this._text = String(v);
    this.children = [];
  }
  get classList() {
    const names = () => this.className.split(/\s+/).filter(Boolean);
    return {
      add: (...c) => {
        this.className = [...new Set([...names(), ...c])].join(" ");
      },
      remove: (...c) => {
        this.className = names()
          .filter((n) => !c.includes(n))
          .join(" ");
      },
      contains: (c) => names().includes(c),
    };
  }
  append(...nodes) {
    for (const n of nodes) {
      n.parent?.children.splice(n.parent.children.indexOf(n), 1);
      n.parent = this;
      this.children.push(n);
    }
  }
  replaceChildren(...nodes) {
    for (const c of this.children) c.parent = null;
    this.children = [];
    this.append(...nodes);
  }
  after(n) {
    const kids = this.parent.children;
    n.parent = this.parent;
    kids.splice(kids.indexOf(this) + 1, 0, n);
  }
  remove() {
    if (this.parent) {
      this.parent.children.splice(this.parent.children.indexOf(this), 1);
      this.parent = null;
    }
  }
  get isConnected() {
    let n = this;
    while (n.parent) n = n.parent;
    return n === globalThis.document.body;
  }
  contains(n) {
    for (; n; n = n.parent) if (n === this) return true;
    return false;
  }
  querySelectorAll(selector) {
    const cls = selector.replace(/^\./, "");
    const out = [];
    const walk = (n) => {
      for (const c of n.children) {
        if (c.classList.contains(cls)) out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  querySelector(selector) {
    return this.querySelectorAll(selector)[0] || null;
  }
  setAttribute(k, v) {
    this.attrs[k] = String(v);
  }
  getAttribute(k) {
    return this.attrs[k] ?? null;
  }
  addEventListener(type, fn) {
    (this.listeners[type] ||= []).push(fn);
  }
  fire(type) {
    for (const fn of this.listeners[type] || []) fn({ type, target: this });
  }
  click() {
    this.fire("click");
  }
  focus() {
    globalThis.document.activeElement = this;
  }
  showModal() {
    this.open = true;
  }
  close() {
    if (this.open) {
      this.open = false;
      this.fire("close");
    }
  }
}
globalThis.document = {
  body: new Elem("body"),
  activeElement: null,
  createElement: (tag) => new Elem(tag),
};
const { createStackCalendar } = await import("./src/calendar-stack.mjs");

const day = "2026-11-30";
const records = prepare(
  ["a", "b", "c"].map((id) => ({
    source: "aws_events_api",
    session_id: id,
    code: id.toUpperCase(),
    title: "Session " + id,
    start_local: `${day}T09:00:00-08:00`,
    end_local: `${day}T10:00:00-08:00`,
  })),
  [],
);
const planItem = (r, source) => ({
  placement: r.placement,
  key: r.key,
  session_id: r.session.session_id,
  source,
});
const card = (container) => container.querySelector(".atlas-stack-trigger");
const marks = (button) =>
  button
    .querySelectorAll(".atlas-stack-preview-title")
    .map((p) => p.textContent);
const summary = (button) =>
  button.querySelector(".atlas-stack-local-plan")?.textContent ?? null;

test("stacked cards show reserved/favorite/local marks and a group count", () => {
  const container = new Elem("div");
  const stack = createStackCalendar({ container });
  stack.update({
    records,
    days: [day],
    selection: null,
    plan: [planItem(records[0], "reserved"), planItem(records[2], "local")],
  });
  const button = card(container);
  assert.deepEqual(marks(button), ["✓ A · Session a", "B · Session b"]);
  assert.ok(
    button
      .querySelector(".atlas-stack-preview-title")
      .classList.contains("plan-reserved"),
  );
  assert.equal(summary(button), "✓ 官方已預約 1 · ● 已在本機安排 1"); // counts c, which has no preview line
});

test("a plan update while the comparison is open also updates the cards behind it", () => {
  const container = new Elem("div");
  document.body.append(container);
  const stack = createStackCalendar({ container });
  stack.update({ records, days: [day], selection: null, plan: [] });
  card(container).click(); // opens the comparison dialog for the 3-session group
  const dialog = document.body.querySelector(".atlas-stack-dialog");
  assert.ok(dialog?.open);
  stack.update({
    records,
    days: [day],
    selection: null,
    plan: [planItem(records[1], "favorite")],
  });
  assert.ok(dialog.open, "a plan refresh keeps the comparison open");
  assert.match(dialog.textContent, /官方收藏/);
  const button = card(container);
  assert.deepEqual(marks(button), ["A · Session a", "★ B · Session b"]);
  assert.equal(summary(button), "★ 官方收藏 1");
  dialog.close();
  assert.equal(
    summary(card(container)),
    "★ 官方收藏 1",
    "still current after the dialog closes",
  );
  stack.update({ records, days: [day], selection: null, plan: [] });
  assert.equal(summary(card(container)), null);
});
