import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import {
  buildCampus,
  geometryFor,
  inside,
  metres,
  stitch,
  VENUE_BINDINGS,
} from "./build-map.mjs";
import { layoutVenueLabels } from "./src/scene.mjs";
const source = JSON.parse(
  await readFile(
    new URL(
      "../data/osm/osm-public-sample.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
const audit = JSON.parse(
  await readFile(
    new URL(
      "../data/osm/geometry-audit.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
const { campus, manifest } = buildCampus(source, audit);
const feature = (ref) => campus.features.find((f) => f.id === ref);
const element = (ref) =>
  source.elements.find((e) => `${e.type}/${e.id}` === ref);
const ringArea = (ring) =>
  ring
    .slice(1)
    .reduce((sum, p, i) => sum + ring[i][0] * p[1] - p[0] * ring[i][1], 0) / 2;

test("all six venues bind exactly to audited feature IDs, excluding similarly named station", () => {
  assert.equal(manifest.venues.length, 6);
  assert.deepEqual(
    new Set(Object.values(VENUE_BINDINGS).flat()),
    new Set(audit.venues.flatMap((v) => v.features.map((f) => f.reference))),
  );
  for (const [id, refs] of Object.entries(VENUE_BINDINGS))
    for (const ref of refs) assert.equal(feature(ref).properties.venue_id, id);
  assert.equal(element("way/1557762828").tags.railway, "station");
  assert.notEqual(feature("way/1557762828")?.properties.venue_id, "mgm");
  const unnamed = feature("way/115093734");
  assert.equal(unnamed.properties.name, null);
  assert.equal(
    unnamed.properties.identity_status,
    "unnamed-spatial-association",
  );
  assert.equal(unnamed.properties.room_geometry, "unverified");
});

test("actual Venetian relation retains its exact courtyard hole and RFC7946 winding", () => {
  const osm = element("relation/7770314");
  const result = feature("relation/7770314").geometry;
  assert.equal(result.type, "Polygon");
  assert.equal(result.coordinates.length, 2);
  const sourceHole = osm.members
    .find((m) => m.role === "inner")
    .geometry.map((p) => [p.lon, p.lat]);
  assert.deepEqual(
    new Set(result.coordinates[1].map((p) => p.join(","))),
    new Set(sourceHole.map((p) => p.join(","))),
  );
  assert.ok(ringArea(result.coordinates[0]) > 0);
  assert.ok(ringArea(result.coordinates[1]) < 0);
});

test("actual multi-building relation assigns each courtyard to its containing outer ring", () => {
  const result = geometryFor(element("relation/1631815"));
  assert.equal(result.type, "MultiPolygon");
  assert.equal(result.coordinates.length, 5);
  assert.equal(
    result.coordinates.reduce((sum, polygon) => sum + polygon.length - 1, 0),
    4,
  );
  for (const polygon of result.coordinates)
    for (const hole of polygon.slice(1)) assert.ok(inside(hole[0], polygon[0]));
});

test("heights use explicit metric tags only; even two or fifty-two floors cannot infer height", () => {
  assert.equal(feature("way/116770006").properties.levels_raw, "2");
  assert.equal(feature("way/116770006").properties.height_m, null);
  assert.equal(
    feature("way/116770006").properties.height_status,
    "unknown-flat",
  );
  assert.equal(feature("way/762169780").properties.height_m, null);
  assert.equal(feature("way/30618090").properties.height_m, 145);
  assert.equal(feature("way/115093734").properties.height_m, 89);
  assert.equal(feature("way/27910891").properties.height_m, 192);
  const levelsOnly = structuredClone(source);
  delete levelsOnly.elements.find((e) => e.type === "way" && e.id === 27910891)
    .tags.height;
  const withoutHeight = buildCampus(levelsOnly, audit).campus.features.find(
    (f) => f.id === "way/27910891",
  );
  assert.equal(withoutHeight.properties.levels_raw, "52");
  assert.equal(withoutHeight.properties.height_m, null);
  assert.equal(withoutHeight.properties.height_status, "unknown-flat");
  assert.equal(feature("way/136516661").properties.min_height_m, 20);
  assert.equal(metres("52 floors"), null);
  assert.equal(metres("160 ft"), null);
  assert.equal(metres("89 m"), 89);
  assert.equal(metres(undefined), null);
});

test("every output ring is closed, finite, and derived without fabricated closure", () => {
  for (const f of campus.features) {
    const polygons =
      f.geometry.type === "MultiPolygon"
        ? f.geometry.coordinates
        : f.geometry.type === "Polygon"
          ? [f.geometry.coordinates]
          : [];
    for (const polygon of polygons)
      for (const ring of polygon) {
        assert.deepEqual(ring[0], ring.at(-1));
        assert.ok(ring.length >= 4);
        assert.ok(
          ring.every((p) => p.length === 2 && p.every(Number.isFinite)),
        );
      }
  }
  const ring = feature("way/30618090").geometry.coordinates[0];
  const cut = Math.floor(ring.length / 2);
  assert.deepEqual(stitch([ring.slice(0, cut + 1), ring.slice(cut)])[0], ring);
  assert.throws(
    () =>
      stitch([
        [
          [0, 0],
          [1, 1],
          [2, 0],
        ],
      ]),
    /Incomplete/,
  );
});

test("roads preserve every named source segment and source geometry", () => {
  const roads = source.elements.filter(
    (e) =>
      e.type === "way" &&
      e.tags?.highway &&
      e.tags?.name &&
      e.geometry?.length >= 2,
  );
  assert.equal(manifest.road_count, roads.length);
  for (const road of roads) {
    const built = feature(`way/${road.id}`);
    assert.equal(built.properties.name, road.tags.name);
    assert.deepEqual(
      built.geometry.coordinates,
      road.geometry.map((p) => [p.lon, p.lat]),
    );
  }
});

test("generated public data is deterministic and carries attribution plus observation time", async () => {
  assert.deepEqual(buildCampus(source, audit), { campus, manifest });
  assert.equal(manifest.source_timestamp, "2026-10-24T14:41:20Z");
  assert.match(manifest.attribution, /OpenStreetMap/);
  assert.equal(manifest.license, "ODbL 1.0");
  assert.deepEqual(
    JSON.parse(
      await readFile(
        new URL("./public/geo/campus.json", import.meta.url),
        "utf8",
      ),
    ),
    campus,
  );
  assert.deepEqual(
    JSON.parse(
      await readFile(
        new URL("./public/geo/manifest.json", import.meta.url),
        "utf8",
      ),
    ),
    manifest,
  );
});

test("campus overview labels remain deterministic, bounded and separate in narrow map panes", () => {
  for (const width of [350, 550, 900])
    for (const height of [290, 330, 520]) {
      const points = [
        { id: "encore", x: width * 0.58, y: 104 },
        { id: "wynn", x: width * 0.57, y: 114 },
        { id: "venetian", x: width * 0.53, y: 137 },
        { id: "forum", x: width * 0.56, y: 153 },
        { id: "palace", x: width * 0.43, y: 158 },
        { id: "mgm", x: width * 0.53, y: height - 60 },
      ].map((p) => ({ ...p, width: 136, height: 40 }));
      const result = layoutVenueLabels(points, { width, height });
      assert.deepEqual(result, layoutVenueLabels(points, { width, height }));
      for (const label of result) {
        assert.ok(label.x - label.width / 2 >= 9);
        assert.ok(label.x + label.width / 2 <= width - 9);
        assert.ok(label.y - label.height / 2 >= 91);
        assert.ok(label.y + label.height / 2 <= height - 24);
        for (const other of result.filter((l) => l.id !== label.id)) {
          const separatedX =
            Math.abs(label.x - other.x) >= (label.width + other.width) / 2 + 7;
          const separatedY =
            Math.abs(label.y - other.y) >=
            (label.height + other.height) / 2 + 7;
          assert.ok(
            separatedX || separatedY,
            `${width}×${height}: ${label.id} overlaps ${other.id}`,
          );
        }
      }
    }
});
