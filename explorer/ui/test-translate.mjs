import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

// Exercise the real detail renderer without booting the calendar or a browser.
const app = await readFile(new URL("src/app.mjs", import.meta.url), "utf8");
const reader = app.slice(
  app.indexOf("async function renderReader("),
  app.indexOf("async function changePlan("),
);
function element(tag, className = "", text = "") {
  return {
    tag,
    className,
    textContent: text,
    children: [],
    dataset: {},
    attrs: {},
    hidden: false,
    append(...children) {
      this.children.push(...children);
    },
    replaceChildren(...children) {
      this.children = children;
    },
    setAttribute(key, value) {
      this.attrs[key] = value;
    },
  };
}
function setup(fetch) {
  const nodes = { reader: element("div"), "reader-panel": element("section") };
  const context = vm.createContext({
    readerVersion: 0,
    $: (id) => nodes[id],
    el: element,
    meta: {},
    fetch,
    encodeURIComponent,
    button: (label, onclick, cls) =>
      Object.assign(element("button", cls, label), { onclick }),
    planButtonText: () => "Plan",
    togglePlan() {},
    planToggleDisabled: () => false,
    timeText: () => "09:00",
    observationLabel: () => "today",
    sourceTimingNote: () => "",
  });
  const render = new vm.Script(`(${reader})`).runInContext(context);
  const record = (id) => ({
    levels: [],
    officialFacets: [],
    systemTopics: [],
    companies: [],
    session: {
      session_id: id,
      title: "Original title",
      abstract: "Original abstract",
      code: "TST101",
    },
  });
  const find = (predicate, node = nodes.reader) => {
    if (predicate(node)) return node;
    for (const child of node.children) {
      const found = find(predicate, child);
      if (found) return found;
    }
  };
  return { render: (id = "test session") => render(record(id)), find, nodes };
}
const reply = (data, ok = true) => ({ ok, json: async () => data });
const translation = (source = "nova") => ({
  title: "譯文標題",
  abstract: "譯文摘要",
  lang: "zh-Hant",
  source,
  cached: source === "cache",
});
const translateButton = (ui) =>
  ui.find((e) => e.textContent === "翻譯 / Translate");
const note = (ui) => ui.find((e) => e.className === "translation-note");
const output = (ui) => ui.find((e) => e.className === "session-translation");

test("translation is on demand, uses profile language, preserves originals, and shows cache provenance", async () => {
  const calls = [];
  const ui = setup(async (url) => {
    calls.push(url);
    return reply(
      url === "/api/profile"
        ? { fields: { language: "ja" } }
        : { ...translation(calls.length > 2 ? "cache" : "nova"), lang: "ja" },
    );
  });
  await ui.render();
  assert.equal(calls.length, 0);
  const button = translateButton(ui);
  const pending = button.onclick();
  assert.equal(button.disabled, true);
  assert.match(note(ui).textContent, /Translating/);
  await pending;
  assert.equal(button.disabled, false);
  assert.deepEqual(calls, [
    "/api/profile",
    "/api/translate/test%20session?lang=ja",
  ]);
  assert.ok(ui.find((e) => e.textContent === "Original title"));
  assert.ok(ui.find((e) => e.textContent === "Original abstract"));
  assert.equal(output(ui).hidden, false);
  assert.equal(output(ui).lang, "ja");
  assert.equal(output(ui).children[1].textContent, "譯文摘要");
  assert.match(note(ui).textContent, /unofficial translation \(Nova\)/);
  await button.onclick();
  assert.match(note(ui).textContent, /cached/);
});

test("empty profile defaults to zh-Hant and official output is labelled official", async () => {
  const calls = [];
  const ui = setup(async (url) => {
    calls.push(url);
    return reply(
      url === "/api/profile" ? { fields: {} } : translation("official"),
    );
  });
  await ui.render();
  await translateButton(ui).onclick();
  assert.ok(calls[1].endsWith("?lang=zh-Hant"));
  assert.match(note(ui).textContent, /Official translation/);
  assert.doesNotMatch(note(ui).textContent, /unofficial|Nova/);
});

test("failed requests keep originals and re-enable retry without exposing upstream text", async () => {
  const ui = setup(async (url) =>
    reply(
      url === "/api/profile"
        ? { fields: {} }
        : { error: "private upstream details" },
      url === "/api/profile",
    ),
  );
  await ui.render();
  await translateButton(ui).onclick();
  assert.match(note(ui).textContent, /please retry/);
  assert.doesNotMatch(note(ui).textContent, /private/);
  assert.equal(translateButton(ui).disabled, false);
  assert.equal(output(ui).hidden, true);
  assert.ok(ui.find((e) => e.textContent === "Original abstract"));
});

test("a delayed translation never overwrites a newly selected session", async () => {
  let resolve;
  const ui = setup(async (url) =>
    url === "/api/profile"
      ? reply({ fields: {} })
      : new Promise((r) => {
          resolve = r;
        }),
  );
  await ui.render("first");
  const pending = translateButton(ui).onclick();
  while (!resolve) await Promise.resolve();
  await ui.render("second");
  resolve(reply(translation()));
  await pending;
  assert.equal(output(ui).hidden, true);
  assert.doesNotMatch(note(ui).textContent, /unofficial/);
});
