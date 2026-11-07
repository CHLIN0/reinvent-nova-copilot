import { DAYS, dayLabel, inDay, normalize } from "./model.mjs";
import { sessionFacets } from "./session-facets.mjs";

export const DISCOVERY_DIMENSIONS = Object.freeze([
  "topics",
  "tags",
  "companies",
  "types",
  "levels",
  "venues",
  "dates",
]);
const dimensions = new Set(DISCOVERY_DIMENSIONS);
const strings = (values) => [
  ...new Set(
    (Array.isArray(values) ? values : []).filter(
      (value) => typeof value === "string" && value.length > 0,
    ),
  ),
];
const sourceIs = (facet, source) =>
  facet.source === source || facet.sources?.includes(source);

/** Keep the original public session and its evidence intact; projections are separate. */
export function enrichRecords(records, taxonomy = []) {
  return records.map((record) => {
    const facets = sessionFacets(record.session, taxonomy);
    return {
      ...record,
      officialFacets: facets.filter((facet) => sourceIs(facet, "official")),
      formatFacets: facets.filter(
        (facet) =>
          facet.category === "format" &&
          (sourceIs(facet, "official") || sourceIs(facet, "inferred_title")),
      ),
      systemTopics: strings(record.session.system_topics),
      companies: strings(
        (record.session.derived_company_matches || []).map(
          (match) => match.company,
        ),
      ),
    };
  });
}

/** Bound restored/untrusted UI state without changing scalar search/time fields into arrays. */
export function normaliseFilters(filters = {}) {
  const input = filters && typeof filters === "object" ? filters : {};
  const result = {};
  for (const dimension of DISCOVERY_DIMENSIONS) {
    const raw =
      typeof input[dimension] === "string"
        ? [input[dimension]]
        : input[dimension];
    result[dimension] = strings(raw)
      .filter((value) => value.length <= 512)
      .slice(0, 200);
  }
  result.query =
    typeof input.query === "string" ? input.query.slice(0, 2000) : "";
  for (const name of ["from", "to"]) {
    const value = input[name];
    result[name] =
      typeof value === "string" &&
      (/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(value) ||
        (name === "to" && value === "24:00"))
        ? value
        : "";
  }
  result.planOnly = input.planOnly === true;
  return result;
}

/** Calendar navigation owns the date range; invisible date facets cannot persist. */
export function normaliseCalendarFilters(filters = {}) {
  return { ...normaliseFilters(filters), dates: [] };
}

function projected(record) {
  return record.officialFacets &&
    record.formatFacets &&
    record.systemTopics &&
    record.companies
    ? record
    : enrichRecords([record])[0];
}
function valuesFor(record, dimension) {
  switch (dimension) {
    case "topics":
      return record.systemTopics;
    case "tags":
      return strings(record.officialFacets.map((facet) => facet.key));
    case "companies":
      return record.companies;
    case "types":
      return strings(record.formatFacets.map((facet) => facet.label));
    case "levels":
      return strings(record.levels);
    case "venues":
      return [record.venue?.id || "unmapped"];
    case "dates":
      return DAYS.filter((day) => inDay(record, day));
    default:
      return [];
  }
}
const minute = (clock, fallback) =>
  clock ? Number(clock.slice(0, 2)) * 60 + Number(clock.slice(3)) : fallback;
