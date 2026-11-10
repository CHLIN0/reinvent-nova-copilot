# T9c: "Tuesday" always means 2026-12-01

- Change class: C (agent input facts / tool results)
- Branch: t9c-weekday-resolution   Base: main
- Builder: Claude Code, Opus 5.5   Blind reviewer (planned): Codex `review` profile through `codex-run.mjs` if its weekly quota has reset (2026-11-12); otherwise a fresh Claude Sonnet subagent

## Goal
When the attendee names a conference weekday in any language the panel supports, the plan, the search and the answer all use that weekday's date. The answer names the weekday next to the date so a mismatch is visible.

## Why (observed on BR's account, 2026-11-11, branch with T9a+T9b)
- 「我住 Park MGM，每天最多走 8000 步，幫我排週二的議程。」 and "I'm at Park MGM, max 8000 steps a day. Plan my Tuesday." both called `search_sessions` and `plan_itinerary` with `day: "2026-12-02"`, which is Wednesday. The English answer opened with "Here's your Tuesday itinerary" and ended with "No additional session fits around your reservations on Wednesday."
- `atlas/prompts.py:20` already states "Mon 2026-11-30, Tue 2026-12-01, Wed 2026-12-02 …", and the tools already accept `'Tue'` (`atlas/tools.py`, `EVENT_DAYS`). The model converts the weekday to an ISO date itself and gets it wrong. Correctness must not depend on that conversion.

## Scope
1. **Resolve weekday words in code before the model sees the turn.** In the chat path (`web.py` `_chat` or `atlas/agent.py`, your choice, one place), find conference weekday words in the attendee's message and add one fact line to that turn, for example "Tuesday = 2026-12-01 (Las Vegas)". Cover English full and short names (Monday…Friday, Mon…Fri), 週一…週五, 星期一…星期五, 禮拜一…禮拜五. Facts only, no instruction-like rule about tool arguments.
2. **Tool results carry the weekday.** `search_sessions`, `plan_itinerary` and `check_itinerary` results name the day as weekday plus date (for example `"day": "2026-12-01", "weekday": "Tue"`), so the model's answer can quote it.
3. **Visible mismatch, never silent.** If the attendee named exactly one weekday and the successful `plan_itinerary` call planned a different date, append one sentence to the answer that says which day was planned and that the attendee asked for another one. Append only, never delete or rewrite model text (`atlas/format.py` rule).
4. **Tests.** Offline: the fact line for each language form; no fact line when no weekday is named; tool results carry `weekday`; the mismatch sentence is appended in a scripted battery case where the model plans 2026-12-02 for "Tuesday", and not appended when it plans 2026-12-01.

## Tests
- Matrix rows: add C1–C3 to `docs/test-matrix.md` in your branch (the host reviews the rows): C1 fact line, C2 weekday in tool results, C3 mismatch sentence.
- Live smoke required: yes. Your own instance (port 8570/8571, signed out, synthetic catalog): ask "Plan my Tuesday" and 「幫我排週二的議程」; record the `day` arguments and the answers. At most about 8 Nova calls. Report the head SHA. The host repeats it on BR's account.

## Done when
- [ ] `python -m unittest discover -s tests` and the CI node tests green; CI green on the PR head
- [ ] live smoke recorded with the head SHA
- [ ] secret scan (`gitleaks` if installed, else a pattern scan, stated in the report)
- [ ] blind review `VERDICT: MERGE`
- [ ] a short report: files changed, test output, live smoke transcript, review verdict, anything you could not do

## Must not
- delete, skip or weaken an existing test, or edit CI config
- push, open a PR, merge, or force-push (no builder grant in this repo yet; the host pushes)
- add prompt rules that name tool arguments, or delete or rewrite model text
- touch `explorer/ui`, the error mapping or the ledger code

## Notes / pointers
- Worktree: `git -C /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot worktree add /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot-wt-t9c -b t9c-weekday-resolution origin/main`. Never use port 8500/8493 (BR's instance).
- Run tests with the Python that has `boto3` and `mcp` (`requirements.txt`; mcp is pinned below 2). Tests use a temporary cost ledger since T9b.
- Blind review prompt: `~/.claude/skills/dev-host/references/blind-review.md`. Reviewer gets only this brief's path, the worktree path and `git diff main...HEAD`. At most two rounds; no MERGE after round 2, or a scope question, goes back to the host.
- `.env` (git-ignored) holds Bedrock credentials; never print or commit it.
