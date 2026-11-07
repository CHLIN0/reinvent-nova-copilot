import { test } from "node:test";
import assert from "node:assert/strict";
import {
  chooseTab,
  homeDay,
  dayAgenda,
  dayCounts,
  freeLabel,
  createHomeChoice,
  createCalendarSync,
} from "./src/my-day.mjs";

const item = (code, source, start, end) => ({
  code,
  source,
  title: code,
  session_id: code,
  start: `${start.length === 5 ? "2026-11-30T" + start : start}:00-08:00`,
  end: `${end.length === 5 ? "2026-11-30T" + end : end}:00-08:00`,
});

test("signed in opens My re:Invent; signed out opens Explore", () => {
  assert.equal(chooseTab({ signedIn: true }), "mine");
  assert.equal(chooseTab({ signedIn: true, requested: null }), "mine");
  assert.equal(chooseTab({ signedIn: false }), "explore");
  assert.equal(chooseTab({ signedIn: false, requested: "mine" }), "explore");
  assert.equal(chooseTab({ signedIn: true, requested: "explore" }), "explore");
  assert.equal(chooseTab({ signedIn: true, requested: "bogus" }), "mine");
});

test("the day is the first conference day until it arrives, then today (Las Vegas date)", () => {
  assert.equal(homeDay(new Date("2026-11-07T12:00:00Z")), "2026-11-30");
  // 2026-11-30 07:30 UTC is still 11-29 in Las Vegas.
  assert.equal(homeDay(new Date("2026-11-30T07:30:00Z")), "2026-11-30");
  assert.equal(homeDay(new Date("2026-11-30T09:00:00-08:00")), "2026-11-30");
  assert.equal(homeDay(new Date("2026-12-02T23:30:00-08:00")), "2026-12-02");
  assert.equal(homeDay(new Date("2026-12-04T08:00:00-08:00")), "2026-12-04");
  assert.equal(homeDay(new Date("2026-12-06T08:00:00-08:00")), "2026-11-30");
});

test("gaps between reserved sessions carry their length, picks inside them are nested", () => {
  const plan = [
    item("GHJ308", "reserved", "13:30", "15:30"),
    item("CMP321", "reserved", "09:00", "10:00"),
    item("INV538", "reserved", "10:30", "11:30"),
    item("FAV1", "favorite", "12:00", "13:00"),
    item("LOC1", "local", "15:00", "16:00"),
    item("OTHERDAY", "reserved", "2026-12-01T09:00", "2026-12-01T10:00"),
  ];
  const rows = dayAgenda(plan, "2026-11-30");
  assert.deepEqual(
    rows.map((r) =>
      r.kind === "gap"
        ? `gap ${r.label} [${r.items.map((p) => p.code)}]`
        : r.item.code,
    ),
    [
      "CMP321",
      "gap 30 min free []",
      "INV538",
      "gap 2 h free [FAV1]",
      "GHJ308",
      "LOC1",
    ],
  );
  assert.equal(rows[3].minutes, 120);
  assert.equal(dayAgenda(plan, "2026-12-01").length, 1);
  assert.deepEqual(dayAgenda(plan, "2026-12-02"), []);
});

test("overlapping or back-to-back reservations leave no gap; every positive gap is shown", () => {
  const rows = dayAgenda(
    [
      item("A", "reserved", "09:00", "11:00"),
      item("B", "reserved", "10:00", "10:30"),
      item("C", "reserved", "11:00", "12:00"),
      item("D", "reserved", "12:10", "13:00"),
      item("E", "reserved", "14:00", "15:00"),
    ],
    "2026-11-30",
  );
  assert.deepEqual(
    rows.map((r) => (r.kind === "gap" ? r.label : r.item.code)),
    ["A", "B", "C", "10 min free", "D", "1 h free", "E"],
  );
});

test("a ten-minute gap between reservations is shown with its length (Codex T3 finding 1)", () => {
  const rows = dayAgenda(
    [item("A", "reserved", "09:00", "10:00"), item("B", "reserved", "10:10", "11:00")],
    "2026-11-30",
  );
  assert.deepEqual(
    rows.map((r) => (r.kind === "gap" ? `${r.label} ${r.minutes}` : r.item.code)),
    ["A", "10 min free 10", "B"],
  );
});

test("items without times are left out; counts per day", () => {
  const plan = [
    { code: "X", source: "reserved", start: "", end: "" },
    item("A", "favorite", "09:00", "10:00"),
  ];
  assert.deepEqual(
    dayAgenda(plan, "2026-11-30").map((r) => r.item.code),
    ["A"],
  );
  assert.equal(dayCounts(plan)["2026-11-30"], 1);
  assert.equal(dayCounts(plan)["2026-12-01"], 0);
});

