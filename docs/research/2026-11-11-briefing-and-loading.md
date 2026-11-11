# Briefing reliability and agenda loading: measurements and best practice (2026-11-11)

Host research for T11–T13.
- **Sources:** gathered by a research subagent (Claude Sonnet); the host re-read the two AWS pages marked "host-verified".
- **Measurements:** the host's own, taken on BR's account with server 251259b, signed in, in the shared agent browser.

## Measurements

| What | Cold (cache expired) | Warm |
|---|---|---|
| Full official ListSessions read | 11.3 s: 11 pages of about 1 s, in order (`nextToken`), 2,516 sessions | n/a |
| `/api/catalog` (Atlas) | 10.4–11.3 s, 7.0 MB uncompressed | 0.2 s |
| `/api/my-schedule` | 10.7 s | 1.2 s |
| `/api/plan` | 14.0 s | 1.7 s |
| Briefing | starts at 11.3 s and returns at 23.1 s (2–3 Bedrock calls, 4k–16k input tokens each) | about 12 s |
| First paint | 0.06 s (page frame) | 0.06 s |

Causes in our code:
- **Atlas refreshes inside the request.** `explorer/official_catalog.py` reads the catalog again when the snapshot is older than 60 s, and the request waits for it.
- **The Copilot side reads the catalog a second time.** `atlas/catalog.py` (5-minute TTL) does its own full read. Requests that arrive on a cold cache at the same time each start their own read.
- **`get_session` copies the whole list on every lookup.**
- **`/api/catalog` is large and copied each time.** About 7 MB uncompressed, deep-copied on every request.

The official API's cost is fixed at about 11 s per full read. The fix is to keep that read out of the user's path.

Briefing first-after-restart results:
- **Before PR #15:** 0 of 4 passed. A replay of a captured request showed the empty "schedule changed" sentence was the cause: 0/3 with it, 5/5 without.
- **After PR #15:** 3 of 4 passed. The remaining failure is the same `ModelErrorException`.

## Sources

**A. Amazon Nova tool use**
- [Tool-use troubleshooting](https://docs.aws.amazon.com/nova/latest/userguide/tools-troubleshooting.html) (undated; **host-verified**):
  - It lists "The model produced an invalid sequence as part of ToolUse" under Model Error Exception.
  - Fixes it recommends:
    - greedy decoding (temperature 0, `topK` 1);
    - a larger `maxTokens` ("If the model response is larger than your max token count, it will trigger an exception");
    - keeping the `<thinking>` output but dropping it in the app.
  - No root cause is stated.
- [Prompting for tool use](https://docs.aws.amazon.com/nova/latest/userguide/prompting-tools-function.html) (undated): do not instruct the model how to format tool calls or `<thinking>`. Our system prompt has no such instruction (host-checked).
- [Defining tools](https://docs.aws.amazon.com/nova/latest/userguide/tool-use-definition.html) (undated): `auto`, `any` and `tool` are supported; `any` "will call exactly one tool each time".
- [Structured output](https://docs.aws.amazon.com/nova/latest/userguide/prompting-structured-output.html) (undated): ways to get structured output without free tool choice.
- **Not found:** an official tool-count limit for Nova Pro.

**B. Bedrock errors and retries**
- [Converse API reference](https://docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_Converse.html) (undated; **host-verified**):
  - `ModelErrorException` is HTTP 424, "The request failed due to an error while processing the model". The page never calls it retryable.
  - Only `ModelNotReadyException` is described as retried automatically by the SDK.
- [boto3 retries](https://docs.aws.amazon.com/boto3/latest/guide/retries.html) (undated): standard mode retries timeouts, throttling and HTTP 500/502/503/504, not 424. Retrying this error in the app would be our own choice, not an AWS recommendation.

**C. Agent design**
- [Anthropic, Building effective agents](https://www.anthropic.com/engineering/building-effective-agents) (2024-12-19):
  - It defines workflows as "LLMs and tools orchestrated through predefined code paths".
  - It advises the "simplest solution possible".
  - Agentic systems "trade latency and cost for better task performance".
- [Anthropic, Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) (2025-09-29): retrieve some data up front for speed; "runtime exploration is slower than retrieving pre-computed data".
- [OpenAI, A practical guide to building agents](https://cdn.openai.com/business-guides-and-resources/a-practical-guide-to-building-agents.pdf) (undated): when decisions are not complex, "a deterministic solution may suffice".
- [AWS Prescriptive Guidance, orchestration models](https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-serverless/orchestration-models.html) (undated): for a deterministic workflow, agents are "not needed"; rule-based flows give a full state trace.

**D. Perceived performance**
- [NN/g, Response times: 3 important limits](https://www.nngroup.com/articles/response-times-3-important-limits/): 0.1 s feels instant, 1 s keeps the user's train of thought, 10 s is the limit of attention; past 10 s, show progress.
- [NN/g, Skeleton screens 101](https://www.nngroup.com/articles/skeleton-screens/) (2023-06-04): skeletons for full-page loads under 10 s, spinners for single modules, progress bars past 10 s.
- [web.dev, Web Vitals](https://web.dev/articles/vitals) (2024-10-31): LCP ≤ 2.5 s, INP ≤ 200 ms, CLS ≤ 0.1 at the 75th percentile.
- [web.dev, stale-while-revalidate](https://web.dev/articles/stale-while-revalidate): serve the cached response at once and revalidate in the background.
- [OpenAI, latency optimization](https://developers.openai.com/api/docs/guides/latency-optimization) (undated):
  - make fewer sequential requests;
  - hard-code steps that are tightly constrained;
  - stream output.

## Decisions (host, by best practice)
1. **T11:** the briefing runs its fixed steps in code, and Nova gets one request with no tools. If that request fails, a briefing written by code is shown. Chat stays agentic and forced. There is no retry loop, because the error is not documented as retryable and the code-written briefing covers the failure.
2. **T12:** stale-while-revalidate with one shared catalog read; indexed lookups; gzip.
3. **T13:** status the user can read (sync progress and data age), a fixed briefing area with skeletons, facts and summary in one response (facts still shown if Nova fails); measured against LCP, CLS and INP.
4. **Not now:**
   - streaming the summary: after T11 there is one short request, so measure first;
   - a catalog stored on disk for the first load after a restart: sign-in already starts the sync;
   - lazy-loading the 3D map: it is off by default.
