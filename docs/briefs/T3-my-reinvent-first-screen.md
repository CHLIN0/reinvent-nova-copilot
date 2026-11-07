# T3 · Signed-in first screen = "My re:Invent" (fixes P2, P6; depends on T1, merged)

## Why
Signed in, the first screen is still the whole catalog: 2,471 sessions, first cards "Wishing Booths" and "Breakfast", the attendee's 9 reservations not distinguished, the Copilot hidden behind a corner button. The product must answer "what is my day", not "what exists".

## Scope
1. After sign-in (`/api/status` signed_in, or `/api/plan` official.status == live), Event Atlas opens on **My re:Invent**: single-day view of the first conference day (2026-11-30) until that date, then today; reserved sessions highlighted, favorites and local picks marked (use the T1 source marks), gaps between reserved sessions shown as visible empty blocks with their length ("2 h free"). Catalog browsing moves to a second tab **Explore** (the current full view, filters collapsed by default).
2. The Copilot briefing is shown inline at the top of My re:Invent (call `/api/briefing` once per page load when signed in; reuse `web/copilot.js` rendering), not only inside the panel. The panel itself becomes a persistent side panel with a toggle in the header, not a floating corner button. One sign-in control only (remove the duplicate in the Copilot panel).
3. Signed out: keep today's behaviour (banner + Explore), with the demo notice.
4. Implement in `explorer/ui/src/*.mjs` + `explorer/ui/index.html` + `web/copilot.js` + `web/copilot.css`; rebuild `explorer/ui/dist` (symlink node_modules from `/Users/br/Documents/_Project/_AWS/event-atlas/ui/node_modules`). Keep the five-day view available inside Explore.
5. Tests: node tests for the view selection logic (signed-in + date → My re:Invent/day; signed-out → Explore) and an offline Python test if you touch `web.py`.

## Acceptance
- Screenshot from a real run (your instance on 8510/8511 with a fake signed-in state via `official_auth.set_auth` stub and the synthetic catalog): first paint shows My re:Invent for the demo profile's day with reserved sessions highlighted and gaps labelled; no breakfast/booth cards unless Explore is opened; the briefing is visible at the top; one sign-in control.
- All tests green.

## Must not
- Restyle colours/typography; remove the five-day view; add animations; change `atlas/` tool contracts; touch `atlas/prompts.py` (T4 owns it).

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
