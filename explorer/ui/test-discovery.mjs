import { test } from "node:test";
import assert from "node:assert/strict";
import { prepare } from "./src/model.mjs";
import {
  enrichRecords,
  filterDiscovery,
  facetChoices,
  normaliseFilters,
  normaliseCalendarFilters,
} from "./src/discovery.mjs";

const taxonomy = [
  { id: "agent", label: "Agentic AI" },
  { id: "security", label: "Security" },
];
const venues = [{ id: "forum", name: "Caesars Forum", aliases: [] }];
const session = (id, extra = {}) => ({
  source: "catalog",
  session_id: id,
  title: "Agent workflows",
  abstract: "Durable orchestration",
  tags: ["Agentic AI"],
  type: "Workshop",
  level: "300 – Advanced",
  venue: "Caesars Forum",
  start_local: "2026-11-30T09:00:00-08:00",
  end_local: "2026-11-30T10:00:00-08:00",
  system_topics: ["agent"],
  derived_company_matches: [],
  ...extra,
});
const records = (sessions) =>
  enrichRecords(prepare(sessions, venues), taxonomy);
const ids = (rows) => rows.map((row) => row.session.session_id);
const count = (options, value) =>
  options.find((option) => option.value === value)?.count;

test("calendar restoration cannot retain invisible date facets", () => {
  const state = normaliseCalendarFilters({
    dates: ["2026-12-04"],
    companies: ["OpenAI"],
    query: "agents",
  });
  assert.deepEqual(state.dates, []);
  assert.deepEqual(state.companies, ["OpenAI"]);
  assert.equal(state.query, "agents");
  assert.deepEqual(normaliseFilters({ dates: ["2026-12-04"] }).dates, [
    "2026-12-04",
  ]);
});

test("multi-select is OR within a dimension and AND across dimensions and query tokens", () => {
  const rows = records([
    session("a", { derived_company_matches: [{ company: "OpenAI" }] }),
    session("b", {
      system_topics: ["security"],
      type: "Chalk talk",
      level: "400 – Expert",
    }),
    session("c", {
      system_topics: ["security"],
      title: "Security only",
      abstract: "Other",
    }),
  ]);
  assert.deepEqual(
    ids(
      filterDiscovery(rows, {
        topics: ["agent", "security"],
        types: ["Workshop", "Chalk talk"],
        query: "WORKFLOWS durable",
      }),
    ),
    ["a", "b"],
  );
  assert.deepEqual(
    ids(
      filterDiscovery(rows, {
        topics: ["agent", "security"],
        companies: ["OpenAI"],
        levels: ["300 – Advanced", "400 – Expert"],
      }),
    ),
    ["a"],
  );
  assert.deepEqual(ids(filterDiscovery(rows, { companies: ["openai"] })), []);
});

test("official tags and system topics remain separate with original public evidence", () => {
  const original = session("a", {
    tags: ["Agentic AI", "Unknown official label"],
    classification_reasons: [
      { id: "agent", reason: "title", evidence: ["Agent"] },
    ],
  });
  const [row] = records([original]);
  assert.equal(row.session, original);
  assert.deepEqual(row.systemTopics, ["agent"]);
  assert.ok(
    row.officialFacets.some(
      (facet) => facet.key === "other:unknown official label",
    ),
  );
  assert.ok(
    row.officialFacets.every((facet) => facet.sources.includes("official")),
  );
  assert.deepEqual(
    ids(filterDiscovery([row], { tags: ["topic:agentic ai"] })),
    ["a"],
  );
  assert.deepEqual(
    ids(filterDiscovery([row], { topics: ["topic:agentic ai"] })),
    [],
  );
});

test("self-excluded facet counts retain other dimensions, query and exact placement plan", () => {
  const rows = records([
    session("a"),
    session("b", { system_topics: ["security"] }),
    session("c", { type: "Chalk talk", system_topics: ["security"] }),
  ]);
  const options = facetChoices(
    rows,
    { topics: ["agent"], types: ["Workshop"] },
    [],
    "topics",
    taxonomy,
  );
  assert.equal(count(options, "agent"), 1);
  assert.equal(count(options, "security"), 1);
  assert.equal(
    count(facetChoices(rows, { topics: ["agent"] }, [], "types"), "Chalk talk"),
    0,
  );
  assert.deepEqual(
    ids(
      filterDiscovery(rows, { planOnly: true }, [
        { placement: rows[1].placement },
      ]),
    ),
    ["b"],
  );
  assert.equal(
    count(
      facetChoices(
        rows,
        { planOnly: true },
        [{ placement: "stale" }],
        "topics",
        taxonomy,
      ),
      "agent",
    ),
    0,
  );
});

test("same official facet from several fields counts a session once and preserves provenance", () => {
  const rows = records([
    session("a", {
      tags: ["Workshop", "Workshop"],
      attributevalues: [{ attribute_id: "Type", value: "Workshop" }],
    }),
  ]);
  const option = facetChoices(rows, {}, [], "tags").find(
    (entry) => entry.value === "format:workshop",
  );
  assert.equal(option.count, 1);
  assert.deepEqual(option.provenance.map((entry) => entry.field).sort(), [
    "attributevalues.Type",
    "tags",
    "type",
  ]);
});

