# T2 · Reservations are locked in code (fixes P3, P4)

## Why
Asked to plan Wednesday "around my reserved sessions, keep my reservations", Nova Pro called `plan_itinerary` without `must`; the plan overlapped BR's real reservations GHJ315 (08:00–10:00) and DVT415-R2 (10:30–11:30). The briefing also claimed "feasible, no conflicts" after only `get_profile` + `get_my_schedule`, never calling `check_itinerary`. Correctness must not depend on the model remembering a parameter.

## Scope
1. `atlas/tools.py`: in `_call` for `plan_itinerary` and `check_itinerary`, when `official_auth.is_signed_in()` (import lazily; tolerate failure), load the official schedule via the backend's `get_schedule` and resolve ids with `get_session`: reserved sessions become `must` (union with caller's `must`) and their time windows become `blocked` entries for the plan day; favorites are added to candidates with priority. Add `locked_from_schedule: [codes]` to the result so the model and the UI can state it. Offline tests use a `Backend` stub whose `get_schedule` returns ids.
2. New `atlas/guard.py`: `strip_unverified_feasibility(text, trace) -> (text, removed: list[str])`: if no `check_itinerary`/`plan_itinerary` call succeeded in the trace, remove sentences that assert feasibility/no conflicts/tight transitions (keyword list: feasible, no conflicts, conflict-free, tight transition, enough time, can make it, reachable) and append one sentence: "I have not checked travel feasibility yet." Pure function, unit-tested.
3. `web.py`: in `_briefing` only, (a) instruct the model to call `check_itinerary` per conference day with the reserved ids, and (b) pass the result through `guard.strip_unverified_feasibility`, returning `removed` in the JSON. Do not change other routes (another session owns `web.py` routes for the plan).
4. `atlas/prompts.py`: one rule under Tool rules: reserved sessions are locked by the tools; never propose a session that overlaps a reservation; when the tool reports `locked_from_schedule`, say so in one clause.
5. Tests: `tests/test_locked.py`: the Wednesday case rebuilt on the synthetic fixture (pick three fixture sessions as "reserved", assert no chosen session overlaps them and all three are in `chosen`); guard tests (claims removed when trace lacks the check; untouched when present).

## Acceptance
- Wednesday-style test passes; `check_itinerary` appears in every briefing trace in an offline test with a mocked Agent that returns no tool calls (guard must then strip the claim).
- All tests green. Report includes one live run (`python3 chat.py --profile dev --trace "..."` on the synthetic catalog) showing `locked_from_schedule` in the trace when a fake signed-in state is injected (use `official_auth.set_auth` with a stub whose `status()` says connected and a Backend stub; do not use BR's real account).

## Must not
- Change routing or the planner's algorithm. Add new tools. Touch `explorer/`, `web/copilot.js`, or `web.py` outside `_briefing`.

## Repository facts (read these first)
- Repo: re:Invent Nova Copilot, Python 3.12 stdlib + boto3 + mcp. Public on GitHub (CHLIN0/reinvent-nova-copilot), MIT.
- Layout: `atlas/` (agent.py Bedrock Converse loop; tools.py tool specs + dispatcher; catalog.py official Events API + synthetic fixture; official_auth.py OAuth PKCE loopback; official_mcp.py; routing.py; planner.py; profile.py local per-attendee profile + state; prompts.py; env.py), `web.py` (local web app on 127.0.0.1:8500 serving Event Atlas from `explorer/` plus the Copilot panel `web/copilot.js`), `explorer/` (Event Atlas: server.py, ui/src/*.mjs, ui/dist built), `tests/` (unittest, offline), `docs/plans/2026-11-07-ux-overhaul.md` (the roadmap; your task's acceptance and must-nots are there and repeated below).
- Run: `python3 -m unittest discover -s tests` (must stay green). Web: `python3 web.py --port 8510 --explorer-port 8511 --profile dev` (do NOT use 8500/8493: BR's instance runs there; never stop it).
- `.env` (git-ignored) holds Bedrock credentials; never print or commit it. `local-private/` is git-ignored user data.
- Live Nova Pro calls cost money: keep test runs small; offline tests mock Bedrock.
- Commit on your own branch with clear messages; do NOT push and do NOT open a PR; the host does. No secrets, no absolute local paths, no chat/session ids in committed files.
- Deliver: a short report at the end: files changed, test output, what you verified live vs offline, and anything you could not do.
