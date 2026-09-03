"""Make a live prediction and write the JSON (locked decisions 9 and 13).

Trains BOTH models fresh on every completed 2026 race, predicts the named
event, and writes two files:

    predictions/<season>-r<round>-<call>-direct.json   Plackett-Luce
    predictions/<season>-r<round>-<call>-sim.json      Monte Carlo simulator

Same schema in each: the full P(driver, position) matrix, the derived
headlines and run metadata, with the `model` field saying which is which.
Both are committed before lights out, so the live season is an out-of-sample
head-to-head between them. Git history is the timestamp.

    conda run -n gridcast python scripts/predict.py "Italian Grand Prix" thursday
    conda run -n gridcast python scripts/predict.py "Italian Grand Prix" saturday
    conda run -n gridcast python scripts/predict.py "Italian Grand Prix" thursday ANT=22

thursday uses each driver's season-average grid (locked decision 12).
saturday uses the qualifying classification, so it only works after quali.
The entry list is the set of drivers from the latest completed race.

Trailing DRIVER=POSITION arguments override the grid feature. Grid penalties
are the case that needs them: build_data.py trains on the real post-penalty
starting grid, but neither call can see a penalty. The season average cannot,
and qualifying classification cannot either, because penalties are applied
after the session. Without the override the model is fed a front-row start
for a driver who is starting last.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import fastf1
import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

from backtest import add_history_features, grid_scatter, load_tables, races_as_arrays
from hazards import canonical
from model import fit, sample_position_matrix, strengths
from sim import fit_race, simulate

ROOT = Path(__file__).resolve().parent.parent
SEASON = 2026
N_SAMPLES = 20000
SIM_SAMPLES = 10000
DEFAULT_LAPS = 60
MODELS = {"direct": "direct-v1-plackett-luce", "sim": "sim-v1-monte-carlo"}


def qualifying_grid(round_number: int, drivers: list[str]) -> dict[str, float]:
    """Qualifying classification. NOT the starting grid: penalties come after,
    so anything already known has to be passed in as a DRIVER=POSITION override."""
    session = fastf1.get_session(SEASON, round_number, "Q")
    session.load(telemetry=False, weather=False, messages=False)
    positions = dict(zip(session.results["Abbreviation"], session.results["Position"]))
    missing = [d for d in drivers if d not in positions]
    if missing:
        raise SystemExit(f"no qualifying position for {missing}")
    return positions


def parse_grid_overrides(args: list[str], drivers: list[str]) -> dict[str, float]:
    """Turn ['ANT=22'] into {'ANT': 22.0}, refusing anything unrecognised."""
    overrides = {}
    for arg in args:
        if "=" not in arg:
            raise SystemExit(f"expected DRIVER=POSITION, got {arg!r}")
        driver, position = arg.split("=", 1)
        if driver not in drivers:
            raise SystemExit(f"{driver} is not in the entry list: {' '.join(drivers)}")
        overrides[driver] = float(position)
    return overrides


def expected_laps(tables: dict, circuit: str) -> int:
    """Race distance from this circuit's history, since the event has not run."""
    seen = tables["seen"]
    here = seen[seen["circuit"].map(canonical) == canonical(circuit)]
    return int(here["total_laps"].median()) if len(here) else DEFAULT_LAPS


def predicted_order(matrix: np.ndarray, drivers: list[str]) -> list[str]:
    """Most probable finishing order via the Hungarian algorithm.

    Finds the single permutation of drivers to positions that maximises the
    joint probability, with each driver assigned exactly one position."""
    row_idx, col_idx = linear_sum_assignment(-matrix)
    order = [""] * len(drivers)
    for r, c in zip(row_idx, col_idx):
        order[c] = drivers[r]
    return order


