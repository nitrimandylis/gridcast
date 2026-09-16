"""Run the race-weekend ritual unattended. Meant for an hourly timer.

Looks at the next round after the last one in data/driver_races.csv and does
whichever step is due, exactly the commands a person would run by hand:

    thursday   first run after qualifying start minus 48h: predict.py thursday
    saturday   first run after qualifying is classified:   predict.py saturday
    score      first run after the race is classified:     the four builders,
               then score.py

Each prediction call is committed, stamped (score.py records the commit hash
in the manifest) and committed again, like the manual history. Everything is
pushed once at the end. A run pulls --ff-only first and refuses to work on a
tree that is dirty or behind, so a human is always the one who resolves git.

    python scripts/weekend.py          do what is due, if anything
    python scripts/weekend.py --check  self-check, no network

Exit codes, for the wrapper that posts to Discord:

    0  nothing due, nothing printed
    1  a step ran; stdout is the message to post (first line is the title)
    2  the repo is not in a state this script may touch (dirty, behind)
    3  a step failed; the traceback is on stderr

Grid penalties are not handled here. The saturday call runs on the raw
qualifying classification, and the post shows the grid it used, so a penalty
is a manual rerun of predict.py with DRIVER=POSITION. The one exception is a
driver FastF1 serves as NaN (no lap time) after the session has ended: they
are placed at the back, which is what the stewards do, and it is recorded in
grid_overrides in the JSON.
"""

import json
import subprocess
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fastf1
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
PREDICTIONS = ROOT / "predictions"
RACES = ROOT / "data" / "driver_races.csv"
SEASON = 2026
SITE_URL = "https://nitrimandylis.github.io/gridcast/"
RECORD_URL = SITE_URL + "record.html"
THURSDAY_LEAD = timedelta(hours=48)
QUALI_LENGTH = timedelta(hours=1)
QUALI_SETTLED = timedelta(hours=2)   # after this, a NaN is a driver with no time, not a delay
RACE_SETTLED = timedelta(hours=2)    # classification lands after the podium, not at the flag
BUILDERS = ["build_data.py", "build_laps.py", "build_race_events.py", "build_dnf_history.py"]


def run(*args: str, capture: bool = False) -> str:
    """Run a command from the repo root, failing loudly."""
    # Child output goes to stderr: stdout of this script is the Discord message.
    out = subprocess.run(args, cwd=ROOT, check=True, text=True,
                         capture_output=capture, stdout=None if capture else sys.stderr)
    return out.stdout if capture else ""


def python(script: str, *args: str) -> None:
    run(sys.executable, str(SCRIPTS / script), *args)


def git(*args: str) -> str:
    return run("git", *args, capture=True).strip()


def sync_repo() -> None:
    """Pull fast-forward only. Anything else is a human's job."""
    if git("status", "--porcelain"):
        raise SystemExit(2)
    try:
        run("git", "pull", "--ff-only", "--quiet", capture=True)
    except subprocess.CalledProcessError as error:
        print(error.stderr, file=sys.stderr)
        raise SystemExit(2)


def commit(message: str, *paths: str) -> None:
    run("git", "add", "--", *paths)
    run("git", "commit", "--quiet", "-m", message)


def short_name(event_name: str) -> str:
    """'Azerbaijan Grand Prix' -> 'azerbaijan', for commit messages."""
    return event_name.replace("Grand Prix", "").strip().lower()


def prediction_files(round_number: int, call: str) -> list[Path]:
    return [PREDICTIONS / f"{SEASON}-r{round_number:02d}-{call}-{model}.json"
            for model in ("direct", "sim")]


def next_round(schedule: pd.DataFrame) -> pd.Series | None:
    """The first round not yet in the training data, or None when the season is done."""
    last = int(pd.read_csv(RACES)["round"].max())
    rows = schedule[schedule["RoundNumber"] == last + 1]
    return None if rows.empty else rows.iloc[0]


def session_time(event: pd.Series, name: str) -> datetime:
    """UTC start of the session called `name`, whatever slot it sits in.
    Sprint weekends move Qualifying to a different slot."""
    for i in range(1, 6):
        if event[f"Session{i}"] == name:
            return event[f"Session{i}DateUtc"].to_pydatetime().replace(tzinfo=timezone.utc)
    raise KeyError(f"{event['EventName']} has no session called {name}")


def qualifying_positions(round_number: int) -> dict[str, float] | None:
    """Driver -> classified position, NaN kept, or None if FastF1 cannot serve it yet."""
    try:
        session = fastf1.get_session(SEASON, round_number, "Q")
        session.load(telemetry=False, weather=False, messages=False)
    except Exception:
        return None
    results = session.results
    if results is None or results.empty:
        return None
    return dict(zip(results["Abbreviation"], results["Position"].astype(float)))


def fill_missing(positions: dict[str, float]) -> list[str]:
    """DRIVER=POSITION overrides placing every NaN driver after the last classified one."""
    classified = [p for p in positions.values() if pd.notna(p)]
    back = int(max(classified)) if classified else 0
    overrides = []
    for driver, position in sorted(positions.items()):
        if pd.isna(position):
            back += 1
            overrides.append(f"{driver}={back}")
    return overrides


