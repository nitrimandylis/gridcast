"""Build the driver-race table for the direct model.

Loads every completed 2026 race, cleans the laps, and writes one row per
driver per race to data/driver_races.csv:

    round, event, driver, grid, finish_rank, n_entrants, pace_delta,
    laps_completed, status

finish_rank is the official classification order, with unclassified drivers
(DNF, DNS) ranked at the back by laps completed. pace_delta is that driver's
median clean lap time minus the race-wide median of driver medians, in
seconds, so negative means faster than the field. Clean laps drop in-laps,
out-laps, the first two racing laps, non-green track status and anything
FastF1 flags as inaccurate. Fuel load mostly cancels in the delta because
every car burns down over the same race.

    conda run -n gridcast python scripts/build_data.py
"""

from pathlib import Path

import fastf1
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
OUT = ROOT / "data" / "driver_races.csv"


def completed_rounds(season: int) -> pd.DataFrame:
    schedule = fastf1.get_event_schedule(season, include_testing=False)
    done = schedule[schedule["EventDate"] < pd.Timestamp.now()]
    return done


def clean_laps(laps: pd.DataFrame) -> pd.DataFrame:
    ok = (
        laps["PitInTime"].isna()
        & laps["PitOutTime"].isna()
        & (laps["LapNumber"] > 2)
        & (laps["TrackStatus"] == "1")
        & laps["IsAccurate"]
        & laps["LapTime"].notna()
    )
    return laps[ok]


def race_rows(season: int, rnd: int, event_name: str) -> list[dict]:
    session = fastf1.get_session(season, rnd, "R")
    session.load(telemetry=False, weather=False, messages=False)
    results = session.results
    laps = session.laps

    laps_done = laps.groupby("Driver")["LapNumber"].max()
    clean = clean_laps(laps)
    seconds = clean["LapTime"].dt.total_seconds()
    driver_median = seconds.groupby(clean["Driver"]).median()
    field_median = driver_median.median()

    n = len(results)
    rows = []
    for _, res in results.iterrows():
        drv = res["Abbreviation"]
        grid = res["GridPosition"]
        if pd.isna(grid) or grid == 0:  # pit lane start reports grid 0
            grid = n
        rows.append(
            {
                "round": rnd,
                "event": event_name,
                "driver": drv,
                "grid": int(grid),
                "position": res["Position"],  # NaN when unclassified
                "n_entrants": n,
                "pace_delta": round(driver_median.get(drv, np.nan) - field_median, 3)
                if drv in driver_median
                else np.nan,
                "laps_completed": int(laps_done.get(drv, 0)),
                "status": res["Status"],
            }
        )

    # Classified drivers keep their official position. Unclassified drivers go
    # to the back, ordered by how many laps they completed.
    rows.sort(
        key=lambda r: (
            (0, r["position"]) if pd.notna(r["position"]) else (1, -r["laps_completed"])
        )
    )
    for rank, row in enumerate(rows, start=1):
        row["finish_rank"] = rank
        del row["position"]
    return rows


def main() -> None:
    CACHE.mkdir(exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE))
    OUT.parent.mkdir(exist_ok=True)

    all_rows = []
    for _, ev in completed_rounds(2026).iterrows():
        rnd = int(ev["RoundNumber"])
        name = ev["EventName"]
        print(f"[round {rnd:2d}] {name}")
        try:
            all_rows.extend(race_rows(2026, rnd, name))
        except Exception as error:
            print(f"  SKIPPED: {type(error).__name__}: {error}")

    table = pd.DataFrame(all_rows)
    table.to_csv(OUT, index=False)
    print(f"\nwrote {len(table)} rows across {table['round'].nunique()} races to {OUT}")


if __name__ == "__main__":
    main()
