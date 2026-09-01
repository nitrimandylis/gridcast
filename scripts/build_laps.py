"""Build the lap table the simulator runs on.

One row per driver per lap across the 2026 season:

    round, event, driver, lap_number, stint, compound, tyre_age,
    lap_time, track_status, is_clean

is_clean marks the laps the degradation fit is allowed to use: no in-lap, no
out-lap, past the opening two racing laps, green track only, and flagged
accurate by FastF1. The rule is build_data.clean_laps, reused rather than
restated so the pace model and the simulator can never disagree about what a
usable lap is.

Unclean laps are kept rather than dropped, because the simulator needs them.
Replay mode reads the strategy teams actually ran, and a pit stop is visible
only as a stint boundary.

Car properties do not transfer across the 2026 regulation change
(data-validity rule 1), so this is 2026 only. The rounds come from
driver_races.csv, so the two tables always cover the same races.

    conda run -n gridcast python scripts/build_laps.py
"""

from pathlib import Path

import fastf1
import pandas as pd

from build_data import clean_laps

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
RACES = ROOT / "data" / "driver_races.csv"
OUT = ROOT / "data" / "laps.csv"
SEASON = 2026

COLUMNS = ["Driver", "LapNumber", "Stint", "Compound", "TyreLife",
           "LapTime", "TrackStatus"]


def race_laps(rnd: int, event_name: str) -> pd.DataFrame:
    session = fastf1.get_session(SEASON, rnd, "R")
    session.load(telemetry=False, weather=False, messages=False)
    laps = session.laps

    table = laps[COLUMNS].copy()
    table.columns = ["driver", "lap_number", "stint", "compound",
                     "tyre_age", "lap_time", "track_status"]
    table["lap_time"] = table["lap_time"].dt.total_seconds()
    table.insert(0, "event", event_name)
    table.insert(0, "round", rnd)

    # Index alignment does the work: clean_laps returns a subset of the rows.
    table["is_clean"] = laps.index.isin(clean_laps(laps).index)
    return table


def main() -> None:
    CACHE.mkdir(exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE))

    races = pd.read_csv(RACES)[["round", "event"]].drop_duplicates()
    all_laps = []
    for _, race in races.iterrows():
        rnd, name = int(race["round"]), race["event"]
        try:
            table = race_laps(rnd, name)
        except Exception as error:
            print(f"[round {rnd:2d}] SKIPPED {type(error).__name__}: {error}")
            continue
        all_laps.append(table)
        print(f"[round {rnd:2d}] {name[:28]:<28} {len(table):5d} laps, "
              f"{int(table['is_clean'].sum()):5d} clean")

    table = pd.concat(all_laps, ignore_index=True)
    table.to_csv(OUT, index=False)
    print(f"\nwrote {len(table)} laps ({int(table['is_clean'].sum())} clean) "
          f"across {table['round'].nunique()} races to {OUT}")


if __name__ == "__main__":
    main()
