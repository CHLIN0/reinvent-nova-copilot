import * as maplibregl from "maplibre-gl";

// Identity is explicitly bound to audited OSM IDs; labels never infer a meeting room.
export const VENUES = [
  {
    id: "venetian",
    name: "Venetian",
    color: "#497dc4",
    center: [-115.16753865, 36.12180245],
    bounds: [
      [-115.1707693, 36.1201194],
      [-115.164308, 36.1234855],
    ],
    aliases: ["The Venetian", "Venetian Expo"],
  },
  {
    id: "forum",
    name: "Caesars Forum",
    color: "#b97a35",
    center: [-115.1661886, 36.11893695],
    bounds: [
      [-115.1679836, 36.1180197],
      [-115.1643936, 36.1198542],
    ],
    aliases: ["CAESARS FORUM"],
  },
  {
    id: "palace",
    name: "Caesars Palace",
    color: "#8b6ab4",
    center: [-115.17665295, 36.11662475],
    bounds: [
      [-115.1794537, 36.1150138],
      [-115.1738522, 36.1182357],
    ],
    aliases: ["Caesars Palace Convention Center"],
  },
  {
    id: "mgm",
    name: "MGM Grand",
    color: "#268879",
    center: [-115.16830025, 36.10319275],
    bounds: [
      [-115.1725194, 36.1011552],
      [-115.1640811, 36.1052303],
    ],
    aliases: ["MGM", "MGM Grand Conference Center"],
  },
  {
    id: "wynn",
    name: "Wynn",
    color: "#b85c75",
    center: [-115.1656312, 36.1266511],
    bounds: [
      [-115.1660161, 36.125622],
      [-115.1652463, 36.1276802],
    ],
    aliases: ["Wynn Las Vegas"],
  },
  {
    id: "encore",
    name: "Encore",
    color: "#827335",
    center: [-115.16446655, 36.12831185],
    bounds: [
      [-115.166579, 36.1265346],
      [-115.1623541, 36.1300891],
    ],
    aliases: ["Encore Las Vegas"],
  },
];
const CAMPUS_BOUNDS = [
  [-115.1794537, 36.1011552],
  [-115.1623541, 36.1300891],
];
const DATA_NOTE =
  "OpenStreetMap 公開建築輪廓 · 高度僅依社群公尺標籤；未知高度維持平面。會議翼、房間與入口未核實。";
