"""Week-1 data gates.

Three things the plan depends on. Each one, if it fails, changes what we can
build. Run this before writing any model code.

    conda run -n gridcast python scripts/gates.py
"""

from pathlib import Path

import fastf1

CACHE = Path(__file__).resolve().parent.parent / "cache"


def setup() -> None:
    CACHE.mkdir(exist_ok=True)
    fastf1.Cache.enable_cache(str(CACHE))


def gate_1_2026_sessions() -> bool:
    """Does FastF1 serve 2026 race sessions at all?

    If not, there is no project: 2026 is the only season whose car data is
    valid under the new regulations.
    """
    schedule = fastf1.get_event_schedule(2026, include_testing=False)
    print(f"  2026 events in schedule: {len(schedule)}")

    session = fastf1.get_session(2026, "Dutch Grand Prix", "R")
    session.load(telemetry=False, weather=False, messages=False)
    laps = session.laps
    print(f"  Dutch GP 2026 laps loaded: {len(laps)} rows, {laps['Driver'].nunique()} drivers")
    return len(laps) > 0


def gate_2_track_status_2018() -> bool:
    """Does FastF1 serve track status back to 2018?

    Safety car rate is a track property, so we fit it on 2018-2026 history.
    Ergast and Jolpica never carried track status, so FastF1 is the only
    source. If the history is missing, decision 6 collapses to circuit-type
    base rates.
    """
    session = fastf1.get_session(2018, "British Grand Prix", "R")
    session.load(telemetry=False, weather=False, messages=False)
    status = session.track_status
    print(f"  2018 British GP track status rows: {len(status)}")
    if len(status):
        print(f"  distinct status codes: {sorted(status['Status'].unique())}")
    return len(status) > 0


def gate_3_compound_2026() -> bool:
    """Does FastF1 give per-lap tyre compound and age for 2026?

    Per-driver per-compound degradation slopes are decision 4. Without
    compound and TyreLife per lap they cannot be fit, and Jolpica has never
    carried compound data.
    """
    session = fastf1.get_session(2026, "Dutch Grand Prix", "R")
    session.load(telemetry=False, weather=False, messages=False)
    laps = session.laps
    needed = ["Compound", "TyreLife", "Stint", "TrackStatus", "LapTime"]
    missing = [c for c in needed if c not in laps.columns]
    if missing:
        print(f"  MISSING columns: {missing}")
        return False
    compounds = laps["Compound"].dropna().unique()
    filled = laps["Compound"].notna().sum()
    print(f"  compounds seen: {sorted(compounds)}")
    print(f"  laps with a compound: {filled}/{len(laps)}")
    return filled > 0


GATES = [
    ("2026 sessions available", gate_1_2026_sessions),
    ("track status back to 2018", gate_2_track_status_2018),
    ("2026 per-lap compound and tyre age", gate_3_compound_2026),
]


def main() -> None:
    setup()
    results = {}
    for name, gate in GATES:
        print(f"\n[{name}]")
        try:
            results[name] = gate()
        except Exception as error:
            print(f"  FAILED: {type(error).__name__}: {error}")
            results[name] = False

    print("\n" + "=" * 50)
    for name, passed in results.items():
        print(f"{'PASS' if passed else 'FAIL'}  {name}")


if __name__ == "__main__":
    main()
