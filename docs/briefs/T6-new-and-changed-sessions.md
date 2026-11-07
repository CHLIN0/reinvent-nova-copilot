# T6 · New and changed sessions since last visit (E1; depends on T1, merged)

## Why
The catalog changes until the event: sessions are added, rooms and times move, a few are cancelled. Today the briefing only diffs the attendee's reserved/favorite ids against the last visit (`web.py` `_briefing`, `state["schedule"]`). An attendee who opens the app three days later never learns that a new session on their topic appeared or that a reserved session moved to another venue. The product must tell them, with codes, before it recommends anything.

## Scope
1. **Catalog snapshot per profile, on the server.** When the briefing runs signed in and the catalog actually came from the official API (`catalog.last_source()["source"] == "official_api"`; never from the synthetic fixture, never after a fallback), save a compact snapshot: `{"taken_at": iso, "sessions": {id: {"start", "end", "room", "venue", "hash"}}}` where `hash` is a short digest of title + abstract. Store it in its own git-ignored file `local-private/profiles/<name>.catalog.json`, written the way `profile.save_state` writes (0600 temp file, rename); keep `<name>.state.json` small. Add the helper to `atlas/profile.py`.
2. **Diff on each visit** (in `_briefing`, next to the existing schedule diff, inside the same locked read-modify-write): `new` = ids not in the snapshot; for the attendee's reserved sessions: `moved` = start/end/room/venue differ from the snapshot (old → new), `cancelled` = a reserved id that is in the snapshot but no longer in the live catalog. A first visit (no snapshot) records and reports nothing. If the catalog is unavailable or came from the fixture, do not update the snapshot and do not report anything as cancelled.
3. **Recommendations from the new sessions.** Server-side, pick up to 10 new sessions that match the profile's interests/role/level using the existing `catalog.search_sessions` ranking (one query per interest keyword, union, keep order). Put their codes, titles, day and venue into the briefing prompt as facts, together with the moved/cancelled reservations (code, old time/room → new time/room). The model may cite only these codes. Keep the briefing's existing rules (check_itinerary per day, under 120 words, one question at most). State facts in the prompt; do not add instruction-like rules about tool parameters (see Lessons).
4. **API and panel.** `/api/briefing` returns `catalog_diff` = `{"new": n, "moved": [...], "cancelled": [...], "recommended": [codes]}` (ids and codes only, no abstracts). In `web/copilot.js`, the briefing head that already shows "Since your last visit: reserved +a/−b" adds one short clause when `catalog_diff` has anything: "N new sessions, 1 reservation moved". Nothing else in the UI changes.
5. **Tests** (offline, Bedrock mocked as in `tests/test_battery.py`): a fixture test that loads the synthetic catalog, saves a snapshot, then serves a modified catalog (one new session on the profile's interest, one reserved session moved to another room/time, one reserved session removed) and asserts: the diff is exact; the prompt sent to the model names the new session's code and the moved reservation with old → new; `catalog_diff` is in the response; a fixture-sourced or failed catalog load leaves the snapshot untouched and reports no cancellation; the first visit reports nothing. One battery scenario for the briefing with a diff.

## Acceptance
- Fixture test green: the briefing prompt and `catalog_diff` name the new session and the moved reservation; all tests green (`python3 -m unittest discover -s tests`).
- Snapshot file is 0600, git-ignored, absent until the first signed-in briefing with a live catalog.
- No new model call: the briefing still costs one Nova Pro conversation; `docs/costs.md` unchanged unless the ledger format changed.

## Must not
- Touch `explorer/ui` (Event Atlas) or `atlas/prompts.py` (system prompt). The briefing prompt lives in `web.py` `_briefing`; change only that.
- Add tools, dependencies, a database, or a background poller; the diff runs only when the briefing runs.
- Put the snapshot in `state.json`, in git, or in the browser.
- Report anything as cancelled when the catalog did not load fully from the official API.

## Lessons from T3/T4 (apply them)
- Nova Pro failed every signed-in briefing (`ModelErrorException: invalid sequence as part of ToolUse`, 6/6) when the prompt contained an instruction-like rule about a tool argument ("do not pass max_sessions"). Put guidance about tool arguments in the tool spec, never in prose rules. New prompt text in this task is facts (codes, times), not rules.
- Server post-processing never deletes model text (`atlas/format.py`). Do not add text rewriting.
- Codex reviews scope strictly: anything not in this brief comes back as FIX FIRST.

## Repository facts (read these first)
- Repo: re:Invent Nova Copilot, Python 3.12 stdlib + boto3 + mcp. Public on GitHub (CHLIN0/reinvent-nova-copilot), MIT.
- Layout: `atlas/` (agent.py Bedrock Converse loop; tools.py tool specs + dispatcher; catalog.py official Events API + synthetic fixture + `last_source()`; official_auth.py OAuth PKCE loopback; profile.py local per-attendee profile + state (`update_state`, `save_state`); prompts.py; format.py; guard.py; costs.py), `web.py` (local web app on 127.0.0.1:8500 serving Event Atlas from `explorer/` plus the Copilot panel `web/copilot.js`; `_briefing`, `_my_schedule`, `_plan`), `explorer/` (Event Atlas), `tests/` (unittest, offline; `test_battery.py` shows how Bedrock is mocked with scripted tool calls), `docs/plans/2026-11-07-ux-overhaul.md` (the roadmap).
- Waves 1–3 are merged on `main`: `/api/plan` (server-side plan), `atlas/guard.py` + `locked_from_schedule`, cost ledger (`Agent(feature=...)`), T3 My re:Invent first screen (the briefing is rendered by `web/copilot.js` into `#mine-briefing` and the Ask tab, once per page load), T4 `atlas/format.py` + response style, T5 token lifetime, T10 on-demand translation. Build on them.
- Run: `python3 -m unittest discover -s tests` (must stay green). Web for your own checks: `ATLAS_PROFILE_DIR=<your scratch dir>/profiles python3 web.py --port 8520 --explorer-port 8521 --profile dev` (do NOT use 8500/8493: BR's instance runs there; never stop it; use your own profile dir so you never write into `local-private/profiles`). You cannot sign in to the official API yourself; live checks on BR's account are done by the host.
- `.env` (git-ignored) holds Bedrock credentials; never print or commit it. `local-private/` is git-ignored user data.
- Live Nova Pro calls cost money: keep test runs small; offline tests mock Bedrock.
- Work in your own git worktree and branch (create it: `git -C /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot worktree add /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot-wt-t6 -b t6-catalog-diff`); commit there with clear messages; do NOT push and do NOT open a PR; the host does. No secrets, no absolute local paths, no chat/session ids in committed files.
- T7 (RSVP lifecycle) and T8 (remove `/copilot`) run in parallel and also edit `web.py` routes and `web/copilot.js`. Keep your edits inside `_briefing`, the new profile helper, and the briefing head in `copilot.js`, so the host can merge without conflicts.
- Codex (gpt-6.1-sol) reviews your branch against this brief; findings come back to you until MERGE.
- Deliver: a short report at the end: files changed, test output, what you verified offline, and anything you could not do.
