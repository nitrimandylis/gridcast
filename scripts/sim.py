"""Monte Carlo race simulator (Phase 2).

One simulated race is: draw each driver's form for the day, pick a pit plan,
run the laps one at a time, throw in the random events, rank by total time.
Repeat a few thousand times and the histogram of finishing positions is the
prediction. Output shape matches the direct model exactly, so RPS compares
them directly (locked decision 1).

What is modelled
  - per-driver base pace, from that driver's earlier races only, with a
    per-race form draw whose spread is that driver's own race-to-race scatter
  - per-driver per-compound degradation and a compound speed prior
  - a minimum-race-time pit plan search, never a threshold rule (decision 5),
    with per-car jitter on the pit lap so the field does not pit in unison
  - safety cars and VSCs sampled per circuit; a stop is brought forward when
    a neutralisation makes it cheap (decision 6)
  - red flags at one pooled rate: free tyre change, gaps to zero, and the
    standing restart re-draws the first-lap incident (decision 6, revised)
  - retirements split by owner: first-lap incident (track), mid-race
    retirement (team) (decision 7)
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

import degradation
from degradation import DRY, slope_for
from hazards import fit_dnf, fit_events, sample_events

# ponytail: one pit loss for every circuit. Real values run 16s at Monza to
# 28s at Singapore, so this is the second thing to make per-circuit after the
# compound offsets. Both live here rather than in the loop so they are easy
# to find and tune.
GREEN_PIT_LOSS = 23.0
SC_PIT_LOSS = 12.0
SC_WINDOW = 10            # a stop planned within this many laps is taken under SC
PIT_JITTER = 2            # each car's pit lap moves by up to this many laps
SC_GAP = 1.0              # seconds between cars after a safety car bunches them
RED_GAP = 0.3             # seconds between cars at a standing restart
PIT_LAP_STEP = 3          # candidate pit laps, coarse so the search stays cheap
POOLED_FORM_SD = 0.48     # median race-to-race scatter of pace_delta in 2026
MIN_FORM_RACES = 3        # fewer races than this and a driver gets the pooled sd
# ponytail: grid persistence is a calibration term, not an overtaking model
# (decision 8). Starting one slot further back costs PASS_PACE seconds on
# every lap of the race, i.e. you need that much pace in hand per lap to make
# up one place over a race distance. Backtest RPS is flat from 0.6 s/lap up,
# and a rank blend or a small fixed start offset both scored worse. Its
# ceiling: it can say how often the grid order survives, never why. When a
# safety car bunches the field the penalty is re-issued by current order over
# the laps that remain, so a restart closes the gaps without handing out
# passes.
# Per-circuit values (Monaco high, Monza low) are the next step; a pairwise
# P(pass | pace delta, circuit, DRS) model replaces it in Phase 3.
PASS_PACE = 1.0           # seconds per lap per grid slot


# --- pit strategy ---------------------------------------------------------

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


# --- assembling one race --------------------------------------------------

def build_race(entry: pd.DataFrame, history: pd.DataFrame, deg: dict,
               hz: dict, dnf: dict, total_laps: int,
               observed: dict | None = None) -> dict:
    """Everything one race needs, as arrays indexed like `entry`.

    entry: one row per driver with driver, team, grid, and optionally grid_sd.
      grid_sd > 0 means the grid is a guess (the Thursday call): every run
      draws each driver's slot from N(grid, grid_sd) and ranks the draws, so
      the proxy grid carries its uncertainty instead of posing as known
      (the same rule as locked decision 12 for the direct model).
    history: driver_races rows from strictly earlier rounds (pace only).
    deg, hz, dnf: fitted by degradation.fit, hazards.fit_events, hazards.fit_dnf.
    observed: {driver: plan} to replay instead of optimising (backtest control).
    """
    drivers = list(entry["driver"])
    per_driver = history.groupby("driver")["pace_delta"].agg(["mean", "std", "count"])
    base, sd = [], []
    for d in drivers:
        if d in per_driver.index and per_driver.loc[d, "count"] >= 1:
            base.append(per_driver.loc[d, "mean"])
        else:
            base.append(0.0)  # no history: field average
        if d in per_driver.index and per_driver.loc[d, "count"] >= MIN_FORM_RACES:
            sd.append(per_driver.loc[d, "std"])
        else:
            sd.append(POOLED_FORM_SD)

    plans = candidate_plans(total_laps)
    chosen = []
    for d in drivers:
        plan = observed.get(d) if observed else None
        chosen.append(plan if plan else best_plan(d, deg, total_laps, plans))

    return {
        "drivers": drivers,
        "grid": entry["grid"].to_numpy(dtype=float),
        "grid_sd": (entry["grid_sd"].to_numpy(dtype=float)
                    if "grid_sd" in entry else np.zeros(len(entry))),
        "base": np.array(base, dtype=float),
        "sd": np.array(sd, dtype=float),
        "team_hazard": np.array([dnf["team_hazard"].get(t, dnf["pooled_hazard"])
                                 for t in entry["team"]]),
        "p_first_lap": dnf["p_first_lap"],
        "hz": hz,
        "offsets": np.array([deg["offsets"][c] for c in DRY]),
        "slopes": np.array([[slope_for(deg, d, c) for c in DRY] for d in drivers]),
        "progress": deg["progress"],
        "plans": chosen,
        "jitter": 0 if observed else PIT_JITTER,
        "total_laps": total_laps,
    }


def fit_race(tables: dict, before_round: int, circuit: str, entry: pd.DataFrame,
             total_laps: int, replay_round: int | None = None) -> dict:
    """Fit every input from the raw tables and assemble the race.

    tables: {"races", "laps", "events", "seen", "dnf_history"} DataFrames as
    written by the build scripts. Only 2026 rows from rounds strictly before
    `before_round` are used, so the result is walk-forward safe. Pre-2026
    rows are track history and are always used (data-validity rule 2).
    replay_round: read the observed strategies from that round's laps instead
    of optimising. Backtest control only: it looks at the race being scored.
    """
    races = tables["races"][tables["races"]["round"] < before_round]
    laps = tables["laps"][tables["laps"]["round"] < before_round]
    seen = tables["seen"]
    seen = seen[(seen["season"] < 2026) | (seen["round"] < before_round)]
    events = tables["events"].merge(seen[["season", "round"]], on=["season", "round"])

    deg = degradation.fit(laps)
    hz = fit_events(events, seen, circuit)
    dnf = fit_dnf(tables["dnf_history"], races, circuit)
    observed = None
    if replay_round is not None:
        observed = {d: observed_plan(tables["laps"], replay_round, d)
                    for d in entry["driver"]}
    return build_race(entry, races, deg, hz, dnf, total_laps, observed)


# --- running one race -----------------------------------------------------

def run_once(race: dict, rng: np.random.Generator) -> np.ndarray:
    """One simulated race. Returns each driver's finishing position, 1-based."""
    n = len(race["drivers"])
    total_laps = race["total_laps"]
    form = rng.normal(race["base"], race["sd"])

    # Pit plans as arrays, padded so every driver has the same width. One
    # spare column on the right keeps the index valid after the last stop.
    n_stops = np.array([len(laps_i) for laps_i, _ in race["plans"]])
    width = int(n_stops.max()) + 1
    pit_laps = np.full((n, width), total_laps + 99, dtype=int)
    compounds = np.zeros((n, width + 1), dtype=int)
    for i, (laps_i, comps_i) in enumerate(race["plans"]):
        shift = rng.integers(-race["jitter"], race["jitter"] + 1, size=len(laps_i))
        pit_laps[i, :len(laps_i)] = np.clip(np.array(laps_i) + shift, 1, total_laps - 1)
        compounds[i, :len(comps_i)] = [DRY.index(c) for c in comps_i]
    next_stop = np.zeros(n, dtype=int)          # index into pit_laps
    compound = compounds[:, 0].copy()
    age = np.zeros(n)
    grid = race["grid"]
    if race["grid_sd"].any():
        # Thursday: the grid is a guess, so draw one and rank it into slots.
        drawn = rng.normal(grid, race["grid_sd"])
        grid = np.empty(n)
        grid[np.argsort(drawn)] = np.arange(1, n + 1)
    time = PASS_PACE * total_laps * (grid - 1)   # track position, as time owed

    alive = rng.random(n) >= race["p_first_lap"]
    retired_on = np.where(alive, 0, 1)          # lap a car stopped, 0 = finished
    retire_at = rng.geometric(np.maximum(race["team_hazard"], 1e-9))  # p must be > 0

    # Expand the sampled events into a per-lap lookup.
    status = {}
    sc_ends = set()
    for kind, start, end in sample_events(race["hz"], total_laps, rng):
        for lap in range(start, end + 1):
            status[lap] = kind
        if kind == "SC":
            sc_ends.add(end)

    for lap in range(1, total_laps + 1):
        kind = status.get(lap)
        age[alive] += 1
        if kind is None:
            tyre = race["offsets"][compound] + race["slopes"][np.arange(n), compound] * age
            time[alive] += form[alive] + tyre[alive] + race["progress"] * lap
        # Neutralised laps: everyone circulates at the same speed, so the lap
        # adds nothing to the gaps and is left out of the clock entirely.

        # Pit stops. Under SC or VSC a stop planned soon is taken now because
        # it is cheap; that is the re-solve decision 5 asks for, in its
        # simplest form.
        due_lap = pit_laps[np.arange(n), next_stop]
        has_stop = next_stop < n_stops
        if kind in ("SC", "VSC"):
            pitting = alive & has_stop & (due_lap <= lap + SC_WINDOW)
            loss = SC_PIT_LOSS
        else:
            pitting = alive & has_stop & (due_lap == lap)
            loss = GREEN_PIT_LOSS
        if pitting.any():
            time[pitting] += loss
            next_stop[pitting] += 1
            compound[pitting] = compounds[pitting, next_stop[pitting]]
            age[pitting] = 0

        if kind == "RED":
            # Free tyre change: the next planned stop is taken for nothing.
            free = alive & (next_stop < n_stops)
            next_stop[free] += 1
            compound[free] = compounds[free, next_stop[free]]
            age[alive] = 0
            time = bunch(time, alive, RED_GAP, PASS_PACE * (total_laps - lap))
            # Standing restart: another lap-one incident draw.
            crash = alive & (rng.random(n) < race["p_first_lap"])
            alive[crash] = False
            retired_on[crash] = lap
        elif lap in sc_ends:
            time = bunch(time, alive, SC_GAP, PASS_PACE * (total_laps - lap))

        # Mid-race retirements, per-lap hazard by team.
        dying = alive & (retire_at == lap)
        alive[dying] = False
        retired_on[dying] = lap

    return finishing_positions(time, alive, retired_on)


