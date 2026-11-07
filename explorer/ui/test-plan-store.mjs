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
