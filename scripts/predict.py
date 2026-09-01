"""Make a live prediction and write the JSON (locked decisions 9 and 13).

Trains the direct model fresh on every completed 2026 race, predicts the
named event, and writes predictions/<season>-r<round>-<call>.json holding the
full P(driver, position) matrix, the derived headlines and run metadata.
The file must be committed before lights out: git history is the timestamp.

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

from backtest import add_history_features, races_as_arrays
from model import fit, sample_position_matrix, strengths

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "driver_races.csv"
SEASON = 2026
N_SAMPLES = 20000
MODEL_VERSION = "direct-v1-plackett-luce"


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


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[2] not in ("thursday", "saturday"):
        raise SystemExit(__doc__)
    event_name, call = sys.argv[1], sys.argv[2]

    fastf1.Cache.enable_cache(str(ROOT / "cache"))
    event = fastf1.get_event(SEASON, event_name)
    round_number = int(event["RoundNumber"])

    table = pd.read_csv(DATA)
    trained_rounds = sorted(int(r) for r in table["round"].unique())
    if round_number <= max(trained_rounds):
        raise SystemExit(f"round {round_number} is already in the training data")

    # Entry list and season-to-date features, from all completed races.
    latest = table[table["round"] == max(trained_rounds)]
    drivers = sorted(latest["driver"])
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

    # Train on walk-forward features, exactly as the backtest validated.
    train = add_history_features(table)
    model = fit(*races_as_arrays(train, feature_cols))

    X = np.array(
        [[grid_feature[d], per_driver.loc[d, "pace_hist"]] for d in drivers]
    )
    matrix = sample_position_matrix(strengths(model, X), n_samples=N_SAMPLES)

    rows = []
    for i, driver in enumerate(drivers):
        rows.append(
            {
                "driver": driver,
                "p_win": round(float(matrix[i, 0]), 4),
                "p_podium": round(float(matrix[i, :3].sum()), 4),
                "p_points": round(float(matrix[i, :10].sum()), 4),
                "p_position": [round(float(p), 4) for p in matrix[i]],
            }
        )
    rows.sort(key=lambda r: -r["p_win"])

    out = {
        "event": event["EventName"],
        "season": SEASON,
        "round": round_number,
        "call": call,
        "model": MODEL_VERSION,
        "trained_on_rounds": trained_rounds,
        "n_samples": N_SAMPLES,
        "grid_overrides": overrides,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "drivers": rows,
    }
    path = ROOT / "predictions" / f"{SEASON}-r{round_number:02d}-{call}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(out, indent=1) + "\n")

    print(f"{out['event']} round {round_number}, {call} call\n")
    print("driver   p_win  p_podium  p_points")
    for r in rows:
        print(f"{r['driver']:<6} {r['p_win']:7.3f} {r['p_podium']:9.3f} {r['p_points']:9.3f}")
    print(f"\nwrote {path.relative_to(ROOT)}  (commit before lights out)")


if __name__ == "__main__":
    main()
