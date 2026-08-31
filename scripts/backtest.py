"""Walk-forward backtest of the direct model (locked decision 3).

For each test race, fit on every earlier race only, predict the finishing
position distribution, and score it with the ranked probability score
against the grid-order baseline. Three predictors are scored:

  baseline   finish order equals grid order (a point mass on the grid slot)
  saturday   PL model on [actual grid, pace history]
  thursday   PL model on [season-average grid so far, pace history]

Every feature is walk-forward safe: a race is only ever predicted from data
that existed before it. Pace history for race r is the mean of a driver's
pace deltas over rounds before r, so race r's own laps never leak in.
Lower RPS is better.

    conda run -n gridcast python scripts/backtest.py
"""

from pathlib import Path

import numpy as np
import pandas as pd

from model import fit, sample_position_matrix, strengths

DATA = Path(__file__).resolve().parent.parent / "data" / "driver_races.csv"
MIN_TRAIN_RACES = 3


def add_history_features(table: pd.DataFrame) -> pd.DataFrame:
    """pace_hist and grid_avg for each row, from strictly earlier rounds."""
    table = table.sort_values(["round", "finish_rank"]).copy()
    pace_hist, grid_avg = [], []
    for _, row in table.iterrows():
        earlier = table[(table["driver"] == row["driver"]) & (table["round"] < row["round"])]
        pace_hist.append(earlier["pace_delta"].mean())  # NaN when no history
        grid_avg.append(earlier["grid"].mean())
    table["pace_hist"] = pace_hist
    table["grid_avg"] = grid_avg
    return table


def races_as_arrays(table: pd.DataFrame, feature_cols: list[str]):
    features, orders = [], []
    for _, race in table.groupby("round"):
        race = race.sort_values("finish_rank")
        features.append(race[feature_cols].to_numpy(dtype=float))
        orders.append(np.arange(len(race)))  # rows already in finish order
    return features, orders


def rps(cdf_pred: np.ndarray, finish_rank: int) -> float:
    """Ranked probability score for one driver, 0 is perfect."""
    n = len(cdf_pred)
    cdf_actual = (np.arange(1, n + 1) >= finish_rank).astype(float)
    return float(((cdf_pred - cdf_actual) ** 2).sum() / (n - 1))


def score_matrix(matrix: np.ndarray, race: pd.DataFrame) -> float:
    """Mean RPS over the race's drivers. Row i of matrix = finish_rank i+1."""
    cdfs = np.cumsum(matrix, axis=1)
    scores = [
        rps(cdfs[i], int(row["finish_rank"]))
        for i, (_, row) in enumerate(race.iterrows())
    ]
    return float(np.mean(scores))


def baseline_matrix(race: pd.DataFrame) -> np.ndarray:
    """Point mass: every driver finishes exactly where they started."""
    n = len(race)
    matrix = np.zeros((n, n))
    for i, (_, row) in enumerate(race.iterrows()):
        matrix[i, int(row["grid"]) - 1] = 1.0
    return matrix


def main() -> None:
    table = add_history_features(pd.read_csv(DATA))
    rounds = sorted(table["round"].unique())
    models = {
        "saturday": ["grid", "pace_hist"],
        "thursday": ["grid_avg", "pace_hist"],
    }

    results = []
    for k in rounds[MIN_TRAIN_RACES:]:
        train = table[table["round"] < k]
        race = table[table["round"] == k].sort_values("finish_rank")
        row = {"round": k, "event": race["event"].iloc[0][:20]}
        row["baseline"] = score_matrix(baseline_matrix(race), race)
        for name, cols in models.items():
            model = fit(*races_as_arrays(train, cols))
            s = strengths(model, race[cols].to_numpy(dtype=float))
            row[name] = score_matrix(sample_position_matrix(s), race)
        results.append(row)
        print(
            f"round {k:2d} {row['event']:<20}  baseline {row['baseline']:.4f}"
            f"  saturday {row['saturday']:.4f}  thursday {row['thursday']:.4f}"
        )

    scores = pd.DataFrame(results)
    print("\nmean RPS (lower is better)")
    for col in ["baseline", "saturday", "thursday"]:
        print(f"  {col:<9} {scores[col].mean():.4f}")


if __name__ == "__main__":
    main()
