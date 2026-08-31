# gridcast: project instructions

F1 race outcome prediction. Read PRODUCT.md for what it is. This file is the
set of decisions that are already made, and the traps that cost time to find.

## READ FIRST: unresolved decisions, grill Nick before building

Thirteen decisions are locked (below; 11-13 resolved the former Phase 1
blockers in the 2026-08-31 grill). The rest are NOT, and they were
deliberately left open rather than forgotten.

Run each as a grill, one question at a time, in the format he expects: the
full written case first, then options, then your recommendation. Options
without the case get rejected. Do not ask them all at once, and do not answer
them yourself and proceed.

### Resolve before Phase 2 (October)

4. **Fork TUMFTM/race-simulation, or reimplement?** See the prior-art section.
   Forking imports a validated engine and imposes LGPL on gridcast. That
   collides with his default of MIT for public repos, and the licence has to
   be chosen before the repo is published, not after.
5. **Build the "real strategy replay" backtest control?** Replaying the
   strategy teams actually used isolates strategy error from pace error. It is
   the single most useful validation tool we do not have, and it is not free.
6. **Do red flags go into the model?** v1 omits them, but the gate scan found
   two in four sampled 2026 races. That is far commoner than the omission
   assumed. See gate results below.
7. **What is the real qualifying model?** October scope, entirely unspecified.
   One-lap pace is not race pace and track evolution matters.

### Housekeeping, but blocking publication

8. **Licence.** Not chosen, and gated by question 4.
9. **Publishing.** Repo is local only. `publish-repo` requires a README and a
   LICENSE first, and neither exists. The scorecard depends on the repo being
   public, so this cannot slip past the first live prediction.
10. **A third baseline from bookmaker implied probabilities?** Proposed, never
    decided. Betting markets are the honest hard benchmark since no public F1
    forecast carries a track record. Needs an odds source that can be
    collected before each race, and if that is not practical the idea dies.

### Scorecard, low urgency

11. **What the results page actually shows.** Undesigned. It only matters once
    there are two or three predictions to display.

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
   Model VSC separately from full SC. Red flags omitted from v1, but see
   the gate results below: they are commoner in 2026 than assumed, so revisit
   before Phase 2 ships.
7. **DNFs split by cause**, because the causes have different owners:
   mechanical (team; weak 2025 operational-quality prior, updated by 2026),
   first-lap incident (grid position and circuit, from long history, pools
   across teams), mid-race collision (pooled across drivers).
8. **Track position: one per-circuit grid-persistence parameter** blending
   pace-derived order toward grid order. This is a calibration term, not an
   overtaking model. Its job is to cancel the strategy optimiser's undercut
   optimism. Mark it in code with its ceiling.
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
    Upgrades in October when the real qualifying model replaces the proxy.
13. **The prediction JSON stores the full P(driver, position) matrix, the
    derived P(win)/P(podium)/P(points), and run metadata** (event, call type,
    model version, races trained on, timestamp) (grilled 2026-08-31).
    Headlines-only was rejected: RPS can never be computed from data that was
    never written, and git history means no regeneration after the race.

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

Note if forking is ever considered: LGPL is copyleft, so gridcast would have
to be LGPL rather than MIT.

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