def headline_rows(matrix: np.ndarray, drivers: list[str], teams: list[str]) -> list[dict]:
    rows = []
    for i, driver in enumerate(drivers):
        rows.append({
            "driver": driver,
            "team": teams[i],
            "p_win": round(float(matrix[i, 0]), 4),
            "p_podium": round(float(matrix[i, :3].sum()), 4),
            "p_points": round(float(matrix[i, :10].sum()), 4),
            "p_position": [round(float(p), 4) for p in matrix[i]],
        })
    rows.sort(key=lambda r: -r["p_win"])
    return rows


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[2] not in ("thursday", "saturday"):
        raise SystemExit(__doc__)
    event_name, call = sys.argv[1], sys.argv[2]

    fastf1.Cache.enable_cache(str(ROOT / "cache"))
    event = fastf1.get_event(SEASON, event_name)
    round_number = int(event["RoundNumber"])

    tables = load_tables()
    table = tables["races"]
    trained_rounds = sorted(int(r) for r in table["round"].unique())
    if round_number <= max(trained_rounds):
        raise SystemExit(f"round {round_number} is already in the training data")

    # Entry list and season-to-date features, from all completed races.
    latest = table[table["round"] == max(trained_rounds)].sort_values("driver")
    drivers = list(latest["driver"])
    per_driver = table.groupby("driver").agg(
        pace_hist=("pace_delta", "mean"), grid_avg=("grid", "mean")
    )

    if call == "thursday":
        feature_cols = ["grid_avg", "pace_hist"]
        grid_feature = {d: per_driver.loc[d, "grid_avg"] for d in drivers}
    else:
        feature_cols = ["grid", "pace_hist"]
        grid_feature = qualifying_grid(round_number, drivers)

    overrides = parse_grid_overrides(sys.argv[3:], drivers)
    grid_feature.update(overrides)

    # Direct model, trained on walk-forward features exactly as the backtest validated.
    train = add_history_features(table)
    model = fit(*races_as_arrays(train, feature_cols))
    X = np.array([[grid_feature[d], per_driver.loc[d, "pace_hist"]] for d in drivers])
    matrices = {"direct": sample_position_matrix(strengths(model, X), n_samples=N_SAMPLES)}

    # Simulator, fit on the same rounds. The grid it sees is the same feature
    # the direct model sees, so on Thursday both run on the season average.
    entry = pd.DataFrame({"driver": drivers, "team": list(latest["team"]),
                          "grid": [grid_feature[d] for d in drivers]})
    if call == "thursday":
        # A guessed grid carries its scatter; an overridden slot (penalty) is known.
        by_driver = table.groupby("driver")["grid"]
        entry["grid_sd"] = [0.0 if d in overrides else grid_scatter(by_driver.get_group(d))
                            for d in drivers]
    circuit = event["Location"]
    # Lights out, UTC. The page counts down to it; the commit must beat it.
    race_start = event["Session5DateUtc"].strftime("%Y-%m-%dT%H:%M:%SZ")
    total_laps = expected_laps(tables, circuit)
    race = fit_race(tables, round_number, circuit, entry, total_laps)
    matrices["sim"] = simulate(race, n_samples=SIM_SAMPLES)

    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for key, matrix in matrices.items():
        rows = headline_rows(matrix, drivers, list(latest["team"]))
        order = predicted_order(matrix, drivers)
        out = {
            "event": event["EventName"],
            "season": SEASON,
            "round": round_number,
            "circuit": circuit,
            "race_start": race_start,
            "call": call,
            "model": MODELS[key],
            "trained_on_rounds": trained_rounds,
            "n_samples": N_SAMPLES if key == "direct" else SIM_SAMPLES,
            "grid_overrides": overrides,
            "generated_at": generated_at,
            "predicted_order": order,
            "drivers": rows,
        }
        if key == "sim":
            out["total_laps"] = total_laps
        path = ROOT / "predictions" / f"{SEASON}-r{round_number:02d}-{call}-{key}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(out, indent=1) + "\n")

        print(f"\n{out['event']} round {round_number}, {call} call, {MODELS[key]}\n")
        print("driver   p_win  p_podium  p_points")
        for r in rows:
            print(f"{r['driver']:<6} {r['p_win']:7.3f} {r['p_podium']:9.3f} {r['p_points']:9.3f}")
        print(f"\nwrote {path.relative_to(ROOT)}")
    print("\ncommit both before lights out")


if __name__ == "__main__":
    main()
