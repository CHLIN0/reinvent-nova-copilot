# Roadmap: re:Invent Nova Copilot (post-submission)

Status: **v2.2, approved by BR on 2026-11-07 with adjustments (section M2). M0 T0/T1/T2 merged to main 2026-11-07 (PRs #1–#3, Codex MERGE on each, verified on BR's account); research memos in `docs/research/`; wave 2: T5 (PR #5) and T10 (PR #4) merged 2026-11-07 after Codex MERGE and host verification on BR's account; wave 3: T3 (PR #6) and T4 (PR #7) merged 2026-11-07 after Codex MERGE and host verification on BR's account; wave 4: T8 (PR #8), T6 (PR #9) and T7 (PR #10) merged 2026-11-09 after Codex round 1, a blind Claude round 2 (MERGE) and host verification on BR's account; T7's supervised real write test passed on BR's account 2026-11-09; wave 5: T9b (PR #11) merged 2026-11-11; T9a (PR #12) merged then reverted on main (9196f04) because the signed-in briefing failed; T9a round 2 (PR #14, greedy decoding) merged 2026-11-11 after Codex MERGE and host verification; T9c (PR #13) merged 2026-11-11 after host verification (Tuesday and 週二 planned on 2026-12-01); T9a round 3 (PR #15) merged 2026-11-11: the briefing no longer states an empty schedule diff as a change, which failed every replay; first briefing after a restart now passes 3 of 4 live (was 0 of 4); open: the residual ToolUse failure, decision pending with BR.** Defaults BR did not object to: T3 opens on the first conference day until 2026-11-30, then today; T8 keeps the CLI and deletes `/copilot`; T7's real cancel waits for BR's go on the day; M2a spend cap USD 20. v1 (the UX overhaul) is now Milestone 0 of this roadmap.

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
- Status 2026-11-07: merged (PR #4). Live: 1.5 s on a short synthetic abstract, 3.35 s on a long real one (includes the official-locale attempt first); cache instant; ledger line present. Follow-up for a later PR: a Taiwan-Traditional-Chinese glossary in the translation prompt (the first outputs used Mainland terms such as 構建／代理／數據), and skip the official-locale round trip when the event reports only en-US.
T1 server-side state · T2 reservations locked in code · T3 signed-in first screen = my re:Invent · T4 panel-sized answers · T5 token/restart handling · T6 new/changed sessions since last visit · T7 RSVP lifecycle · T8 remove duplicates · T9 reliability gate. Acceptance criteria and must-nots are in section 5. Plus **T0 · cost ledger**: every Bedrock call logs model, input/output tokens and estimated USD to `local-private/costs.jsonl`; `docs/costs.md` summarises per feature. This starts in M0 so M2 has a baseline.

### M1 · Explainable recommendations and more ways to explore (E1)
- **M1a Filter trace**: every recommendation shows the chain: profile facts used → search filters → candidates → feasibility checks → chosen/dropped with reasons. One click from the answer. The attendee can edit a filter (day, level, venue, walking limit) and the plan recomputes without re-asking the model.
- **M1b Compare plans**: for one day, two or three alternatives side by side (depth-first / fewest steps / explore adjacent topics) with the same columns: sessions, travel, slack, steps, what you give up.
- **M1c Exploration views on the catalog** (in Atlas's Explore tab): by goal ("bring back an agent security approach"), by level progression, by venue-day heatmap, by "related to what I reserved". Each view is a query over the same catalog with a visible definition.
- Acceptance: a judge-style test: for any plan, every line can be traced to a tool result in the trace view; changing a filter updates the plan in under 2 s without a model call.
- Must not: new model calls per view; embeddings unless M1c proves a need with examples.

### M2 · Agent architecture, runtime and cost (E2; widened on 2026-11-07 per BR)
BR's asks: evaluate AgentCore specifically for (a) the official re:Invent API/MCP integration and (b) our own service interface (API, MCP, or better); route different tasks to different models and integrate their results; keep the user profile as Markdown with a *principle* layer (a harness: rules that adapt behaviour to the user's situation); treat the agenda as a database and ideally a knowledge base, cost-aware; use good, current frameworks so the AI solves tasks more cheaply, clearly and correctly. Research and evaluate before building; use Codex (gpt-6.1-sol) for the research, not only Claude.
- **M2r Architecture research (Codex, 2 days, read-only)**: one memo, `docs/research/agent-architecture-2026-11.md`, with dated sources and a cost column per option, covering: (1) AgentCore Runtime / Gateway / Identity / Memory / Observability as they exist today, and how each would carry our tools, the official MCP, Builder ID OAuth and the profile; (2) our service interface: keep REST + our MCP server, or expose through AgentCore Gateway, or both; (3) task→model routing: which steps need Nova Pro, which can use Nova Lite/Micro or deterministic code, with measured token costs from our ledger; (4) profile as Markdown + principles (harness) vs. the current JSON: format, where the principles live, how the prompt consumes them; (5) agenda storage: local SQLite/JSON vs. Bedrock Knowledge Bases vs. a small local vector index, with cost and freshness (the catalog changes), and what "knowledge base" buys for explainable recommendations; (6) a recommended target architecture with a migration path from today's code and the first two steps. Each recommendation names the attendee-visible benefit; anything without one is marked "not now".
- **M2a Spike (after the memo, 2 days, spend cap USD 20)**: deploy the existing agent on the recommended runtime path; same 8-scenario battery both ways; latency, tokens, USD, operational differences.
- **M2b Decide**: migrate only with numbers and an attendee-visible benefit.
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
- Status 2026-11-07: merged (PR #6) after three Codex rounds (every positive gap shown, plan-driven tab switch, sign-in control recovers after a transient status failure, calendar date follows the chosen day). Verified on BR's account: Monday first paint with 3 reserved, 2 favorites, two labelled gaps, briefing inline, docked panel. Open point: after the event (from Dec 5) the view returns to 11/30.

### T4 · Answers that fit a panel (fixes P5)
- Plan answers = lines for leave hotel / sessions / back; one line per transition; dropped list collapsed to "N dropped (3 shown)"; no Markdown symbols; yes/no questions answered in the first sentence; `max_sessions` derived from free windows.
- Acceptance: 8-question real-catalog battery; each answer ≤ 160 words; first-sentence rule and no `**` checked by test.
- Added 2026-11-07 from the live T2 check: when the planner keeps only the reservations and adds nothing (search returned 10 candidates, none fit), the answer must say "no additional session fits" instead of "feasible with the added sessions". Include this case in the battery.
- Must not: change tool contracts.
- Status 2026-11-07: merged (PR #7). Host decision after four Codex rounds on a 460-line regex rewriter: the post-processor must never delete model text (strip Markdown, append the no-addition sentence per day, collapse only a single sentence of >3 dropped codes); no word cap in code, length is the prompt's job and the battery asserts it. Default `max_sessions` = fixed sessions + one per free hour (clamped 1–8), not the literal window count, which could never add a session. A prompt rule "do not pass max_sessions" made Nova Pro fail every signed-in briefing with a tool-use ModelErrorException (6/6) and was removed; the tool spec keeps the guidance. Prompt-adherence gaps for T9: the briefing lists every missing profile field instead of one question; a combined "can I make it + plan my day" question answered only the travel part; reserved sessions in session cards still show RSVP (T7).

### T5 · Sessions that survive time (fixes P7)
- Token expiry shown, re-sign-in prompt before expiry, refresh token where allowed; restart message explains the sign-out.
- Must not: persist tokens to disk.

### T6 · New and changed sessions since last visit (E1; depends on T1)
- Server-side catalog snapshot per profile (id → start, end, room, abstract hash). Each visit: new ids, moved or cancelled reserved sessions. Briefing reports them; new sessions matching interests are recommended with codes.
- Acceptance: fixture test with a modified catalog; briefing names the new session and the moved reservation.
- Status 2026-11-09: merged (PR #9). Snapshot in `local-private/profiles/<name>.catalog.json` (0600), written only when every row is official. Codex round 1 found provenance read from a process-global flag, lost cancellation history after a fallback, unreserved sessions reported as moved; fixed with tests. Verified live: an edited snapshot copy produced "3 new sessions, 1 reservation moved" and the briefing named CMP321-R and AIM370/AIM341/ANT303. Known limits: a non-numeric `experience_level` yields no recommendations; a session the attendee unreserved that then leaves the catalog reads as "no longer in the catalog".

### T7 · RSVP lifecycle
- Cancel reservation with confirm → official call → read-back; seat status on cards; result codes in plain words.
- Acceptance: offline test; one supervised real cancel + re-reserve on a low-stakes session, with BR's go-ahead.
- Status 2026-11-09: merged (PR #10). Cancel = documented CancelReservation (DELETE per session, 404 treated as already gone, 409 operationClosed), click-only with read-back; seat words and plain-words result codes in Atlas and the panel; reserved cards never show RSVP. Verified live without a write (CMP321-R reserved: cancel action, 已滿/Full, no RSVP). Supervised real write test 2026-11-09 on BR's go: reserve-then-cancel instead of cancel-then-re-reserve, because BR's existing reservations were full (cancelling one could lose the seat). CON344-R1 (Fri 08:00, seats available, no clash): RSVP from the panel card → "✓ Done and verified", GetSchedule 10 reserved; cancel from the Atlas card → "✓ 已取消，並已在官方行程中確認", GetSchedule back to the original 9, CMP321-R untouched; both confirms named code, title and time; the panel card returned to RSVP without reload. Seen during verification for T9: Nova answered a session question from conversation context without calling get_session, so no session cards appeared.

### T8 · Remove duplicates (fixes P8)
- Delete `/copilot` chat-only page; keep CLI for judges and tests; one sign-in path; one place where the plan is shown.
- Status 2026-11-09: merged (PR #8). `web/index.html`, `/copilot`, POST `/api/signin` and POST `/api/profile` removed; the panel keeps only Ask (profile edits go through `update_profile`); GET `/api/profile` kept for Atlas translation. Verified live: `/copilot` 404, one sign-in control.

### T9 · Reliability gate
- Offline scenario battery in CI; user-facing text for 401/403/429 and Bedrock unavailable; `unittest` green.
- 2026-11-10, BR said start. Split into two parallel builders: T9a (`docs/briefs/T9a-answers-grounded-in-tools.md`, class C: force a tool call on the first request of every turn after a live Tuesday answer used no tools and gave GHJ212 a wrong time; one profile question chosen in code; combined questions) and T9b (`docs/briefs/T9b-errors-ledger-ci.md`, class D: tests isolated from the private cost ledger, plain-words errors, GitHub Actions CI, PR template). Test scope in `docs/test-matrix.md`. Blind review by a Claude Sonnet subagent started by each builder (Codex out of weekly quota until 11-12); the host pushes and opens PRs because this repo has no builder grant yet.
- Status 2026-11-11: T9b merged (PR #11: ledger isolation via `ATLAS_COSTS_LEDGER` and `tests/__init__.py`, error codes with one plain sentence in the panel and Atlas, GitHub Actions CI, PR template, `mcp<2` pin because mcp 2.x dropped FastMCP) and T9a merged (PR #12: `toolChoice: any` with read tools only on the first request of every turn; one profile question chosen in code). Both: Sonnet blind review MERGE, CI green; Codex cloud review is connected but out of usage, so no bot review. Host check on BR's account: the briefing asks one question (arrival date); the Tuesday question now calls tools with official times but plans Wednesday (`day: 2026-12-02` for 週二 and for "Tuesday", 2/2). Next: T9c (`docs/briefs/T9c-weekday-resolution.md`), weekday words resolved to dates in code. Known limits carried: two-part questions are answered but plans are built without `plan_itinerary`; "no walking limit" cannot be saved.
- 2026-11-11 later: on BR's account the signed-in briefing failed with `ModelErrorException` 3 of 3 times on main (T9a+T9b) and 2 of 2 on the T9c branch, while pre-T9 `a0dd70b` briefed normally on the same data. Host reverted the T9a merge (9196f04, CI green, briefing verified working again on 8500). Leading suspect: the forced `toolChoice: any` on the briefing's first request; the exact Bedrock message was not captured because the server logs only the class. T9c's own fix worked live (週二 planned on 2026-12-01 with GHJ212 12:00–14:00 and GHJ301-S), but PR #13 carries T9a and is back in draft. After the quota reset: T9a builder reproduces with the full error message and fixes; T9c is rebased onto the result.

### Wave 6 · Reliability and speed (proposed 2026-11-11, waits for BR's 開始)
BR asked for a best-practice fix for the remaining briefing failure and a faster agenda load, with UI/UX in scope. Measurements, sources and decisions are in `docs/research/2026-11-11-briefing-and-loading.md`.
- **T11 · Briefing as a workflow** (`docs/briefs/T11-briefing-as-workflow.md`, class C).
  - The server runs `get_profile`, the schedule and `check_itinerary` for each reserved day.
  - Nova gets one request with no tools and writes the summary; if it fails, a briefing written by code is shown.
  - This removes the "invalid sequence as part of ToolUse" failure from the briefing, and every reserved day is always checked.
- **T12 · Catalog stale-while-revalidate** (`docs/briefs/T12-catalog-stale-while-revalidate.md`, class D).
  - Requests get the last snapshot at once, with at most one background refresh.
  - Atlas and Copilot share one catalog read.
  - `get_session` uses an index, and `/api/catalog` is gzipped.
  - Today a page load after 60 s idle waits about 11 s for 11 sequential official pages.
- **T13 · Loading UX** (`docs/briefs/T13-loading-ux.md`, class D, after T11 and T12).
  - The header shows sync progress and how old the data is.
  - The briefing area has a fixed height with skeletons; facts and summary arrive together, and the facts still show if Nova fails.
  - Grayed-out cards explain themselves.
  - Measured against LCP ≤ 2.5 s, CLS ≤ 0.1, INP ≤ 200 ms.
- **Order:** T11 and T12 run in parallel (no shared files), then T13.

## 6. How the work runs

1. **Host (this session)**: owns this roadmap and the order; writes one brief per task from this file; starts one session per task in its own worktree, at most three in parallel; verifies acceptance in BR's Chrome before merging; merges sequentially.
2. **Builders**: Claude Code sessions on Opus 5.5 for product code; Codex (gpt-6.1-sol) for research memos (M2r, M3a, M4a) and for development tasks the host assigns it (same brief format, same PR rules). Different models for different steps is a design goal of the product too (M2r item 3). Never GPT-6 Astra without BR's say. Work is not kept in the host session: the host dispatches, verifies and merges.
3. **Review gate on every PR**: Codex review (gpt-6.1-sol) with a fixed checklist: scope equals the task's acceptance and nothing more; no speculative abstraction; no new dependency without a line in the brief; tests present and meaningful; no secrets or local paths; UI claims backed by a screenshot; cost ledger entries present for any new model call.
4. **BR's gates**: approve this roadmap; read each spike memo before its build starts; approve real writes to the official schedule (T7); approve removals (T8); approve any spend above the ledger's running estimate.
5. **Hygiene**: usage check before each fan-out; Codex availability verified before the first PR; every merge updates `docs/costs.md` if a model call changed.

## 7. Decisions for BR

1. Approve the milestone order (M0 → spikes in parallel with M0's second wave → M1 → builds after memos)?
2. T3 default day: first conference day until 2026-11-30, then today?
3. T8: delete `/copilot`, keep CLI?
4. T7: one supervised real cancel + re-reserve on a low-stakes session?
5. Spend ceiling for the M2a AgentCore spike (proposal: stop and report at USD 20)?
