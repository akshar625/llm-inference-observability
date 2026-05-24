from shared import LogEvent

# USD per 1M tokens: (input_rate, output_rate). Update from provider pricing pages.
MODEL_PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001":  (0.80,  4.00),
    "claude-3-5-haiku-20241022":  (0.80,  4.00),
    "claude-sonnet-4-6":          (3.00, 15.00),
    "claude-opus-4-7":            (15.00, 75.00),
    "gpt-4o-mini":                (0.15,  0.60),
    "gpt-4o":                     (2.50, 10.00),
    "gpt-4-turbo":                (10.00, 30.00),
    "gemini-flash-latest":        (0.075, 0.30),
    "gemini-2.0-flash":           (0.075, 0.30),
    "gemini-2.5-flash-preview-05-20": (0.15, 0.60),
}


class CostCalculatorEnricher:
    """Estimates cost from token counts via a static price map.
    Production swap: pull pricing from a config service or DB for hot updates."""

    async def enrich(self, event: LogEvent) -> LogEvent:
        pricing = MODEL_PRICING.get(event.model)
        if pricing is None:
            return event

        input_rate, output_rate = pricing
        cost = 0.0
        if event.tokens_in:
            cost += (event.tokens_in / 1_000_000) * input_rate
        if event.tokens_out:
            cost += (event.tokens_out / 1_000_000) * output_rate

        event.estimated_cost_usd = round(cost, 8)
        return event
