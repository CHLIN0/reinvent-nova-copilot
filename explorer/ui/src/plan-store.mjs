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
