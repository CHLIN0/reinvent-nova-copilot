import { test } from "node:test";
import assert from "node:assert/strict";
import { createPlanStore } from "./src/plan-store.mjs";

const item = (id, source = "local") => ({
  placement: JSON.stringify(["aws_events_api", id, null, null]),
  key: JSON.stringify(["aws_events_api", id]),
  session_id: id,
  code: id,
  title: "Session " + id,
  start: "",
  end: "",
  location: "",
  addedAt: "",
  source,
});

function fakeServer(initial = []) {
  const calls = [];
  let items = initial;
  const fetch = async (url, init = {}) => {
    calls.push({ url, init });
    if (init.method === "POST") {
      const body = JSON.parse(init.body);
      if (body.action === "add") items = [...items, item(body.session_id)];
      else items = items.filter((p) => p.session_id !== body.session_id);
    }
    return {
      ok: true,
      json: async () => ({ items, official: { status: "live" } }),
    };
  };
  return { fetch, calls };
}

test("load reads the plan from the server, no browser storage", async () => {
  const server = fakeServer([
    item("a", "reserved"),
    item("b", "favorite"),
    item("c"),
  ]);
  const store = createPlanStore({ fetch: server.fetch });
  const items = await store.load();
  assert.deepEqual(
    items.map((p) => p.source),
    ["reserved", "favorite", "local"],
  );
  assert.equal(server.calls[0].url, "/api/plan");
  assert.equal(server.calls[0].init.cache, "no-store");
  assert.deepEqual(store.official, { status: "live" });
});

test("add and remove post the session id and return the server's plan", async () => {
  const server = fakeServer();
  const store = createPlanStore({ fetch: server.fetch });
  assert.equal((await store.add(item("x"))).length, 1);
  assert.deepEqual(JSON.parse(server.calls[0].init.body), {
    action: "add",
    session_id: "x",
  });
  assert.equal((await store.update(item("x"), "remove")).length, 0);
  assert.deepEqual(JSON.parse(server.calls[1].init.body), {
    action: "remove",
    session_id: "x",
  });
});

test("unknown action and missing session id are rejected before any request", async () => {
  const server = fakeServer();
  const store = createPlanStore({ fetch: server.fetch });
  await assert.rejects(store.update(item("x"), "toggle"));
  await assert.rejects(store.add({ placement: "p" }));
  assert.equal(server.calls.length, 0);
});

test("server errors and malformed items surface as one plain message", async () => {
  const failing = createPlanStore({
    fetch: async () => ({
      ok: false,
      json: async () => ({
        error: "session id(s) not in the loaded catalog: ['z']",
      }),
    }),
  });
  await assert.rejects(failing.load(), /not in the loaded catalog/);
  const offline = createPlanStore({
    fetch: async () => {
      throw TypeError("network");
    },
  });
  await assert.rejects(offline.load(), /我的安排/);
  const malformed = createPlanStore({
    fetch: async () => ({
      ok: true,
      json: async () => ({ items: [{ ...item("a"), source: "other" }] }),
    }),
  });
  await assert.rejects(malformed.load(), /我的安排/);
});

test("Copilot's event makes Atlas re-read the server plan and apply it", async () => {
  const { watchPlan, PLAN_CHANGED } = await import("./src/plan-store.mjs");
  assert.equal(PLAN_CHANGED, "atlas:plan-changed"); // the name web/copilot.js dispatches
  const server = fakeServer([item("a", "reserved")]);
  const store = createPlanStore({ fetch: server.fetch });
  const target = new EventTarget();
  const applied = [];
  watchPlan({ store, target, doc: { visibilityState: "visible" }, onPlan: (items) => applied.push(items.map((p) => p.session_id)), onError: assert.fail });
  await store.add(item("b")); // Copilot's POST, then its event
  target.dispatchEvent(new Event(PLAN_CHANGED));
  await new Promise((r) => setTimeout(r, 10));
  assert.deepEqual(applied, [["a", "b"]]);
  assert.deepEqual(server.calls.map((c) => c.init.method || "GET"), ["POST", "GET"]);
  target.dispatchEvent(new Event("visibilitychange"));
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(applied.length, 2);
});

test("a slower, older plan read never overwrites a newer one", async () => {
  const { watchPlan } = await import("./src/plan-store.mjs");
  const replies = [];
  const store = { official: null, load: () => new Promise((resolve) => replies.push(resolve)) };
  const applied = [];
  const refresh = watchPlan({ store, target: new EventTarget(), onPlan: (items) => applied.push(items), onError: assert.fail });
  const first = refresh(), second = refresh();
  replies[1](["new"]);
  replies[0](["old"]);
  await Promise.all([first, second]);
  assert.deepEqual(applied, [["new"]]);
});

test("a server error code becomes the plain sentence", async () => {
  const fetch = async () => ({
    ok: false,
    json: async () => ({ error: "model_unavailable", message: "Nova is unavailable right now." }),
  });
  await assert.rejects(createPlanStore({ fetch }).load(), {
    message: "Nova 暫時無法使用；你的安排與官方行程不受影響，請稍後再試。",
  });
});