def bunch(time: np.ndarray, alive: np.ndarray, gap: float, slot: float) -> np.ndarray:
    """Close the field up in its current order.

    Leader unchanged, each car `gap` seconds behind the one ahead, plus `slot`
    seconds per place: the track-position penalty for the laps still to run.
    """
    time = time.copy()
    order = np.argsort(np.where(alive, time, np.inf))
    leader = time[order[0]]
    for rank, i in enumerate(order):
        if alive[i]:
            time[i] = leader + rank * (gap + slot)
    return time


def finishing_positions(time: np.ndarray, alive: np.ndarray,
                        retired_on: np.ndarray) -> np.ndarray:
    """Classified cars by race time, retirements behind by laps completed."""
    n = len(time)
    running = np.where(alive)[0]
    classified = running[np.argsort(time[running])]

    stopped = np.where(~alive)[0]
    stopped = stopped[np.argsort(-retired_on[stopped], kind="stable")]

    positions = np.empty(n, dtype=int)
    positions[np.concatenate([classified, stopped])] = np.arange(1, n + 1)
    return positions


def simulate(race: dict, n_samples: int = 2000, seed: int = 0) -> np.ndarray:
    """P(driver, position) matrix, rows in `race['drivers']` order."""
    # ponytail: one Python loop per sample, numpy across drivers within it.
    # About 2 ms a race, so 2,000 samples is seconds. Vectorise across
    # samples only if the backtest becomes the slow step.
    rng = np.random.default_rng(seed)
    n = len(race["drivers"])
    counts = np.zeros((n, n))
    for _ in range(n_samples):
        positions = run_once(race, rng)
        counts[np.arange(n), positions - 1] += 1
    return counts / n_samples