test("free labels", () => {
  assert.equal(freeLabel(120), "2 h free");
  assert.equal(freeLabel(90), "1 h 30 min free");
  assert.equal(freeLabel(45), "45 min free");
});

function home(requested = null) {
  const changes = [];
  const choice = createHomeChoice({ requested, onChange: (c) => changes.push(c) });
  return { choice, changes, last: () => changes.at(-1) };
}

test("a failed auth check followed by a live plan opens My re:Invent (Codex T3 finding 2)", () => {
  const h = home();
  h.choice.auth(false); // /api/auth/status failed: connection_unavailable → connected false
  assert.deepEqual(h.last(), { tab: "explore", previous: null, signedIn: false });
  h.choice.plan("live"); // /api/plan then proves the official schedule was read
  assert.deepEqual(h.last(), { tab: "mine", previous: "explore", signedIn: true });
});

test("a live plan alone decides before auth answers; signed-out plan alone waits", () => {
  const waiting = home();
  waiting.choice.plan("signed_out");
  assert.equal(waiting.changes.length, 0);
  waiting.choice.auth(true);
  assert.equal(waiting.last().tab, "mine");
  const live = home();
  live.choice.plan("live");
  assert.deepEqual(live.last(), { tab: "mine", previous: null, signedIn: true });
});

test("an explicit Explore choice is kept; losing sign-in leaves My re:Invent", () => {
  const h = home("explore");
  h.choice.auth(true);
  assert.equal(h.last().tab, "explore");
  h.choice.plan("live");
  assert.equal(h.last().tab, "explore");
  const user = home();
  user.choice.auth(true);
  user.choice.choose("explore");
  user.choice.plan("live");
  assert.equal(user.last().tab, "explore");
  const expired = home();
  expired.choice.auth(true);
  expired.choice.plan("live");
  expired.choice.auth(false);
  expired.choice.plan("signed_out");
  assert.deepEqual(expired.last(), { tab: "explore", previous: "mine", signedIn: false });
});

test("picking a day on My re:Invent moves the Explore calendar too (Codex T3 finding 4)", () => {
  const calls = [];
  const calendar = { changeView: (...a) => calls.push(a) };
  // Explore, single-day view on Tuesday.
  const sync = createCalendarSync(calendar, "day", "2026-12-01");
  // My re:Invent: pick Wednesday; Atlas's render calls go(view, day) on every state change.
  sync.go("day", "2026-12-02");
  // Back to Explore: same state, nothing more to move; the calendar is already on Wednesday.
  sync.go("day", "2026-12-02");
  assert.deepEqual(calls, [["timeGridDay", "2026-12-02"]]);
  sync.go("week", "2026-12-03");
  sync.go("week", "2026-12-04");
  assert.deepEqual(calls.at(-1), ["fiveDays", "2026-11-30"]);
  assert.equal(calls.length, 2);
});

test("a saved tab=mine does not block My re:Invent after a failed auth check (Codex T3 round 2)", () => {
  const h = home("mine");
  h.choice.auth(false);
  assert.deepEqual(h.last(), { tab: "explore", previous: null, signedIn: false });
  h.choice.plan("live");
  assert.deepEqual(h.last(), { tab: "mine", previous: "explore", signedIn: true });
});

test("only a chosen Explore is remembered in the URL or blocks My re:Invent", () => {
  const fallback = home();
  fallback.choice.auth(false);
  assert.equal(fallback.choice.urlTab, null, "an Explore the page fell back to is not saved");
  fallback.choice.plan("live");
  assert.equal(fallback.choice.urlTab, "mine");
  const clicked = home();
  clicked.choice.auth(true);
  clicked.choice.choose("explore");
  assert.equal(clicked.choice.urlTab, "explore");
  // Chose My re:Invent, lost sign-in (fallback Explore), signed in again: back to My re:Invent.
  const back = home();
  back.choice.auth(true);
  back.choice.choose("mine");
  back.choice.auth(false);
  assert.equal(back.last().tab, "explore");
  assert.equal(back.choice.urlTab, null);
  back.choice.auth(true);
  assert.equal(back.last().tab, "mine");
  // A URL tab=explore stays until the attendee clicks something else.
  const url = home("explore");
  url.choice.auth(false);
  url.choice.plan("live");
  assert.equal(url.last().tab, "explore");
  assert.equal(url.choice.urlTab, "explore");
});
