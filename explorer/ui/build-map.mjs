/** Build only from the checked-in public OSM snapshot. Never contacts a provider. */
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve, dirname } from "node:path";

const root = dirname(fileURLToPath(import.meta.url));
export const VENUE_BINDINGS = {
  venetian: ["relation/7770314", "way/30618090", "way/111367819"],
  forum: ["way/762169780"],
  palace: ["way/115672893", "way/134949715"],
  mgm: ["way/116770006", "way/27897924", "way/115093734"],
  wynn: ["way/205501268"],
  encore: ["way/135291730", "way/27910891"],
};
const COLORS = {
  venetian: "#497dc4",
  forum: "#b97a35",
  palace: "#8b6ab4",
  mgm: "#268879",
  wynn: "#b85c75",
  encore: "#827335",
};
export function metres(raw) {
  if (raw === undefined || raw === null) return null;
  const match = String(raw)
    .trim()
    .match(/^(\d+(?:\.\d+)?)\s*(?:m|meters?|metres?)?$/i);
  return match && Number(match[1]) > 0 ? Number(match[1]) : null;
}
const same = (a, b) => a[0] === b[0] && a[1] === b[1];
const coords = (geometry) => (geometry || []).map((p) => [p.lon, p.lat]);
const signedArea = (ring) =>
  ring
    .slice(1)
    .reduce((n, p, i) => n + ring[i][0] * p[1] - p[0] * ring[i][1], 0) / 2;
const wind = (ring, outer) =>
  signedArea(ring) > 0 === outer ? ring : [...ring].reverse();
