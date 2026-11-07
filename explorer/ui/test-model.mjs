import { test } from "node:test";
import assert from "node:assert/strict";
import {
  DAYS,
  ZONE,
  prepare,
  filterRecords,
  inDay,
  dayForSelection,
  overlap,
  localDate,
  localClock,
  interval,
  facets,
  makePlanItem,
  loadPlan,
  savePlan,
  placementKey,
  sourceKey,
  observationLabel,
} from "./src/model.mjs";
const venues = [
  { id: "forum", name: "Caesars Forum", aliases: [] },
  { id: "palace", name: "Caesars Palace", aliases: [] },
];
const session = (id, start, end, extra = {}) => ({
  session_id: id,
  source: "rainfocus",
  code: id,
  title: "Agent workflow",
  abstract: "Durable orchestration",
  venue: "Caesars Forum",
  location: "Caesars Forum | Level 1",
  start_local: "2026-11-30T" + start + ":00-08:00",
  end_local: "2026-11-30T" + end + ":00-08:00",
  tags: ["Agentic AI", "4:00 p.m. Monday, Nov 30"],
  speakers: [],
  level: "300 – Advanced",
  ...extra,
});
test("Las Vegas timestamps ignore host zone and coarse official time tags", () => {
  const r = prepare([session("a", "16:30", "17:00")], venues)[0];
  assert.equal(ZONE, "America/Los_Angeles");
  assert.equal(localDate(r.session.start_local), "2026-11-30");
  assert.equal(localClock(r.session.start_local), "16:30");
  assert.equal(r.times.end - r.times.start, 1800000);
  assert.equal(r.date, DAYS[0]);
});
test("half-open intervals allow back-to-back while true overlap stays", () => {
  const [a, b, c] = prepare(
    [
      session("a", "09:00", "10:00"),
      session("b", "10:00", "11:00"),
      session("c", "09:30", "10:30"),
    ],
    venues,
  );
  assert.equal(overlap(a, b), false);
  assert.equal(overlap(a, c), true);
  assert.equal(overlap(b, c), true);
});
test("invalid, naive and reverse time remain unplaced, no invented duration", () => {
  for (const s of [
    session("a", "11:00", "10:00"),
    session("b", "09:00", "10:00", { end_local: null }),
    session("c", "09:00", "10:00", { start_local: "2026-11-30T09:00:00" }),
  ])
    assert.equal(interval(s), null);
});
test("calendar rollover dates and24hour timestamps are not silently normalized", () => {
  for (const start of [
    "2026-02-30T09:00:00-08:00",
    "2026-11-30T24:00:00-08:00",
  ])
    assert.equal(
      interval(session("a", "09:00", "10:00", { start_local: start })),
      null,
    );
});
test("bad observation metadata does not prevent reading the agenda", () => {
  assert.equal(observationLabel("not a date"), "觀測時間未知");
  assert.equal(observationLabel(null), "觀測時間未知");
  assert.match(observationLabel("2026-10-25T07:00:00Z"), /15:00/);
});
test("cross-midnight belongs to both days but not exclusive end date", () => {
  const [r] = prepare(
    [
      session("a", "23:00", "01:00", {
        end_local: "2026-12-01T01:00:00-08:00",
      }),
    ],
    venues,
  );
  assert.equal(inDay(r, DAYS[0]), true);
  assert.equal(inDay(r, DAYS[1]), true);
  assert.equal(inDay(r, DAYS[2]), false);
  assert.equal(dayForSelection(r, DAYS[1], "day"), DAYS[1]);
  assert.equal(dayForSelection(r, DAYS[1], "week"), DAYS[0]);
  assert.equal(dayForSelection(r, DAYS[2], "day"), DAYS[0]);
});
test("week selection carries its date to day view; unplaced selection preserves date", () => {
  const [r, missing] = prepare(
    [
      session("dec3", "15:00", "16:00", {
        start_local: "2026-12-03T15:00:00-08:00",
        end_local: "2026-12-03T16:00:00-08:00",
      }),
      session("missing", "09:00", "10:00", { end_local: null }),
    ],
    venues,
  );
  assert.equal(dayForSelection(r, DAYS[2], "week"), DAYS[3]);
  assert.equal(dayForSelection(r, DAYS[2], "day"), DAYS[3]);
  assert.equal(dayForSelection(missing, DAYS[2], "week"), DAYS[2]);
  const [priorNight] = prepare(
    [
      session("prior", "23:00", "01:00", {
        start_local: "2026-11-29T23:00:00-08:00",
        end_local: "2026-11-30T01:00:00-08:00",
      }),
    ],
    venues,
  );
  assert.equal(dayForSelection(priorNight, DAYS[2], "week"), DAYS[0]);
});
test("ambiguous and unknown venues never select nearest known campus", () => {
  const [a, b] = prepare(
    [
      session("a", "09:00", "10:00", {
        location: "Caesars Palace",
        venue: "Caesars Forum",
      }),
      session("b", "09:00", "10:00", {
        location: "Unpublished room",
        venue: "Other hotel",
      }),
    ],
    venues,
  );
  assert.equal(a.venue, null);
  assert.equal(b.venue, null);
});
test("official scalar/tag level differences are both filterable", () => {
  const rs = prepare(
    [session("a", "09:00", "10:00", { tags: ["400 – Expert"] })],
    venues,
  );
  assert.equal(filterRecords(rs, { level: "300 – Advanced" }).length, 1);
  assert.equal(filterRecords(rs, { level: "400 – Expert" }).length, 1);
  assert.equal(facets(rs, "level").length, 2);
});
test("filters and local plans leave input untouched and preserve overlaps", () => {
  const input = [
      session("a", "09:00", "10:00"),
      session("b", "09:30", "11:00"),
    ],
    before = JSON.stringify(input);
  const rs = prepare(input, venues),
    plans = rs.map(makePlanItem);
  assert.equal(plans.length, 2);
  assert.equal(filterRecords(rs, { query: "unmatched" }, plans).length, 0);
  assert.equal(plans.length, 2);
  assert.equal(filterRecords(rs, { planOnly: true }, plans).length, 2);
  assert.equal(JSON.stringify(input), before);
});
test("changed time remains a different provisional placement, never official ID", () => {
  const a = session("a", "09:00", "10:00"),
    b = session("a", "11:00", "12:00");
  assert.equal(sourceKey(a), sourceKey(b));
  assert.notEqual(placementKey(a), placementKey(b));
  const p = makePlanItem(prepare([a], venues)[0]);
  assert.equal(
    filterRecords(prepare([b], venues), { planOnly: true }, [p]).length,
    0,
  );
});
test("local persistence validates payload and retains malformed source", () => {
  let value = "bad";
  const storage = { getItem: () => value, setItem: (_, v) => (value = v) };
  assert.ok(loadPlan(storage).error);
  assert.equal(value, "bad");
  const p = makePlanItem(prepare([session("a", "09:00", "10:00")], venues)[0]);
  savePlan(storage, [p]);
  assert.deepEqual(loadPlan(storage).items, [p]);
  assert.equal(JSON.parse(value).version, 1);
  assert.throws(() =>
    savePlan(
      {
        setItem() {
          throw Error("quota");
        },
      },
      [p],
    ),
  );
});
test("nullable public metadata remains reloadable in a local plan", () => {
  let value;
  const storage = { getItem: () => value, setItem: (_, v) => (value = v) };
  const p = makePlanItem(
    prepare(
      [
        session("a", "09:00", "10:00", {
          location: null,
          code: null,
          title: null,
        }),
      ],
      venues,
    )[0],
  );
  savePlan(storage, [p]);
  assert.equal(loadPlan(storage).error, null);
  assert.equal(loadPlan(storage).items[0].location, "");
});
test("save and load apply the same size bound before overwriting previous data", () => {
  let value = "preserved";
  const storage = { setItem: (_, v) => (value = v) };
  const p = makePlanItem(
    prepare(
      [
        session("a", "09:00", "10:00", {
          title: "x".repeat(5000),
          location: "y".repeat(5000),
        }),
      ],
      venues,
    )[0],
  );
  assert.throws(() => savePlan(storage, Array(50).fill(p)));
  assert.equal(value, "preserved");
});
