# T9b: Plain-words errors, tests that never touch the private ledger, and CI

- Change class: D (multi-file: costs, web error handling, panel and Atlas error display, CI)
- Branch: t9b-errors-ledger-ci   Base: main
- Builder: Claude Code, Opus 5.5   Blind reviewer (planned): a fresh Claude Sonnet subagent (Codex is out of weekly quota until 2026-11-12; the rule allows a different model of the same family in that case)

## Goal
1. Running the offline tests never writes to `local-private/costs.jsonl`.
2. When sign-in has expired or is refused, the official API rate-limits, or Bedrock is unavailable, the attendee reads one plain sentence that says what happened and what to do. No exception class names or raw service text reach the UI.
3. Every pull request and every push to `main` runs the offline tests on GitHub Actions with no cloud credentials.

## Why (observed)
- Each `python3 -m unittest discover -s tests` run appends about 44 rows with null usage to BR's private ledger in about 50 ms (seen 2026-11-07, 2026-11-09 03:05 UTC and 2026-11-10 05:58 UTC; 167 of 202 rows). `tests/test_agent.py`, `test_costs.py` and `test_translate.py` already patch `costs.LEDGER_PATH`; the other suites that run the real agent loop with a mocked client do not.
- `web.py` `do_POST` returns `{"error": f"{type(e).__name__}: {e}"}` on any exception, which shows raw Bedrock/botocore text in the panel. Roadmap T9 asks for user-facing text for 401/403/429 and Bedrock unavailable.
- There is no CI. The repo is public on GitHub.

## Scope
1. **Ledger isolation.** Add an environment override for the ledger path in `atlas/costs.py` (name it `ATLAS_COSTS_LEDGER`) and make the test package use a temporary ledger for every test by default, for example in `tests/__init__.py` or a shared base, so a new test cannot forget it. Add a test that runs a mocked agent turn and asserts the real `local-private/costs.jsonl` is unchanged (size and mtime). Do not edit or clean the existing ledger file; the host handles that with BR.
2. **Error mapping, server side.** One small mapping in `web.py` from failure to a short code and an English sentence, used by the chat, briefing, translate, RSVP/favorite/cancel and plan routes:
   - official API 401 or expired token → `signin_expired`: "Your AWS Events sign-in has expired. Sign in again from the top of the page."
   - official API 403 → `forbidden`: "AWS Events refused this request for your account."
   - official API 429 → `rate_limited`: "AWS Events is busy. Wait a minute and try again."
   - Bedrock throttling, unavailable, access denied, model error, or no credentials → `model_unavailable`: "Nova is unavailable right now. Your plan and the official schedule are unaffected; try again shortly."
   - anything else → `server_error`: "Something went wrong on this computer's Nova Copilot service. Try again; if it repeats, restart it."
   Response shape: `{"error": "<code>", "message": "<sentence>"}` with the matching HTTP status. Log the exception class (never the token, credentials or request body) to stderr. Keep existing specific errors that already read well (for example RSVP per-item result codes from T7) as they are.
3. **Error display.** `web/copilot.js` shows `message` when present (fallback to the code). Event Atlas (`explorer/ui/src`) shows it in its existing notice for translate and plan/cancel failures, in 繁體中文 matching its labels: 登入已過期，請從頁面上方重新登入。／AWS Events 拒絕了這個要求。／AWS Events 目前忙碌，請稍候一分鐘再試。／Nova 暫時無法使用；你的安排與官方行程不受影響，請稍後再試。／本機的 Nova Copilot 服務發生錯誤，請再試一次；若重複發生請重新啟動。 Rebuild `explorer/ui/dist` with `node build.mjs`.
4. **CI.** `.github/workflows/ci.yml` based on `~/.claude/skills/dev-host/references/ci-starter.yml`, adapted to this repo: Python 3.12, `pip install -r requirements.txt`, `python -m unittest discover -s tests` (not pytest), Node 22, and the Event Atlas node tests listed as rows with "Runs in CI: yes" in `docs/test-matrix.md`. `test-scene-data.mjs` needs `explorer/data/osm/`, which is not in git; leave it out of CI and do not change the test. No secrets, no AWS credentials, `permissions: contents: read`. Also add `.github/pull_request_template.md` from `~/.claude/skills/dev-host/references/pull_request_template.md`.
5. **Tests.** The ledger test above; one test per error code through the HTTP handler with the failure mocked (botocore `ClientError` codes for Bedrock, `HTTPError` 401/403/429 for the official API); a node test on `web/copilot.js` that an error with `message` renders that sentence.

## Tests
- Matrix rows: B1–B4 in `docs/test-matrix.md` (add the tests; keep every other row green).
- Live smoke: not required (no prompt or tool-spec change). Show one error in your own instance (port 8560/8561, synthetic catalog, signed out), for example by setting an invalid `NOVA_MODEL_ID`, and screenshot the panel.
- CI: the host pushes your branch; the workflow must be green on your head SHA before merge.

## Done when
- [ ] `python3 -m unittest discover -s tests` green with the real ledger untouched (show size and mtime before and after)
- [ ] node tests green (the ones in CI)
- [ ] secret scan clean (`gitleaks detect --no-git -s .` or say "not scanned" and why)
- [ ] blind review `VERDICT: MERGE` (see Notes)
- [ ] a short report: files changed, test output, the error screenshot path, anything you could not do

## Must not
- delete, skip or weaken an existing test
- push, open a PR, merge, or force-push (this repo has no builder grant yet; the host pushes)
- touch `atlas/agent.py`, `atlas/prompts.py`, `atlas/tools.py`, or `_briefing`/`_chat` in `web.py` (T9a owns them)
- restyle the UI or add dialogs; reuse the existing notice areas
- put any credential, token or real user data in CI, fixtures or screenshots

## Notes / pointers
- Worktree: `git -C /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot worktree add /Users/br/Documents/_Project/_AWS/reinvent-nova-copilot-wt-t9b -b t9b-errors-ledger-ci`. Commit there. Do not use ports 8500/8493 (BR's instance; never stop it).
- Until your ledger fix is in place, each full unittest run on the real tree appends fake rows to BR's ledger. Land item 1 first, then run the full suite.
- Blind review: when your tests pass, start a fresh Claude subagent on model Sonnet with the prompt in `~/.claude/skills/dev-host/references/blind-review.md`. Give it only this brief's path, the worktree path and `git diff main...HEAD`. Not your report. Fix or decline each finding with a reason. Round 2 gets the new diff and the previous findings only. No MERGE after round 2, or a finding that questions scope: stop and report to the host.
- `.env` (git-ignored) holds Bedrock credentials; never print or commit it. No secrets, absolute local paths, or chat/session ids in committed files.
- T9a runs in parallel and edits `atlas/agent.py` and `_briefing`/`_chat` in `web.py`. Keep your `web.py` edits to the error mapping and the route handlers so the host can merge both.
