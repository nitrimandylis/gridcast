# gridcast

F1 race outcome prediction. Publishes a probability distribution over finishing
positions for every driver, before the race, with a public scorecard.

## What it is

Two calls per race weekend:

- **Thursday**, from each driver's season-average grid position, standing in
  for a predicted grid until the real qualifying model exists.
- **Saturday**, from the actual grid after qualifying.

Each call is committed to this repo as JSON before the race starts, once per
model: the full P(driver, position) matrix, the derived P(win), P(podium),
P(points) per driver, and run metadata. The commit history is the timestamp
proof: every prediction demonstrably existed before the result.

Two models run side by side and both publish every weekend: the direct
Plackett-Luce model and the Monte Carlo race simulator. The live season is
their out-of-sample head-to-head.

The scorecard is a static page in `site/`, served by GitHub Pages. `score.py`
computes RPS for every prediction with a result and writes JSON; the page only
renders it, and gets more convincing every fortnight without further work.

## Why it exists

Two reasons, both real:

1. A portfolio piece with a falsifiable accuracy number rather than a screenshot.
2. A tool to show friends before a GP, and argue about afterwards.

## Where it is headed

**Phase 1, built.** A direct statistical model: Plackett-Luce, each driver's
strength a linear function of grid position and season pace history. No
simulation. Walk-forward backtest over rounds 4-12 scores 0.1340 mean RPS
(Saturday call) and 0.1390 (Thursday call) against 0.1655 for the grid-order
baseline. First live call made for Monza, round 13.

**Phase 2, built 1 September 2026.** A Monte Carlo race simulator: per-driver
pace with a per-race form draw, per-driver per-compound tyre degradation, a
minimum-race-time pit strategy search, safety cars, VSCs and red flags sampled
per circuit, retirements split by owner, and one track-position parameter
standing in for overtaking. Same walk-forward backtest: **0.1220** (Saturday)
and **0.1271** (Thursday), so it beats the direct model on both calls. The
real-strategy replay control scores 0.1211, which says strategy error is
small and the remaining gap is pace and event error. Monaco is the one race
the sim loses, as expected with no overtaking model. Two caveats on the
number: the backtest is nine races, and two constants (pass pace, pooled form
scatter) were tuned on those same races.

**MVP publication, target 5 September 2026 (Monza qualifying).** Repo public
under MIT, both models' JSON per call, GitHub Pages scorecard. The Monza
Saturday call is the acceptance test.

**Refinement, after publication.** Both models, judged on the live scorecard:
per-circuit pass pace and pit loss, compound offsets from practice long runs,
a real qualifying model for the Thursday call, a bookmaker baseline if odds
can be collected.

**Phase 3, if the residuals ask for it.**
A pairwise overtaking model, P(pass | pace delta, circuit, DRS). Until then
the single track-position parameter stands in.

## How it is judged

Walk-forward validation: fit on races 1..k, predict race k+1. Scored with
ranked probability score on driver-race rows, against two baselines:

- finish order equals grid order
- the Phase 1 direct model

The backtest is a smoke test. The real evidence is the live season: every race
from Monza to Abu Dhabi is a genuine out-of-sample prediction, published
before the event, from both models.

## Not doing

- A race game or a live timing viewer.
- Car interaction: no dirty air, DRS or blocking. One calibration term stands in.
- Packaging as an installable CLI. This is a personal pipeline.
- Any claim of accuracy that a backtest alone supports.

## Origin

Scoped 29-31 August 2026 after reading `Daniel200308/f1-simulator`, a race sim
whose inputs were real but whose cars never interacted. The lesson taken from
it: plausible-looking output is not evidence, so validation comes before
features here.
