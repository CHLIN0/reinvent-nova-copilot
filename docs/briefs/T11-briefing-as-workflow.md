# T11: The briefing runs its fixed steps in code; Nova only writes the summary

- Change class: C (briefing prompt and agent behaviour)
- Branch: t11-briefing-workflow   Base: main
- Builder: Claude Code, Opus 5.5   Blind reviewer: Codex `review` profile through `node ~/.claude/skills/dev-host/scripts/codex-run.mjs`; a fresh Claude Sonnet subagent only if Codex is unavailable

## Goal
The signed-in briefing never fails because of a tool call, and every briefing checks every reserved day. The server runs the steps that never change. Nova Pro gets one request with no tools and writes a summary of at most 120 words. If that request fails, the attendee still gets a useful briefing written by code.

## Why (observed, 2026-11-11)
- After T9a round 3 (PR #15), the first briefing after a restart passed 3 of 4 on BR's account; before that it passed 0 of 4. The remaining failure is Bedrock `ModelErrorException`, "Model produced invalid sequence as part of ToolUse". Bedrock documents this error as HTTP 424, and boto3's standard retry mode does not retry it.
- The briefing always does the same steps: `get_profile`, `get_my_schedule`, then `check_itinerary` for each reserved day. Today Nova chooses those calls itself. In one run it called `check_itinerary` once and said there were "no conflicts or tight transitions". The other runs called it once per day and found Tuesday's GHJ212 → GHJ301-S too tight.
- The briefing makes 2–3 Bedrock calls of 4,000–16,000 input tokens, about 12 s in total, and starts only after the catalog has loaded.
- Best practice (sources in the ER and `docs/research/`; host summary):
  - Anthropic, "Building effective agents" (2024-12-19): use predefined code paths for fixed steps, and "find the simplest solution possible".
  - OpenAI, "A practical guide to building agents": "a deterministic solution may suffice" when the decisions are not complex.
  - AWS Prescriptive Guidance, orchestration models: for a deterministic workflow, agents are "not needed".
  - The Amazon Nova tool-use troubleshooting page gives no root cause for this error.

## Scope
1. **Run the fixed steps in code.** In `web.py` `_briefing`, the server calls the same functions the tools use, through `atlas.tools.dispatch`, so the results match what a tool call would return:
   - `get_profile`;
   - the official schedule, which `_briefing` already reads;
   - `check_itinerary` once for every conference day that has reservations, with the reserved ids for that day.

   Keep the existing facts: the schedule diff only when non-empty (PR #15), new and moved/cancelled sessions (T6), and the one profile question chosen in code (T9a).
2. **One text-only request.** Put the facts and the check results into a single Converse request with **no `toolConfig`**. Keep greedy decoding as it is today. Use a `maxTokens` that fits 120 words with room to spare, and state the value. Ask for the same three-part summary:
   - the conflicts or tight transitions the checks found;
   - what to do next;
   - the one profile question, or no question.

   State facts and the output shape only. Add no rules about tools or tool arguments.
3. **The trace stays honest.** The response keeps its current shape (`text`, `trace`, `schedule_diff`, `catalog_diff`, `first_visit`). The trace lists the calls the server made, each marked as made by the server, so the panel can still show "N checks". `guard.strip_unverified_feasibility` keeps working: the checks now always exist.
4. **Fallback written by code.** If the summary request fails with any Bedrock error, return a briefing built from the facts. It has the since-last-visit line, one line per day with what the checks found, and the profile question. It also carries the T9b code `model_unavailable` with a short note that Nova's summary is missing. The panel must still show the facts. Never return only an error when the facts are available.
5. **Conversation context.** Follow-up chat must still see the briefing. Append the briefing exchange (prompt and summary) to the agent's history as plain text. Chat turns stay exactly as they are (forced first request, T9a).
6. **Tests** (mocked Bedrock):
   - the briefing request has no `toolConfig`;
   - `check_itinerary` runs once per reserved day;
   - a mocked `ModelErrorException` returns the code-written briefing with the facts;
   - the one-question rule and the empty-diff rule still hold;
   - a follow-up chat turn sees the briefing in its history and is still forced.

## Tests
- Matrix rows: A1–A4, B2, L2. Add rows T11-1…T11-3 to your branch's `docs/test-matrix.md` for the no-tools request, the per-day checks and the fallback. The host reviews them.
- Live smoke (class C) on your own instance with the synthetic catalog and a fake sign-in, as in T9a round 2: 5 briefings, all pass. Record the Bedrock calls and input tokens per briefing. Then one chat follow-up, which must call a tool.
- The host checks on BR's account: 5 first briefings after a restart and sign-in, all pass.

## Done when
- [ ] `python -m unittest discover -s tests` green, with `ATLAS_COSTS_LEDGER` pointing at a scratch file
- [ ] live smoke recorded with the head SHA
- [ ] secret scan (`gitleaks detect --no-git -s .` or "not scanned" and why)
- [ ] blind review `VERDICT: MERGE`, at most 2 rounds; anything that questions scope goes back to the host
- [ ] commit on `t11-briefing-workflow`; do not push. Report the files changed, the tests, the smoke record and the calls/tokens per briefing before and after.

## Must not
- change chat turns, `toolChoice` handling for chat, or the system prompt used by chat
- touch `explorer/`, `web/copilot.js` or the catalog code (T12 and T13 own them)
- delete, skip or weaken an existing test; edit CI config
- add text post-processing that deletes or rewrites model text
- push, open a PR or merge

## Notes
- Worktree: `git -C /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot worktree add ../reinvent-nova-copilot-wt-t11 -b t11-briefing-workflow origin/main`. Python: `/Users/br/.pyenv/versions/3.12.9/bin/python`. Do not use ports 8500/8493 (BR's instance).
- `.env` (git-ignored) holds Bedrock credentials; never print or commit it.
