import { loadPlan } from "./model.mjs";

const DATABASE = "reinvent.local-plan.v2";
const STORE = "plan";
const CURRENT = "current";
const STORAGE_ERROR = "無法安全儲存本機安排；原資料仍保留。";

function validatedRecord(record) {
  let serialized;
  try {
    serialized = JSON.stringify(record);
  } catch {
    throw Error(STORAGE_ERROR);
  }
  if (typeof serialized !== "string") throw Error(STORAGE_ERROR);
  const parsed = loadPlan({ getItem: () => serialized });
  if (parsed.error) throw Error(parsed.error);
  return parsed.items;
}

/**
 * Each read/migration/update uses one native readwrite transaction over `plan`.
 * IndexedDB serializes that scope across connections/tabs: intents are applied
 * to the transaction's latest `current`, never a caller's stale list. The first
 * committed transaction copies valid v1 legacy data; legacy is never modified.
 * Invalid/unreadable legacy or current data aborts without creating a record.
 * Success is reported only on transaction complete, including no-op updates.
 */
export function createPlanStore({ indexedDB, legacyStorage } = {}) {
  let connection;

  function open() {
    if (connection) return connection;
    connection = new Promise((resolve, reject) => {
      if (!indexedDB?.open) return reject(Error(STORAGE_ERROR));
      let request;
      try {
        request = indexedDB.open(DATABASE, 1);
      } catch {
        return reject(Error(STORAGE_ERROR));
      }
      let failed = false;
      const fail = () => {
        failed = true;
        reject(Error(STORAGE_ERROR));
      };
      request.onerror = fail;
      request.onblocked = fail;
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(STORE)) {
          request.result.createObjectStore(STORE);
        }
      };
      request.onsuccess = () => {
        const db = request.result;
        if (failed) return db.close();
        db.onversionchange = () => {
          db.close();
          connection = undefined;
        };
        resolve(db);
      };
    });
    connection.catch(() => {
      connection = undefined;
    });
    return connection;
  }

  async function transact(item, action) {
    if (action !== undefined && !["add", "remove"].includes(action)) {
      throw Error("未知的安排操作。");
    }
    // Snapshot an add before awaiting a connection; later caller mutations must
    // not alter its intent. Removal only needs the stable placement identity.
    const intent =
      action === "add"
        ? validatedRecord({ version: 1, items: [item] })[0]
        : action === "remove"
          ? { placement: item?.placement }
          : null;
    if (action === "remove" && typeof intent.placement !== "string") {
      throw Error(STORAGE_ERROR);
    }
    const db = await open();
    return new Promise((resolve, reject) => {
      let transaction;
      try {
        transaction = db.transaction(STORE, "readwrite");
      } catch {
        return reject(Error(STORAGE_ERROR));
      }
      let items, failure;
      transaction.oncomplete = () => resolve(items);
      transaction.onabort = () => reject(failure || Error(STORAGE_ERROR));
      transaction.onerror = () => {
        failure ||= Error(STORAGE_ERROR);
      };
      const abort = (error) => {
        failure = error;
        try {
          transaction.abort();
        } catch {
          reject(failure);
        }
      };
      try {
        const store = transaction.objectStore(STORE);
        const request = store.get(CURRENT);
        request.onsuccess = () => {
          try {
            const missing = request.result === undefined;
            if (missing) {
              const legacy = loadPlan(legacyStorage);
              if (legacy.error) throw Error(legacy.error);
              items = validatedRecord({ version: 1, items: legacy.items });
            } else {
              items = validatedRecord(request.result);
            }
            if (
              action === "add" &&
              !items.some((p) => p.placement === intent.placement)
            ) {
              items = [...items, intent];
            } else if (action === "remove") {
              items = items.filter((p) => p.placement !== intent.placement);
            }
            // Reuse the same 500-item / 500,000-character schema validation for
            // both migration and final writes; exceptions abort the transaction.
            items = validatedRecord({ version: 1, items });
            if (missing || action !== undefined) {
              store.put({ version: 1, items }, CURRENT);
            }
          } catch (error) {
            abort(error);
          }
        };
      } catch (error) {
        abort(error);
      }
    });
  }

  return {
    load: () => transact(),
    update: (item, action) => {
      if (action === undefined)
        return Promise.reject(Error("未知的安排操作。"));
      return transact(item, action);
    },
  };
}
