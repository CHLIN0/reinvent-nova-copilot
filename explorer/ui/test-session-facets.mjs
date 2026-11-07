import { test } from "node:test";
import assert from "node:assert/strict";
import { sessionFacets } from "./src/session-facets.mjs";

test("official native dimensions supersede only identical field-prefixed flattened tags", () => {
  const session = {
    source: "aws_events_api",
    topics: ["Agentic AI"],
    areasOfInterest: ["Agentic AI"],
    services: ["Amazon Bedrock"],
    roles: ["Developer / Engineer"],
    features: ["Example feature"],
    tags: [
      "topics: Agentic AI",
      "areasOfInterest: Agentic AI",
      "services: Amazon Bedrock",
      "roles: Developer / Engineer",
      "features: Example feature",
      "topics: Unmapped topic",
      "Unknown raw label",
    ],
  };
  const before = structuredClone(session);
  const facets = sessionFacets(session);
  assert.deepEqual(session, before);
  const topic = facets.filter((f) => f.label === "Agentic AI");
  assert.equal(topic.length, 1);
  assert.equal(topic[0].category, "topic");
  assert.deepEqual(topic[0].evidence, ["topics", "areasOfInterest"]);
  assert.ok(topic[0].aliases.includes("official:topics: Agentic AI"));
  assert.ok(!facets.some((f) => f.label === "topics: Agentic AI"));
  assert.equal(
    facets.find((f) => f.label === "Amazon Bedrock").category,
    "service",
  );
  assert.equal(
    facets.find((f) => f.label === "Developer / Engineer").category,
    "audience",
  );
  assert.equal(
    facets.filter((f) => f.label === "features: Example feature").length,
    1,
  );
  assert.deepEqual(
    facets.find((f) => f.label === "features: Example feature").provenance,
    [{ source: "official", field: "features", value: "Example feature" }],
  );
  assert.ok(facets.some((f) => f.label === "topics: Unmapped topic"));
  assert.ok(facets.some((f) => f.label === "Unknown raw label"));
});

test("legacy prefixed raw tags retain their original evidence", () => {
  const facets = sessionFacets({
    source: "rainfocus",
    topics: ["Agentic AI"],
    tags: ["topics: Agentic AI"],
  });
  assert.ok(
    facets.some(
      (f) => f.label === "topics: Agentic AI" && f.evidence.includes("tags"),
    ),
  );
});
