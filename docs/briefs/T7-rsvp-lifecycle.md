# T7 · RSVP lifecycle

## Why
Reserving works (`catalog.reserve_sessions`, click → official call → GetSchedule read-back), but the lifecycle stops there: no cancel, seat availability is fetched but never shown, failure codes are printed raw ("code: conflict"), and the Copilot panel still offers an RSVP button for sessions the attendee has already reserved (seen live on 2026-11-07). Reservations are scarce and real; the attendee must see seat status before acting, be able to undo, and read every result in plain words.

## Scope
1. **Cancel reservation, official call.** Find the cancel operation in the AWS Events API developer guide (https://docs.aws.amazon.com/events/latest/devguide/; the reserve call is `POST /v1/events/{eventId}/reservations` with `sessionIds`). Implement `catalog.cancel_reservations(session_ids)` in `atlas/catalog.py` with the exact same shape as `reserve_sessions`: 1–10 distinct ids, per-item result, then GetSchedule read-back; an item is verified when it is no longer in `reserved`. Quote the guide page you used in your report. If the API exposes no cancel operation, implement nothing for this item and say so; do not invent an endpoint.
2. **Server route.** `POST /api/rsvp/cancel` in `web.py`, same validation as `/api/rsvp`. Click-only, like every official write: not a model tool (`WRITE_TOOLS` stays `{"add_favorites"}`), never called from the briefing or the chat.
3. **Confirm → call → read-back in both UIs.**
   - Event Atlas cards (`explorer/ui/src/app.mjs`, `planButtonText`/`planToggleDisabled`): a reserved session's button becomes "取消官方預約" and opens a confirm step that names the session code, title and time; on confirm it calls `/api/rsvp/cancel`, then re-reads `/api/plan` so the card, 我的安排 and the My re:Invent day view update without reload. Favorites keep "請在 AWS Events 變更".
   - Copilot panel (`web/copilot.js`, `sessionCards`): a session that is already reserved shows a reserved state plus the cancel action, never an RSVP button; an already-favorited session shows a favorited state. Use the schedule the panel already loads (`/api/my-schedule`) or `/api/plan`. The RSVP confirm names the code, title and time.
4. **Seat status on cards.** The catalog already carries `seats` (`seatAvailability`: available / limited / veryLimited / unavailable / walkUp; Atlas records have `seat_availability`). Show it as plain words on the panel's session cards and on Atlas session cards (繁體中文 in Atlas, matching its labels; English in the panel, matching its labels): 尚有座位 / 座位有限 / 所剩極少 / 已滿 / 現場排隊. Nothing shown when the field is empty.
5. **Result codes in plain words.** Map the official per-item failure codes (from the developer guide's reserve/cancel responses) to one sentence each, with the conflicting session codes when `conflicts_with` is present; an unknown code shows the code verbatim plus "see AWS Events". Apply in both UIs. "Verified in your official schedule" stays as the success read-back line.
6. **Tests.** Offline: `cancel_reservations` with a mocked `_request` (all ok, partial failure, read-back mismatch → `verified` false, id validation); the new route; the plain-words mapping; a node test on `web/copilot.js` (see `tests/copilot_plan_event.mjs` for the fake-DOM pattern) asserting a reserved session renders no RSVP button and a cancel action; a node test for the Atlas button text/state (`explorer/ui/test-*.mjs` pattern). Rebuild `explorer/ui/dist` with `node build.mjs`.

## Acceptance
- All tests green (`python3 -m unittest discover -s tests`, plus the node tests you add).
- Screenshot from your own instance with a fake signed-in state (stub `official_auth` as T3 did) and the synthetic catalog: a reserved session card shows the reserved state, seat words and the cancel action; the panel's suggested cards show no RSVP button on a reserved session.
- The real cancel + re-reserve on a low-stakes session happens later, on BR's explicit go, in the host's verification on BR's account. You never call the real API.

## Must not
- Perform any write against the real AWS Events account; your instance has no real token and must not get one.
- Add model tools, let the model cancel or reserve, or change `atlas/prompts.py`.
- Change the plan model (`/api/plan` shape, `source` marks) beyond re-reading it after a cancel.
- Restyle; change My re:Invent layout (`my-day.mjs`) beyond the card action and seat line; add animations or dialogs libraries.

## Lessons from T3/T4 (apply them)
- Server post-processing never deletes model text; this task adds no text rewriting.
- Prompt rules must not name tool arguments (Nova Pro tool-use failure, 6/6); this task adds no prompt text at all.
- Codex reviews scope strictly: anything not in this brief comes back as FIX FIRST.

## Repository facts (read these first)
- Repo: re:Invent Nova Copilot, Python 3.12 stdlib + boto3 + mcp. Public on GitHub (CHLIN0/reinvent-nova-copilot), MIT.
- Layout: `atlas/` (catalog.py official Events API: `_request`, `get_schedule`, `reserve_sessions`, `add_favorites`; tools.py `WRITE_TOOLS`; official_auth.py; profile.py), `web.py` (routes `/api/rsvp`, `/api/favorite`, `/api/plan`, `/api/my-schedule`; `_suggested` builds the panel's session cards), `web/copilot.js` (panel: `sessionCards`, schedule loading, plan events), `explorer/ui/src/app.mjs` (Atlas cards and plan buttons), `explorer/official_catalog.py` (`seat_availability`), `tests/`, `docs/ux-flow.md` section 5 (the confirm → execute → verify pattern), `docs/plans/2026-11-07-ux-overhaul.md` (the roadmap).
- Waves 1–3 are merged on `main`: `/api/plan` (server-side plan with `source` reserved | favorite | local), locked reservations, cost ledger, T3 My re:Invent (tabs, docked panel), T4 answer format, T5 token lifetime, T10 translation. Build on them.
- Run: `python3 -m unittest discover -s tests` (must stay green). Web for your own checks: `ATLAS_PROFILE_DIR=<your scratch dir>/profiles python3 web.py --port 8530 --explorer-port 8531 --profile dev` (do NOT use 8500/8493: BR's instance runs there; never stop it). Rebuild the Atlas bundle with `cd explorer/ui && node build.mjs` (node_modules is a symlink; `npm test`'s map step fails on main too because `explorer/data/osm/` is absent, run the other `test-*.mjs` directly).
- `.env` (git-ignored) holds Bedrock credentials; never print or commit it. `local-private/` is git-ignored user data.
- Work in your own git worktree and branch (create it: `git -C /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot worktree add /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot-wt-t7 -b t7-rsvp-lifecycle`); commit there with clear messages; do NOT push and do NOT open a PR; the host does. No secrets, no absolute local paths, no chat/session ids in committed files.
- T6 (catalog diff) and T8 (remove `/copilot` and the panel's plan tab) run in parallel and also edit `web.py` and `web/copilot.js`. Keep your edits inside the routes you add, `sessionCards`, and the Atlas card actions, so the host can merge without conflicts. T8 removes the panel's "day/plan" tab; do not build on it.
- Codex (gpt-6.1-sol) reviews your branch against this brief; findings come back to you until MERGE.
- Deliver: a short report at the end: files changed, test output, the developer-guide page used for cancel and its result codes, the screenshot path, and anything you could not do.
