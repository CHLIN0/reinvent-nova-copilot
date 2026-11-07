export const ZONE = "America/Los_Angeles";
export const DAYS = [
  "2026-11-30",
  "2026-12-01",
  "2026-12-02",
  "2026-12-03",
  "2026-12-04",
];
export const normalize = (value) =>
  String(value ?? "")
    .normalize("NFKC")
    .toLocaleLowerCase()
    .replace(/[’']/g, "")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
export const sourceKey = (s) => JSON.stringify([s.source, s.session_id]);
export const placementKey = (s) =>
  JSON.stringify([s.source, s.session_id, s.start_local, s.end_local]);
const parts = (value) =>
  Object.fromEntries(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: ZONE,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
    })
      .formatToParts(new Date(value))
      .map((p) => [p.type, p.value]),
  );
export function localDate(value) {
  try {
    const p = parts(value);
    return `${p.year}-${p.month}-${p.day}`;
  } catch {
    return "";
  }
}
export function localClock(value) {
  try {
    const p = parts(value);
    return `${p.hour}:${p.minute}`;
  } catch {
    return "";
  }
}
export function dayLabel(value) {
  return new Intl.DateTimeFormat("zh-TW", {
    timeZone: ZONE,
    month: "numeric",
    day: "numeric",
    weekday: "short",
  }).format(new Date(value + "T12:00:00-08:00"));
}
export function observationLabel(value) {
  return typeof value === "string" && Number.isFinite(Date.parse(value))
    ? new Intl.DateTimeFormat("zh-TW", {
        timeZone: "Asia/Taipei",
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).format(new Date(value)) + " 台北"
    : "觀測時間未知";
}
export function interval(s) {
  // Offset-bearing source timestamps are authoritative; coarse time tags are not.
  if (
    ![s.start_local, s.end_local].every((x) => {
      if (typeof x !== "string") return false;
      const m = x.match(
        /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})$/,
      );
      if (!m) return false;
      const date = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]));
      return (
        date.getUTCFullYear() === +m[1] &&
        date.getUTCMonth() === +m[2] - 1 &&
        date.getUTCDate() === +m[3] &&
        +m[4] < 24 &&
        +m[5] < 60
      );
    })
  )
    return null;
  const start = Date.parse(s.start_local),
    end = Date.parse(s.end_local);
  return Number.isFinite(start) && Number.isFinite(end) && end > start
    ? { start, end }
    : null;
}
export function venueFor(s, venues) {
  const value = " " + normalize([s.venue, s.location].join(" ")) + " ";
  const found = venues.filter((v) =>
    [v.name, ...(v.aliases || [])].some((a) =>
      value.includes(" " + normalize(a) + " "),
    ),
  );
  return found.length === 1 ? found[0] : null;
}
export function prepare(sessions, venues) {
  return sessions.map((s) => {
    const times = interval(s);
    return {
      key: sourceKey(s),
      placement: placementKey(s),
      session: s,
      times,
      date: times ? localDate(s.start_local) : "",
      venue: venueFor(s, venues),
      search: normalize(
        [
          s.code,
          s.title,
          s.abstract,
          ...(s.speakers || []),
          ...(s.tags || []),
        ].join(" "),
      ),
      levels: [
        ...new Set(
          [
            s.level,
            ...(s.tags || []).filter((t) => /^[1-5]00\s*[–-]/.test(t)),
          ].filter(Boolean),
        ),
      ],
    };
  });
}
export function filterRecords(records, f, plan = []) {
  const tokens = normalize(f.query).split(" ").filter(Boolean),
    planned = new Set(plan.map((p) => p.placement));
  return records.filter(
    (r) =>
      tokens.every((t) => r.search.includes(t)) &&
      (!f.topic || (r.session.tags || []).includes(f.topic)) &&
      (!f.type || r.session.type === f.type) &&
      (!f.level || r.levels.includes(f.level)) &&
      (!f.venue || r.venue?.id === f.venue) &&
      (!f.planOnly || planned.has(r.placement)),
  );
}
export function inDay(r, day) {
  if (!r.times) return false;
  const start = Date.parse(day + "T00:00:00-08:00"),
    end = start + 86400000;
  return r.times.start < end && r.times.end > start;
}
export function dayForSelection(record, currentDay, view) {
  if (view === "day" && inDay(record, currentDay)) return currentDay;
  return DAYS.includes(record.date)
    ? record.date
    : DAYS.find((day) => inDay(record, day)) || currentDay;
}
export function overlap(a, b) {
  return (
    !!a.times &&
    !!b.times &&
    a.times.start < b.times.end &&
    b.times.start < a.times.end
  );
}
export function facets(records, field) {
  return [
    ...new Set(
      records
        .flatMap((r) =>
          field === "level"
            ? r.levels
            : field === "topic"
              ? (r.session.tags || []).filter(
                  (t) =>
                    !/^\d+:|^\d+\s*[ap]\.|^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),/.test(
                      t,
                    ),
                )
              : [r.session[field]],
        )
        .filter(Boolean),
    ),
  ].sort();
}
export function makePlanItem(r) {
  return {
    placement: r.placement,
    key: r.key,
    session_id: String(r.session.session_id || ""),
    code: String(r.session.code || ""),
    title: String(r.session.title || ""),
    start: String(r.session.start_local || ""),
    end: String(r.session.end_local || ""),
    location: String(r.session.location || ""),
    addedAt: new Date().toISOString(),
  };
}
const PLAN_LABELS = {
  reserved: "官方已預約",
  favorite: "官方收藏",
  local: "已在本機安排",
};
const PLAN_MARKS = { reserved: "✓ ", favorite: "★ ", local: "● " };
/** How a plan item is marked: official reservation, official favorite, or a local pick. */
export const planLabel = (item) => PLAN_LABELS[item?.source] || PLAN_LABELS.local;
export const planMark = (item) => (item ? PLAN_MARKS[item.source] || PLAN_MARKS.local : "");
export function loadPlan(storage) {
  try {
    const raw = storage.getItem("reinvent.local-plan.v1");
    if (!raw) return { items: [], error: null };
    if (raw.length > 500000) throw Error();
    const d = JSON.parse(raw);
    if (d.version !== 1 || !Array.isArray(d.items) || d.items.length > 500)
      throw Error();
    if (
      d.items.some(
        (x) =>
          !x ||
          [
            "placement",
            "key",
            "code",
            "title",
            "start",
            "end",
            "location",
          ].some((k) => typeof x[k] !== "string"),
      )
    )
      throw Error();
    return { items: d.items, error: null };
  } catch {
    return { items: [], error: "無法讀取本機安排；原資料仍保留，暫不覆寫。" };
  }
}
export function savePlan(storage, items) {
  if (items.length > 500) throw Error("本機安排已達 500 場上限。");
  const serialized = JSON.stringify({ version: 1, items });
  if (serialized.length > 500000)
    throw Error("本機安排資料過大，未覆寫原安排。");
  storage.setItem("reinvent.local-plan.v1", serialized);
}
export async function abstractHash(text) {
  const raw = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(text),
  );
  return [...new Uint8Array(raw)]
    .map((x) => x.toString(16).padStart(2, "0"))
    .join("");
}
export function validateCatalog(d) {
  if (!d || d.version !== 1 || !Array.isArray(d.sessions) || !d.meta)
    throw Error("議程資料格式不符，保留目前畫面。");
  return d;
}
