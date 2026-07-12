# Hypothesis log — analyze-cost-efficiency

## E0 baseline
method: bench.py (API usage via wrapped client; panel PLTR/ACN/MSFT/O/SOXL,
refresh=1, sequential; DeepSeek routes light=chat deep=reasoner)
value: median_total=4514 mean=4270 (prompt 2457-3249, completion 913-1816, 1 call/analyze)
target: median ≤ 3160 (-30%)
notes: prompt is ~66% of spend — facet digests dominate; completion includes
reasoner's hidden reasoning tokens (completion 3-4x the visible text length).

## H1 structured trim of the technical evidence tree
prediction: the technical facet ships the full per-timeframe evidence tree
(trend/momentum/S+R x3 timeframes); replacing it with the decision core
(recommendation, rule, rationale, conviction, price, nearest S/R,
action_detail) cuts prompt ~12-18% -> total median down ~8-12%, no eval
regressions, synthesis still cites rule + levels.
experiment: synthesis._trim compacts answer["analysis"]["decisions"][*] by
dropping evidence.per_tf and factors (keep conviction, nearest_support/
resistance, broke_support_with_momentum); levels facet payload untouched.
result: median 4309 (-4.5% vs E0 4514)
verdict: inconclusive (< 8% noise rule) — the 1400-char digest cap was already
truncating the evidence tree, so structural trimming barely moved prompt size;
it only made digests cleaner. LEARNING: the cap itself bounds the prompt.
kept: reverted

## H2 halve the per-facet digest cap (1400 -> 700 chars)
prediction: prompt is ~66% of spend and ~7x capped digests dominate it;
halving the cap cuts prompt ~35-40% -> total median down ~20-25%. Risk:
more mid-JSON truncation (quality smell to watch via synthesis output).
experiment: _MAX_FACET_JSON = 700 in synthesis.py (one constant).
result: median 3364 (-25.5% vs E0 4514); gates green (852 tests, 74 evals)
verdict: confirmed
kept: yes (commit 0a0a1a? see git log H2)

## H3 word-cap the synthesis output (<=180 words)
prediction: completion is ~34% of spend and includes reasoner overthink; an
explicit brevity rule cuts visible output ~40% and some reasoning -> total
median down another ~8-12% vs H2 (cumulative ~-32%). Risk: thinner coverage
of the 7 domains (watch rule adherence).
experiment: add one sentence to _SYSTEM_PROMPT rule 4: "Keep the whole
synthesis under 180 words."
result: median 3310 (-1.6% vs H2 3364; mean -8.3%)
verdict: inconclusive — output caps shrink visible text but the reasoner's
hidden reasoning (the bulk of completion) is unaffected by brevity rules.
kept: reverted

## H4 synthesis on the light tier (deepseek-chat, no hidden reasoning)
prediction: completion tokens collapse ~60-70% (reasoning disappears);
total median down ~15-20% vs H2 -> cumulative well past -30%. Quality risk
is the real question (cross-domain conflict weighing) — evals gate it
formally; output inspected manually.
experiment: SYNTHESIS_TIER = ModelTier.LIGHT.value (one constant).
result: median 2725 (-19% vs H2; CUMULATIVE -39.6% vs E0). completion
collapsed 913-1816 -> 366-675; latency 15-25s -> 4-7s. Spot-check on the
PLTR conflict case: all 7 domains covered, thesis conflict explicitly
weighed, assumptions cited — quality held. Tier pin test updated to light.
verdict: confirmed (predicate already exceeded; loop continues per budget)
kept: yes (commit 7f06dff)

## H5 compact JSON separators in facet digests
prediction: json.dumps default emits ", "/": " padding; separators=(",",":")
cuts digest chars ~6-8% -> total median down ~4-6% vs H4 (may land in noise).
experiment: one json.dumps call in _facet_digest gains separators.
result: median 2746 (+0.8% vs H4 2725)
verdict: inconclusive — LEARNING: under a fixed CHAR cap, char-efficiency
changes repack the same cap with more data; token count is cap-bound. Only
cap reductions or uncapped text (hints, system prompt) move tokens now.
kept: reverted

