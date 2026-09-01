# gridcast: project instructions

F1 race outcome prediction. Read PRODUCT.md for what it is. This file is the
set of decisions that are already made, and the traps that cost time to find.

## READ FIRST: what is open, what is closed

Eighteen decisions are locked (below). The 2026-09-01 grill closed the Phase 2
blockers (4, 5, 6, 8, 11) and set the MVP bar: the simulator works end to end,
every weekend publishes BOTH models, the repo is public with a GitHub Pages
scorecard. Refinement of both models is a separate project after that.

Two decisions stay open on purpose. Run each as a grill, one question at a
time, in the format he expects: the full written case first, then options,
then your recommendation. Options without the case get rejected.

7. **What is the real qualifying model?** Refinement scope, unspecified.
   One-lap pace is not race pace and track evolution matters. Until it
   exists the Thursday grid is the season-average proxy (decision 12) and the
   simulator draws the grid from each driver's scatter (decision 16).
10. **A third baseline from bookmaker implied probabilities?** Proposed, never
    decided. Betting markets are the honest hard benchmark since no public F1
    forecast carries a track record. Needs an odds source that can be
    collected before each race, and if that is not practical the idea dies.

The race-weekend ritual (Thursday call, Saturday call, score after the race)
is deliberately NOT tracked in Things. Only build work goes there.

## Environment

- conda env `gridcast`, Python 3.12. Install into it, never into base.
- `fastf1` is the data layer. Cache to `cache/` (gitignored).
- Ask before adding any dependency beyond what fastf1 pulls in.

## The two data-validity rules

These are the most important rules in the project. Almost every modelling
decision follows from them.

1. **Car properties do NOT transfer across the 2026 regulation change.**
   Pace, degradation and power-unit reliability must be fit on 2026 data only.
   2025 car data is worthless for these.

2. **Track properties DO transfer.** Safety car rates, first-lap incident
   rates and how much grid position persists are functions of barriers,
   run-off and layout. Use 2018-2026 history for these. This is what rescues
   them from the one-observation-per-circuit problem.

Before using any historical data, decide which of the two it is.

## Locked decisions

1. **Direct statistical model first, simulator second.** The sim must beat the
   direct model on RPS or it is decoration. Both emit the same output shape.
2. **Two calls per weekend.** Thursday on predicted grid, Saturday on actual.
   The race model takes grid as an INPUT and never assumes it.
3. **Walk-forward validation, ranked probability score.** Not Brier: finish
   position is ordered, and RPS correctly punishes predicting P4 when the
   answer was P12 harder than P4 when the answer was P5. Score on driver-race
   rows (~240), not on races (~12).
4. **Per-driver pace terms, no team term.** Plus per-driver per-compound
   degradation SLOPES for dry compounds; pool intermediates and wets.
   Once every driver has a parameter, a team term is collinear and buys
   nothing.
5. **Pit strategy is a minimum-race-time search**, never a threshold rule.
   Enumerate 1/2/3-stop plans over candidate pit laps, pick min total time.
   Re-solve when race control changes: SC pit loss is ~12s against ~23s green,
   and that flips the answer. Inject noise per car or all 20 pit on the same
   lap and the Monte Carlo loses its variance.
6. **Safety car: per-circuit rate from 2018-2026**, shrunk toward a
   street/permanent base rate. Sample occurrence, lap timing AND duration.
   Model VSC separately from full SC. **Red flags are in** (grilled
   2026-09-01): ONE pooled rate, never per circuit (16 in 98 races is noise
   per circuit), a free tyre change, gaps to zero, and the standing restart
   re-draws the first-lap incident. `scripts/hazards.py`.
7. **DNFs split by cause**, because the causes have different owners:
   mechanical (team; weak 2025 operational-quality prior, updated by 2026),
   first-lap incident (grid position and circuit, from long history, pools
   across teams), mid-race collision (pooled across drivers). As built: 2026
   status strings say only "Retired", so mechanical and collision are one
   per-team per-lap hazard; first-lap rate was flat across grid quartiles
   (2.4-3.0%) so it is pooled by circuit only. `scripts/hazards.py`.
