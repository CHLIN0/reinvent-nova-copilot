# T0 · Cost ledger (Codex development task)

## Why
BR requires every model cost to be recorded from now on, as the baseline for the AgentCore evaluation (M2).

## Scope
1. `atlas/pricing.py`: a price table for Amazon Bedrock Nova models in us-east-1 (per 1K input/output tokens) with the source URL and the date you read it; if you cannot read the live page, mark values `unverified` and say so in the report. Function `estimate_usd(model_id, input_tokens, output_tokens) -> float | None`.
2. `atlas/agent.py`: after every `converse` response, read `response["usage"]` (`inputTokens`, `outputTokens`, `totalTokens`) and append one JSON line to `local-private/costs.jsonl` (create dir, file mode 0600): `ts, model, feature, input_tokens, output_tokens, usd, rounds`. `feature` comes from an optional `Agent(feature=...)` argument (default `chat`); `web.py` passes `briefing` for the briefing. Never log prompt text.
3. `python3 -m atlas.costs`: prints a per-feature and per-day summary (calls, tokens, USD) and writes `docs/costs.md` with the price table used and its date. `docs/costs.md` is committed; the JSONL is not.
4. Tests: `tests/test_costs.py` with a mocked client that returns a `usage` block; assert the ledger line and the summary math. Keep offline.

## Acceptance
- After `python3 -m unittest discover -s tests`, `python3 -m atlas.costs` works on an empty ledger and on the test ledger.
- All tests green; no change to tool contracts or prompts.

## Must not
- Call Bedrock in tests. Touch `atlas/tools.py`, `atlas/prompts.py`, `web/`, `explorer/`.

## Repository facts (read these first)
- Repo: re:Invent Nova Copilot, Python 3.12 stdlib + boto3 + mcp. Public on GitHub (CHLIN0/reinvent-nova-copilot), MIT.
- Layout: `atlas/` (agent.py Bedrock Converse loop; tools.py tool specs + dispatcher; catalog.py official Events API + synthetic fixture; official_auth.py OAuth PKCE loopback; official_mcp.py; routing.py; planner.py; profile.py local per-attendee profile + state; prompts.py; env.py), `web.py` (local web app on 127.0.0.1:8500 serving Event Atlas from `explorer/` plus the Copilot panel `web/copilot.js`), `explorer/` (Event Atlas: server.py, ui/src/*.mjs, ui/dist built), `tests/` (unittest, offline), `docs/plans/2026-11-07-ux-overhaul.md` (the roadmap; your task's acceptance and must-nots are there and repeated below).
- Run: `python3 -m unittest discover -s tests` (must stay green). Web: `python3 web.py --port 8510 --explorer-port 8511 --profile dev` (do NOT use 8500/8493: BR's instance runs there; never stop it).
- `.env` (git-ignored) holds Bedrock credentials; never print or commit it. `local-private/` is git-ignored user data.
- Live Nova Pro calls cost money: keep test runs small; offline tests mock Bedrock.
- Commit on your own branch with clear messages; do NOT push and do NOT open a PR; the host does. No secrets, no absolute local paths, no chat/session ids in committed files.
- Deliver: a short report at the end: files changed, test output, what you verified live vs offline, and anything you could not do.
