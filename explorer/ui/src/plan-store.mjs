const PLAN_ERROR = "暫時無法讀取「我的安排」；請稍後再試。";
const FIELDS = [
  "placement",
  "key",
  "session_id",
  "code",
  "title",
  "start",
  "end",
  "location",
  "source",
];
const SOURCES = new Set(["reserved", "favorite", "local"]);

function validItems(data) {
  if (!data || !Array.isArray(data.items)) throw Error(PLAN_ERROR);
  for (const item of data.items)
    if (
      !item ||
      FIELDS.some((k) => typeof item[k] !== "string") ||
      !SOURCES.has(item.source)
    )
      throw Error(PLAN_ERROR);
  return data.items;
}

/**
 * The plan lives on the server (GET/POST /api/plan): official reservations and
 * favorites plus local picks, each item tagged with `source`. Nothing is kept in
 * browser storage. `official` holds the server's last report on the official read.
 */
export function createPlanStore({
  fetch: request = (...a) => globalThis.fetch(...a),
  endpoint = "/api/plan",
} = {}) {
  const store = { official: null };
  async function call(body) {
    let response, data;
    try {
      response = await request(
        endpoint,
        body === undefined
          ? { cache: "no-store" }
          : {
              method: "POST",
              cache: "no-store",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            },
      );
      data = await response.json();
    } catch {
      throw Error(PLAN_ERROR);
    }
    if (!response.ok)
      throw Error(typeof data?.error === "string" ? data.error : PLAN_ERROR);
    const items = validItems(data);
    store.official = data.official || null;
    return items;
  }
  function update(item, action) {
    if (!["add", "remove"].includes(action))
      return Promise.reject(Error("未知的安排操作。"));
    const id = item?.session_id;
    if (typeof id !== "string" || !id) return Promise.reject(Error(PLAN_ERROR));
    return call({ action, session_id: id });
  }
  return Object.assign(store, {
    load: () => call(),
    update,
    add: (item) => update(item, "add"),
    remove: (item) => update(item, "remove"),
  });
}

/** Window event Nova Copilot (same page) dispatches after it changes the plan or the official schedule. */
export const PLAN_CHANGED = "atlas:plan-changed";

/**
 * Keeps the page's plan in step with the server: re-reads the store on PLAN_CHANGED and when the
 * tab becomes visible again, and drops replies that a newer read has overtaken. Returns `refresh`.
 */
export function watchPlan({ store, onPlan, onError, target = globalThis, doc = globalThis.document }) {
  let latest = 0;
  async function refresh() {
    const request = ++latest;
    try {
      const items = await store.load();
      if (request === latest) onPlan(items, store.official);
    } catch (error) {
      if (request === latest) onError(error);
    }
  }
  target.addEventListener(PLAN_CHANGED, () => refresh());
  target.addEventListener("visibilitychange", () => {
    if (doc?.visibilityState === "visible") refresh();
  });
  return refresh;
}
