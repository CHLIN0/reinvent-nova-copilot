# M3a · Indoor and landmark data availability (Codex, read-only, memo)

Write `docs/research/indoor-data-2026-11.md`. Dated sources; mark unverified items. Finish within about 40 minutes; partial memo with gaps is acceptable.

Context: re:Invent 2026 (Las Vegas, Nov 30–Dec 4) across The Venetian/Palazzo, Wynn, Encore, Caesars Forum, Caesars Palace, MGM Grand, Mandalay Bay. The official AWS Events API gives session venue and room names only (no coordinates, floor plans, indoor graph). Our routing (`atlas/routing.py`, `data/venue_graph.json`) is venue-to-venue; Event Atlas (`explorer/`) has OpenStreetMap building footprints in a MapLibre 3D scene.

Answer per venue: what indoor/landmark data exists and may be used legally: official re:Invent venue maps and their terms; OSM indoor tagging (indoor=*, level=*, entrances) coverage for each venue; public floor plans; what the official AWS Events app exposes and whether anything is reusable. For each: yes / partial / no, license, and what we could build with it (entrance choice, floor, room-level path). Recommend the minimum viable step (e.g. entrances + floors from OSM where present) and what must never be invented.
