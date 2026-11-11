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

## Round 2 (after the revert, 2026-11-12)

Branch: `t9a-fix-briefing` from `origin/main`. Start with `git revert --no-edit 9196f04` so the T9a changes come back, then fix on top. Same builder, same must-nots as above.

### Why
T9a (PR #12) merged on 2026-11-11 and was reverted on main (9196f04). On BR's account the signed-in briefing failed every time T9a was in the code: 3 of 3 on main with T9a and T9b, 2 of 2 on the T9c branch. The server logged `nova-copilot briefing: ModelErrorException (ModelErrorException) -> model_unavailable`. The pre-T9 commit `a0dd70b` and main after the revert briefed normally on the same data. The full Bedrock message was not captured, because `_log_failure` in `web.py` logs only the class and code. The briefing worked once on the T9a+T9b integration branch, on 2026-11-10 around 17:40 UTC, so the failure may depend on the briefing's content (a catalog diff, new-session facts or the one-question fact). Leading suspect: `toolChoice: any` on the briefing's first request, which the briefing prompt already tells to call `get_profile` and `get_my_schedule`.

### Scope
1. **Capture the real error.** For Bedrock `ModelErrorException` and `ValidationException` only, `_log_failure` also logs the first 300 characters of the Bedrock error message on stderr. Never log tokens, credentials or the request body. This is the only change allowed outside `_briefing`, `_chat` and `atlas/agent.py`.
2. **Reproduce before fixing.** Build the briefing request the way `_briefing` does, with the synthetic catalog and a synthetic profile missing the arrival date. Include a reservation set across several days, a new-session fact and a moved-reservation fact. Run it against real Nova Pro with T9a restored. Record how often it fails and the error message. If it does not fail, say so and try the variants above. At most about 15 Nova calls.
3. **Fix the cause you found, not the symptom.** Chat turns must stay forced to call a tool on their first request; that is T9a's goal and it held in the live smoke. If forcing is the cause for the briefing, the briefing may run its first request with `auto`; it already calls `get_profile`, `get_my_schedule` and `check_itinerary`, and `guard.strip_unverified_feasibility` covers it. Explain the choice with the evidence from step 2.
4. **Tests.** An offline test pins whatever decides forced versus `auto` for the briefing, and a test covers the log line from step 1, asserting that no token-like text appears.

### Done when
- [ ] the reproduction record (counts and the error message) is in your report
- [ ] all tests green; the briefing reproduction from step 2 passes 5 of 5 against real Nova on the fixed code
- [ ] the L1 chat smoke from round 1 still shows a tool call on every answer (at most 4 calls)
- [ ] blind review `VERDICT: MERGE`. Codex `review` profile through `node ~/.claude/skills/dev-host/scripts/codex-run.mjs` if `codex-run.mjs profiles` and a short run show the quota is back; otherwise a fresh Claude Sonnet subagent
- [ ] commit on `t9a-fix-briefing`; do not push (the host pushes, opens the PR and checks the briefing on BR's account)

## Round 3 (first briefing after sign-in, 2026-11-11)

Branch: `t9a-first-briefing` from `origin/main` (87fbc9c or later). Same builder, same must-nots as above.

### Why
PR #14 (greedy decoding) merged on 2026-11-11, and T9c (PR #13) merged on top of it. Host check on BR's account in the shared agent browser:
- The **first** signed-in briefing after each server restart and sign-in failed: 2 of 2 restarts, on f2c1a4a and on f5d489b. Each failure logged `ModelErrorException`, "Model produced invalid sequence as part of ToolUse". No ledger row was written, so the failure is on the round-0 request (forced `toolChoice: any`).
- Every later briefing on the same server passed: 4 of 4. Two of those carried 16 new catalog sessions.
- Chat stays healthy: "Tell me about GHJ212." called `get_session`, and Tuesday / 週二 planned on 2026-12-01.
- Main without T9a briefed normally right after a restart on 2026-11-11.
- Round 2's reproduction ran **signed out**. It had no official MCP tools and no fresh official catalog load, so it could not hit this path.

What changes on the first briefing after sign-in (from the code; unverified as the cause):
- `_start_sign_in` clears `catalog` and `tools._official_cache` only after `official_auth.sign_in` returns. The page may already be loading `/?signin=complete` by then, so the first briefing can race those resets.
- The first briefing loads the official catalog and lists the official MCP tools. On this path the forced request offers those read-only `aws_events__*` tools.
- The agent's history is empty. The schedule diff runs against the previous server run.

### Scope
1. **Capture the failing request.** On a briefing `ModelErrorException` or `ValidationException`, write what was sent to one JSON file under `local-private/debug/` (git-ignored). Include:
   - `toolChoice`;
   - each tool's name and the byte size of its input schema, plus the full schema of every `aws_events__*` tool;
   - the system prompt's length;
   - the messages.

   Never write tokens, credentials or headers. Keep one file per failure, and at most the 5 newest files. Test it.
2. **Stop and hand off for capture.** Commit step 1 and report to the host. The host will run your branch on BR's account, restart, sign in, and put the captured file in your worktree's `local-private/debug/`.
3. **Replay and find the cause.** Replay the captured request against real Nova Pro. Change one thing at a time: drop the official tools, `toolChoice: auto`, and an empty versus non-empty history. Name the smallest change that turns the failure into a pass. At most about 20 Nova calls.
4. **Fix the cause.** Keep chat turns forced on their first request. If the cause is the forced request together with the official tool specs, prefer fixing what the forced request offers (for example only our own read tools) over dropping forcing. Explain the choice with the replay evidence.
5. **Tests.** Pin the fix offline. Add a test that the capture holds no token-like text.

### Done when
- [ ] the capture is committed and tested, and the host has handed back a captured failing request
- [ ] the replay table (variant, passes / tries) is in your report
- [ ] all tests green; replaying the captured request on the fixed code passes 5 of 5
- [ ] blind review `VERDICT: MERGE` (Codex `review` profile if its quota allows, else a fresh Claude Sonnet subagent)
- [ ] commit on `t9a-first-briefing`; do not push (the host pushes, opens the PR and checks the first briefing after a restart on BR's account)

### Host decision after two review rounds (2026-11-11)
The capture (scope 1) did its job: the replay found the cause. Both rounds of review on `t9a-first-briefing` returned only P1s on the capture's redaction rules, never on the fix. **Round 3 ships the root-cause fix alone**, on branch `t9a-empty-diff`: the briefing states a schedule change only when something was added or removed, with a test. The capture code is **not** part of this delivery and stays unpushed on `t9a-first-briefing`. The round-2 `bedrock-message` stderr line remains for diagnosis. For this delivery, scope 1, 2 and 5's capture test and the first Done-when line are void. The replay of the captured request (3 of 3 on the fixed code) and the host's live check of the first briefing after a restart replace them.
