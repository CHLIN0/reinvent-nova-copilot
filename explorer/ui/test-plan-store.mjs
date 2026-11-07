import { test } from "node:test";
import assert from "node:assert/strict";
import { createPlanStore } from "./src/plan-store.mjs";

const clone = (value) => structuredClone(value);
const tick = () => new Promise((resolve) => setImmediate(resolve));
const item = (id, extra = {}) => ({
  placement: id,
  key: id,
  code: id,
  title: "Session " + id,
  start: "2026-11-30T09:00:00-08:00",
  end: "2026-11-30T10:00:00-08:00",
  location: "Fixture room",
  ...extra,
});

// Bounded integration fake of the IDB events used by the adapter. Connections
// share a serialized readwrite scope; writes remain private until commit, and
// abort discards them. No Web Locks, browser, storage files, or network involved.
class FakeIndexedDB {
  constructor() {
    this.current = undefined;
    this.queue = [];
    this.transactions = [];
    this.holdCommit = false;
    this.abortNextCommit = false;
    this.schemaCreated = false;
  }
  open(name, version) {
    assert.equal(name, "reinvent.local-plan.v2");
    assert.equal(version, 1);
    const request = {};
    queueMicrotask(() => {
      request.result = {
        objectStoreNames: { contains: () => this.schemaCreated },
        createObjectStore: (name) => {
          assert.equal(name, "plan");
          this.schemaCreated = true;
        },
        transaction: (name, mode) => {
          assert.equal(name, "plan");
          assert.equal(mode, "readwrite");
          const transaction = new FakeTransaction(this);
          this.transactions.push(transaction);
          this.queue.push(transaction);
          if (this.queue.length === 1)
            queueMicrotask(() => transaction.start());
          return transaction;
        },
        close() {},
      };
      if (!this.schemaCreated) request.onupgradeneeded?.();
      request.onsuccess?.();
    });
    return request;
  }
  finish(transaction, abort = false) {
    assert.equal(this.queue[0], transaction);
    if (abort) transaction.onabort?.();
    else {
      this.current = clone(transaction.draft);
      transaction.oncomplete?.();
    }
    this.queue.shift();
    if (this.queue.length) queueMicrotask(() => this.queue[0].start());
  }
  releaseCommit(abort = false) {
    this.holdCommit = false;
    this.finish(this.queue[0], abort);
  }
}

class FakeTransaction {
  constructor(database) {
    this.database = database;
    this.aborted = false;
    this.puts = 0;
  }
  objectStore(name) {
    assert.equal(name, "plan");
    return {
      get: (key) => {
        assert.equal(key, "current");
        this.request = {};
        return this.request;
      },
      put: (value, key) => {
        assert.equal(key, "current");
        this.puts += 1;
        this.draft = clone(value);
        return {};
      },
    };
  }
  start() {
    this.draft = clone(this.database.current);
    this.request.result = clone(this.draft);
    this.request.onsuccess?.();
    queueMicrotask(() => {
      if (this.aborted) return;
      if (this.database.abortNextCommit) {
        this.database.abortNextCommit = false;
        this.database.finish(this, true);
      } else if (!this.database.holdCommit) this.database.finish(this);
    });
  }
  abort() {
    this.aborted = true;
    queueMicrotask(() => this.database.finish(this, true));
  }
}

function fixture(raw = null) {
  const indexedDB = new FakeIndexedDB();
  let reads = 0;
  const legacyStorage = {
    getItem(key) {
      assert.equal(key, "reinvent.local-plan.v1");
      reads += 1;
      return raw;
    },
    setItem() {
      assert.fail("Legacy writes forbidden");
    },
    removeItem() {
      assert.fail("Legacy removal forbidden");
    },
  };
  const tab = () => createPlanStore({ indexedDB, legacyStorage });
  return { indexedDB, tab, reads: () => reads };
}

test("first native transaction migrates once across connections and preserves legacy", async () => {
  const original = JSON.stringify({ version: 1, items: [item("legacy")] });
  const f = fixture(original);
  const [a, b] = await Promise.all([f.tab().load(), f.tab().load()]);
  assert.deepEqual(a, [item("legacy")]);
  assert.deepEqual(b, a);
  assert.equal(f.reads(), 1);
  assert.deepEqual(f.indexedDB.current, { version: 1, items: a });
  assert.equal(f.indexedDB.transactions[0].puts, 1);
  assert.equal(f.indexedDB.transactions[1].puts, 0);
});

test("concurrent stale tabs apply add/remove intents to committed latest state", async () => {
  const f = fixture(JSON.stringify({ version: 1, items: [item("old")] }));
  const a = f.tab(),
    b = f.tab();
  await Promise.all([a.load(), b.load()]);
  await Promise.all([
    a.update(item("old"), "remove"),
    b.update(item("new"), "add"),
    a.update(item("other"), "add"),
    b.update(item("new"), "add"),
  ]);
  assert.deepEqual(
    (await a.load()).map((p) => p.placement),
    ["new", "other"],
  );
  await b.update(item("missing"), "remove");
  assert.deepEqual(
    (await b.load()).map((p) => p.placement),
    ["new", "other"],
  );
});

