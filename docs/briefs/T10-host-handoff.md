# T10 integration note for the host and T4

`atlas/prompts.py` currently has no profile-language answer rule. T4 owns this
file, so T10 deliberately leaves it untouched. Integrate this single line in
the Personal context rules when merging T4:

> Call get_profile before answering and answer in its language field, defaulting to Traditional Chinese (zh-Hant) when absent; keep session codes and product names unchanged.

This pending prompt rule is required for the Copilot-language portion of T10.
The session-detail Translate action independently reads the profile language
and defaults to `zh-Hant`. Common human-readable profile labels such as
`Traditional Chinese` and `繁體中文` normalize to a language tag on the server.

## Verification (2026-11-07)

- `python3 -m unittest discover -s tests`: 137 tests, OK, including 16 new
  offline translation/HTTP-handler tests. Bedrock is mocked; cost-report output,
  official locale headers, content hash invalidation and concurrent cache misses
  are covered.
- Four new JavaScript tests exercise the actual detail renderer with a DOM
  double: explicit click, profile/default language, provenance, original text,
  retry and stale-response handling. All 51 frontend tests outside the existing
  scene-data module pass.
- `node build.mjs` rebuilt `dist/app.js` and its source map. Full `npm run build`
  and `npm test` are blocked by missing pre-existing inputs
  `explorer/data/osm/osm-public-sample.json`.
  Existing generated map assets are retained.
- `git diff --check` passes. No dependencies or translations are committed.
- Live validation is incomplete: the sandbox denied binding the local web
  server and blocked the Bedrock runtime domain. No successful live Nova
  response or billable ledger entry was produced; the first-call 3-second
  threshold remains unmeasured. Do not interpret offline timing as acceptance.
- Rendered verification is unavailable: shared agent browser reports
  `agent_browser_not_running_and_cannot_start_here`; its required sandbox probe
  also reports the wake listener unavailable.
- Independent Claude review is unavailable: the sandbox blocked the Anthropic
  API domain during the wrapper's auth check. No actual reviewer model was
  verified, so an Opus review is not claimed.

Host follow-up: integrate the one-line T4 prompt rule, run rendered acceptance
and one live synthetic-session translation with timing, click again to confirm
cache provenance and one total model response, then run `python3 -m atlas.costs`
to verify a real `translate` line. Keep translations and the ledger private.
