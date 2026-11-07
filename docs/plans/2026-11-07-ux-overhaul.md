# Roadmap: re:Invent Nova Copilot (post-submission)

Status: **v2 draft for BR's review, 2026-11-07**. Nothing is started. v1 (the UX overhaul) is now Milestone 0 of this roadmap.

## 1. What BR wants (his words, condensed; the roadmap must not drift from these)

| # | Expectation | Where it lands |
|---|---|---|
| E0 | The basics: browse the agenda, understand session content, and translation (if the official API has none, at least translate when I talk to the agent; translating everything is too costly) | M0 basics + T10 on-demand translation (per session, cached, cost logged) |
| E1 | An AI agent that understands my situation, arranges my schedule and recommends; I can *see* how it filtered, and get more ways to understand re:Invent so I can plan precisely | M0 (correctness), M1 (explainable recommendations, exploration views) |
| E2 | Consider Amazon Bedrock AgentCore for the agent; record all costs | M2 (spike first, then decide), cost ledger from M0 |
| E3 | 3D and route planning because of the many buildings and landmarks; indoor routes if possible | M3 (indoor feasibility spike, then build what the data allows) |
| E4 | Multi-user / team: explore, but pending | Parked list (no work until BR unparks) |
| E5 | Cloud deployment so users can use it themselves; open source with a license | M4 (deployment spike on the sign-in constraint, then build); license already MIT |
| E6 | BR's role: host the project, dispatch to Opus 5.5 sessions and Codex (gpt-6.1-sol), no drift, nothing meaningless | Section 6 |

## 2. Hard constraints and facts to re-verify

| Constraint | Source | Effect on the roadmap |
|---|---|---|
| The Events API sign-in is OAuth PKCE with a **loopback redirect only** (127.0.0.1:8484–8489); no hosted redirect URI as of the 2026-10-26 reading of the docs | Codex research 10/26; `docs/research/official-api` in event-atlas | A hosted web app cannot sign users in by itself today. M4 starts with a spike to re-read the docs and test the options (local helper, device-style flow, or ask AWS). Until then, "cloud" means hosting everything except the sign-in. |
| The API has no floor plans, rooms-to-coordinates, or indoor graph | Same docs | Indoor routing needs another data source. M3 starts with a spike on what exists legally (venue maps, OSM indoor tags, official app) before any build. |
| Bedrock Nova Pro is the model; AgentCore is a candidate runtime | BR | M2 spike measures cost and latency of the *same* agent on AgentCore vs. direct Converse before any migration. No rewrite without numbers. |
| BR's Chrome blocks site storage for this origin | Walkthrough 11-07 | All state lives on the server (M0 T1). |

## 3. Milestones

### M0 · Basics, correct and usable (the v1 overhaul plus basics)
Basics that must simply work: browse by day/venue/type/level and search; open a session and read the full abstract, speakers, room and seat status; add to the plan; ask the agent about any session. **T10 · Understand sessions in your language**: the official API accepts `locale`, but re:Invent 2026 reports `supportedLanguageCodes: ["en-US"]` (10/26 reading), so translation is ours, on demand: `GET /api/translate/<id>?lang=` checks a server cache (session id + abstract hash), otherwise Nova Pro translates title and abstract once, stored under `local-private/translations/`, cost logged; Atlas session view gets a Translate button with an "unofficial translation" mark; Copilot answers in the profile language and keeps session titles and codes in the original. Never pre-translate the whole catalog. Acceptance: a zh-Hant user sees a translated abstract within 3 s; the second open makes no model call; `docs/costs.md` has a translation line.
T1 server-side state · T2 reservations locked in code · T3 signed-in first screen = my re:Invent · T4 panel-sized answers · T5 token/restart handling · T6 new/changed sessions since last visit · T7 RSVP lifecycle · T8 remove duplicates · T9 reliability gate. Acceptance criteria and must-nots are in section 5. Plus **T0 · cost ledger**: every Bedrock call logs model, input/output tokens and estimated USD to `local-private/costs.jsonl`; `docs/costs.md` summarises per feature. This starts in M0 so M2 has a baseline.

