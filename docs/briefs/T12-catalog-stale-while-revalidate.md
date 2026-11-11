# T12: The agenda answers from the last catalog at once and refreshes in the background

- Change class: D (catalog loading in `explorer/` and `atlas/`, multi-file)
- Branch: t12-catalog-swr   Base: main
- Builder: Claude Code, Opus 5.5   Blind reviewer: Codex `review` profile through `codex-run.mjs`; a fresh Claude Sonnet subagent only if Codex is unavailable

## Goal
While the server is running, no page load waits for the official API. Requests are served from the last complete catalog snapshot. A refresh runs at most once at a time, in the background, and the response says how old the data is. Only the very first load after sign-in waits for a full read.

## Why (measured by the host on 2026-11-11 on BR's account, server 251259b, signed in)
- **One full ListSessions read takes 11.3 s.** That is 11 pages of about 1 s each for 2,516 sessions, read in order because each page needs the previous `nextToken`. Warm, `/api/catalog` answers in 0.2 s.
- **Atlas waits for a refresh before answering.** `explorer/official_catalog.py` refreshes inside the request whenever the snapshot is older than 60 s (`MIN_REFRESH_SECONDS`). So any page load after a minute idle waits about 11 s.
- **The Copilot side reads the catalog a second time.** `atlas/catalog.py` does its own full read (5-minute TTL). Concurrent requests on a cold cache each start their own read, because nothing makes them share one in-flight read. In a cold page load, `/api/my-schedule` took 10.7 s and `/api/plan` 14 s, against 1.2 s and 1.7 s warm.
- **`catalog.get_session(id)` copies the whole list on every lookup.** It calls `load_sessions()`, which copies about 2,500 dicts, so resolving a 14-item schedule copies 35,000 dicts.
- **`/api/catalog` sends about 7 MB of uncompressed JSON** and deep-copies the snapshot on every request.
- Best practice: web.dev, "stale-while-revalidate" says the stale response "will be used to fulfill the browser's request" while revalidation runs in the background. NN/g: 1 s keeps the user's train of thought, 10 s is the attention limit.

## Scope
1. **Atlas: stale-while-revalidate.** In `OfficialCatalog`, when a snapshot exists, return it at once. When it is older than the refresh interval, start at most one background refresh. The response `meta` gains:
   - `refreshing` (bool);
   - `received_at`, which already exists;
   - the existing sync progress (`pages`, `collected`), so the UI can show it.

   Waiting is allowed only when no snapshot exists yet. Keep the generation guard: a refresh started before a sign-in change must never fill the cache afterwards. Sign-in still clears the cache.
2. **One read for the whole process.** The Copilot side (`atlas/catalog.py` `load_sessions`) must not run its own full read while Atlas holds a snapshot of the same signed-in catalog.
   - Preferred: build Copilot's rows from Atlas's snapshot.
   - Otherwise: give `atlas/catalog.py` the same behaviour as step 1 (serve the snapshot, at most one background refresh).

   Explain the choice. Every row keeps `source: "official_api"`, and T6 (`_briefing`'s `live` check) must keep working.
3. **Lookups.** `get_session` uses an index by id and by code, built once per snapshot, with no copy of the list. Callers that change a returned row must get a copy of that row only.
4. **Payload.**
   - `/api/catalog` returns gzip when the request accepts it.
   - It sends the snapshot without a deep copy per request. The snapshot is never changed after it is built.
   - Report the bytes on the wire before and after.
5. **Tests** (fake transport and clock):
   - a stale snapshot is returned at once and one refresh starts;
   - concurrent stale requests start exactly one refresh;
   - a refresh that started before a sign-in change is discarded;
   - the first load with no snapshot waits;
   - Copilot's `load_sessions` makes no ListSessions call while Atlas has a fresh snapshot (or the alternative from step 2 is covered);
   - `get_session` makes no list copy;
   - gzip is used only when it is accepted.

## Tests
- Matrix: add rows T12-1…T12-5 on your branch; the host reviews them. All existing rows stay green, including the T6 tests.
- Live smoke on your own instance: synthetic catalog plus the fake transport timings, or report why not. The host measures on BR's account:
  - after 70 s idle, a page load gets `/api/catalog` in under 300 ms and `/api/my-schedule` in under 1.5 s;
  - one ListSessions sync per refresh, seen in `/api/health`.

## Done when
- [ ] tests green, with `ATLAS_COSTS_LEDGER` pointing at a scratch file; the node tests that passed on main still pass
- [ ] a timing table (before and after) for cold, stale and warm loads from your fake-transport tests or local runs
- [ ] secret scan line
- [ ] blind review `VERDICT: MERGE`, at most 2 rounds
- [ ] commit on `t12-catalog-swr`; do not push

## Must not
- change session row content or projection, the T6 snapshot file or its semantics, auth or token handling
- add a dependency or a database
- touch `explorer/ui` (T13), `web/copilot.js`, or `_briefing`'s prompt (T11)
- delete, skip or weaken a test; edit CI config
- push, open a PR or merge

## Notes
- Worktree `../reinvent-nova-copilot-wt-t12` from `origin/main`. Do not use ports 8500/8493.
- The official API is access-controlled: never commit real catalog data. Use the synthetic fixture.
