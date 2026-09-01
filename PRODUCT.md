# gridcast

F1 race outcome prediction. Publishes a probability distribution over finishing
positions for every driver, before the race, with a public scorecard.

## What it is

Two calls per race weekend:

- **Thursday**, from each driver's season-average grid position, standing in
  for a predicted grid until the real qualifying model exists.
- **Saturday**, from the actual grid after qualifying.

Each call is committed to this repo as JSON before the race starts: the full
P(driver, position) matrix, the derived P(win), P(podium), P(points) per
driver, and run metadata. The commit history is the timestamp proof: every
prediction demonstrably existed before the result.

The scorecard page is generated from the accumulated JSON and gets more
convincing every fortnight without further work.

## Why it exists

Two reasons, both real:

1. A portfolio piece with a falsifiable accuracy number rather than a screenshot.
2. A tool to show friends before a GP, and argue about afterwards.

## Where it is headed

**Phase 1, built. First public target 26 September 2026 (Azerbaijan GP).**
A direct statistical model: Plackett-Luce, each driver's strength a linear
function of grid position and season pace history. No simulation. Walk-forward
backtest over rounds 4-12 scores 0.1340 mean RPS (Saturday call) against
0.1655 for the grid-order baseline. First live call made for Monza, round 13.
This is the benchmark everything later has to beat.

**Phase 2, October 2026.**
A Monte Carlo race simulator: per-driver pace and tyre degradation, a
cost-based pit strategy optimiser, safety cars, retirements. It ships only if
it beats Phase 1 on ranked probability score. If it does not, that is a real
result and worth knowing.

**Phase 3, if the residuals ask for it.**
A pairwise overtaking model, P(pass | pace delta, circuit, DRS). Until then a
single per-circuit grid-persistence parameter stands in.

## How it is judged

Walk-forward validation: fit on races 1..k, predict race k+1. Scored with
ranked probability score on driver-race rows, against two baselines:

- finish order equals grid order
- the Phase 1 direct model

The backtest is a smoke test. The real evidence is the live season: every race
from Azerbaijan to Abu Dhabi is a genuine out-of-sample prediction, published
before the event.

## Not doing

- A race game or a live timing viewer.
- Red flag modelling in v1.
- Packaging as an installable CLI. This is a personal pipeline.
- Any claim of accuracy that a backtest alone supports.

## Origin

Scoped 29-31 August 2026 after reading `Daniel200308/f1-simulator`, a race sim
whose inputs were real but whose cars never interacted. The lesson taken from
it: plausible-looking output is not evidence, so validation comes before
features here.
