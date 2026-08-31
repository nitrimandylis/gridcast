# gridcast: project instructions

F1 race outcome prediction. Read PRODUCT.md for what it is. This file is the
set of decisions that are already made, and the traps that cost time to find.

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
   Model VSC separately from full SC. Red flags omitted from v1.
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
