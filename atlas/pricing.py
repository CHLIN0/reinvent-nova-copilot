"""USD estimates for standard on-demand Nova text inference in us-east-1.

The live pricing page was read, but its dynamic Nova rate table was unavailable.
All rates below are therefore UNVERIFIED, not current billing guarantees.
"""
from __future__ import annotations

SOURCE_URL = "https://aws.amazon.com/bedrock/pricing/"
READ_DATE = "2026-11-07"
STATUS = "unverified"
REGION = "us-east-1"
# USD per 1,000 tokens: (input, output). No batch, cache or service-tier discounts.
PRICES = {
    "amazon.nova-micro-v1:0": (0.000035, 0.00014),
    "amazon.nova-lite-v1:0": (0.00006, 0.00024),
    "amazon.nova-pro-v1:0": (0.0008, 0.0032),
    "amazon.nova-premier-v1:0": (0.0025, 0.0125),
}


def estimate_usd(model_id: str, input_tokens: int, output_tokens: int) -> float | None:
    """Estimate with the dated table; unknown IDs return None, never zero.

    Accept base IDs and US cross-region inference IDs. Other geographies, ARNs,
    and newer model versions need their own verified pricing entries.
    """
    model = model_id.removeprefix("us.")
    rates = PRICES.get(model)
    if rates is None:
        return None
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("Token counts must be non-negative")
    return (input_tokens * rates[0] + output_tokens * rates[1]) / 1000