export function inside(point, ring) {
  let yes = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const a = ring[i],
      b = ring[j];
    if (
      a[1] > point[1] !== b[1] > point[1] &&
      point[0] < ((b[0] - a[0]) * (point[1] - a[1])) / (b[1] - a[1]) + a[0]
    )
      yes = !yes;
  }
  return yes;
}
/** Join actual member endpoints; never close incomplete ways with invented edges. */
export function stitch(parts) {
  const pending = parts.map((p) => p.slice()).filter((p) => p.length >= 2),
    rings = [];
  while (pending.length) {
    let ring = pending.shift(),
      changed = true;
    while (!same(ring[0], ring.at(-1)) && changed) {
      changed = false;
      for (let i = 0; i < pending.length; i++) {
        let p = pending[i];
        if (same(ring.at(-1), p[0])) ring.push(...p.slice(1));
        else if (same(ring.at(-1), p.at(-1)))
          ring.push(...p.slice(0, -1).reverse());
        else if (same(ring[0], p.at(-1))) ring.unshift(...p.slice(0, -1));
        else if (same(ring[0], p[0])) ring.unshift(...p.slice(1).reverse());
        else continue;
        pending.splice(i, 1);
        changed = true;
        break;
      }
    }
    if (
      ring.length >= 4 &&
      same(ring[0], ring.at(-1)) &&
      Math.abs(signedArea(ring)) > 0
    )
      rings.push(ring);
    else
      throw new Error(
        "Incomplete or degenerate source polygon; refusing to fabricate closure",
      );
  }
  return rings;
}
export function geometryFor(element) {
  if (element.type === "way") {
    const rings = stitch([coords(element.geometry)]);
    return { type: "Polygon", coordinates: [wind(rings[0], true)] };
  }
  const outer = stitch(
    (element.members || [])
      .filter((m) => m.type === "way" && m.role !== "inner")
      .map((m) => coords(m.geometry)),
  );
  const inner = stitch(
    (element.members || [])
      .filter((m) => m.type === "way" && m.role === "inner")
      .map((m) => coords(m.geometry)),
  );
  if (!outer.length) throw new Error(`No outer ring: ${element.id}`);
  const polygons = outer.map((r) => [wind(r, true)]);
  for (const hole of inner) {
    const containers = outer
      .map((r, i) => ({ r, i }))
      .filter(({ r }) => inside(hole[0], r))
      .sort((a, b) => Math.abs(signedArea(a.r)) - Math.abs(signedArea(b.r)));
    if (!containers.length)
      throw new Error(`Uncontained source hole: ${element.id}`);
    polygons[containers[0].i].push(wind(hole, false));
  }
  return {
    type: polygons.length === 1 ? "Polygon" : "MultiPolygon",
    coordinates: polygons.length === 1 ? polygons[0] : polygons,
  };
}
function extent(geometry) {
  const pairs =
    geometry.type === "LineString"
      ? geometry.coordinates
      : geometry.type === "Polygon"
        ? geometry.coordinates.flat()
        : geometry.coordinates.flat(2);
  return [
    Math.min(...pairs.map((p) => p[0])),
    Math.min(...pairs.map((p) => p[1])),
    Math.max(...pairs.map((p) => p[0])),
    Math.max(...pairs.map((p) => p[1])),
  ];
}
export function buildCampus(source, audit) {
  const binding = new Map(
    Object.entries(VENUE_BINDINGS).flatMap(([id, refs]) =>
      refs.map((ref) => [ref, id]),
    ),
  );
  const expected = new Set(
    audit.venues.flatMap((v) => v.features.map((f) => f.reference)),
  );
  if (
    expected.size !== binding.size ||
    [...expected].some((ref) => !binding.has(ref))
  )
    throw new Error("Venue bindings differ from geometry audit");
  const relationMembers = new Set(
    source.elements
      .filter(
        (e) =>
          e.type === "relation" &&
          (e.tags?.building || e.tags?.["building:part"]),
      )
      .flatMap((e) =>
        (e.members || []).filter((m) => m.type === "way").map((m) => m.ref),
      ),
  );
  const features = [];
  for (const e of source.elements) {
    const tags = e.tags || {},
      ref = `${e.type}/${e.id}`,
      venue = binding.get(ref) || null;
    if (
      (tags.building || tags["building:part"]) &&
      e.type !== "node" &&
      (!relationMembers.has(e.id) || e.type === "relation" || venue)
    ) {
      const height = metres(tags.height),
        minimum = metres(tags.min_height);
      const geometry = geometryFor(e);
      features.push({
        type: "Feature",
        id: ref,
        properties: {
          kind: "building",
          source_id: ref,
          name: tags.name || null,
          venue_id: venue,
          color: COLORS[venue] || "#a6afb8",
          building_part: !!tags["building:part"],
          height_m: height,
          min_height_m:
            height !== null && minimum !== null && minimum < height
              ? minimum
              : 0,
          height_raw: tags.height || null,
          height_status: height === null ? "unknown-flat" : "community-tag",
          levels_raw: tags["building:levels"] || null,
          identity_status:
            ref === "way/115093734"
              ? "unnamed-spatial-association"
              : venue
                ? "named-source-candidate"
                : "background-source",
          room_geometry: "unverified",
        },
        geometry,
      });
    } else if (
      e.type === "way" &&
      tags.highway &&
      tags.name &&
      e.geometry?.length >= 2
    ) {
      features.push({
        type: "Feature",
        id: ref,
        properties: {
          kind: "road",
          source_id: ref,
          name: tags.name,
          road_class: tags.highway,
          major: [
            "motorway",
            "trunk",
            "primary",
            "secondary",
            "tertiary",
          ].includes(tags.highway),
        },
        geometry: { type: "LineString", coordinates: coords(e.geometry) },
      });
    }
  }
  for (const ref of binding.keys())
    if (!features.some((f) => f.id === ref))
      throw new Error(`Missing required venue footprint ${ref}`);
  const venues = Object.entries(VENUE_BINDINGS).map(([id, refs]) => {
    const bounds = refs.map((ref) =>
      extent(features.find((f) => f.id === ref).geometry),
    );
    const b = [
      Math.min(...bounds.map((b) => b[0])),
      Math.min(...bounds.map((b) => b[1])),
      Math.max(...bounds.map((b) => b[2])),
      Math.max(...bounds.map((b) => b[3])),
    ];
    return {
      id,
      source_ids: refs,
      bounds: [
        [b[0], b[1]],
        [b[2], b[3]],
      ],
      center: [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2],
    };
  });
  const roadNames = [
    "South Las Vegas Boulevard",
    "East Flamingo Road",
    "West Flamingo Road",
    "Sands Avenue",
    "Koval Lane",
    "Paradise Road",
    "East Tropicana Avenue",
    "Spring Mountain Road",
    "East Desert Inn Road",
  ];
  const streetLabels = roadNames.flatMap((name) => {
    const candidates = features.filter(
      (f) => f.properties.kind === "road" && f.properties.name === name,
    );
    if (!candidates.length) return [];
    const longest = candidates.sort(
      (a, b) => b.geometry.coordinates.length - a.geometry.coordinates.length,
    )[0];
    return [
      {
        name,
        center:
          longest.geometry.coordinates[
            Math.floor(longest.geometry.coordinates.length / 2)
          ],
        source_id: longest.id,
      },
    ];
  });
  const campus = { type: "FeatureCollection", features };
  const manifest = {
    version: 1,
    source: "Saved public OpenStreetMap / Overpass sample",
    source_file:
      "data/osm/osm-public-sample.json",
    source_timestamp: source.osm3s.timestamp_osm_base,
    attribution: "© OpenStreetMap contributors",
    license: "ODbL 1.0",
    license_url: "https://www.openstreetmap.org/copyright",
    geometry_policy:
      "Actual source polygons, stitched multipolygons and holes; no synthetic building or room geometry.",
    height_policy:
      "Only explicit metric community height tags are extruded. Unknown heights stay flat; levels, layer and elevation never infer height.",
    identity_policy:
      "Venue bindings follow geometry-audit.json. Unnamed MGM building part is spatial evidence only; station way/1557762828 is excluded from venue bindings.",
    feature_count: features.length,
    building_count: features.filter((f) => f.properties.kind === "building")
      .length,
    road_count: features.filter((f) => f.properties.kind === "road").length,
    venues,
    street_labels: streetLabels,
  };
  return { campus, manifest };
}
export async function writeCampus() {
  const source = JSON.parse(
    await readFile(
      resolve(
        root,
        "../data/osm/osm-public-sample.json",
      ),
      "utf8",
    ),
  );
  const audit = JSON.parse(
    await readFile(
      resolve(
        root,
        "../data/osm/geometry-audit.json",
      ),
      "utf8",
    ),
  );
  const { campus, manifest } = buildCampus(source, audit);
  await mkdir(resolve(root, "public/geo"), { recursive: true });
  await writeFile(
    resolve(root, "public/geo/campus.json"),
    JSON.stringify(campus) + "\n",
  );
  await writeFile(
    resolve(root, "public/geo/manifest.json"),
    JSON.stringify(manifest, null, 2) + "\n",
  );
  console.log(
    `Public map: ${manifest.building_count} buildings + ${manifest.road_count} named road segments, ${Buffer.byteLength(JSON.stringify(campus))} bytes`,
  );
}
if (
  process.argv[1] &&
  resolve(process.argv[1]) === fileURLToPath(import.meta.url)
)
  await writeCampus();
