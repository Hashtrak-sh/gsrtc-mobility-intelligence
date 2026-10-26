# Milestone 5 — Competition, Pricing and Survey Intelligence

Implement the following from shared source tables.

## Competition

- State vs synthetic private departures and seats by time slot.
- Fare index (state fare / median private fare) for normal and illustrative peak/surge conditions.
- Bus-type and departure-time gaps.
- State/private review theme comparison.
- Competitive gap score with visible component weights.
- Recommendations for a possible departure slot, bus type and fare scenario, with projected occupancy and assumptions.

Do not scrape private booking platforms or imply the competitor data is live.

## Pricing

- Interactive fare slider or input.
- Use documented elasticity formula and sensitivity range.
- Recalculate projected demand, fare revenue, occupancy and contribution using explicit included costs.
- Enforce reasonable fare bounds and guard against division by zero.

## Survey intelligence

- Descriptive analysis of current mode, trip purpose, reasons, and switch conditions.
- Fit a simple logistic model only if synthetic labels and sample size support a meaningful demonstration; show it as illustrative.
- Deterministic theme tagging is the fallback. LLM theme analysis is optional and cached.
- Generate `docs/survey_questions.md` with a QR-friendly short survey matching the schema. If a live response endpoint is not implemented, do not imply the QR is collecting responses.

## Verification

Test fare elasticity calculations, theme aggregation, and survey schema alignment. Clearly distinguish descriptive synthetic survey findings from model-based switching probabilities.