const buildingFilter = ["==", ["get", "kind"], "building"];
const roadFilter = ["==", ["get", "kind"], "road"];
const taggedHeight = [">", ["coalesce", ["get", "height_m"], 0], 0];
const roadWidth = [
  "interpolate",
  ["linear"],
  ["zoom"],
  11,
  ["case", ["get", "major"], 1.3, 0.55],
  14,
  ["case", ["get", "major"], 7, 2.5],
  17,
  ["case", ["get", "major"], 25, 10],
];
const style = {
  version: 8,
  sources: {
    campus: {
      type: "geojson",
      data: "/geo/campus.json",
      attribution:
        '© <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap contributors</a>',
      generateId: false,
    },
  },
  layers: [
    {
      id: "ground",
      type: "background",
      paint: { "background-color": "#e7ebe8" },
    },
    {
      id: "road-edge",
      type: "line",
      source: "campus",
      filter: roadFilter,
      layout: { "line-join": "round", "line-cap": "round" },
      paint: {
        "line-color": "#c2cbc9",
        "line-width": [
          "interpolate",
          ["linear"],
          ["zoom"],
          11,
          ["case", ["get", "major"], 3.1, 2.35],
          14,
          ["case", ["get", "major"], 8.8, 4.3],
          17,
          ["case", ["get", "major"], 26.8, 11.8],
        ],
      },
    },
    {
      id: "roads",
      type: "line",
      source: "campus",
      filter: roadFilter,
      layout: { "line-join": "round", "line-cap": "round" },
      paint: { "line-color": "#fafbf8", "line-width": roadWidth },
    },
    {
      id: "building-land",
      type: "fill",
      source: "campus",
      filter: buildingFilter,
      paint: {
        "fill-color": ["get", "color"],
        "fill-opacity": ["case", ["!=", ["get", "venue_id"], null], 0.55, 0.55],
      },
    },
    {
      id: "building-outline",
      type: "line",
      source: "campus",
      filter: buildingFilter,
      paint: {
        "line-color": [
          "case",
          ["!=", ["get", "venue_id"], null],
          ["get", "color"],
          "#7d898d",
        ],
        "line-width": [
          "interpolate",
          ["linear"],
          ["zoom"],
          11,
          0.5,
          15,
          1.2,
          18,
          1.7,
        ],
        "line-opacity": 0.85,
      },
    },
    {
      id: "building-heights",
      type: "fill-extrusion",
      source: "campus",
      filter: ["all", buildingFilter, taggedHeight],
      paint: {
        "fill-extrusion-color": [
          "case",
          ["!=", ["get", "venue_id"], null],
          ["get", "color"],
          "#adb7bf",
        ],
        "fill-extrusion-height": ["get", "height_m"],
        "fill-extrusion-base": ["get", "min_height_m"],
        "fill-extrusion-opacity": 0.87,
        "fill-extrusion-vertical-gradient": true,
      },
    },
    {
      id: "selected-land",
      type: "fill",
      source: "campus",
      filter: ["==", ["get", "venue_id"], "__none__"],
      paint: { "fill-color": ["get", "color"], "fill-opacity": 0.8 },
    },
    {
      id: "selected-heights",
      type: "fill-extrusion",
      source: "campus",
      filter: ["all", ["==", ["get", "venue_id"], "__none__"], taggedHeight],
      paint: {
        "fill-extrusion-color": ["get", "color"],
        "fill-extrusion-height": ["get", "height_m"],
        "fill-extrusion-base": ["get", "min_height_m"],
        "fill-extrusion-opacity": 1,
        "fill-extrusion-vertical-gradient": true,
      },
    },
    {
      id: "selected-outline",
      type: "line",
      source: "campus",
      filter: ["==", ["get", "venue_id"], "__none__"],
      paint: { "line-color": "#172f43", "line-width": 3, "line-opacity": 1 },
    },
  ],
  light: {
    anchor: "viewport",
    color: "#fff7e5",
    intensity: 0.42,
    position: [1.15, 210, 45],
  },
};

let sceneSequence = 0;
const LABEL_OFFSETS = {
  encore: [78, -12],
  wynn: [-83, 10],
  venetian: [78, 12],
  palace: [-82, 12],
  forum: [90, 32],
  mgm: [-70, 12],
};
const LABEL_ORDER = ["encore", "wynn", "venetian", "palace", "forum", "mgm"];
/** Deterministic screen-space placement: real anchors stay fixed, labels avoid one another. */
export function layoutVenueLabels(
  points,
  { width, height, top = 91, padding = 9, gap = 7 },
) {
  const placed = [];
  for (const point of [...points].sort(
    (a, b) => LABEL_ORDER.indexOf(a.id) - LABEL_ORDER.indexOf(b.id),
  )) {
    const w = point.width,
      h = point.height,
      halfW = w / 2,
      halfH = h / 2;
    const minX = padding + halfW,
      maxX = Math.max(minX, width - padding - halfW),
      minY = top + halfH,
      maxY = Math.max(minY, height - 24 - halfH);
    const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
    const preferred = LABEL_OFFSETS[point.id] || [0, -12];
    const ideal = {
      x: clamp(point.x + preferred[0], minX, maxX),
      y: clamp(point.y + preferred[1], minY, maxY),
    };
    const candidates = [ideal];
    for (let y = minY; y <= maxY; y += 10)
      for (let x = minX; x <= maxX; x += 16) candidates.push({ x, y });
    candidates.push({ x: maxX, y: maxY }, { x: minX, y: maxY });
    let best = null,
      bestScore = Infinity;
    for (const candidate of candidates) {
      const overlap = placed.reduce((sum, other) => {
        const dx =
          (w + other.width) / 2 + gap - Math.abs(candidate.x - other.x);
        const dy =
          (h + other.height) / 2 + gap - Math.abs(candidate.y - other.y);
        return sum + (dx > 0 && dy > 0 ? dx * dy : 0);
      }, 0);
      const score =
        overlap * 1e7 +
        (candidate.x - ideal.x) ** 2 +
        (candidate.y - ideal.y) ** 2 +
        0.15 * ((candidate.x - point.x) ** 2 + (candidate.y - point.y) ** 2);
      if (score < bestScore) {
        bestScore = score;
        best = candidate;
      }
    }
    placed.push({
      ...point,
      ...best,
      offset: [best.x - point.x, best.y - point.y],
    });
  }
  return placed;
}