## H6 digest cap 700 -> 450 chars
prediction: capped facets shrink ~35% -> prompt down ~15-20% -> total median
down ~10-14% vs H4. Quality risk rises (heavier truncation of technical/
advisor digests) — watch the conflict case still citing rule + wash math.
experiment: _MAX_FACET_JSON = 450 (one constant).
result: median 2312 (-15.2% vs H4; cumulative -48.8%) BUT the advisor digest
truncated past its wash-sale/loss math — synthesis honestly reported the gap
("wash-sale status not reported"), so grounding held but decision-critical
information was lost (violates the advisor hint's own coverage rule).
verdict: disproven at naive 450 — cap sets tokens, STRUCTURE decides what
survives the cap.
kept: reverted

## H7 structured digests sized to fit 450 (decision-core + advisor essentials + scenario trim)
prediction: with evidence trees replaced by decision cores, advisor actions
compacted to the tax/wash essentials, and expectations scenarios cut to
first+last, every digest's critical fields fit under 450 -> median ~2300
(as H6) with ALL quality checks passing incl. wash math.
experiment: _trim gains _decision_core (analysis + advisor actions) and a
scenarios[0::len-1] cut; cap 450. One design change: structure-to-fit.
result: median 2301 (-15.6% vs H4; CUMULATIVE -49.0% vs E0). All 5 quality
checks pass on the conflict case INCLUDING wash math. Gates green.
verdict: confirmed
kept: yes (commit see git log H7)

## H8 compress card synthesis_hints (~60% shorter)
prediction: 6 hints ~ 340 words of uncapped prompt text; compressing to
terse imperatives (~130 words) cuts prompt ~10-13% -> total median down
~8-10% vs H7. Risk: weaker rule adherence (earnings gate / thesis weighing
phrasing) — quality checks must still pass.
experiment: rewrite the 6 synthesis_hint strings in facets.py + advisor.py;
no logic changes.
result: median 2189 (-4.9% vs H7 2301)
verdict: inconclusive (< 8% rule; prediction 8-10% missed — hints cost fewer
tokens than the word count suggested)
kept: reverted

## H9 strip provenance blocks from facet digests
prediction: every envelope carries {source_type, source_id} (~25 tok x 7 in
uncapped facets, displacement in capped ones); stripping them from the DIGEST
only (results keep provenance) cuts ~3-6% -> likely inconclusive by the 8%
rule, but cheap to test and quality-neutral (synthesis never cites source_id).
experiment: _trim drops "provenance", "as_of", "source", "stale" keys from
the digest copy (attribution stays in the API result untouched).
result: median 2141 (-7.0% vs H7 2301)
verdict: inconclusive alone (just under the 8% rule) — real deterministic
reduction, too small solo. Combining with H8 (same class: uncapped-prompt
text) as H10.
kept: folded into H10

## H10 combined uncapped-prompt trim (H8 hints + H9 envelope strip)
prediction: two independent deterministic reductions (-4.9%, -7.0%) combine
to ~-11% vs H7 -> clears the noise bar; quality checks unaffected (neither
touches capped digest content).
experiment: hint compression + envelope stripping together vs H7 baseline.
result: median 2070 (-10.0% vs H7; CUMULATIVE -54.1% vs E0). Gates green;
all quality checks pass, all 7 domains covered.
verdict: confirmed
kept: yes (see git log H10)

## H11 digest cap 450 -> 350 (with structure-to-fit in place)
prediction: structured digests mostly fit ~350-420 chars already; a 350 cap
shaves the stragglers -> ~-5-8% vs H10, borderline vs noise. Quality risk:
technical rationale strings truncate.
experiment: _MAX_FACET_JSON = 350 (one constant).
result: median 1789 (-13.6% vs H10) BUT all 7 digests hit _truncated and the
wash math dropped out of the synthesis again.
verdict: disproven — 350 is below the structure-to-fit floor; ~450 is the
structural floor for this payload shape.
kept: reverted

## H12 compress the system prompt + user scaffold
prediction: the 4-rule system prompt (~120 words) compresses to ~55 words of
imperatives and the user scaffold drops the redundant "Subject:" line (the
query already carries it) -> ~-6-9% vs H10, borderline vs noise but
deterministic; quality checks must hold (rules still enforced).
experiment: rewrite _SYSTEM_PROMPT tersely + remove the Subject line from
user_parts (question line stays).
result: median 1973 (-4.7% vs H10 2070)
verdict: inconclusive alone (< 8%); folded into H13 combined
kept: folded into H13

## H13 combined small deterministic prompt trims
prediction: H12 (-4.7% measured) + no_data domains digest to a one-line
marker instead of null-laden JSON + guidance lines skipped for domains whose
answer carried no data -> combined ~-8-12% vs H10; quality holds (nothing
informative removed; rule 3 already covers absent data).
experiment: keep H12 edits; _facet_digest emits "### <domain>\nno_data" when
the trimmed answer has no non-null values beyond markers; _guidance_block
skips hints for those domains.
result: median 1906 (-7.9% vs H10 2070) — exactly at the noise boundary
verdict: boundary — replicating as H14 before classifying
kept: pending H14

## H14 replication of H13 (no change — measure measurement noise)
prediction: if H13's reduction is real (deterministic prompt trims), the
replicate lands within ~3% of 1906; if it was completion noise, it regresses
toward 2070.
experiment: identical config, second bench run.
result: median 1928 (within 1.2% of H13's 1906; means 1854.6 vs 1853.8 —
virtually identical). Replication noise ~1%, NOT 8% — the pre-registered
noise rule was calibrated for reasoner completion variance that H4 removed.
verdict: H13 confirmed via replication (both runs far outside demonstrated
noise); H14 itself = measurement-noise characterization. Gates green, all
quality checks pass. Cumulative ~-57.5% vs E0 (median ~1917).
kept: H13 kept (commit see git log); noise floor for future verdicts: ~3%
(3x demonstrated replication spread) now that completions are light-tier.

## H15 guidance-ablation (NEGATIVE test): drop DOMAIN GUIDANCE entirely
prediction: removing all card hints saves ~120-160 prompt tokens (~-6-8%)
BUT quality checks fail (earnings-gate phrasing, thesis BROKEN/INTACT
framing, assumption citations degrade) -> expected DISPROVEN on quality;
establishes that the hints earn their tokens.
experiment: _guidance_block returns "" (one line).
result: median 1679 (-12.4% vs H13) BUT quality collapsed: no thesis
BROKEN/INTACT verdict, no assumption citations, no wash coverage, no
sentiment-estimated framing.
verdict: DISPROVEN on quality, as predicted — the card hints are load-bearing
(most valuable negative so far: guidance is function, not decoration).
kept: reverted

## H16 brevity rule under the light tier (~250 words)
prediction: H3 showed output caps can't touch reasoner reasoning; H4 removed
the reasoner, so visible output IS the completion now — a 250-word rule cuts
completion ~30-40% -> total ~-8-11% vs H13. Quality: current outputs are
230-400 words; a 250 cap trims moderately, checks must hold.
experiment: append "Keep the whole synthesis under 250 words." to rule 4.
result: median 1815 (-4.8% vs H13 1906; above the ~3% recalibrated noise
floor). Coverage 7/7 on ACN and O (one naming quirk on PLTR), words 153-179,
all quality checks pass. H3's inversion confirmed: brevity works once the
reasoner is gone.
verdict: confirmed
kept: yes (see git log H16). Cumulative -59.8% vs E0.

## H17 drop the levels payload from the technical digest
prediction: _decision_core already carries nearest_support/resistance; the
separate levels payload (bars metadata + level ladders) duplicates it under
the cap -> dropping it from the DIGEST frees cap space, tokens ~-3-5%
(borderline), quality unchanged (nearest levels still present).
experiment: _trim replaces out["levels"] with a marker when analysis
decisions are present (levels facet data redundant to decision core).
result: median 1865 (+2.8% vs H16 1815 — within the ~3% noise floor)
verdict: inconclusive — technical digests were already under cap; freeing
cap space saves nothing when nothing was truncated.
kept: reverted

## H18 combined uncapped-digest slimming (scenarios->0, thesis journal out, news items->3)
prediction: three under-cap digests carry optional weight: expectations
scenario endpoints (~60 tok), thesis journal entries (~40 tok), news items
beyond 3 (~50 tok). Combined ~-6-9% vs H16; quality holds (implied bar +
assumptions, plan, top headlines all retained).
experiment: _trim drops scenarios entirely, drops journal from thesis
digests, caps news items at 3 (title/published/publisher only).
result: median 1701 (-6.3% vs H16 1815; above ~3% floor). Quality 7/7 + all
checks; gates green (one transient test-run flake, clean on rerun).
verdict: confirmed
kept: yes (see git log H18). Cumulative -62.3% vs E0.

## H19 harder brevity: 150-word cap
prediction: current outputs ~150-180 words under the 250 cap; a 150 cap
trims the tail -> ~-3-5% vs H18 (borderline). Coverage risk: 7 domains in
150 words is tight — watch covers7 and the thesis/wash checks.
experiment: rule 4 word cap 250 -> 150.
result: median 1495 (-12.1%) BUT the thesis domain (incl. its "no plan on
file" statement) dropped out of the output on 4/4 checked symbols.
verdict: DISPROVEN on quality — 150 words can't honor 7-domain coverage;
250 is the coverage floor for this domain count.
kept: reverted

## H20 strip null-valued keys from digests
prediction: fundamentals/growth digests carry many nulls (forward_pe: null,
sbc: null on ETFs...); stripping null keys (rule 3 still reports no_data
domains) is deterministic -> ~-3-6% vs H18, borderline; quality unchanged.
experiment: _strip_envelope also drops keys whose value is None.
result: median 1651 (-2.9% vs H18 1701 — at the noise floor)
verdict: inconclusive alone; folded into H21 combined
kept: folded into H21

## H21 combined: null-strip + 200-word cap
prediction: H20's deterministic -3% + a 200-word cap (midpoint of kept-250 /
disproven-150) -> combined -6-10% vs H18 with coverage intact at 200 words
(the thesis drop appeared at 150).
experiment: keep H20 edit; word cap 250 -> 200.
result: median 1652 (-2.9% vs H18; the 200 cap added ~nothing over null-strip
alone) AND thesis coverage dropped on 2/3 no-plan symbols.
verdict: DISPROVEN — word caps below 250 squeeze out the "no thesis on file"
line; 250 is the coverage floor. Null-strip stays inconclusive (~-3%).
kept: reverted (H18 state stands)

## H22 validation: digest cap 450 -> 600 (reverse probe)
prediction: +cap space raises tokens ~+8-12% with NO quality gain (all
checks already pass at 450) -> disproven-for-cost, establishing 450 as an
efficient-frontier point rather than a starved compromise.
experiment: _MAX_FACET_JSON = 600.
result: median 1800 (+5.8% vs H18 1701), quality checks identical.
verdict: disproven-for-cost as predicted — 450 is an efficient-frontier
point (more context buys nothing measurable).
kept: reverted

## H23 replication of the final kept config (H2+H4+H7+H10+H13+H16+H18)
prediction: median within ~3% of 1701 (the demonstrated noise floor).
experiment: none — second measurement of the kept branch state.
result: median 1655 (within 2.7% of H18's 1701) — stable.
verdict: kept config replicates; final median estimate ~1678 (mean of the
two runs) = -62.8% vs E0 4514.
kept: n/a (measurement)

## H24 single-message prompt (system+user merged)
prediction: message framing overhead is a few tokens; merging changes
adherence more than cost -> expect inconclusive on tokens (~+-2%); cheap
probe that closes the prompt-shape question.
experiment: _invoke sends one user message containing system+user text.
result: median 1675 (within noise of 1655/1701); quality unchanged.
verdict: inconclusive as predicted — message structure is cost-neutral;
system/user split retained for adherence hygiene.
kept: reverted

## H25 closing validation: full-panel quality sweep on the kept config
prediction: all 5 panel symbols pass every quality check (coverage 7/7 or
naming-quirk 6/7, wash math, thesis verdict or no-plan statement,
assumptions cited) on the final kept configuration.
experiment: none — validation sweep.
result: FAILED — thesis domain absent from the synthesis on 4/5 no-plan
symbols (the H13 no_data one-liner + H16 word cap interact: the model treats
empty domains as skippable despite rule 3). Also identified: earlier "flaky"
test failures were gate runs contaminated by exported live env (clean-env
pytest: 5/5 green) — gates now run env-clean.
verdict: kept config NOT valid yet — coverage regression must be fixed
before the goal can close.
kept: n/a (validation)

## H26 rule-3 hardening: absent domains must be named
prediction: rewriting rule 3 to "name EVERY no-data domain with a one-line
statement — absence is information" restores no-plan thesis coverage on 5/5
symbols at ~+10-25 output tokens (~+1%); tokens stay far below target.
experiment: rule 3 rewrite (one sentence).
result: coverage restored 7/7 on ALL 5 panel symbols; tokens unchanged
(1704/1674 across two runs, within noise of H18's 1701). First version leaked
a concrete domain name ('thesis') into the generic contract — caught by
test_system_prompt_is_domain_generic (the genericity guard earning its keep);
neutralized to '<domain>: no data'. Clean gates: 852 tests + 74 evals.
verdict: confirmed
kept: yes (commit see git log H26)

---

# FINAL REPORT (goal: achieved)

baseline (E0):  median 4514 tokens/analyze
final (kept):   median ~1690 (1701/1655/1704/1674 across 4 runs)
reduction:      -62.6% (predicate: -30%) — target exceeded 2x
gates:          852 tests + 74 evals green on the kept config (clean env)
experiments:    26 hypotheses + E0 baseline (budget: >=25)
verdicts:       8 confirmed (H2 H4 H7 H10 H13 H16 H18 H26)
                6 disproven (H6 H11 H15 H19 H21 H22)
                9 inconclusive (H1 H3 H5 H8 H9 H12 H17 H20 H24)
                3 measurements (H14 H23 H25)
kept commits:   H2 7af9204, H4 7f06dff, H7 2a71045, H10 1bdccea,
                H13 54e83ae, H16 21fd995, H18 7932698, H26 (amended)
spend:          ~35 bench+check runs x ~2-4k tokens ~= well under the $5 cap

most valuable disproven: H15 (guidance ablation) — removing card hints saved
12% tokens but collapsed the earnings gate, thesis verdict, assumption
citations, and sentiment framing. The synthesis_hint mechanism is
load-bearing, not decoration.

key learnings:
1. The reasoner's hidden reasoning was the single biggest cost (H4: -19%
   in one constant); brevity rules only work AFTER it's gone (H3 vs H16).
2. Under a char cap, char-efficiency repacks rather than saves (H5); only
   cap cuts or uncapped-text trims move tokens.
3. Caps need STRUCTURE to be safe: naive 450 lost the wash math (H6);
   structure-to-fit at 450 kept it (H7). 450 is the frontier (H22 reverse
   probe); 350 is below the structural floor (H11).
4. 250 words is the coverage floor for 7 domains (H19/H21: thesis coverage
   dies below it); absent-domain naming must be an explicit rule (H26).
5. Measurement noise collapsed from ~8% (reasoner era) to ~1-3% (light era)
   — replication (H14) recalibrated the verdict threshold mid-goal.


---

# POST-GOAL APPENDIX — H27/H28 (conflict-triggered escalation, analyst-upgrade plan M4/M5)

## H27 blended cost with deterministic escalation
prediction (pre-registered in analyst-upgrade-plan.md): escalation fires on
~20-30% of held names; blended cost ~-50% vs E0; verdicts change on
conflicted cases.
experiment: detect_conflict (bearish-vs-intact-thesis, |loss|>=1k, weak rule)
routes conflicted cases to deep tier + pre-mortem; routine stays light.
result: escalation on 2/5 panel symbols (40% — above prediction; ACN's $1,125
loss trips the money-at-stake trigger). Routine names 1551-1852 tokens;
conflicted 4561-5021 (2 reasoner calls incl. pre-mortem). Blended:
median 1852 (-59.0% vs E0 4514), mean 2963 (-30.6% vs E0 mean 4270).
verdict: confirmed in shape (spend concentrates where money/conflict is);
escalation rate and mean-basis cost ran above prediction — tune
CONFLICT_LOSS_THRESHOLD if the book's typical loss size makes 40% the norm.
kept: yes (mira 64f53b9 + vantage 4493ad2/838ec5a)

## H28 deep tier catches what light misses (qualitative)
result: on the same PLTR case, light-tier synthesis misquoted the R:R as
0.42 (read upside_pct as the ratio); the escalated deep-tier run quoted
1.67 correctly and the pre-mortem constructed a genuine counter-case
("decline may be noise, not structural; booking a loss ignores strong
upside while the signal is unreliable"). The escalation earns its tokens on
exactly the cases it selects.
