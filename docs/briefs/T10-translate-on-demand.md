# T10 · Understand sessions in your language (E0) — Codex development task

## Why
BR: "at least translate when I talk to the agent; translating everything is too costly." The official API accepts `locale` but re:Invent 2026 reports `supportedLanguageCodes: ["en-US"]` (10/26 reading), so translation is ours, on demand.

## Scope
1. `atlas/translate.py`: `translate_session(session_id, lang) -> dict` returns `{title, abstract, lang, source: "official"|"nova"|"cache", model, cached: bool}`. Order: (a) ask the official API with `locale=lang` via `atlas/catalog.py` (`GetSession` supports `locale`; read `Content-Language` to know what came back; if it is already `lang`, return it as `official`); (b) cache lookup keyed by `event, session_id, sha256(title+abstract), lang, translator_version` under `local-private/translations/<lang>.jsonl` (mode 0600); (c) one Nova call (default `us.amazon.nova-pro-v1:0`, env `TRANSLATE_MODEL_ID` to try Lite/Micro) with a fixed prompt: keep the session code and product names, translate title and abstract, no additions; log the cost through the T0 ledger with `feature="translate"`. Never translate the whole catalog; no batch endpoint.
2. `web.py`: `GET /api/translate/<session_id>?lang=zh-Hant` → that dict. Event Atlas session detail: a "翻譯 / Translate" button that calls it and shows the translation under the original with an "unofficial translation (Nova)" mark; language from the profile `language` field, default zh-Hant. (Touch only the session detail rendering in `explorer/ui/src/app.mjs`; T3 is reworking the page layout elsewhere.) Rebuild dist.
3. Copilot: answers in the profile language (prompt already has a language rule? check `atlas/prompts.py` and add one line only if missing, coordinating with T4 which owns that file: if T4 is in progress, put the rule in the brief for the host instead of editing).
4. Tests: `tests/test_translate.py` offline: official-locale path, cache hit (no model call), cache miss (mocked Bedrock), hash invalidation when the abstract changes, cost ledger line with feature `translate`.

## Acceptance
- A zh-Hant user clicking Translate on any session sees the translated abstract within 3 s (first time, live Nova; measure once on the synthetic catalog); the second click makes no model call; `python3 -m atlas.costs` shows a `translate` line.
- All tests green.

## Must not
- Pre-translate the catalog; commit translations; add dependencies; touch `atlas/prompts.py` while T4 owns it.

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
