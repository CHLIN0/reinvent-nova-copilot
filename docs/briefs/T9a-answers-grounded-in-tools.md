# T9a: Every Copilot answer is grounded in a tool call; the briefing asks one question

- Change class: C (agent loop / tool behaviour / briefing prompt)
- Branch: t9a-grounded-answers   Base: main
- Builder: Claude Code, Opus 5.5   Blind reviewer (planned): a fresh Claude Sonnet subagent (Codex is out of weekly quota until 2026-11-12; the rule allows a different model of the same family in that case)

## Goal
When the attendee asks the Copilot panel anything, Nova Pro reads the official data through a tool before it answers, so a plan or a time can never come from conversation memory alone. The signed-in briefing asks at most one profile question, chosen by code, not a list of every empty field.

## Why (observed on BR's account)
- 2026-11-10, 06:00:47 UTC: BR asked 「我住 Park MGM，每天最多走 8000 步，幫我排週二的議程。」 Nova answered with zero tool calls (ledger row `rounds: 0`, no trace line) and wrote "08:30 - 14:00 GHJ212"; the official time is 12:00–14:00. It also ignored BR's two Tuesday favorites, gave no departure or step count, and said it had "considered the walking limit" without computing a route. The panel's agent shares its conversation history with the briefing, so the model answered from the briefing's context.
- 2026-11-09: a session question was answered from conversation context without `get_session`, so no session cards appeared (roadmap line 109).
- T2 locked reservations inside the planning tools. That protection only holds for answers that go through the tools.
- The briefing on BR's account lists "name, role, experience level, goals, arrival, departure, transport, mobility, diet, special arrangements, and language". Root cause: `get_profile` returns `missing` = every field in `profile.FIELDS` that is empty (`atlas/profile.py:78`), and the briefing prompt (`web.py` `_briefing`, rule 3) cannot stop the model from reading that list back.
- Combined questions (for example "can I make it from Wynn to X at 10:00, and plan the rest of my day") were answered only in part (T4 status, roadmap line 95).

## Scope
1. **Tool call before every answer.** In `atlas/agent.py`, the first Converse request of each user turn must make the model call a tool. Check the current Amazon Bedrock Converse and Amazon Nova documentation for `toolConfig.toolChoice` (`auto` / `any` / `tool`) and Nova Pro's support for it, and quote the page you used in your report. Later rounds of the same turn stay `auto` so the model can finish. If Nova Pro does not support forcing a tool, stop and report to the host with the evidence; do not build a text-rewriting workaround.
2. **One profile question in the briefing, chosen in code.** The briefing must name at most one missing profile item, and only one that matters for planning. Pick it in `web.py` `_briefing` with a fixed priority order (hotel, walking limit, arrival/departure dates, then the rest), and give it to the model as a fact ("My profile does not yet say <x>."). Keep `get_profile`'s output usable for chat. If you change `missing`, keep every existing caller and test working. State facts in the prompt; do not add instruction-like rules about tool arguments.
3. **Combined questions.** Add one battery scenario with a two-part question (travel feasibility plus plan the day) and make both parts answered. Prefer a fix in the tool spec descriptions or in deterministic code over new prompt rules. If no fix holds on the live smoke, report that instead of adding rules.
4. **Tests.** Offline, with Bedrock mocked as in `tests/test_battery.py` and `tests/test_agent.py`:
   - the first request of a turn carries the forcing `toolChoice` and later rounds do not;
   - a follow-up turn in the same conversation is forced again;
   - the briefing prompt names at most one missing profile item, and the right one for a profile missing everything, for one missing only the hotel, and for a complete profile (no question);
   - the combined-question scenario.

## Tests
- Matrix rows: A1–A4 in `docs/test-matrix.md` (add the tests; keep every other row green).
- Live smoke required: yes (class C). On your own instance (`ATLAS_PROFILE_DIR=<scratch>/profiles python3 web.py --port 8550 --explorer-port 8551 --profile dev`, synthetic catalog, signed out), ask three questions and record the trace and the answer for each: a day-plan question, a session question by code, and "thanks". At most about 10 Nova calls in total. Report the head SHA. The signed-in check on BR's account is the host's.

## Done when
- [ ] `python3 -m unittest discover -s tests` green; node tests that passed on main still pass
- [ ] live smoke recorded with the head SHA
- [ ] secret scan clean (`gitleaks detect --no-git -s .` or say "not scanned" and why)
- [ ] blind review `VERDICT: MERGE` (see Notes)
- [ ] a short report: files changed, the doc page used for toolChoice, test output, live smoke transcript, anything you could not do

## Must not
- delete, skip or weaken an existing test, or edit CI config
- push, open a PR, merge, or force-push (this repo has no builder grant yet; the host pushes)
- add text post-processing that deletes or rewrites model text (`atlas/format.py` rule)
- add prompt rules that name tool arguments (Nova Pro failed every briefing, 6/6, on such a rule in T4)
- touch `explorer/ui`, the cost ledger code (T9b owns `atlas/costs.py`), or HTTP error handling in `web.py` `do_GET`/`do_POST` (T9b)
- run `python3 -m unittest` against the real ledger more than needed: until T9b lands, each run appends about 44 fake rows to `local-private/costs.jsonl`. Run the suite with `ATLAS_COSTS_LEDGER=<scratch>/costs.jsonl` only if T9b's variable exists on your base; otherwise run the files you changed plus one full run at the end, and say so in the report.

## Notes / pointers
- Worktree: `git -C /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot worktree add /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot-wt-t9a -b t9a-grounded-answers`. Commit there. Do not use ports 8500/8493 (BR's instance; never stop it).
- Blind review: when your tests pass, start a fresh Claude subagent on model Sonnet with the prompt in `~/.claude/skills/dev-host/references/blind-review.md`. Give it only this brief's path, the worktree path and `git diff main...HEAD`. Not your report. Fix or decline each finding with a reason. Round 2 gets the new diff and the previous findings only. No MERGE after round 2, or a finding that questions scope: stop and report to the host.
- `.env` (git-ignored) holds Bedrock credentials; never print or commit it. No secrets, absolute local paths, or chat/session ids in committed files.
- T9b runs in parallel and edits `atlas/costs.py`, `web.py` error handling, `web/copilot.js` error display, `.github/`. Keep your `web.py` edits inside `_briefing` and `_chat` so the host can merge both.
