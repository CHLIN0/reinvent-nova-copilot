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

// Codex T3 finding 3: Event Atlas's button is the one sign-in control, so it must follow the server.
function signedInController(serverStatus = status({ connected: true })) {
  const calls = [];
  let copy = null;
  const controller = createOfficialConnection({
    request: async (url, init = {}) => {
      calls.push({ url, method: init.method || "GET" });
      return url === "/api/auth/start"
        ? response({ authorization_url: "https://example.invalid/authorize" })
        : response(serverStatus);
    },
    onChange: (state) => {
      copy = connectionCopy(state);
    },
    schedule: () => 0,
    cancel: () => {},
  });
  return { controller, calls, copy: () => copy };
}

test("signed out or expired per the status poll re-enables the sign-in button", async () => {
  const { controller, copy, calls } = signedInController();
  await controller.refresh();
  assert.deepEqual([copy().button, copy().disabled], ["已登入", true]);
  assert.equal(await controller.start(), null);
  controller.applyStatus({ signed_in: false, soon: false });
  assert.deepEqual([copy().button, copy().disabled], ["登入 AWS Events", false]);
  assert.equal(await controller.start(), "https://example.invalid/authorize");
  assert.equal(calls.filter((c) => c.url === "/api/auth/start").length, 1);
  controller.stop();
});

test("about to expire offers 再次登入 on the same button and allows a new sign-in", async () => {
  const { controller, copy } = signedInController();
  await controller.refresh();
  controller.applyStatus({ signed_in: true, soon: true });
  assert.deepEqual([copy().button, copy().disabled], ["再次登入", false]);
  await controller.refresh(); // a re-check keeps the warning while still connected
  assert.equal(copy().button, "再次登入");
  assert.equal(await controller.start(), "https://example.invalid/authorize");
  controller.applyStatus({ signed_in: true, soon: false });
  assert.deepEqual([copy().button, copy().disabled], ["已登入", true]);
  controller.stop();
});

test("an expired token the server still holds is not shown as signed in", async () => {
  const past = Date.now() / 1000 - 60;
  const expired = signedInController(
    status({ connected: true, expires_at: past, refreshable: false }),
  );
  await expired.controller.refresh();
  assert.equal(expired.controller.snapshot().connected, false);
  assert.equal(expired.copy().disabled, false);
  const refreshable = signedInController(
    status({ connected: true, expires_at: past, refreshable: true }),
  );
  await refreshable.controller.refresh();
  assert.equal(refreshable.controller.snapshot().connected, true);
});

test("signed in per the poll while Atlas still shows signed out re-checks the server", async () => {
  const { controller, calls } = signedInController(status({ connected: false }));
  await controller.refresh();
  const before = calls.length;
  controller.applyStatus({ signed_in: true, soon: false });
  await new Promise((r) => setImmediate(r));
  assert.equal(calls.length, before + 1);
  assert.equal(calls.at(-1).url, "/api/auth/status");
  controller.stop();
});
