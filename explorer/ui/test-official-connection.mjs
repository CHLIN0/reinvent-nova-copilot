import { test } from "node:test";
import assert from "node:assert/strict";
import {
  createOfficialConnection,
  connectionCopy,
  catalogFailureMessage,
  safeConnectionError,
  sourceTimingNote,
} from "./src/official-connection.mjs";

const status = (extra = {}) => ({
  provider: "aws_events_api",
  connected: false,
  callback_available: true,
  pending_sign_in: false,
  error: null,
  ...extra,
});
const response = (data, ok = true) => ({ ok, json: async () => data });

test("concurrent status callers share one request and load only on connection transitions", async () => {
  let requests = 0,
    loads = 0,
    resolve;
  const controller = createOfficialConnection({
    request: () => {
      requests++;
      return new Promise((done) => {
        resolve = done;
      });
    },
    onConnected: async () => {
      loads++;
    },
  });
  const a = controller.refresh(),
    b = controller.refresh();
  assert.equal(a, b);
  resolve(response(status({ connected: true })));
  await a;
  assert.equal(requests, 1);
  assert.equal(loads, 1);
  const c = controller.refresh();
  resolve(response(status({ connected: true })));
  await c;
  assert.equal(loads, 1);
  controller.stop();
});

test("pending polling waits for each response and stops after connection", async () => {
  let poll,
    loads = 0,
    scheduled = 0;
  const replies = [
    status({ pending_sign_in: true }),
    status({ connected: true }),
  ];
  const controller = createOfficialConnection({
    request: async () => response(replies.shift()),
    schedule(fn, ms) {
      assert.equal(ms, 3000);
      scheduled++;
      poll = fn;
      return scheduled;
    },
    cancel() {},
    onConnected: () => {
      loads++;
    },
  });
  await controller.refresh();
  assert.equal(scheduled, 1);
  poll();
  await controller.refresh();
  assert.equal(loads, 1);
  assert.equal(scheduled, 1);
  controller.stop();
});

test("explicit auth start is single-flight and never emits or persists its URL", async () => {
  let resolve,
    calls = 0;
  const observations = [];
  const controller = createOfficialConnection({
    request: async (url, options) => {
      calls++;
      assert.equal(url, "/api/auth/start");
      assert.equal(options.method, "POST");
      assert.equal(options.body, "{}");
      return new Promise((done) => {
        resolve = done;
      });
    },
    onChange: (s) => observations.push(JSON.stringify(s)),
    schedule: () => 1,
    cancel() {},
  });
  const first = controller.start();
  assert.equal(await controller.start(), null);
  const url =
    "https://signin.aws.amazon.com/authorize?state=private-test-state";
  resolve(response({ authorization_url: url }));
  assert.equal(await first, url);
  assert.equal(calls, 1);
  assert.ok(observations.every((s) => !s.includes("private-test-state")));
  controller.stop();
});

test("unsafe redirect and arbitrary server error text cannot become UI copy", async () => {
  for (const authorization_url of [
    "http://example.com/",
    "javascript:alert(1)",
    "https://user:password@example.com/",
  ]) {
    const controller = createOfficialConnection({
      request: async () => response({ authorization_url }),
    });
    assert.equal(await controller.start(), null);
    assert.equal(controller.snapshot().error, "connection_unavailable");
    controller.stop();
  }
  assert.equal(safeConnectionError("secret-payload"), "connection_unavailable");
  assert.ok(
    !catalogFailureMessage("secret-payload").includes("secret-payload"),
  );
});

test("catalog auth failure restores sign-in action without altering local plans", async () => {
  const controller = createOfficialConnection({
    request: async () => response(status({ connected: true })),
  });
  await controller.refresh();
  controller.requireSignIn("not_registered");
  const state = controller.snapshot();
  assert.equal(state.connected, false);
  assert.equal(connectionCopy(state).disabled, false);
  assert.match(connectionCopy(state).title, /註冊/);
  assert.match(
    catalogFailureMessage("sign_in_required", true),
    /保留上次議程與本機安排/,
  );
  controller.stop();
});

test("malformed auth provider or network failure does not imply valid sign-in", async () => {
  const controller = createOfficialConnection({
    request: async () => response({ provider: "rainfocus", connected: true }),
  });
  await controller.refresh();
  assert.equal(controller.snapshot().connected, false);
  assert.equal(connectionCopy(controller.snapshot()).disabled, true);
  controller.stop();
});

test("callback binding can be retried and completed OAuth does not imply catalog validation", () => {
  const copy = connectionCopy(
    status({
      checked: true,
      callback_available: false,
      error: "callback_unavailable",
    }),
  );
  assert.equal(copy.button, "重試登入");
  assert.equal(copy.disabled, false);
  assert.equal(
    connectionCopy(status({ connected: true })).title,
    "已完成 AWS Events 登入",
  );
  assert.match(sourceTimingNote("aws_events_api"), /官方 API/);
  assert.ok(!sourceTimingNote("aws_events_api").includes("正規化快取"));
  assert.match(sourceTimingNote("rainfocus"), /正規化快取/);
});
