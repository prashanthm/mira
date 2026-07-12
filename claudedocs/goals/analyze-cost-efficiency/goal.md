# Goal: /analyze cost-efficiency

- **Status**: achieved (2026-07-11) — median -62.6% vs E0, gates green, 26 experiments
- **Started**: 2026-07-11
- **Branch**: `goal/analyze-cost-efficiency`

## Outcome
`/analyze` produces the same grounded, decision-useful synthesis at materially
lower LLM cost.

## Success predicate
Median **API-reported total tokens per /analyze** (prompt + completion summed
over every LLM call in one analyze; completion includes deepseek-reasoner's
hidden reasoning tokens) across the fixed panel drops **≥30%** vs the E0
baseline, AND `make test` + `make eval` are fully green on the kept
configuration.

## Measurement method (fixed for the whole goal)
- Panel: PLTR, ACN, MSFT, O, SOXL — held symbols, one question:
  "what should I do about <SYM>?", `refresh=1` (no cache).
- Harness: `claudedocs/goals/analyze-cost-efficiency/bench.py` — builds the
  real app composition (live Vantage MCP :8640 + DeepSeek routes), wraps the
  OpenAI client to record `usage` per call, sums tokens per analyze, reports
  the panel median.
- Noise rule: |Δ median| < 8% vs the comparison point → inconclusive.

## Budget
- **25 experiments minimum** (loop continues past an early predicate hit).
- Spend ceiling ≈ $5 DeepSeek; abort the loop if projected to exceed.

## Constraints
- Mira repo only; experiments on this branch; `main` stays clean.
- Never weaken the grounding contract (facts attributed to domains, no
  fabrication) — `make eval` + `make test` enforce; a win that breaks a gate
  is disproven by definition.
- Don't touch the running containers or Vantage data.

## Trigger
Immediate (2026-07-11).
