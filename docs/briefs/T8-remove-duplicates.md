# T8 · Remove duplicates (fixes P8)

## Why
Two front ends survived the hackathon: the Event Atlas page with the docked Copilot panel (what BR uses), and the older chat-only page `web/index.html` served at `/copilot`, with its own sign-in button, its own profile form and its own plan rendering. The docked panel also still has a "plan/day" tab that duplicates what My re:Invent and 我的安排 now show from `/api/plan`. Two places for the same state is where attendees lose trust (`docs/ux-flow.md`, principle 1). BR approved: delete `/copilot`, keep the CLI.

## Scope
1. **Delete the chat-only page.** Remove `web/index.html` and the `/copilot` route in `web.py`; `/` serves the Event Atlas page with the panel. When Event Atlas is not available (`--explorer-port 0` or `explorer/ui/dist` missing), `/` returns a plain 503 text saying Atlas is not built and how to build it (`cd explorer/ui && node build.mjs`); no second UI. Update the startup print line and README line "`/copilot` is a chat-only view", and `docs/ux-flow.md` where it mentions two login buttons.
2. **One sign-in path.** With the page gone, `/api/signin` (used only by `web/index.html`; check) goes too if nothing else calls it; `/api/auth/start` (Atlas header) stays. Verify with grep and the node tests before removing any route; remove only what is dead.
3. **One place where the plan is shown.** In `web/copilot.js`, remove the "day/plan" tab (`bodies.day`, `renderPlan`, `lastPlan`, the schedule list) and the profile tab if Atlas or the panel's Ask flow already covers what it does (the profile is edited through conversation with `update_profile`; check whether the profile tab is the only way to edit `fields_help` entries and keep it if so, saying why). The panel keeps: the briefing, the Ask conversation with trace, suggested session cards with their actions, and the near-expiry re-sign-in button. Plan picks still go to `/api/plan` and show in Atlas (the existing plan event).
4. **Tests.** Update `tests/copilot_status.mjs` and `tests/copilot_plan_event.mjs` for the removed tab; add an offline handler test that `/copilot` is 404 and that `/` without Atlas returns the 503 text; keep every other test green. Remove dead CSS in `web/copilot.css`.

## Acceptance
- `curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8540/copilot` → 404; `/` renders Atlas with the panel.
- Screenshot from your own instance: header with one sign-in control, panel without a plan tab, Ask tab working with the synthetic catalog (offline-mocked or one small live call at most).
- `python3 -m unittest discover -s tests` green; node tests green; `chat.py` and `atlas/mcp_server.py` unchanged and working (`python3 chat.py --help`).

## Must not
- Remove or change `chat.py`, `atlas/mcp_server.py`, or anything under `atlas/`.
- Restyle, rename tabs, or change My re:Invent/Explore behaviour in `explorer/ui`.
- Remove a route or function that something else still calls (tests count); when in doubt keep it and list it in the report.

## Lessons from T3/T4 (apply them)
- Codex reviews scope strictly: this is a removal task; anything added beyond the 503 text and test updates comes back as FIX FIRST.
- No prompt changes, no post-processing changes.

## Repository facts (read these first)
- Repo: re:Invent Nova Copilot, Python 3.12 stdlib + boto3 + mcp. Public on GitHub (CHLIN0/reinvent-nova-copilot), MIT.
- Layout: `web.py` (routes; `/` injects `web/copilot.js` + `web/copilot.css` into Atlas's `explorer/ui/dist/index.html` when `explorer_port` is set, else serves `web/index.html`; `/copilot` always serves `web/index.html`), `web/` (index.html, copilot.js, copilot.css), `explorer/` (Event Atlas), `atlas/`, `tests/` (`copilot_status.mjs` and `copilot_plan_event.mjs` run the real `web/copilot.js` against a fake DOM), `README.md`, `docs/ux-flow.md`, `docs/plans/2026-11-07-ux-overhaul.md` (the roadmap).
- Waves 1–3 are merged on `main`: T3 made the panel a docked side panel with a header toggle and the briefing inline; T5 added the near-expiry re-sign-in button in the panel; T4/T10 are server-side. Build on them.
- Run: `python3 -m unittest discover -s tests` (must stay green). Web for your own checks: `ATLAS_PROFILE_DIR=<your scratch dir>/profiles python3 web.py --port 8540 --explorer-port 8541 --profile dev` (do NOT use 8500/8493: BR's instance runs there; never stop it).
- `.env` (git-ignored) holds Bedrock credentials; never print or commit it. `local-private/` is git-ignored user data.
- Work in your own git worktree and branch (create it: `git -C /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot worktree add /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot-wt-t8 -b t8-remove-duplicates`); commit there with clear messages; do NOT push and do NOT open a PR; the host does. No secrets, no absolute local paths, no chat/session ids in committed files.
- T6 (briefing catalog diff: `_briefing` in `web.py`, briefing head in `copilot.js`) and T7 (RSVP lifecycle: new routes, `sessionCards` in `copilot.js`, Atlas card actions) run in parallel. Keep your removals surgical so the host can merge all three; the host merges T8 first.
- Codex (gpt-6.1-sol) reviews your branch against this brief; findings come back to you until MERGE.
- Deliver: a short report at the end: files removed/changed, routes removed and the grep proving they were dead, test output, screenshot path, and anything you kept on purpose.
