# Model costs

Run `python3 -m atlas.costs` to refresh this report offline. The private ledger is `local-private/costs.jsonl` (git-ignored, mode 0600).

## Price table

Source: [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/). Read date: 2026-11-07. Region: `us-east-1`. Status: **unverified**.

The live page was readable, but its dynamic Nova rate table could not be read. These fallback rates require verification before billing decisions. Estimates assume standard on-demand input/output tokens in us-east-1, including US cross-region IDs. Other regions, cache pricing, batch, service-tier discounts, taxes, and non-model services are outside this estimate.

| Model ID | Input USD / 1K tokens | Output USD / 1K tokens | Status |
| --- | ---: | ---: | --- |
| `amazon.nova-micro-v1:0` | 0.000035 | 0.000140 | unverified |
| `amazon.nova-lite-v1:0` | 0.000060 | 0.000240 | unverified |
| `amazon.nova-pro-v1:0` | 0.000800 | 0.003200 | unverified |
| `amazon.nova-premier-v1:0` | 0.002500 | 0.012500 | unverified |

Unknown model IDs have `usd: null`. Missing usage has null token counts and cost. USD columns sum known recorded estimates; unknown costs are counted separately and must not be interpreted as free calls. Token sums include known usage only. Historical entries retain their recorded USD when the table changes.

Each call is one successful Converse response, including tool rounds and the final budget-exhausted request. `rounds` counts completed tool rounds before that response (starting at 0). Failed requests without a response cannot supply usage. Days are UTC. No prompt or response text is recorded. Ledger write errors fail the request visibly.

## Per feature

| Group | Calls | Input tokens | Output tokens | Total tokens | Estimated USD (known) | Unknown USD calls | Missing usage calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| No calls recorded | 0 | 0 | 0 | 0 | 0.00000000 | 0 | 0 |

## Per day (UTC)

| Group | Calls | Input tokens | Output tokens | Total tokens | Estimated USD (known) | Unknown USD calls | Missing usage calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| No calls recorded | 0 | 0 | 0 | 0 | 0.00000000 | 0 | 0 |
