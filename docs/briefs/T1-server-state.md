# T1 · State lives on the server (fixes P1, P6)

## Why
BR's Chrome blocks site storage for 127.0.0.1:8500 (IndexedDB "The user denied permission", localStorage SecurityError). Event Atlas keeps its plan ("我的安排") in IndexedDB, so for BR it shows "無法安全儲存本機安排" and "我的安排 0" while the official schedule has 9 reservations. All attendee state must live on the server.

## Scope
1. New endpoints in `web.py`: `GET /api/plan` and `POST /api/plan` (actions add/remove by session id). The plan = official reservations + official favorites (from `catalog.get_schedule()` when signed in, resolved to sessions like `_my_schedule()` does) + local picks, stored in the profile state file via `atlas/profile.py` `load_state`/`save_state` (key `plan`). Each item carries `source`: `reserved` | `favorite` | `local`.
2. Event Atlas reads the plan from `/api/plan` instead of IndexedDB/localStorage: replace `explorer/ui/src/plan-store.mjs` usage in `app.mjs` with a small fetch-based store (same `load/add/remove` surface so `refreshPlan`, `isPlanned`, `makePlanItem` keep working). Mark reserved/favorite/local items differently in the calendar and list (reuse existing styling hooks; no restyle). Filters: keep them in the URL hash only; remove the localStorage filter save (`FILTER_KEY`) and its notice.
3. `web/copilot.js`: replace `atlasItems`/`writeAtlas`/`syncOfficial`/`addToAtlas` (IndexedDB) with calls to `/api/plan`; after adding, tell Atlas to refresh without a page reload (dispatch a `window` event the Atlas app listens to, or call its exposed refresh).
4. Rebuild the UI: `ln -s /Users/br/Documents/_Project/_AWS/event-atlas/ui/node_modules explorer/ui/node_modules` (gitignored) then `cd explorer/ui && node build.mjs`. Commit `explorer/ui/dist` changes.
5. Tests: `tests/test_plan_api.py` (offline): plan merges official + local, remove works, state file mode 0600, and a test that the built `explorer/ui/dist/app.js` contains no `indexedDB` or `localStorage` plan access.

## Acceptance
- With browser storage blocked (verify by running your instance and executing in the page console: `Object.defineProperty(window,'indexedDB',{get(){throw new Error('denied')}})` before load is not possible; instead confirm no code path touches indexedDB/localStorage for the plan, and test with the synthetic catalog that "我的安排" shows items from `/api/plan`).
- No storage error is ever rendered.
- Adding a session from the Copilot panel appears in the Atlas calendar without reload.
- All tests green.

## Must not
- Add a database. Change the 3D map. Touch `atlas/tools.py`, `atlas/prompts.py`, `atlas/planner.py` (another session owns them). Restyle. Change sign-in.

## Repository facts (read these first)
- Repo: re:Invent Nova Copilot, Python 3.12 stdlib + boto3 + mcp. Public on GitHub (CHLIN0/reinvent-nova-copilot), MIT.
- Layout: `atlas/` (agent.py Bedrock Converse loop; tools.py tool specs + dispatcher; catalog.py official Events API + synthetic fixture; official_auth.py OAuth PKCE loopback; official_mcp.py; routing.py; planner.py; profile.py local per-attendee profile + state; prompts.py; env.py), `web.py` (local web app on 127.0.0.1:8500 serving Event Atlas from `explorer/` plus the Copilot panel `web/copilot.js`), `explorer/` (Event Atlas: server.py, ui/src/*.mjs, ui/dist built), `tests/` (unittest, offline), `docs/plans/2026-11-07-ux-overhaul.md` (the roadmap; your task's acceptance and must-nots are there and repeated below).
- Run: `python3 -m unittest discover -s tests` (must stay green). Web: `python3 web.py --port 8510 --explorer-port 8511 --profile dev` (do NOT use 8500/8493: BR's instance runs there; never stop it).
- `.env` (git-ignored) holds Bedrock credentials; never print or commit it. `local-private/` is git-ignored user data.
- Live Nova Pro calls cost money: keep test runs small; offline tests mock Bedrock.
- Commit on your own branch with clear messages; do NOT push and do NOT open a PR; the host does. No secrets, no absolute local paths, no chat/session ids in committed files.
- Deliver: a short report at the end: files changed, test output, what you verified live vs offline, and anything you could not do.