export function createScene({
  container,
  onVenueSelect = () => {},
  onStatus = () => {},
}) {
  if (!container) throw new Error("Map container is required");
  let map = null,
    loaded = false,
    destroyed = false,
    selected = null,
    pitchMode = 50,
    observer;
  let settleReady;
  const ready = new Promise((resolve) => {
    settleReady = resolve;
  });
  const venueMarkers = new Map(),
    streetMarkers = [];
  const instance = `scene-${++sceneSequence}`;
  container.dataset.sceneStatus = "loading";
  container.dataset.sceneInstance = instance;
  let leaderOverlay;
  function publishCamera() {
    const camera = getCamera();
    if (!camera) return;
    container.dataset.scenePitch = String(+camera.pitch.toFixed(3));
    container.dataset.sceneBearing = String(+camera.bearing.toFixed(3));
    container.dataset.sceneCenter = JSON.stringify(
      camera.center.map((n) => +n.toFixed(7)),
    );
    container.dataset.sceneZoom = String(+camera.zoom.toFixed(5));
    container.dataset.sceneSelection = selected || "";
  }
  function positionVenueLabels() {
    if (!map || !loaded || !venueMarkers.size) return;
    const { width, height } = container.getBoundingClientRect();
    const points = [...venueMarkers.values()].map((item) => {
      const point = map.project(item.venue.center),
        box = item.element.getBoundingClientRect();
      return {
        id: item.venue.id,
        x: point.x,
        y: point.y,
        width: box.width || 136,
        height: box.height || 41,
      };
    });
    for (const placement of layoutVenueLabels(points, { width, height })) {
      const item = venueMarkers.get(placement.id),
        anchor = map.project(item.venue.center);
      item.marker.setOffset(placement.offset);
      const dx = placement.x - anchor.x,
        dy = placement.y - anchor.y;
      const ratio = Math.min(
        dx ? placement.width / (2 * Math.abs(dx)) : Infinity,
        dy ? placement.height / (2 * Math.abs(dy)) : Infinity,
      );
      item.leader.setAttribute("x1", String(anchor.x));
      item.leader.setAttribute("y1", String(anchor.y));
      item.leader.setAttribute(
        "x2",
        String(placement.x - dx * Math.min(1, ratio)),
      );
      item.leader.setAttribute(
        "y2",
        String(placement.y - dy * Math.min(1, ratio)),
      );
      item.leader.setAttribute("visibility", ratio >= 1 ? "hidden" : "visible");
    }
  }
  const reduced = () =>
    globalThis.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
  const motion = () => (reduced() ? 0 : 650);
  const status = (message) => {
    if (!destroyed) onStatus(message);
  };
  const fail = (reason) => {
    if (destroyed) return;
    loaded = false;
    container.dataset.sceneStatus = "unavailable";
    if (map) {
      map.remove();
      map = null;
    }
    const fallback = document.createElement("div");
    fallback.className = "map-fallback";
    fallback.setAttribute("role", "status");
    fallback.textContent = `地理地圖無法顯示：${reason}。仍可使用場館清單、篩選與行事曆。${DATA_NOTE}`;
    container.replaceChildren(fallback);
    status(`地圖無法顯示：${reason}`);
    settleReady({ available: false, reason });
  };
  const updateMarkers = () => {
    for (const [id, item] of venueMarkers) {
      item.element.classList.toggle("is-selected", id === selected);
      item.element.setAttribute("aria-pressed", String(id === selected));
    }
    for (const item of streetMarkers)
      item.element.hidden = !map || map.getZoom() < 13.3;
  };
  function setSelection(venueId, { focus = false } = {}) {
    selected = VENUES.some((v) => v.id === venueId) ? venueId : null;
    if (!loaded || !map) return;
    const selection = ["==", ["get", "venue_id"], selected || "__none__"];
    map.setFilter("selected-land", selection);
    map.setFilter("selected-outline", selection);
    map.setFilter("selected-heights", ["all", selection, taggedHeight]);
    updateMarkers();
    publishCamera();
    const venue = VENUES.find((v) => v.id === selected);
    status(
      venue
        ? `${venue.name}：顯示已核對來源的建築範圍；議程位置仍以場館為單位，房間／會議區未定位。高度僅採用社群公尺標籤。`
        : DATA_NOTE,
    );
    if (focus && venue)
      map.fitBounds(venue.bounds, {
        padding: 72,
        maxZoom: 16,
        pitch: map.getPitch(),
        bearing: map.getBearing(),
        duration: motion(),
      });
  }
  function setVisibleVenueCounts(counts = {}) {
    for (const [id, item] of venueMarkers) {
      const value = counts instanceof Map ? counts.get(id) : counts[id];
      const count = Number.isFinite(Number(value))
        ? Math.max(0, Math.trunc(Number(value)))
        : 0;
      item.count.textContent = String(count);
      item.element.setAttribute(
        "aria-label",
        `${item.venue.name}，目前篩選 ${count} 場議程；會議區高度未知，房間未定位`,
      );
    }
  }
  function setPitch(mode) {
    pitchMode =
      mode === "2d" || mode === "2D" || mode === 0 || mode === "flat" ? 0 : 50;
    // A camera-only change: no map, source, marker, or selection re-creation.
    if (map) map.easeTo({ pitch: pitchMode, duration: motion() });
  }
  function resize() {
    if (map && !destroyed) {
      map.resize();
      positionVenueLabels();
      publishCamera();
    }
  }
  function reset() {
    if (map) map.easeTo({ bearing: 0, duration: motion() });
  }
  function getCamera() {
    if (!map) return null;
    const center = map.getCenter();
    return {
      center: [center.lng, center.lat],
      zoom: map.getZoom(),
      pitch: map.getPitch(),
      bearing: map.getBearing(),
      selection: selected,
    };
  }
  function destroy() {
    destroyed = true;
    container.dataset.sceneStatus = "unavailable";
    observer?.disconnect();
    venueMarkers.clear();
    streetMarkers.length = 0;
    if (map) {
      map.remove();
      map = null;
    }
    settleReady({ available: false, reason: "destroyed" });
  }
  status("載入公開地理資料…");
  try {
    // The bundled CSP-compatible worker is copied locally by build.mjs.
    maplibregl.setWorkerUrl("/maplibre-worker.js");
    map = new maplibregl.Map({
      container,
      style,
      center: [-115.169, 36.116],
      zoom: 13.3,
      bearing: 0,
      pitch: 50,
      maxPitch: 60,
      minZoom: 11,
      maxZoom: 19,
      attributionControl: { compact: true },
      renderWorldCopies: false,
      canvasContextAttributes: { antialias: true },
    });
    map.on("error", (event) => {
      const message = event.error?.message || "繪圖或資料載入失敗";
      if (!loaded) fail(message);
      else status(`地圖資料錯誤：${message}`);
    });
    map.on("webglcontextlost", () => fail("WebGL 繪圖內容遺失"));
    map.on("move", positionVenueLabels);
    map.on("moveend", () => {
      positionVenueLabels();
      publishCamera();
    });
    map.on("load", async () => {
      if (destroyed || !map) return;
      try {
        const response = await fetch("/geo/manifest.json");
        if (!response.ok) throw new Error("公開地圖來源資訊無法載入");
        const manifest = await response.json();
        if (destroyed || !map) return;
        leaderOverlay = document.createElementNS(
          "http://www.w3.org/2000/svg",
          "svg",
        );
        leaderOverlay.classList.add("venue-leaders");
        leaderOverlay.setAttribute("aria-hidden", "true");
        leaderOverlay.style.cssText =
          "position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:1;overflow:hidden";
        container.append(leaderOverlay);
        for (const venue of VENUES) {
          const element = document.createElement("button");
          element.type = "button";
          element.className = `venue-marker venue-marker--${venue.id}`;
          element.dataset.venue = venue.id;
          element.style.setProperty("--venue-color", venue.color);
          element.style.cssText +=
            ";margin:0;display:grid;grid-template-columns:1fr auto;gap:2px 7px;z-index:2;text-align:left";
          const name = document.createElement("span");
          name.className = "venue-marker__name";
          name.textContent = venue.name;
          const count = document.createElement("span");
          count.className = "venue-marker__count";
          count.textContent = "0";
          const heightNote = document.createElement("span");
          heightNote.className = "venue-marker__height";
          heightNote.textContent =
            venue.id === "forum" ? "高度未知" : "會議區高度未知";
          heightNote.style.cssText =
            "grid-column:1 / -1;font-size:9px;line-height:1.25;color:#63736e;font-weight:400";
          element.append(name, count, heightNote);
          element.addEventListener("click", () => {
            setSelection(venue.id);
            onVenueSelect(venue.id);
          });
          const marker = new maplibregl.Marker({
            element,
            anchor: "center",
            offset: [0, 0],
          })
            .setLngLat(venue.center)
            .addTo(map);
          const leader = document.createElementNS(
            "http://www.w3.org/2000/svg",
            "line",
          );
          leader.setAttribute("stroke", "#526a61");
          leader.setAttribute("stroke-width", "1");
          leader.setAttribute("stroke-opacity", ".5");
          leader.setAttribute("stroke-dasharray", "2 2");
          leaderOverlay.append(leader);
          venueMarkers.set(venue.id, { venue, marker, element, count, leader });
        }
        for (const street of manifest.street_labels) {
          const element = document.createElement("span");
          element.className = "street-label";
          element.textContent = street.name;
          element.setAttribute("aria-hidden", "true");
          element.style.cssText =
            "font:600 10px/1.2 system-ui;color:#4d5b60;text-shadow:0 1px 2px #fff,1px 0 2px #fff,-1px 0 2px #fff;pointer-events:none;white-space:nowrap";
          const marker = new maplibregl.Marker({ element, anchor: "center" })
            .setLngLat(street.center)
            .addTo(map);
          streetMarkers.push({ marker, element });
        }
        loaded = true;
        map.fitBounds(CAMPUS_BOUNDS, {
          padding: { top: 65, bottom: 28, left: 22, right: 22 },
          maxZoom: 14.4,
          pitch: pitchMode,
          bearing: 0,
          duration: 0,
        });
        map.on("zoomend", updateMarkers);
        map.on("click", (event) => {
          const found = map
            .queryRenderedFeatures(event.point, {
              layers: ["selected-heights", "building-heights", "building-land"],
            })
            .find((f) => f.properties?.venue_id);
          if (found) {
            setSelection(found.properties.venue_id);
            onVenueSelect(found.properties.venue_id);
          }
        });
        map.on("mousemove", (event) => {
          map.getCanvas().style.cursor = map
            .queryRenderedFeatures(event.point, {
              layers: ["building-land", "building-heights"],
            })
            .some((f) => f.properties?.venue_id)
            ? "pointer"
            : "";
        });
        container.dataset.sceneStatus = "ready";
        setSelection(selected);
        setVisibleVenueCounts(pendingCounts);
        updateMarkers();
        positionVenueLabels();
        publishCamera();
        settleReady({
          available: true,
          sourceTimestamp: manifest.source_timestamp,
        });
      } catch (error) {
        fail(error.message);
      }
    });
    observer =
      typeof ResizeObserver !== "undefined" ? new ResizeObserver(resize) : null;
    observer?.observe(container);
  } catch (error) {
    fail(error.message || "此瀏覽器不支援 WebGL");
  }
  let pendingCounts = {};
  return {
    ready,
    setSelection,
    setVisibleVenueCounts(counts) {
      pendingCounts = counts || {};
      setVisibleVenueCounts(pendingCounts);
    },
    setPitch,
    resize,
    reset,
    getCamera,
    destroy,
  };
}
