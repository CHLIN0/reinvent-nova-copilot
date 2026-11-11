# T13: The first screen says what is loading and keeps its place

- Change class: D (Event Atlas UI and Copilot panel)
- Branch: t13-loading-ux   Base: main **after T11 and T12 are merged** (it uses T12's `meta` fields and T11's briefing shape)
- Builder: Claude Code, Opus 5.5   Blind reviewer: Codex `review` profile; a fresh Claude Sonnet subagent only if Codex is unavailable

## Goal
On the signed-in first screen, the attendee always knows what is happening and how fresh the data is. The schedule never jumps when the briefing arrives. When Nova is unavailable, the facts still appear.

## Why (host screenshots on BR's account, 2026-11-11, cold load)
- **0–11 s.** BR's sessions are visible but grayed out, with venue names missing. The header says only 「確認官方連線…」, with no progress and no reason.
- **0–23 s.** The briefing area shows one line, "Welcome back. Nova Pro is checking your official schedule and profile…".
- **When the briefing arrives**, a tall block is inserted above the schedule and pushes it down (layout shift).
- **Best practice:**
  - NN/g "Skeleton Screens 101" (2023): skeletons for full-page loads under 10 s, progress for longer waits.
  - NN/g response-time limits: 0.1 s, 1 s and 10 s.
  - web.dev Core Web Vitals: LCP ≤ 2.5 s, CLS ≤ 0.1, INP ≤ 200 ms.

## Scope
1. **Catalog status in the header** (`explorer/ui/src/app.mjs` and `official-connection.mjs`), from T12's `meta`:
   - first sync: 「同步官方議程 4/11 頁」;
   - ready: 「2,516 場 · 更新於 HH:MM」;
   - serving a snapshot while refreshing: 「顯示 HH:MM 的資料 · 背景更新中」.

   Use the existing `/api/health` sync progress. Poll only while syncing, at most once a second.
2. **Grayed-out sessions explain themselves.** While the catalog is missing, cards from the plan keep their time and code and show a short 「載入場館…」 where the venue goes. Nothing else changes.
3. **The briefing keeps its place.**
   - It gets a fixed-height area with skeleton lines while waiting, so no layout shift.
   - T11 returns the code-written facts (since-last-visit line, per-day check results) and Nova's summary in one `/api/briefing` response. Show the skeleton until that response arrives, then render both in the same area. When Nova failed (`model_unavailable`), show the facts with a one-line note. Do not add a second endpoint to get the facts earlier; after T11 and T12 the wait is one short Nova request.
   - A long briefing is collapsed to its first lines, with 「展開」, so the day's schedule stays on the first screen at 1280×800.
4. **Explore tab.** While the catalog is loading for the first time, show a skeleton list instead of an empty area.
5. **Measure.** With the agent browser, trace the signed-in My re:Invent page on a warm server and after 70 s idle. Report LCP, CLS and INP against the web.dev thresholds, before (main) and after.

6. **Fewer `/api/plan` requests.** On BR's account one page load after T12 requests `/api/plan` 4 times, at 1.2–1.5 s each. Load it once per page load and after a change, and share the result between Atlas and the panel.
7. **Trace wording.** T11 marks the briefing's calls with `"by": "server"`. Show them as checks the server ran (for example 「伺服器已檢查 4 天的行程」), not as "N tool call(s)" that Nova made. Chat traces keep their current wording.

## Inputs on main (2026-11-11, after PR #16 and #17)
- **`/api/briefing`** returns:
  - `text`: Nova's summary, or the code-written briefing;
  - `facts`: a list of the code-written lines;
  - `trace`: each entry carries `"by": "server"`;
  - `schedule_diff`, `catalog_diff`, `first_visit`;
  - when Nova failed, also `error: "model_unavailable"` and `message`.
- **`/api/catalog` `meta`** and **`/api/health` `public_cache`** carry `received_at`, `refreshing`, `refreshes`, `stale`, and `sync: {phase, pages, collected}`.
- **Measured on BR's account after 72 s idle:** `/api/catalog` 0.06 s; `/api/my-schedule` 1.08 s; the briefing returns at 8.4 s (one Nova request, about 7 s). The briefing area is now the longest wait on the first screen.

## Tests
- Node tests for the header status texts from `meta` (syncing, ready, refreshing), the venue placeholder, and the briefing area's fixed height and collapse.
- Rebuild `explorer/ui/dist` with `node build.mjs`.
- Screenshots (synthetic or dev data) at 2 s and when ready, before and after, at 1280×800 and 390×844.

## Done when
- [ ] tests green; node tests that passed on main still pass
- [ ] trace numbers before and after (LCP, CLS, INP)
- [ ] screenshots
- [ ] blind review `VERDICT: MERGE`, at most 2 rounds
- [ ] commit on `t13-loading-ux`; do not push

## Must not
- change server code (T11 and T12 own it); if a field is missing, report it to the host
- restyle beyond the loading states; remove the five-day view; add animations other than a skeleton shimmer that respects `prefers-reduced-motion`
- touch the 3D map
- push, open a PR or merge