def top_three(path: Path) -> str:
    """'NOR 0.51 · VER 0.20 · PIA 0.12' from a prediction file."""
    pred = json.loads(path.read_text())
    return " · ".join(f"{r['driver']} {r['p_win']:.2f}" for r in pred["drivers"][:3])


def call_message(event_name: str, call: str, files: list[Path], grid_line: str) -> str:
    lines = [f"{short_name(event_name)} {call} call"]
    for path in files:
        model = path.stem.split("-")[-1]
        lines.append(f"{model}: {top_three(path)}")
    lines.append(grid_line)
    lines.append(SITE_URL)
    return "\n".join(lines)


def predict_and_commit(event_name: str, call: str, round_number: int, overrides: list[str]) -> list[Path]:
    """predict.py, commit, stamp, commit: the manual sequence."""
    python("predict.py", event_name, call, *overrides)
    files = prediction_files(round_number, call)
    name = short_name(event_name)
    commit(f"predict {name} {call}", *[str(p) for p in files])
    python("score.py")
    commit(f"stamp {name} {call}", "site/manifest.json", "site/results.json")
    return files


def do_thursday(event: pd.Series) -> str:
    files = predict_and_commit(event["EventName"], "thursday", int(event["RoundNumber"]), [])
    return call_message(event["EventName"], "thursday", files, "grid: season average per driver")


def do_saturday(event: pd.Series, now: datetime) -> str | None:
    """None means qualifying is not classified yet: try again next hour."""
    round_number = int(event["RoundNumber"])
    positions = qualifying_positions(round_number)
    if positions is None:
        return None
    if any(pd.isna(p) for p in positions.values()) and now < session_time(event, "Qualifying") + QUALI_SETTLED:
        return None
    overrides = fill_missing(positions)
    files = predict_and_commit(event["EventName"], "saturday", round_number, overrides)
    order = sorted(positions.items(), key=lambda kv: (pd.isna(kv[1]), kv[1]))
    grid_line = "grid: " + " ".join(d for d, _ in order)
    if overrides:
        grid_line += f" (no time: {' '.join(overrides)})"
    return call_message(event["EventName"], "saturday", files, grid_line)


def do_score(event: pd.Series) -> str | None:
    """None means the race is not classified yet: revert the data and try again next hour."""
    round_number = int(event["RoundNumber"])
    for builder in BUILDERS:
        python(builder)
    if round_number not in set(pd.read_csv(RACES)["round"]):
        run("git", "checkout", "--", "data")
        return None
    python("score.py")
    name = short_name(event["EventName"])
    commit(f"score {name}", "data", "site/manifest.json", "site/results.json")
    results = json.loads((ROOT / "site" / "results.json").read_text())["results"]
    lines = [f"{name} scored"]
    for r in results:
        if r["round"] == round_number:
            model = r["model"].split("-")[0]
            lines.append(f"{r['call']} {model}: rps {r['rps']:.4f} vs baseline {r['baseline_rps']:.4f}")
    lines.append(RECORD_URL)
    return "\n".join(lines)


def main() -> None:
    sync_repo()
    fastf1.Cache.enable_cache(str(ROOT / "cache"))
    schedule = fastf1.get_event_schedule(SEASON, include_testing=False)
    event = next_round(schedule)
    if event is None:
        raise SystemExit(0)
    now = datetime.now(timezone.utc)
    quali = session_time(event, "Qualifying")
    race = session_time(event, "Race")
    round_number = int(event["RoundNumber"])
    have_thursday = all(p.exists() for p in prediction_files(round_number, "thursday"))
    have_saturday = all(p.exists() for p in prediction_files(round_number, "saturday"))

    message = None
    if now < race:
        if not have_thursday and now >= quali - THURSDAY_LEAD:
            message = do_thursday(event)
        elif have_thursday and not have_saturday and now >= quali + QUALI_LENGTH:
            message = do_saturday(event, now)
    elif now >= race + RACE_SETTLED:
        message = do_score(event)

    if message is None:
        raise SystemExit(0)
    run("git", "push", "--quiet", capture=True)
    print(message)
    raise SystemExit(1)


def demo() -> None:
    """Self-check: the NaN rule and the session lookup, no network."""
    positions = {"NOR": 1.0, "VER": 2.0, "ANT": float("nan"), "HAM": 3.0, "ALO": float("nan")}
    assert fill_missing(positions) == ["ALO=4", "ANT=5"], fill_missing(positions)
    assert fill_missing({"NOR": 1.0}) == []
    sprint = pd.Series({"EventName": "Singapore Grand Prix",
                        "Session1": "Practice 1", "Session2": "Sprint Qualifying",
                        "Session3": "Sprint", "Session4": "Qualifying", "Session5": "Race",
                        "Session4DateUtc": pd.Timestamp("2026-10-10 13:00:00"),
                        "Session5DateUtc": pd.Timestamp("2026-10-11 12:00:00")})
    assert session_time(sprint, "Qualifying").hour == 13
    assert session_time(sprint, "Race").day == 11
    assert short_name("United States Grand Prix") == "united states"
    print("self-check passed")


if __name__ == "__main__":
    if "--check" in sys.argv:
        demo()
    else:
        try:
            main()
        except SystemExit:
            raise
        except Exception:
            traceback.print_exc()
            sys.exit(3)
