"""Build the safety car / VSC / red flag history for locked decision 6.

Writes two files, because the incident rate needs a denominator:

    data/race_events.csv   one row per incident: kind, start_lap, end_lap, laps
    data/races_seen.csv    one row per race successfully read

kind is SC, VSC or RED, so the pair gives occurrence, lap timing AND
duration, which is what decision 6 asks for.

Track properties transfer across the 2026 regulation change (data-validity
rule 2), so the whole 2018-2026 range is fair game here. Car properties do
not, which is why this file holds no lap times.

FastF1 gives track status as a change log with session timestamps, not a
per-lap column, so each change is mapped to a lap by asking which lap the
leader had started at that moment.

The FastF1 API allows 500 calls an hour and a race costs roughly nine, so a
full build is about four hours and WILL hit the limit partway. This script is
resumable: it appends after every race and skips races already recorded, so
rerunning it each hour walks the backlog down. Cached races cost no calls, so
a rerun replays what it already has at full speed.

    conda run -n gridcast python scripts/build_race_events.py
"""

from pathlib import Path

import fastf1
import pandas as pd
from fastf1.exceptions import RateLimitExceededError

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
EVENTS = ROOT / "data" / "race_events.csv"
SEEN = ROOT / "data" / "races_seen.csv"
SEASONS = range(2018, 2027)
CODES = {"4": "SC", "5": "RED", "6": "VSC"}


def load_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def periods(session) -> list[dict]:
    """Every SC, VSC and red flag window in one race, as lap ranges."""
    starts = session.laps.groupby("LapNumber")["LapStartTime"].min().dropna().sort_index()
    if starts.empty:
        return []
    last_lap = int(starts.index.max())

    def lap_at(when) -> int:
        earlier = starts[starts <= when]
        return int(earlier.index.max()) if len(earlier) else 1

    # ponytail: substring test on the status code. FastF1 occasionally emits
    # combined codes and this treats them as all-active, which is the safe
    # direction. Parse properly only if the counts look wrong.
    open_at, found = {}, []
    for _, row in session.track_status.iterrows():
        code_text = str(row["Status"])
        for code, kind in CODES.items():
            if code in code_text and kind not in open_at:
                open_at[kind] = lap_at(row["Time"])
            elif code not in code_text and kind in open_at:
                found.append({"kind": kind, "start_lap": open_at.pop(kind),
                              "end_lap": lap_at(row["Time"])})
    for kind, start in open_at.items():
        found.append({"kind": kind, "start_lap": start, "end_lap": last_lap})

    for row in found:
        row["laps"] = row["end_lap"] - row["start_lap"] + 1
    return found


def main() -> None:
    CACHE.mkdir(exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE))
    EVENTS.parent.mkdir(exist_ok=True)

    events, seen = load_csv(EVENTS), load_csv(SEEN)
    done = set() if seen.empty else set(zip(seen["season"], seen["round"]))
    print(f"resuming with {len(done)} races already recorded")

    event_rows = events.to_dict("records")
    seen_rows = seen.to_dict("records")

    def save() -> None:
        pd.DataFrame(event_rows).to_csv(EVENTS, index=False)
        pd.DataFrame(seen_rows).to_csv(SEEN, index=False)

    for season in SEASONS:
        try:
            schedule = fastf1.get_event_schedule(season, include_testing=False)
        except RateLimitExceededError:
            print(f"rate limit hit on the {season} schedule, rerun in an hour")
            return save()
        schedule = schedule[schedule["EventDate"] < pd.Timestamp.now()]

        for _, event in schedule.iterrows():
            rnd = int(event["RoundNumber"])
            if (season, rnd) in done:
                continue
            try:
                session = fastf1.get_session(season, rnd, "R")
                session.load(telemetry=False, weather=False, messages=False)
                found = periods(session)
                total_laps = int(session.laps["LapNumber"].max())
            except RateLimitExceededError:
                print(f"rate limit hit at {season} r{rnd}, rerun in an hour")
                return save()
            except Exception as error:
                print(f"[{season} r{rnd:2d}] SKIPPED {type(error).__name__}: {error}")
                continue

            where = {"season": season, "round": rnd, "event": event["EventName"],
                     "circuit": event["Location"]}
            event_rows.extend({**where, **row} for row in found)
            seen_rows.append({**where, "total_laps": total_laps})
            save()  # after every race: a four-hour job must survive dying
            print(f"[{season} r{rnd:2d}] {event['EventName'][:28]:<28} "
                  f"{len(found)} incidents")

    save()
    print(f"\nwrote {len(event_rows)} incidents across {len(seen_rows)} races")


if __name__ == "__main__":
    main()
