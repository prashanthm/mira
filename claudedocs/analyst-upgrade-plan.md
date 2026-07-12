# Analyst Upgrade Plan — Vantage + Mira

*2026-07-11 · Status: IMPLEMENTED (V1-V4 + M1-M5 same day; V5 skipped — no
clean data source; M6 comparative mode remains open). Measurements in the
analyze-cost goal log's post-goal appendix (H27/H28).*

## Context

The `/analyze` pipeline assembles evidence well (7 grounded domains, −62.6%
token cost after the autoresearch goal) but lacks the steps a fund analyst
performs before and after evidence assembly: computing the bet, decomposing
the move, arguing the other side, sizing, and keeping score. Diagnosis in the
2026-07-11 session ("think like a hedge fund analyst"); this plan turns each
gap into implementable work, split by the settled boundary — **Vantage
computes (deterministic, provenance-carrying), Mira judges (facets, synthesis,
escalation).**

Prereqs already in place: ADR-052 tier plane; analyze groups on cards;
card-carried `synthesis_hint`; parallel StateGraph; nightly jobs (incl.
earnings); `spx_playbook` as the template for new computed datasets; MCP
contract test pins `EXPECTED_TOOLS` (currently 21).

---

## Phase V — Vantage (all deterministic; follow the growth.py / spx_playbook templates)

### V1. Risk/reward + expected value — `vantage.risk_reward`  [HIGHEST VALUE/EFFORT]
- New pure module `server/vantage_server/risk_reward.py`: from ticker_plan
  (target, stop) + current price → upside$, downside$, rr_ratio; optional
  crude EV given user-supplied or default probabilities; nulls when no plan.
- MCP tool `vantage.risk_reward(symbol)` (or fold into `vantage.ticker_plan`
  payload as `risk_reward:{...}` — PREFERRED: no new tool, thesis facet
  already ships it; EXPECTED_TOOLS unchanged).
- Tests: pure math cases (no plan, no stop, price outside band).

### V2. Factor / relative-strength decomposition — `vantage.relative_strength`
- New module computing, from existing bars: return of the name vs SPY and vs
  its sector ETF over 1w/1m/3m; beta vs SPY (daily, 6m); idio move =
  name return − beta × market return for the signal window.
- Needs a symbol→sector-ETF map (small static table in `underlyings.py`
  style; unmapped → SPY only).
- Serve as `vantage.relative_strength(symbol)` (+EXPECTED_TOOLS 21→22);
  nightly not required (bars already synced nightly).
- Purpose: lets synthesis distinguish "PLTR is breaking down" from
  "high-beta software is selling off".

### V3. Position context — extend `vantage.positions`/advisor payload
- Position weight vs book, multiple of median position size, share of
  unrealized P/L; ADV from bars vs position size (liquidity sanity).
- Fold into the existing positions/position_actions payloads (no new tool).

### V4. Recommendation scorecard — `vantage.rec_scorecard`  [HIGHEST LONG-TERM VALUE]
- Nightly job scoring PAST journal recommendations against subsequent bars:
  for each dated recommendation (CLOSE/HOLD_AND_SELL_CALL/MONITOR), forward
  return at +5d/+20d; aggregate per rule → hit rate, avg fwd return.
- Storage: SQLite table (db.py SCHEMA bump) + Store put/load; wire into
  nightly.sh + nightly-docker.sh after analyze.
- MCP tool `vantage.rec_scorecard()` (22→23). This makes the pipeline's own
  judgment measurable — the calibration loop everything else improves on.

### V5 (stretch). Catalyst path beyond earnings
- Extend `vantage.earnings` with any KNOWN dated events available cheaply
  (opex already exists for indexes; skip if no clean data source — do NOT
  fabricate a calendar).

## Phase M — Mira (judgment layer; after Phase V lands)

### M1. Staleness re-entry (fixes the H9 over-trim)
- `_trim`/digest: when a result's `stale` is true or `as_of` is older than
  N days, put ONE line back into that domain's digest ("as_of 2026-07-08,
  stale") — conditional, so the fresh path stays at goal-loop cost.
- Test: stale fixture → line present; fresh → absent.

### M2. Consume the new Vantage data in existing facets
- thesis facet: risk_reward rides the ticker_plan payload automatically (V1).
- technical facet: add `vantage.relative_strength` call (two-tool precedent
  exists); synthesis_hint gains "distinguish idiosyncratic moves from factor
  moves before endorsing a signal".
- advisor: position-context fields flow through (V3) with a hint line
  ("state position size context when endorsing add/close").
- fake_vantage: new result fixtures mirroring V1-V4 payloads; facet tests.

### M3. Calibration guidance from the scorecard (V4)
- analyze graph: fetch `vantage.rec_scorecard` once per analyze (cheap, cached
  server-side) and inject per-rule hit rates into the guidance block
  ("rule2_freefall_close: 62% hit rate over 34 signals") — the synthesis
  weighs the signal BY its track record.
- Falls back silently when the tool is absent.

### M4. Pre-mortem node (the thinking-on step)  [JUDGMENT CORE]
- New optional graph node after `synthesize`: given the draft synthesis +
  digests, construct the strongest counter-argument from the same facts
  (deep tier, thinking ON via explicit `deepseek-reasoner`-class route).
- Output appended as "**Pre-mortem**: ..." section; deterministic fallback =
  omitted (never fabricated).
- Gate by conflict detection (M5) so routine cases don't pay for it.

### M5. Conflict-triggered escalation (H27/H28 from the goal log)
- Deterministic detector over fan-out results: technical/advisor
  recommendation is CLOSE/SELL while thesis has_plan and not invalidated
  (price between stop and target), OR |unrealized P/L| above a threshold,
  OR rec_scorecard hit rate for the firing rule < 55%.
- Conflicted → synthesis (and pre-mortem) on deep tier w/ thinking;
  routine → kept light config. Measure blended cost as goal-log H27/H28
  (pre-registered prediction: escalation on ~20-30% of held names, blended
  ~−50% vs E0, verdicts change on conflicted cases).

### M6 (later). Comparative mode
- `/analyze?group=equity` without subject → fan across all held symbols
  (bounded concurrency), rank by a deterministic score (R:R × conviction ×
  scorecard-weighted signal), one comparative synthesis. Answers "best use
  of the next dollar", not "what about X in isolation".

## Ops checklist (do with implementation, not before)
- Rebuild `vantage-mcp`/`vantage-backend` images after Phase V; `mira` image
  after Phase M (goal-branch wins are already on main and pushed — container
  rebuild pending).
- MCP contract test EXPECTED_TOOLS updates with each new tool.
- Update the equity panel bench (`claudedocs/goals/analyze-cost-efficiency/
  bench.py`) if M5 lands — blended-cost measurement per the goal log.
- Rotate the DeepSeek key (still outstanding) before putting it in deploy/.env.

## Verification (end-to-end, after both phases)
1. Vantage: server + MCP suites green (`VANTAGE_QUOTES=fixture`).
2. Mira: `make lint && make test && make eval` clean-env green.
3. Live PLTR (conflicted case): synthesis states R:R (1.7:1-style math),
   attributes the move (idio vs factor), cites the firing rule's hit rate,
   includes a pre-mortem section; deep-tier span fires ONLY on conflicted
   names (verify with the span-capture script).
4. Live SOXL/ETF: degradations stay honest (no plan → no R:R, nulls stated).

## Sequencing
V1 → V2 → V4 → V3 (V5 only if data exists) → M1 → M2 → M3 → M5 → M4 → M6.
Each Vantage tool lands with its Mira consumer test-first in fake_vantage so
Phase M is mostly wiring.
