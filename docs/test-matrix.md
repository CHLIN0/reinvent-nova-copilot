# Test matrix

Owned by the host (see `docs/plans/2026-11-07-ux-overhaul.md`). Builders add tests; they never delete, skip or weaken a row without the host's OK in their brief. Updated 2026-11-10 for T9.

Offline rows use the synthetic fixture catalog and a mocked Bedrock client; they must not write to `local-private/` (row B1). Live rows cost money or need BR's signed-in account; they stay out of CI and are reported in the PR with the head SHA.

## Existing suites (all must stay green)

| Row | Behaviour / interface | Level | Test location | Fixture / data | Runs in CI? | Notes |
|---|---|---|---|---|---|---|
| P1 | Agent loop: tool rounds, budget, truncated tool use, write confirmation | unit | `tests/test_agent.py` | mocked Bedrock | yes | |
| P2 | Scenario battery: plans, yes/no, routes, briefing, catalog diff | unit | `tests/test_battery.py` | synthetic catalog, scripted tool calls | yes | |
| P3 | Official catalog client, reserve, favorites, schedule read-back | unit | `tests/test_catalog.py` | mocked `_request` | yes | |
| P4 | Catalog snapshot and diff (T6) | unit | `tests/test_catalog_diff.py` | synthetic catalog | yes | |
| P5 | Cost ledger and report (T0) | unit | `tests/test_costs.py` | temp ledger | yes | |
| P6 | Panel-sized answer format (T4) | unit | `tests/test_format.py` | text fixtures | yes | |
| P7 | Reservations locked in planning tools (T2) | unit | `tests/test_locked.py` | synthetic catalog | yes | |
| P8 | Planner and routing | unit | `tests/test_planner.py`, `tests/test_routing.py` | synthetic | yes | |
| P9 | My re:Invent, server plan API (T1, T3) | unit | `tests/test_my_reinvent.py`, `tests/test_plan_api.py` (runs `tests/copilot_plan_event.mjs`) | synthetic | yes | needs Node |
| P10 | Profile and state files | unit | `tests/test_profile.py` | temp dir | yes | |
| P11 | Sign-in status and token lifetime (T5) | unit | `tests/test_status.py` | stubbed auth | yes | |
| P12 | On-demand translation (T10) | unit | `tests/test_translate.py` | mocked Bedrock, temp ledger | yes | |
| P13 | RSVP lifecycle: cancel, seats, result codes (T7) | unit | `tests/test_rsvp_lifecycle.py` (runs `tests/copilot_rsvp_cards.mjs`) | mocked `_request` | yes | needs Node |
| P14 | Panel status line and re-sign-in button | unit | `node tests/copilot_status.mjs` | fake DOM | yes | |
| N1 | Event Atlas UI modules | unit | `explorer/ui/test-calendar-stack.mjs`, `test-discovery.mjs`, `test-model.mjs`, `test-my-day.mjs`, `test-official-connection.mjs`, `test-plan-store.mjs`, `test-rsvp.mjs`, `test-session-facets.mjs`, `test-stack-plan-marks.mjs`, `test-translate.mjs` | synthetic | yes | run each with `node` |
| N2 | 3D scene data | unit | `explorer/ui/test-scene-data.mjs` | needs `explorer/data/osm/`, not in git | no | fails on a clean checkout; unchanged |

## T9 rows

| Row | Behaviour / interface | Level | Test location | Fixture / data | Runs in CI? | Notes |
|---|---|---|---|---|---|---|
| A1 | The first Converse request of every user turn forces a tool call; later rounds are `auto` | unit | T9a adds, `tests/test_agent.py` | mocked Bedrock | yes | |
| A2 | A follow-up turn in the same conversation is forced again | unit | T9a adds | mocked Bedrock | yes | |
| A3 | The briefing prompt names at most one missing profile item, chosen by priority; none when complete | unit | T9a adds, `tests/test_battery.py` | synthetic profiles | yes | |
| A4 | A two-part question (travel + plan the day) is answered in both parts | unit | T9a adds, `tests/test_battery.py` | scripted tool calls | yes | the scripted model only proves the plumbing; L1 proves behaviour |
| B1 | Running the offline suite never writes to `local-private/costs.jsonl` | unit | T9b adds | mocked agent turn | yes | |
| B2 | 401/expired, 403, 429, Bedrock unavailable and unknown errors map to a code and one plain sentence; no exception text reaches the response | unit | T9b adds | mocked failures through the HTTP handler | yes | |
| B3 | The panel shows the error sentence | unit | T9b adds, node test on `web/copilot.js` | fake DOM | yes | |
| B4 | CI runs P1–P14, N1 and the T9 rows on every PR and push to `main` | CI | `.github/workflows/ci.yml` (T9b) | none | yes | no credentials |

## Live rows (not in CI)

| Row | Behaviour | Level | How | Data | Runs in CI? | Notes |
|---|---|---|---|---|---|---|
| L1 | Day-plan question, session-by-code question and "thanks" each show at least one tool call; the plan uses official times | live smoke | builder's own instance, signed out, synthetic catalog | real Nova Pro (costs money) | no | T9a, report head SHA |
| L2 | On BR's account: 「我住 Park MGM，每天最多走 8000 步，幫我排週二的議程。」 calls tools and gives GHJ212 as 12:00–14:00; the briefing asks at most one profile question | live | host, BR's Chrome on 127.0.0.1:8500 | BR's official account | no | host before merge |
| L3 | Real reserve then cancel with read-back | live | host, on BR's go only | BR's official account | no | passed 2026-11-09 (T7) |