test("formats infer explicit title phrases only, while company filters use canonical public matches", () => {
  const rows = records([
    session("a", {
      title: "AWS GameDay with OpenAI",
      type: "",
      tags: [],
      abstract: "Anthropic",
      derived_company_matches: [{ company: "OpenAI" }, { company: "OpenAI" }],
    }),
    session("b", {
      title: "Game architecture",
      abstract: "Join a GameDay and use NVIDIA",
      type: "",
      tags: [],
    }),
  ]);
  assert.deepEqual(ids(filterDiscovery(rows, { types: ["GameDay"] })), ["a"]);
  assert.deepEqual(
    ids(filterDiscovery(rows, { companies: ["NVIDIA", "Anthropic"] })),
    [],
  );
  const company = facetChoices(rows, {}, [], "companies")[0];
  assert.equal(company.label, "OpenAI");
  assert.equal(company.count, 1);
  const format = facetChoices(rows, {}, [], "types")[0];
  assert.equal(format.provenance[0].source, "inferred_title");
  assert.equal(
    facetChoices(rows, {}, [], "tags").some(
      (entry) => entry.value === "format:gameday",
    ),
    false,
  );
});

test("half-open date/time windows preserve cross-midnight portions and date-specific counts", () => {
  const rows = records([
    session("night", {
      start_local: "2026-11-30T23:00:00-08:00",
      end_local: "2026-12-01T01:00:00-08:00",
    }),
    session("atEnd", {
      start_local: "2026-12-01T01:00:00-08:00",
      end_local: "2026-12-01T02:00:00-08:00",
    }),
    session("midnightEnd", {
      start_local: "2026-11-30T23:30:00-08:00",
      end_local: "2026-12-01T00:00:00-08:00",
    }),
    session("unplaced", { end_local: null }),
  ]);
  assert.deepEqual(
    ids(
      filterDiscovery(rows, {
        dates: ["2026-12-01"],
        from: "00:00",
        to: "01:00",
      }),
    ),
    ["night"],
  );
  assert.deepEqual(
    ids(
      filterDiscovery(rows, {
        dates: ["2026-12-01"],
        from: "22:00",
        to: "24:00",
      }),
    ),
    [],
  );
  assert.deepEqual(
    ids(
      filterDiscovery(rows, {
        dates: ["2026-11-30"],
        from: "22:00",
        to: "24:00",
      }),
    ),
    ["night", "midnightEnd"],
  );
  assert.deepEqual(ids(filterDiscovery(rows, { from: "00:30", to: "01:00" })), [
    "night",
  ]);
  assert.equal(filterDiscovery(rows, {}).length, 4);
  assert.equal(filterDiscovery(rows, { dates: ["2026-12-01"] }).length, 2);
  const dates = facetChoices(
    rows,
    { dates: ["2026-11-30"], from: "00:30", to: "01:00" },
    [],
    "dates",
  );
  assert.equal(count(dates, "2026-11-30"), 0);
  assert.equal(count(dates, "2026-12-01"), 1);
  assert.deepEqual(filterDiscovery(rows, { from: "15:00", to: "09:00" }), []);
});

test("unknown and selected zero choices survive, with unmapped venues and date labels", () => {
  const rows = records([
    session("a", { venue: "Undisclosed", system_topics: ["unknown-topic"] }),
  ]);
  const topics = facetChoices(
    rows,
    { topics: ["removed-topic"], query: "no match" },
    [],
    "topics",
    taxonomy,
  );
  assert.equal(count(topics, "unknown-topic"), 0);
  assert.equal(count(topics, "removed-topic"), 0);
  assert.equal(
    topics.find((entry) => entry.value === "agent").label,
    "Agentic AI",
  );
  assert.equal(facetChoices(rows, {}, [], "venues")[0].label, "未定位會場");
  assert.deepEqual(ids(filterDiscovery(rows, { venues: ["unmapped"] })), ["a"]);
  assert.equal(facetChoices(rows, {}, [], "dates").length, 5);
  assert.deepEqual(facetChoices(rows, {}, [], "nonexistent"), []);
});

test("projections, filtering and facet counts never mutate their inputs", () => {
  const input = [
    session("a", {
      tags: ["Workshop"],
      derived_company_matches: [{ company: "OpenAI", evidence: ["text"] }],
    }),
  ];
  const before = JSON.stringify(input);
  const prepared = prepare(input, venues);
  const preparedBefore = JSON.stringify(prepared);
  const rows = enrichRecords(prepared, taxonomy);
  const filters = {
    topics: ["agent"],
    query: "agent",
    from: "09:00",
    planOnly: false,
  };
  const snapshot = JSON.stringify({ rows, filters, taxonomy });
  assert.equal(filterDiscovery(rows, filters)[0], rows[0]);
  const options = facetChoices(rows, filters, [], "tags", taxonomy);
  options[0].provenance[0].source = "changed-output";
  assert.equal(JSON.stringify({ rows, filters, taxonomy }), snapshot);
  assert.equal(JSON.stringify(input), before);
  assert.equal(JSON.stringify(prepared), preparedBefore);
});

test("restored filter state is bounded, exact and retains scalar fields", () => {
  const state = normaliseFilters({
    topics: ["agent", "agent", null],
    types: "Workshop",
    companies: Array.from({ length: 220 }, (_, i) => `Company ${i}`),
    query: "a".repeat(2500),
    from: "25:00",
    to: "24:00",
    planOnly: "true",
  });
  assert.deepEqual(state.topics, ["agent"]);
  assert.deepEqual(state.types, ["Workshop"]);
  assert.equal(state.companies.length, 200);
  assert.equal(state.query.length, 2000);
  assert.equal(state.from, "");
  assert.equal(state.to, "24:00");
  assert.equal(state.planOnly, false);
  assert.deepEqual(normaliseFilters(null).topics, []);
});