# --- self-check -----------------------------------------------------------

def demo() -> None:
    """Self-check: the optimiser responds to degradation, the race responds to pace."""
    flat = {c: 0.0 for c in DRY}
    deg = {"offsets": flat,
           "slopes": {**{f"X/{c}": 0.15 for c in DRY},
                      **{f"Y/{c}": 0.01 for c in DRY}},
           "progress": -0.04}
    plans = candidate_plans(60)
    assert plans, "no candidate plans generated"
    assert all(len(set(c)) > 1 for _, c in plans), "two-compound rule broken"
    hard_on_tyres = best_plan("X", deg, 60, plans)
    kind_on_tyres = best_plan("Y", deg, 60, plans)
    assert len(hard_on_tyres[0]) > len(kind_on_tyres[0]), \
        f"steep degradation should stop more: {hard_on_tyres} vs {kind_on_tyres}"
    global GREEN_PIT_LOSS
    saved, GREEN_PIT_LOSS = GREEN_PIT_LOSS, 500.0
    try:
        assert len(best_plan("X", deg, 60, plans)[0]) == 1, \
            "a 500s stop must force a one-stopper"
    finally:
        GREEN_PIT_LOSS = saved

    # A three-car race. C is on pole and slowest. A starts P2 with 2 s/lap in
    # hand, enough to pass. B starts P3 with 0.5 s/lap over C, not enough.
    entry = pd.DataFrame({"driver": ["A", "B", "C"], "team": ["t", "t", "u"],
                          "grid": [2, 3, 1]})
    history = pd.DataFrame({"driver": ["A"] * 3 + ["B"] * 3 + ["C"] * 3,
                            "pace_delta": [-1.6, -1.5, -1.4, -0.1, 0, 0.1, 0.4, 0.5, 0.6]})
    deg3 = {"offsets": flat, "slopes": {f"{d}/{c}": 0.05 for d in "ABC" for c in DRY},
            "progress": -0.04}
    quiet = {"sc_rate": 0.0, "vsc_rate": 0.0, "red_rate": 0.0,
             "sc_laps": np.array([4.0]), "vsc_laps": np.array([2.0]),
             "start_fracs": np.array([0.5])}
    safe = {"p_first_lap": 0.0, "team_hazard": {"t": 0.0, "u": 0.0}, "pooled_hazard": 0.0}

    race = build_race(entry, history, deg3, quiet, safe, total_laps=40)
    matrix = simulate(race, n_samples=400)
    assert abs(matrix.sum() - 3) < 1e-9 and np.allclose(matrix.sum(axis=1), 1), "rows must sum to 1"
    assert matrix[0, 0] > 0.9, f"2 s/lap in hand from P2 must win: {matrix[:, 0]}"
    assert matrix[2, 1] > matrix[1, 1], \
        f"0.5 s/lap is not enough to pass from P3: P2 probs {matrix[:, 1]}"

    global PASS_PACE
    saved_w, PASS_PACE = PASS_PACE, 100.0
    try:
        locked = simulate(race, n_samples=100)
        assert locked[2, 0] == 1.0, "an unpassable grid slot must reproduce the grid"
    finally:
        PASS_PACE = saved_w

    # A guessed grid must not behave like a known one: with the grid drawn
    # from a wide scatter, the slowest car on "pole" no longer keeps P2.
    guessed = entry.assign(grid_sd=[3.0, 3.0, 3.0])
    race_guess = build_race(guessed, history, deg3, quiet, safe, total_laps=40)
    m = simulate(race_guess, n_samples=400)
    assert m[1, 1] > matrix[1, 1], "grid uncertainty must loosen the grid's grip"

    # A team that always breaks never scores.
    doomed = {**safe, "team_hazard": {"t": 0.0, "u": 0.5}}
    race_dnf = build_race(entry, history, deg3, quiet, doomed, total_laps=40)
    m = simulate(race_dnf, n_samples=200)
    assert m[2, 2] > 0.95, f"a car with a 50%/lap hazard must finish last: {m[2]}"

    # Red flags every race: the free stop must not crash the loop.
    chaos = {**quiet, "red_rate": 1.0, "sc_rate": 2.0}
    race_red = build_race(entry, history, deg3, chaos, safe, total_laps=40)
    m = simulate(race_red, n_samples=100)
    assert np.allclose(m.sum(axis=1), 1), "event handling broke the matrix"

    import time as clock
    start = clock.time()
    simulate(race, n_samples=200)
    per = (clock.time() - start) / 200
    print(f"self-check passed: {len(plans)} plans, steep-deg driver stops "
          f"{len(hard_on_tyres[0])}x, shallow {len(kind_on_tyres[0])}x, "
          f"P(A wins) {matrix[0, 0]:.2f}, {per * 1000:.1f} ms per simulated race")


if __name__ == "__main__":
    demo()
