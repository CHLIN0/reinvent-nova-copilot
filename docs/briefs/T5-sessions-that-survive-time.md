# T5 · Sessions that survive time (fixes P7) — Codex development task

## Why
Server restart = silent sign-out; the Builder ID access token lasts 60 minutes with no warning; the attendee just sees things stop working.

## Scope
1. `web.py` `/api/status`: add `expires_at` (from `official_auth.current_auth().status()`), `seconds_left`, and `restarted_at` (process start time); `signed_in` false with reason `restarted` when the process has never been signed in since start.
2. Refresh: if `atlas/official_auth.py` already supports refresh tokens (check `access_token(force_refresh)` and the refresh path), make the status reflect refreshability; do not persist tokens to disk.
3. `web/copilot.js` banner (coordinate: T3 is reworking the page layout, so touch ONLY the banner text function `loadOfficial` and add a small polling of `/api/status` every 60 s): show "signed in · 42 min left"; at ≤5 min show "sign in again soon" with the sign-in button; after a restart show "the app restarted, please sign in again" instead of the generic demo notice.
4. Tests: `tests/test_status.py` offline with a stub auth whose `status()` returns an `expires_at`.

## Acceptance
- With a stub auth expiring in 3 minutes, `/api/status` reports `seconds_left` and the banner shows the warning (verify by reading the page in your own instance on 8510/8511 or by a unit test of the banner text function if the UI cannot be driven).
- All tests green.

## Must not
- Persist tokens; change sign-in flow; touch `explorer/`.

## Repository facts (read these first) (read these first)
- Repo: re:Invent Nova Copilot, Python 3.12 stdlib + boto3 + mcp. Public on GitHub (CHLIN0/reinvent-nova-copilot), MIT.
- Layout: `atlas/` (agent.py Bedrock Converse loop; tools.py tool specs + dispatcher; catalog.py official Events API + synthetic fixture; official_auth.py OAuth PKCE loopback; official_mcp.py; routing.py; planner.py; profile.py local per-attendee profile + state; prompts.py; env.py), `web.py` (local web app on 127.0.0.1:8500 serving Event Atlas from `explorer/` plus the Copilot panel `web/copilot.js`), `explorer/` (Event Atlas: server.py, ui/src/*.mjs, ui/dist built), `tests/` (unittest, offline), `docs/plans/2026-11-07-ux-overhaul.md` (the roadmap; your task's acceptance and must-nots are there and repeated below).
- Run: `python3 -m unittest discover -s tests` (must stay green). Web: `python3 web.py --port 8510 --explorer-port 8511 --profile dev` (do NOT use 8500/8493: BR's instance runs there; never stop it).
- `.env` (git-ignored) holds Bedrock credentials; never print or commit it. `local-private/` is git-ignored user data.
- Live Nova Pro calls cost money: keep test runs small; offline tests mock Bedrock.
- Work in your own git worktree and branch (create it: `git -C /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot worktree add /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot-wt-<task> -b <branch>`); commit there with clear messages; do NOT push and do NOT open a PR; the host does. No secrets, no absolute local paths, no chat/session ids in committed files.
- Deliver: a short report at the end: files changed, test output, what you verified live vs offline, and anything you could not do.

- Wave 1 is merged on `main`: `/api/plan` (server-side plan), `atlas/guard.py` and `locked_from_schedule` (reservations locked in tools), `atlas/pricing.py` + `atlas/costs.py` (cost ledger; `Agent(feature=...)` tags every model call). Build on them; do not reimplement.
- Codex (gpt-6.1-sol) reviews your branch against the brief; findings come back to you until MERGE.