test("malformed or unreadable legacy aborts migration without a new record", async () => {
  for (const raw of [
    "broken",
    '{"version":2,"items":[]}',
    '{"version":1,"items":[{}]}',
    "x".repeat(500001),
  ]) {
    const f = fixture(raw);
    await assert.rejects(f.tab().load(), /原資料仍保留/);
    assert.equal(f.indexedDB.current, undefined);
    assert.equal(f.indexedDB.transactions[0].puts, 0);
  }
  const database = new FakeIndexedDB();
  const store = createPlanStore({
    indexedDB: database,
    legacyStorage: {
      getItem() {
        throw Error("denied");
      },
    },
  });
  await assert.rejects(store.update(item("x"), "add"), /原資料仍保留/);
  assert.equal(database.current, undefined);
});

test("malformed committed state is never replaced by legacy or a removal", async () => {
  const f = fixture();
  f.indexedDB.current = { version: 1, items: [{ placement: "bad" }] };
  const before = clone(f.indexedDB.current);
  await assert.rejects(f.tab().update(item("bad"), "remove"), /原資料仍保留/);
  assert.deepEqual(f.indexedDB.current, before);
  assert.equal(f.reads(), 0);
});

test("500-record and 500,000-character limits abort without altering current", async () => {
  const f = fixture();
  f.indexedDB.current = {
    version: 1,
    items: Array.from({ length: 500 }, (_, i) => item(String(i))),
  };
  const before = clone(f.indexedDB.current);
  await assert.rejects(f.tab().update(item("overflow"), "add"));
  assert.deepEqual(f.indexedDB.current, before);
  const small = fixture();
  await small.tab().update(item("kept"), "add");
  const kept = clone(small.indexedDB.current);
  await assert.rejects(
    small.tab().update(item("large", { title: "x".repeat(500000) }), "add"),
  );
  assert.deepEqual(small.indexedDB.current, kept);
});

test("request success cannot resolve before transaction complete; abort rejects", async () => {
  const f = fixture();
  f.indexedDB.holdCommit = true;
  let settled = false;
  const pending = f.tab().update(item("x"), "add");
  pending.then(
    () => {
      settled = true;
    },
    () => {
      settled = true;
    },
  );
  await tick();
  assert.equal(f.indexedDB.transactions[0].puts, 1);
  assert.equal(settled, false);
  assert.equal(f.indexedDB.current, undefined);
  f.indexedDB.releaseCommit(true);
  await assert.rejects(pending, /原資料仍保留/);
  assert.equal(f.indexedDB.current, undefined);
  assert.deepEqual(await f.tab().load(), []);
});

test("successful commit is required before resolving the returned items", async () => {
  const f = fixture();
  f.indexedDB.holdCommit = true;
  let settled = false;
  const pending = f.tab().update(item("x"), "add");
  pending.then(() => {
    settled = true;
  });
  await tick();
  assert.equal(settled, false);
  f.indexedDB.releaseCommit();
  assert.deepEqual(await pending, [item("x")]);
  assert.deepEqual(f.indexedDB.current.items, [item("x")]);
});

test("post-put native abort preserves prior record and rejects instead of success", async () => {
  const f = fixture();
  await f.tab().update(item("kept"), "add");
  f.indexedDB.abortNextCommit = true;
  await assert.rejects(f.tab().update(item("lost"), "add"), /原資料仍保留/);
  assert.deepEqual(
    (await f.tab().load()).map((p) => p.placement),
    ["kept"],
  );
});

test("invalid intent, unsupported storage, and caller mutation fail safely", async () => {
  const unsupported = createPlanStore();
  await assert.rejects(unsupported.load(), /原資料仍保留/);
  await assert.rejects(unsupported.update(item("x"), "add"), /原資料仍保留/);
  const f = fixture();
  const store = f.tab();
  for (const action of ["toggle", undefined, null])
    await assert.rejects(store.update(item("x"), action));
  await assert.rejects(store.update({}, "add"));
  await assert.rejects(store.update({}, "remove"));
  assert.equal(f.indexedDB.transactions.length, 0);
  const original = item("x");
  const pending = store.update(original, "add");
  original.title = "Caller changed this after intent";
  assert.equal((await pending)[0].title, "Session x");
});

test("opening failure rejects safely and the next call may retry opening", async () => {
  const database = new FakeIndexedDB();
  let attempts = 0;
  const indexedDB = {
    open(...args) {
      attempts += 1;
      if (attempts === 1) {
        const request = {};
        queueMicrotask(() => request.onerror());
        return request;
      }
      return database.open(...args);
    },
  };
  const store = createPlanStore({
    indexedDB,
    legacyStorage: { getItem: () => null },
  });
  await assert.rejects(store.load(), /原資料仍保留/);
  assert.deepEqual(await store.load(), []);
  assert.equal(attempts, 2);
});

test("blocked opens reject and close a late successful connection without writing", async () => {
  let closed = false,
    request;
  const indexedDB = {
    open() {
      request = {};
      queueMicrotask(() => request.onblocked());
      return request;
    },
  };
  const store = createPlanStore({
    indexedDB,
    legacyStorage: { getItem: () => null },
  });
  await assert.rejects(store.load(), /原資料仍保留/);
  request.result = {
    close() {
      closed = true;
    },
    transaction() {
      assert.fail("A rejected late connection must not create a transaction");
    },
  };
  request.onsuccess();
  assert.equal(closed, true);
});
