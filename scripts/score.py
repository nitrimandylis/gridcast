"""Score every committed prediction that has a result, for the scorecard.

Reads predictions/*.json, joins each to the finishing order in
data/driver_races.csv, and writes two files the static page fetches:

    site/results.json    RPS per prediction file, per driver and averaged,
                         next to the grid-order baseline on the same race,
                         plus a running mean per model and call
    site/manifest.json   every prediction file with its metadata, scored or
                         not, because a browser cannot list a directory, plus
                         the hash and author date of the commit that added it.
                         That commit is the timestamp proof; the page links it.

All the arithmetic is here, in Python, reusing backtest.rps. The page only
renders. Run after build_data.py has picked up the race:

    conda run -n gridcast python scripts/score.py
"""

import json
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import rps

ROOT = Path(__file__).resolve().parent.parent
PREDICTIONS = ROOT / "predictions"
RACES = ROOT / "data" / "driver_races.csv"
SITE = ROOT / "site"


def score_prediction(pred: dict, race: pd.DataFrame) -> dict:
    """RPS for one prediction file against one race's classification."""
    finish = dict(zip(race["driver"], race["finish_rank"]))
    grid = dict(zip(race["driver"], race["grid"]))
    n = len(race)
    per_driver, model_scores, baseline_scores = [], [], []
    for row in pred["drivers"]:
        driver = row["driver"]
        if driver not in finish:
            continue  # did not start, nothing to score
        cdf = np.cumsum(row["p_position"])
        # A point mass on the grid slot, the "you finish where you start" baseline.
        baseline_cdf = (np.arange(1, len(cdf) + 1) >= grid[driver]).astype(float)
        s = rps(cdf, int(finish[driver]))
        b = rps(baseline_cdf, int(finish[driver]))
        per_driver.append({"driver": driver, "team": row.get("team", ""),
                           "finish_rank": int(finish[driver]),
                           "grid": int(grid[driver]), "rps": round(s, 4)})
        model_scores.append(s)
        baseline_scores.append(b)
    return {
        "rps": round(float(np.mean(model_scores)), 4),
        "baseline_rps": round(float(np.mean(baseline_scores)), 4),
        "n_scored": len(model_scores),
        "n_entrants": n,
        "drivers": per_driver,
    }


def first_commit(path: Path) -> dict:
    """Hash and author date of the commit that added the file, or nulls."""
    out = subprocess.run(
        ["git", "log", "--follow", "--diff-filter=A", "--format=%H%x09%aI", "--", str(path)],
        cwd=ROOT, capture_output=True, text=True).stdout.strip()
    if not out:
        return {"commit": None, "committed_at": None}
    commit, when = out.splitlines()[-1].split("\t")  # oldest add, across renames
    return {"commit": commit, "committed_at": when}


def metadata(pred: dict, path: Path) -> dict:
    return {"file": path.name, "season": pred["season"], "round": pred["round"],
            "event": pred["event"], "call": pred["call"], "model": pred["model"],
            "generated_at": pred["generated_at"], **first_commit(path)}


def main() -> None:
    races = pd.read_csv(RACES)
    manifest, results = [], []
    for path in sorted(PREDICTIONS.glob("*.json")):
        pred = json.loads(path.read_text())
        meta = metadata(pred, path)
        race = races[races["round"] == pred["round"]]
        meta["scored"] = not race.empty
        manifest.append(meta)
        if not race.empty:
            results.append({**meta, **score_prediction(pred, race)})

    summary = {}
    for r in results:
        key = f"{r['model']}/{r['call']}"
        summary.setdefault(key, {"model": r["model"], "call": r["call"], "n": 0,
                                 "rps": 0.0, "baseline_rps": 0.0})
        summary[key]["n"] += 1
        summary[key]["rps"] += r["rps"]
        summary[key]["baseline_rps"] += r["baseline_rps"]
    for s in summary.values():
        s["rps"] = round(s["rps"] / s["n"], 4)
        s["baseline_rps"] = round(s["baseline_rps"] / s["n"], 4)

    SITE.mkdir(exist_ok=True)
    (SITE / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    (SITE / "results.json").write_text(json.dumps(
        {"summary": sorted(summary.values(), key=lambda s: (s["call"], s["model"])),
         "results": results}, indent=1) + "\n")
    print(f"{len(manifest)} predictions, {len(results)} scored")
    for s in summary.values():
        print(f"  {s['model']:<24} {s['call']:<9} n={s['n']}  rps {s['rps']:.4f}  baseline {s['baseline_rps']:.4f}")


def demo() -> None:
    """Self-check: a perfect prediction scores 0, a certain wrong one scores worse than the baseline."""
    race = pd.DataFrame({"driver": ["A", "B", "C"], "finish_rank": [1, 2, 3], "grid": [2, 1, 3]})
    perfect = {"drivers": [
        {"driver": "A", "p_position": [1, 0, 0]},
        {"driver": "B", "p_position": [0, 1, 0]},
        {"driver": "C", "p_position": [0, 0, 1]},
        {"driver": "Z", "p_position": [0, 0, 1]},  # not in the race, must be skipped
    ]}
    out = score_prediction(perfect, race)
    assert out["rps"] == 0.0 and out["n_scored"] == 3, out
    assert out["baseline_rps"] > 0, "grid order was wrong for A and B"
    wrong = {"drivers": [{"driver": "A", "p_position": [0, 0, 1]}]}
    assert score_prediction(wrong, race)["rps"] == 1.0, "certain and wrong by two places is the worst score"
    print("self-check passed")


if __name__ == "__main__":
    import sys
    demo() if "--check" in sys.argv else main()
