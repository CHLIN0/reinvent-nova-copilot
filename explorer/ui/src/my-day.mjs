// "My re:Invent": which tab opens first, which day it shows, and the day's agenda with free gaps.
import { DAYS, localDate } from "./model.mjs";

export const TABS = ["mine", "explore"];

/** Signed in → My re:Invent unless the URL asked for Explore; signed out → Explore. */
export function chooseTab({ signedIn, requested = null }) {
  if (!signedIn) return "explore";
  return TABS.includes(requested) ? requested : "mine";
}

/** First conference day until it arrives, then today (Las Vegas date); after the event, the first day again. */
export function homeDay(now = new Date(), days = DAYS) {
  const today = localDate(now);
  return days.includes(today) ? today : days[0];
}

export function freeLabel(minutes) {
  const h = Math.floor(minutes / 60),
    m = Math.round(minutes % 60);
  return `${h ? `${h} h` : ""}${h && m ? " " : ""}${m || !h ? `${m} min` : ""} free`;
}

const ms = (value) => Date.parse(value);
const MIN_GAP = 15;

/**
 * One day of the plan, in time order. Gaps are the free time between consecutive reserved sessions
 * (at least 15 min); favorites and local picks that start inside a gap are listed inside it.
 * Rows: {kind: "session", item} | {kind: "gap", start, end, minutes, label, items}.
 */
export function dayAgenda(items, day) {
  const today = items
    .filter(
      (p) =>
        p.start &&
        p.end &&
        Number.isFinite(ms(p.start)) &&
        localDate(p.start) === day,
    )
    .sort((a, b) => ms(a.start) - ms(b.start) || ms(a.end) - ms(b.end));
  const reserved = today.filter((p) => p.source === "reserved");
  const gaps = [];
  let busyUntil = null;
  for (const r of reserved) {
    if (busyUntil !== null && ms(r.start) - busyUntil >= MIN_GAP * 60000)
      gaps.push({ start: busyUntil, end: ms(r.start) });
    busyUntil = Math.max(busyUntil ?? 0, ms(r.end));
  }
  const rows = [];
  const inGap = new Set();
  const gapRows = gaps.map((g) => {
    const minutes = Math.round((g.end - g.start) / 60000);
    const picks = today.filter(
      (p) =>
        p.source !== "reserved" &&
        ms(p.start) >= g.start &&
        ms(p.start) < g.end,
    );
    for (const p of picks) inGap.add(p);
    return {
      kind: "gap",
      start: new Date(g.start).toISOString(),
      end: new Date(g.end).toISOString(),
      minutes,
      label: freeLabel(minutes),
      items: picks,
      at: g.start,
    };
  });
  const sessions = today
    .filter((p) => !inGap.has(p))
    .map((item) => ({ kind: "session", item, at: ms(item.start) }));
  for (const row of [...sessions, ...gapRows].sort(
    (a, b) => a.at - b.at || (a.kind === "gap") - (b.kind === "gap"),
  )) {
    const { at, ...rest } = row;
    rows.push(rest);
  }
  return rows;
}

/** Plan items per conference day, for the day tabs ("11/30 · 3"). */
export function dayCounts(items, days = DAYS) {
  return Object.fromEntries(
    days.map((d) => [
      d,
      items.filter((p) => p.start && localDate(p.start) === d).length,
    ]),
  );
}