function matchesDayWindow(record, day, filters) {
  if (!record.times || !/^\d{4}-\d{2}-\d{2}$/.test(day)) return false;
  const midnight = Date.parse(`${day}T00:00:00-08:00`);
  // re:Invent's five dates all use PST. Anchor each window to its own midnight:
  // a session continuing after midnight must retain that next day's actual time.
  const start = midnight + minute(filters.from, 0) * 60000;
  const end = midnight + minute(filters.to, 1440) * 60000;
  return end > start && record.times.start < end && record.times.end > start;
}
function matchesTemporal(record, filters) {
  if (!filters.dates.length && !filters.from && !filters.to) return true;
  const days = filters.dates.length ? filters.dates : DAYS;
  return days.some((day) => matchesDayWindow(record, day, filters));
}
function matcher(filters, plan) {
  const tokens = normalize(filters.query).split(" ").filter(Boolean);
  const planned = new Set(
    (Array.isArray(plan) ? plan : []).map((item) => item?.placement),
  );
  return (record) =>
    tokens.every((token) => String(record.search || "").includes(token)) &&
    (!filters.planOnly || planned.has(record.placement)) &&
    DISCOVERY_DIMENSIONS.every(
      (dimension) =>
        dimension === "dates" ||
        !filters[dimension].length ||
        filters[dimension].some((value) =>
          valuesFor(record, dimension).includes(value),
        ),
    ) &&
    matchesTemporal(record, filters);
}

/** OR within each selected dimension; AND across dimensions and search tokens. */
export function filterDiscovery(records, filters = {}, plan = []) {
  const match = matcher(normaliseFilters(filters), plan);
  // Return the input records so selection identity remains stable across filtering.
  return records.filter((record) => match(projected(record)));
}

function mergeProvenance(target, entries = []) {
  for (const entry of entries) {
    if (
      !target.some(
        (item) =>
          item.source === entry.source &&
          item.field === entry.field &&
          item.value === entry.value,
      )
    )
      target.push({ ...entry });
  }
}

/** Counts exclude only this dimension, retaining query, plan, time and other filters. */
export function facetChoices(
  records,
  filters = {},
  plan = [],
  dimension,
  taxonomy = [],
) {
  if (!dimensions.has(dimension)) return [];
  const state = normaliseFilters(filters);
  const projectedRecords = records.map(projected);
  const choices = new Map();
  const add = (value, label = value, extra = {}) => {
    if (typeof value !== "string" || !value) return;
    const existing = choices.get(value);
    if (existing) {
      mergeProvenance(existing.provenance, extra.provenance);
      return;
    }
    const option = {
      value,
      label: String(label || value),
      count: 0,
      ...extra,
      provenance: [],
    };
    mergeProvenance(option.provenance, extra.provenance);
    choices.set(value, option);
  };
  if (dimension === "topics") {
    for (const topic of Array.isArray(taxonomy) ? taxonomy : [])
      add(topic.id, topic.label || topic.id, {
        category: "topic",
        provenance: [
          { source: "system", field: "system_topics", value: topic.id },
        ],
      });
  }
  if (dimension === "dates") for (const day of DAYS) add(day, dayLabel(day));
  for (const record of projectedRecords) {
    if (dimension === "tags" || dimension === "types") {
      const facets =
        dimension === "tags" ? record.officialFacets : record.formatFacets;
      for (const facet of facets)
        add(dimension === "tags" ? facet.key : facet.label, facet.label, {
          category: facet.category,
          provenance: facet.provenance,
        });
    } else if (dimension === "venues") {
      add(record.venue?.id || "unmapped", record.venue?.name || "未定位會場");
    } else {
      for (const value of valuesFor(record, dimension))
        add(
          value,
          value,
          dimension === "companies"
            ? {
                provenance: [
                  {
                    source: "text_match",
                    field: "derived_company_matches",
                    value,
                  },
                ],
              }
            : {},
        );
    }
  }
  for (const value of state[dimension]) add(value);
  const otherFilters = { ...state, [dimension]: [] };
  const candidates = projectedRecords.filter(matcher(otherFilters, plan));
  for (const option of choices.values()) {
    option.count = candidates.reduce(
      (count, record) =>
        count +
        Number(
          dimension === "dates"
            ? matchesDayWindow(record, option.value, state)
            : valuesFor(record, dimension).includes(option.value),
        ),
      0,
    );
  }
  return [...choices.values()].sort(
    (a, b) => a.label.localeCompare(b.label) || a.value.localeCompare(b.value),
  );
}