8. **Track position: one grid-persistence parameter.** This is a calibration
   term, not an overtaking model. Its job is to cancel the strategy
   optimiser's undercut optimism. Mark it in code with its ceiling. As built
   (2026-09-01) it is `PASS_PACE` in `sim.py`: each grid slot costs 1.0 s per
   lap of race distance, re-issued by current order whenever a safety car
   bunches the field. A rank blend was tried first and rejected: it hard-caps
   a fast car's ceiling at its grid rank and zeroes probabilities. Backtest
   RPS is flat from 0.6 s/lap up. Per-circuit values are the next step.
9. **Predictions are committed as JSON before lights out.** Git history is the
   timestamp proof. No database, no timestamping service.
10. **Not a CLI.** Personal pipeline. Do not package it.
11. **The direct model is Plackett-Luce** (grilled 2026-08-31). Each driver
    gets a strength, a linear function of the features; P(win) is softmax over
    strengths, remove the winner and repeat. A race is a ranking, so the
    probabilities are coherent by construction: win probs sum to 1, one driver
    per position. Fit by maximum likelihood on observed finishing orders,
    plain numpy/scipy, no modelling library. Ordinal regression was the
    fallback, boosted tree rejected (uninterpretable, overfits 240 rows).
12. **The Thursday grid column is each driver's season-average grid position**,
    and the Thursday model is trained as its own fit with that feature
    (grilled 2026-08-31). Never feed a guessed grid into the Saturday-trained
    model: it learned the weight of a KNOWN grid and would be overconfident.
    Upgrades when the real qualifying model replaces the proxy (decision 7).
13. **The prediction JSON stores the full P(driver, position) matrix, the
    derived P(win)/P(podium)/P(points), and run metadata** (event, call type,
    model version, races trained on, timestamp) (grilled 2026-08-31).
    Headlines-only was rejected: RPS can never be computed from data that was
    never written, and git history means no regeneration after the race.
14. **Reimplement, do not fork TUMFTM** (closed 2026-09-01). The simulator is
    our own code, nothing LGPL is in the tree, so the licence is MIT per
    Nick's default.
15. **The real-strategy replay control exists** (`observed_plan` in `sim.py`,
    the `replay` column in the backtest). Sim minus replay is strategy error;
    replay minus truth is pace and event error. Replay reads the race being
    scored, so it is a control, never a predictor.
16. **Both models publish every weekend** (grilled 2026-09-01). `predict.py`
    writes `-direct.json` and `-sim.json` per call, same schema, `model`
    field says which. The live season is the out-of-sample head-to-head. The
    Thursday sim draws each driver's grid from their own season scatter, the
    simulator's version of decision 12.
17. **The scorecard is a static page in `docs/` on GitHub Pages.** JS fetches
    `docs/manifest.json`, `docs/results.json` and `predictions/*.json` and
    only renders. RPS is computed in Python by `score.py`, never in JS. No
    framework, no build.
18. **MVP means it works and publishes.** The sim is not gated on beating the
    direct model; the number is published either way (it did beat it: see
    PRODUCT.md). Refinement of both models is the next project.

## Gate results, verified 2026-08-31

All three gates PASS. `scripts/gates.py` reruns them.

- **2026 sessions**: 23 events in schedule. Dutch GP race loads 1368 lap rows
  across 22 drivers.
- **Track status back to 2018**: yes. 2018 British GP returns 22 status-change
  rows. It is a change log, not per-lap, so expand it against lap timestamps.
- **2026 per-lap compound and tyre age**: yes. Compound, TyreLife, Stint,
  TrackStatus and LapTime all present, 1368/1368 laps carry a compound.

Status codes are `1` AllClear, `2` Yellow, `4` SafetyCar, `5` Red, `6` VSC,
`7` VSCEnding. SC and VSC are cleanly distinguishable, so decision 6 holds.

**Red flags are not rare.** Sampling four 2026 races: Australia had VSC only,
Monaco had SC and a red flag, Britain had both SC and VSC, Zandvoort had VSC
and a red flag. Two red flags in four races is far more than v1 assumed.

