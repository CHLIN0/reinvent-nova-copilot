# Third-party notices and provenance

The project's own code is released under the MIT License (see the repository root `LICENSE`). Bundled third-party components keep their own licenses below.

| Component | Pinned version | Upstream license/source |
|---|---|---|
| FullCalendar | 7.1.3 | MIT, https://fullcalendar.io/ |
| MapLibre GL JS | 6.15.0 | BSD-3-Clause, https://maplibre.org/ |
| temporal-polyfill | 1.0.6 | MIT, https://github.com/fullcalendar/temporal-polyfill |
| esbuild (build tool) | 0.28.2 | MIT, https://esbuild.github.io/ |
| Prettier (development tool) | 3.9.10 | MIT, https://prettier.io/ |
| OpenStreetMap data | observed 2026-10-24 | © OpenStreetMap contributors, ODbL, https://www.openstreetmap.org/copyright |

OSM extract and derived geometry remain separately identified under `data/osm/` and `ui/public/geo/`; visible attribution is retained in the app and map. Bundled upstream notices are preserved by esbuild. See installed package LICENSE files for full texts after `npm ci`.

Selected public application modules and public map assets originate from the existing private local reinvent-2026 repository at the revision recorded in `docs/research/source-lineage.json`; they are BR's local project lineage, not a third-party public-license grant. Public agenda text and existing AI translations are provided for local use from the existing public projection. Official documentation and model cards saved in research are reference evidence, not a grant to republish full catalogs or vendor assets. No provider credentials, attendee records or private notes are included.
