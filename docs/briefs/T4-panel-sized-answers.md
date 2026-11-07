# T4 · Answers that fit a panel (fixes P5)

## Why
Answers dump 20+ dropped session codes inline, pick `max_sessions` arbitrarily, run long in a narrow panel, sometimes use Markdown asterisks, and once said "feasible with the added sessions" when the planner had added nothing (search returned 10 candidates, none fit).

## Scope
1. `atlas/prompts.py`: response rules: plan answers = one line per item (leave hotel / each session / back to hotel), one line per transition, no Markdown symbols; yes/no questions answered in the first sentence; when the plan adds no session beyond the reservations, say so plainly ("No additional session fits around your reservations on Wednesday"); never claim sessions were added unless `chosen` contains non-reserved ids; dropped sessions summarised as "N dropped (3 shown: …)".
2. Server post-processing in a new `atlas/format.py` (pure functions, unit-tested) applied in `web.py` `_chat` and `_briefing` and in `chat.py`: strip `**`/`#`/backticks, collapse the dropped list to 3 + count, cap plan answers at 160 words (keep the plan lines intact, trim prose), and add the "no additional session fits" sentence when the tool result shows `chosen` ⊆ reserved and the text claims additions.
3. `atlas/tools.py` `plan_itinerary`: derive the default `max_sessions` from the day's free windows between locked sessions instead of the model's guess when the model does not pass it: fixed sessions plus one per free hour of windows ≥ 60 min, clamped 1–8 (counting windows alone gives 1 for a free day and, on a day with reservations, a cap below the reservation count, so nothing could be added); expose `free_windows` in the result so answers can mention them.
4. Scenario battery `tests/test_battery.py` (offline, mocked Bedrock returning scripted tool calls and texts): 8 cases including the Wednesday "nothing fits" case, the Tuesday profile case, a yes/no feasibility question, a route question, and a briefing; assertions: ≤160 words, first-sentence rule for yes/no, no Markdown symbols, honest "no additional session" wording.

## Acceptance
- Battery green; all tests green; one short live run on the synthetic catalog (`python3 chat.py --profile dev --trace ...`) pasted in the report showing the new format.

## Must not
- Change tool contracts beyond adding `free_windows`; add tools; touch `explorer/` or `web/copilot.js` (T3 owns them).

## Added by the host after T10 merged (2026-11-07)
- Language rule (handed over from T10, see `docs/briefs/T10-host-handoff.md`): answer in the profile's `language` (default follows the attendee's question language); keep session titles and codes in the original; when quoting a translated abstract, mark it as an unofficial translation.

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