FastF1 emits timing integrity warnings on real sessions (misaligned laps,
drivers finishing before session end). Expect them and handle them in
cleaning rather than treating them as failures.

## Prior art, surveyed 2026-08-31

**Nothing exists to fork for prediction.** The GitHub landscape tops out at 11
stars: one-off unlicensed scripts predicting a single 2025 race. The bar is
very low.

**TUMFTM/race-simulation** (115 stars, LGPL, Python 3.8, last pushed
2023-03-25) is the one serious open artifact. Lap-wise discretisation, tyre
degradation, fuel mass, inter-car interaction, Monte Carlo, and a "Virtual
Strategy Engineer" with four pit-decision variants. But it is a STRATEGY
OPTIMISER, not a predictor: it answers "what is the optimal pit strategy given
these parameters", not "who wins Sunday". Its parameter files cover 2014-2019
and were generated from a private timing database we do not have. It claims no
quantitative accuracy.

Do not fork it for Phase 1. Read it before Phase 2 and steal two things:
- **Lap-wise discretisation** instead of a fixed time tick. Pitwall's 10Hz tick
  quantised every lap time to a multiple of 0.1s.
- **Its "real strategy" VSE variant**: replay the strategy teams actually used
  as a backtest control. That isolates strategy error from pace error, and we
  do not currently have that.

Forking was ruled out on 2026-09-01 (decision 14); this section stays as the
record of why.

**Published accuracy numbers in this space are mostly not real.** Two patterns
to never reproduce:
- Claims like "R2 = 0.993 predicting finishing position" almost certainly leak
  post-race features (points, laps completed, status, race time) into the
  inputs. Finishing position is not that predictable.
- "78% accuracy predicting podiums" is worse than the trivial baseline: with 3
  podium slots in 20 drivers, predicting "no podium" for everyone scores 85%.

This is exactly why the harness uses RPS against explicit baselines.

**Academic frontier is strategy control, not outcome prediction.** RSRL
(arXiv 2501.04068) reached P5.33 against a P5.63 baseline in a car with P5.5
expected pace, inside a simulator. arXiv 2512.21570 pairs a MINLP with RL for
~5s suboptimality over a 1.5h race, no public code. Nobody is publishing
calibrated pre-race outcome probabilities with a live scorecard.

**Add a third baseline if odds are easy to obtain**: bookmaker implied
probabilities are the honest hard benchmark. Beating them is not the goal;
comparing calibration against them is a strong line in the writeup.

## Traps

- **Strategy is an OUTPUT of the simulator, never an input to the pace model.**
  Folding observed strategy into a pace estimate bakes a past decision into a
  future prediction. "Hamilton pits late" was a safety car in Barcelona, not a
  trait.
- **Do not let outcome-row anxiety constrain the pace model.** Race outcomes
  are ~240 rows. Pace and degradation fit on LAP rows, ~12,000 of them.
  Per-driver parameters are cheap at that scale.
- **Teammates do not share a car.** Setup, driving style and mechanical
  adjustments diverge, and the effect is largest in the degradation slope,
  which is exactly what the strategy model consumes. A shared team term
  erases it.
- **Setup divergence is unobservable.** No wing, differential, brake bias or
  ride height data exists. It is irreducible noise: widen the intervals, do
  not add parameters that will fit it spuriously.
- **Raw lap times are contaminated.** Drop in-laps, out-laps, the first two
  racing laps and anything under non-green track status. Correct for fuel
  load, compound and tyre age. Clean data matters more than the model on top.
- **Reference: `Daniel200308/f1-simulator`** is the cautionary example. Its
  threshold-based pit rule produced 103 stops across 22 cars, mean stint 7.7
  laps, because it never compared the ~23s cost of a stop against the gain.
  Its cars also never interacted: minimum spacing 0.00m across a full race.

## Style

- Write at Nick's level: plain, explicit, defensible line by line. No clever
  one-liners, no dense generics. He must be able to explain every term.
- Non-trivial logic leaves one runnable check behind. No test suites unless
  asked.
- No em dashes in any prose.
