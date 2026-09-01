"""Build the retirement history the simulator's DNF model reads (decision 7).

One row per driver per race for every pre-2026 race already recorded in
data/races_seen.csv, written to data/dnf_history.csv:

    season, round, circuit, driver, team, grid, laps_completed, total_laps,
    status

The simulator uses it for ONE thing: first-lap incident rates by grid
position and circuit. Those are track properties, so 2018 onward is fair
game (data-validity rule 2). Mechanical reliability is a car property and
comes from 2026 rows in driver_races.csv instead, never from here.

Only races in races_seen.csv are read, so every session is already in the
FastF1 cache and this makes no API calls.

    conda run -n gridcast python scripts/build_dnf_history.py
"""

from pathlib import Path

import fastf1
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
SEEN = ROOT / "data" / "races_seen.csv"
OUT = ROOT / "data" / "dnf_history.csv"


def race_rows(season: int, rnd: int, circuit: str) -> list[dict]:
    session = fastf1.get_session(season, rnd, "R")
    session.load(telemetry=False, weather=False, messages=False)
    laps_done = session.laps.groupby("Driver")["LapNumber"].max()
    total_laps = int(session.laps["LapNumber"].max())
    n = len(session.results)
    rows = []
    for _, res in session.results.iterrows():
        drv = res["Abbreviation"]
        grid = res["GridPosition"]
        if pd.isna(grid) or grid == 0:
            grid = n  # pit lane start
        rows.append({
            "season": season, "round": rnd, "circuit": circuit,
            "driver": drv, "team": res["TeamName"], "grid": int(grid),
            "laps_completed": int(laps_done.get(drv, 0)),
            "total_laps": total_laps, "status": res["Status"],
        })
    return rows


def main() -> None:
    fastf1.Cache.enable_cache(str(CACHE))
    seen = pd.read_csv(SEEN)
    seen = seen[seen["season"] < 2026]
    all_rows = []
    for _, race in seen.iterrows():
        season, rnd = int(race["season"]), int(race["round"])
        try:
            all_rows.extend(race_rows(season, rnd, race["circuit"]))
        except Exception as error:
            print(f"[{season} r{rnd:2d}] SKIPPED {type(error).__name__}: {error}")
    table = pd.DataFrame(all_rows)
    table.to_csv(OUT, index=False)
    print(f"wrote {len(table)} rows across {len(seen)} races to {OUT}")


if __name__ == "__main__":
    main()
