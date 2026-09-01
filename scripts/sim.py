"""Monte Carlo race simulator (Phase 2, thin end-to-end).

One simulated race is: decide each driver's pit plan, run the laps, add the
random events, rank by total time. Repeat a few thousand times and the
histogram of finishing positions is the prediction. Output shape matches the
direct model exactly, so RPS compares them directly (locked decision 1).

What is modelled
  - per-driver base pace, from that driver's earlier races only
  - per-driver per-compound degradation and a compound speed prior
  - a minimum-race-time pit plan search, never a threshold rule (decision 5)
  - safety cars, VSC and red flags sampled per circuit (decision 6)
  - retirements split by cause (decision 7)
  - one grid-persistence parameter standing in for overtaking (decision 8)

What is NOT modelled, deliberately
  Cars do not interact. There is no dirty air, no DRS, no blocking, no
  position-dependent lap time. The grid-persistence blend is a calibration
  term that stands in for all of it, and its ceiling is that the simulator
  cannot ever explain WHY a driver failed to pass, only how often.

    conda run -n gridcast python scripts/sim.py
"""

import numpy as np
import pandas as pd

from degradation import DRY, lap_pace, slope_for

# ponytail: one pit loss for every circuit. Real values run 16s at Monza to
# 28s at Singapore, so this is the second thing to make per-circuit after the
# compound offsets. Both live here rather than in the loop so they are easy
# to find and tune.
GREEN_PIT_LOSS = 23.0
SC_PIT_LOSS = 12.0
PIT_LAP_STEP = 3          # candidate pit laps, coarse so the search stays cheap
GRID_PERSISTENCE = 0.35   # weight on grid order when blending with pace order


def stints_for(plan: tuple, total_laps: int) -> list[tuple]:
    """Turn (pit_laps, compounds) into [(start_lap, end_lap, compound)]."""
    pit_laps, compounds = plan
    edges = [0, *pit_laps, total_laps]
    return [(edges[i] + 1, edges[i + 1], compounds[i])
            for i in range(len(compounds))]


def plan_time(plan: tuple, driver: str, deg: dict, total_laps: int,
              pit_loss: float) -> float:
    """Total race time for one plan, in seconds above the driver's base pace.

    Only the parts that depend on the plan are counted: tyre offset, tyre age
    and the stops. Base pace and the race-progress term are identical across
    plans for a given driver, so they cannot change which plan wins.
    """
    total = len(plan[0]) * pit_loss
    for start, end, compound in stints_for(plan, total_laps):
        n = end - start + 1
        if n <= 0:
            return float("inf")  # a plan that pits on a lap it already used
        total += (deg["offsets"][compound] * n
                  + slope_for(deg, driver, compound) * n * (n + 1) / 2)
    return float(total)


def candidate_plans(total_laps: int, max_stops: int = 3) -> list[tuple]:
    """Every 1, 2 and 3 stop plan on a coarse pit-lap grid.

    F1 requires at least two different dry compounds in a dry race, so plans
    on a single compound are dropped.
    """
    laps = list(range(PIT_LAP_STEP, total_laps, PIT_LAP_STEP))
    plans = []
    for stops in range(1, max_stops + 1):
        for pit_laps in _combinations(laps, stops):
            for compounds in _products(DRY, stops + 1):
                if len(set(compounds)) > 1:
                    plans.append((pit_laps, compounds))
    return plans


def _combinations(items: list, k: int) -> list[tuple]:
    if k == 0:
        return [()]
    out = []
    for i, item in enumerate(items):
        for rest in _combinations(items[i + 1:], k - 1):
            out.append((item, *rest))
    return out


def _products(items, k: int) -> list[tuple]:
    out = [()]
    for _ in range(k):
        out = [(*prefix, item) for prefix in out for item in items]
    return out


def best_plan(driver: str, deg: dict, total_laps: int,
              plans: list[tuple]) -> tuple:
    """The minimum-race-time plan. This is decision 5: a search, not a rule."""
    return min(plans, key=lambda p: plan_time(p, driver, deg, total_laps,
                                              GREEN_PIT_LOSS))


def observed_plan(laps: pd.DataFrame, rnd: int, driver: str) -> tuple | None:
    """The strategy this driver actually ran, for replay mode.

    A pit stop is a stint boundary, so the pit laps are the last lap of every
    stint except the final one.
    """
    rows = laps[(laps["round"] == rnd) & (laps["driver"] == driver)]
    rows = rows.dropna(subset=["stint", "compound"]).sort_values("lap_number")
    if rows.empty:
        return None
    stints = rows.groupby("stint").agg(last=("lap_number", "max"),
                                       compound=("compound", "first"))
    stints = stints.sort_index()
    compounds = [c if c in DRY else "MEDIUM" for c in stints["compound"]]
    # .iloc, not [:-1]: the stint index is float dtype, so plain slicing is
    # label-based and silently returns nothing, reading every race as no stops.
    pit_laps = tuple(int(x) for x in stints["last"].iloc[:-1])
    return (pit_laps, tuple(compounds))


def demo() -> None:
    """Self-check: the optimiser must respond to degradation, not ignore it."""
    # Offsets are held equal so the test isolates one thing: whether stint
    # length responds to degradation. With unequal offsets the optimiser can
    # satisfy the two-compound rule by picking a fast tyre instead of stopping,
    # and the test passes without proving anything.
    flat = {c: 0.0 for c in DRY}
    deg = {"offsets": flat,
           "slopes": {**{f"X/{c}": 0.15 for c in DRY},
                      **{f"Y/{c}": 0.01 for c in DRY}},
           "progress": -0.04}
    plans = candidate_plans(60)
    assert plans, "no candidate plans generated"
    assert all(len(set(c)) > 1 for _, c in plans), "two-compound rule broken"

    # A driver who chews tyres must stop STRICTLY more than one who does not.
    hard_on_tyres = best_plan("X", deg, 60, plans)
    kind_on_tyres = best_plan("Y", deg, 60, plans)
    assert len(hard_on_tyres[0]) > len(kind_on_tyres[0]), \
        f"steep degradation should stop more: {hard_on_tyres} vs {kind_on_tyres}"

    # A stop has to pay for itself: make stops absurdly expensive and the
    # optimiser must fall back to the fewest legal stops.
    global GREEN_PIT_LOSS
    saved, GREEN_PIT_LOSS = GREEN_PIT_LOSS, 500.0
    try:
        assert len(best_plan("X", deg, 60, plans)[0]) == 1, \
            "a 500s stop must force a one-stopper"
    finally:
        GREEN_PIT_LOSS = saved

    import time
    start = time.time()
    best_plan("X", deg, 60, plans)
    print(f"self-check passed: {len(plans)} candidate plans, "
          f"steep-deg driver stops {len(hard_on_tyres[0])}x, "
          f"shallow-deg driver stops {len(kind_on_tyres[0])}x, "
          f"{time.time() - start:.2f}s per driver solve")


if __name__ == "__main__":
    demo()