### M1 · Explainable recommendations and more ways to explore (E1)
- **M1a Filter trace**: every recommendation shows the chain: profile facts used → search filters → candidates → feasibility checks → chosen/dropped with reasons. One click from the answer. The attendee can edit a filter (day, level, venue, walking limit) and the plan recomputes without re-asking the model.
- **M1b Compare plans**: for one day, two or three alternatives side by side (depth-first / fewest steps / explore adjacent topics) with the same columns: sessions, travel, slack, steps, what you give up.
- **M1c Exploration views on the catalog** (in Atlas's Explore tab): by goal ("bring back an agent security approach"), by level progression, by venue-day heatmap, by "related to what I reserved". Each view is a query over the same catalog with a visible definition.
- Acceptance: a judge-style test: for any plan, every line can be traced to a tool result in the trace view; changing a filter updates the plan in under 2 s without a model call.
- Must not: new model calls per view; embeddings unless M1c proves a need with examples.

### M2 · Agent runtime and cost (E2)
- **M2a Spike (2 days)**: deploy the existing agent to Bedrock AgentCore Runtime in us-east-1 (plus AgentCore Memory for the profile and Gateway for the tools, if that is how the service is shaped at the time); run the same 8-scenario battery on both paths; record latency, tokens, USD, and operational differences. Output: a decision memo with numbers.
- **M2b Decide**: migrate only if the memo shows a benefit the attendee feels (reliability, latency, memory across sessions) at a cost BR accepts. Otherwise stay on direct Converse and keep the memo as the record.
- Cost ledger stays either way.

### M3 · Space: 3D, landmarks, indoor (E3)
- **M3a Spike (2 days)**: what indoor and landmark data exists and may be used: official venue maps and their terms, OSM indoor tags for the six venues, public floor plans; and what the official app exposes. Output: a data-availability memo with a yes/partial/no per venue.
- **M3b Build what the data allows**: at minimum, room-level venue positions and entrance choice ("enter Caesars Forum from the north entrance for Forum 110") on the existing 3D scene; indoor paths only for venues with usable data, labelled as such; never invented.
- Acceptance: a route answer names the entrance and, where data exists, the floor; the 3D scene highlights the venues and route of the selected plan.

### M4 · Cloud and open source (E5)
- **M4a Spike (1 day)**: re-read the sign-in docs; test whether a hosted app can complete Builder ID sign-in (hosted redirect, device flow, or a local helper). Output: a memo with the one viable path, or "not possible today".
- **M4b Build**: the hosted deployment on the viable path (container on AWS, per-user server-side state, secrets in a managed store, cost ledger per user); the repo stays open source under MIT with a CONTRIBUTING and a clear "run it yourself" path.
- Acceptance: a second person signs in and plans their own day without BR's machine.

### Parked (E4, by BR's decision)
Team planning, shared plans, consent model. Documented as a parked list; no work.

## 4. Order and parallelism

M0 first (T0+T1+T2 → T3+T4+T5+T10 → T6+T7+T8 → T9). The three spikes (M2a, M3a, M4a) can run in parallel with M0's second wave because they are read-and-measure work that touches no product code. M1 starts after M0 T3. M2b/M3b/M4b start only after BR reads the memos.

## 5. M0 task details (acceptance and must-nots)

### T0 · Cost ledger
- Log every Bedrock call (model, input/output tokens, estimated USD, feature tag) to `local-private/costs.jsonl`; `docs/costs.md` with a per-feature summary and the price table used, dated.
- Acceptance: after the scenario battery, `docs/costs.md` shows cost per scenario.

### T1 · State lives on the server (fixes P1, P6)
- Replace Atlas's browser plan store with `GET/POST /api/plan` backed by `local-private/profiles/<name>.state.json`. The plan = official reservations + favorites (from `GetSchedule`) + local picks, each with a `source`.
- Atlas renders the plan from the server; "我的安排" marks reserved/favorite/local differently. Filters live in the URL hash only. Copilot's "add to plan" writes the same endpoint; no page reload.
- Acceptance: with site data blocked in Chrome, "我的安排" shows 9 reserved and 5 favorites; no storage error ever rendered; adding from Copilot appears without reload.
- Must not: add a database; change the 3D map; touch `explorer/ui` beyond the plan store and its consumers.

### T2 · Reservations are locked in code (fixes P3, P4)
- When signed in, `plan_itinerary` / `check_itinerary` load the official schedule themselves: reserved = `must` + blocked windows; favorites = priority candidates. The model cannot omit them.
- The briefing calls `check_itinerary` per conference day before any feasibility statement; if it did not, the server strips feasibility claims from the text.
- Acceptance: the Wednesday case yields no suggestion overlapping GHJ315, DVT415-R2 or SEC407-R1; offline fixture test; battery asserts `check_itinerary` in every briefing trace.
- Must not: change routing; add tools.

### T3 · Signed-in first screen = "My re:Invent" (fixes P2, P6; depends on T1)
- After sign-in: first conference day (today during the event) in day view, reserved sessions highlighted, gaps marked, briefing at the top of the page. Catalog browsing = "Explore" tab, filters collapsed. One sign-in control; Copilot is a persistent side panel with a toggle.
- Acceptance: screenshot in BR's Chrome: first paint shows BR's Monday (CMP321-R, INV538, GHJ308-S-R) and the gaps; no breakfast/booth cards unless Explore is opened.
- Must not: restyle; remove the five-day view; add animations.

### T4 · Answers that fit a panel (fixes P5)
- Plan answers = lines for leave hotel / sessions / back; one line per transition; dropped list collapsed to "N dropped (3 shown)"; no Markdown symbols; yes/no questions answered in the first sentence; `max_sessions` derived from free windows.
- Acceptance: 8-question real-catalog battery; each answer ≤ 160 words; first-sentence rule and no `**` checked by test.
- Must not: change tool contracts.

### T5 · Sessions that survive time (fixes P7)
- Token expiry shown, re-sign-in prompt before expiry, refresh token where allowed; restart message explains the sign-out.
- Must not: persist tokens to disk.

### T6 · New and changed sessions since last visit (E1; depends on T1)
- Server-side catalog snapshot per profile (id → start, end, room, abstract hash). Each visit: new ids, moved or cancelled reserved sessions. Briefing reports them; new sessions matching interests are recommended with codes.
- Acceptance: fixture test with a modified catalog; briefing names the new session and the moved reservation.

### T7 · RSVP lifecycle
- Cancel reservation with confirm → official call → read-back; seat status on cards; result codes in plain words.
- Acceptance: offline test; one supervised real cancel + re-reserve on a low-stakes session, with BR's go-ahead.

### T8 · Remove duplicates (fixes P8)
- Delete `/copilot` chat-only page; keep CLI for judges and tests; one sign-in path; one place where the plan is shown.

### T9 · Reliability gate
- Offline scenario battery in CI; user-facing text for 401/403/429 and Bedrock unavailable; `unittest` green.

## 6. How the work runs

1. **Host (this session)**: owns this roadmap and the order; writes one brief per task from this file; starts one session per task in its own worktree, at most three in parallel; verifies acceptance in BR's Chrome before merging; merges sequentially.
2. **Builders**: Claude Code sessions on Opus 5.5 for product code; Codex (gpt-6.1-sol) for spikes and research memos, and for development tasks the host assigns it (same brief format, same PR rules). Never GPT-6 Astra without BR's say.
3. **Review gate on every PR**: Codex review (gpt-6.1-sol) with a fixed checklist: scope equals the task's acceptance and nothing more; no speculative abstraction; no new dependency without a line in the brief; tests present and meaningful; no secrets or local paths; UI claims backed by a screenshot; cost ledger entries present for any new model call.
4. **BR's gates**: approve this roadmap; read each spike memo before its build starts; approve real writes to the official schedule (T7); approve removals (T8); approve any spend above the ledger's running estimate.
5. **Hygiene**: usage check before each fan-out; Codex availability verified before the first PR; every merge updates `docs/costs.md` if a model call changed.

## 7. Decisions for BR

1. Approve the milestone order (M0 → spikes in parallel with M0's second wave → M1 → builds after memos)?
2. T3 default day: first conference day until 2026-11-30, then today?
3. T8: delete `/copilot`, keep CLI?
4. T7: one supervised real cancel + re-reserve on a low-stakes session?
5. Spend ceiling for the M2a AgentCore spike (proposal: stop and report at USD 20)?
