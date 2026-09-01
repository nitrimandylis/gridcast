"""Random-event rates for the simulator: neutralisations and retirements.

Two fits, both read from tables build_race_events.py, build_dnf_history.py
and build_data.py already wrote.

fit_events (decision 6): per-circuit safety car and VSC rates from
2018 onward, shrunk toward the mean rate for that kind of circuit (street or
permanent). Red flags get ONE pooled rate: 16 in 98 races is too few to say
anything per circuit, and a per-circuit number would be a decimal point on
noise. Durations and start laps are sampled from the pooled empirical
distributions.

fit_dnf (decision 7): retirements split by owner.
  - first-lap incident: a track property, so pooled over 2018 onward, with a
    per-circuit factor shrunk toward the pooled rate. Grid position was
    checked and dropped: the rate is 2.4-3.0% in every grid quartile, so a
    grid term would fit noise.
  - mid-race retirement: a car property, so 2026 only, one per-lap hazard
    per team shrunk toward the pooled hazard. 2026 status strings say only
    "Retired", so mechanical failures and collisions are pooled here; the
    split in the decision is not observable in this season's data.

Walk-forward safety is the caller's job: pass tables already filtered to
rounds before the race being predicted.

    conda run -n gridcast python scripts/hazards.py
"""

import numpy as np
import pandas as pd

# Circuits where barriers line the track. Everything else is permanent.
STREET = {"Monte Carlo", "Baku", "Marina Bay", "Jeddah", "Miami", "Las Vegas",
          "Melbourne"}
# FastF1 names the same place differently across seasons.
ALIASES = {"Monaco": "Monte Carlo", "Yas Island": "Yas Marina",
           "Singapore": "Marina Bay"}
K_RACES = 3        # a circuit with 3 races counts half its own rate, half the base
K_ENTRIES = 60     # same idea for first-lap incidents, in driver-entries
K_LAPS = 500       # same idea for team hazards, in laps run


def canonical(circuit: str) -> str:
    return ALIASES.get(circuit, circuit)


def fit_events(events: pd.DataFrame, seen: pd.DataFrame, circuit: str) -> dict:
    """SC, VSC and red flag rates for one circuit, plus pooled shape draws."""
    events = events.assign(circuit=events["circuit"].map(canonical))
    seen = seen.assign(circuit=seen["circuit"].map(canonical))
    circuit = canonical(circuit)
    n_races = len(seen)
    races_here = int((seen["circuit"] == circuit).sum())
    same_kind = seen["circuit"].map(lambda c: (c in STREET) == (circuit in STREET))
    n_same = max(int(same_kind.sum()), 1)

    out = {}
    for kind in ("SC", "VSC"):
        rows = events[events["kind"] == kind]
        base = len(rows[rows["circuit"].map(lambda c: (c in STREET) == (circuit in STREET))]) / n_same
        here = int((rows["circuit"] == circuit).sum())
        out[f"{kind.lower()}_rate"] = (here + K_RACES * base) / (races_here + K_RACES)
        out[f"{kind.lower()}_laps"] = rows["laps"].to_numpy(dtype=float)
    out["red_rate"] = int((events["kind"] == "RED").sum()) / max(n_races, 1)

    # Where in the race neutralisations start, as a fraction of the distance.
    with_total = events.merge(seen[["season", "round", "total_laps"]],
                              on=["season", "round"])
    out["start_fracs"] = (with_total["start_lap"] / with_total["total_laps"]).clip(0, 1).to_numpy()
    out["races_here"] = races_here
    return out


def sample_events(hz: dict, total_laps: int, rng: np.random.Generator) -> list[tuple]:
    """One race's neutralisations as (kind, start_lap, end_lap), sorted."""
    found = []
    for kind in ("sc", "vsc"):
        for _ in range(rng.poisson(hz[f"{kind}_rate"])):
            start = 1 + int(rng.choice(hz["start_fracs"]) * (total_laps - 1))
            laps = int(rng.choice(hz[f"{kind}_laps"])) if len(hz[f"{kind}_laps"]) else 3
            found.append((kind.upper(), start, min(start + laps - 1, total_laps)))
    if rng.random() < hz["red_rate"]:
        start = 1 + int(rng.choice(hz["start_fracs"]) * (total_laps - 1))
        found.append(("RED", start, start))
    return sorted(found, key=lambda e: e[1])


def fit_dnf(history: pd.DataFrame, season_rows: pd.DataFrame, circuit: str) -> dict:
    """First-lap incident probability for this circuit, per-lap hazard per team."""
    circuit = canonical(circuit)
    cols = ["circuit", "laps_completed", "status"]
    entries = pd.concat([history[cols], season_rows[cols]], ignore_index=True)
    entries = entries.assign(circuit=entries["circuit"].map(canonical))
    started = entries[~entries["status"].str.contains("not start|Withdrew", case=False)]
    first_lap = started["laps_completed"] <= 1
    pooled = float(first_lap.mean()) if len(started) else 0.03
    here = started["circuit"] == circuit
    p_first = (first_lap[here].sum() + K_ENTRIES * pooled) / (here.sum() + K_ENTRIES)

    mid = season_rows[(season_rows["status"] == "Retired") & (season_rows["laps_completed"] > 1)]
    laps_run = season_rows.groupby("team")["laps_completed"].sum()
    pooled_hazard = len(mid) / max(float(laps_run.sum()), 1.0)
    per_team = mid.groupby("team").size()
    team_hazard = {
        team: float((per_team.get(team, 0) + K_LAPS * pooled_hazard) / (laps_run[team] + K_LAPS))
        for team in laps_run.index
    }
    return {"p_first_lap": float(p_first), "team_hazard": team_hazard,
            "pooled_hazard": pooled_hazard}


def demo() -> None:
    """Self-check: shrinkage pulls toward the base and rates stay sane."""
    seen = pd.DataFrame([
        {"season": 2020, "round": r, "circuit": c, "total_laps": 50}
        for r, c in enumerate(["Monaco", "Monte Carlo", "Monza", "Monza", "Spa", "Baku"], 1)
    ])
    events = pd.DataFrame([
        {"season": 2020, "round": 1, "circuit": "Monaco", "kind": "SC", "start_lap": 10, "laps": 4},
        {"season": 2020, "round": 2, "circuit": "Monte Carlo", "kind": "SC", "start_lap": 40, "laps": 3},
        {"season": 2020, "round": 2, "circuit": "Monte Carlo", "kind": "RED", "start_lap": 2, "laps": 1},
        {"season": 2020, "round": 3, "circuit": "Monza", "kind": "VSC", "start_lap": 25, "laps": 2},
        {"season": 2020, "round": 5, "circuit": "Spa", "kind": "SC", "start_lap": 1, "laps": 5},
    ])
    monaco = fit_events(events, seen, "Monaco")
    assert monaco["races_here"] == 2, "alias must merge Monaco and Monte Carlo"
    assert 0.7 < monaco["sc_rate"] < 0.9, "2 SCs in 2 races shrunk toward the 2/3 street base"
    assert abs(monaco["red_rate"] - 1 / 6) < 1e-9, "red flags are pooled: 1 in 6 races"
    never = fit_events(events, seen, "Nowhere")
    assert never["sc_rate"] > 0, "an unseen circuit falls back to the base rate"

    rng = np.random.default_rng(0)
    draws = [sample_events(monaco, 50, rng) for _ in range(2000)]
    n_sc = np.mean([sum(e[0] == "SC" for e in d) for d in draws])
    assert abs(n_sc - monaco["sc_rate"]) < 0.1, f"sampled SC rate {n_sc:.2f} vs {monaco['sc_rate']:.2f}"
    assert all(1 <= e[1] <= e[2] <= 50 for d in draws for e in d), "event laps out of range"

    history = pd.DataFrame({"circuit": ["Monza"] * 100, "laps_completed": [50] * 97 + [1, 1, 0],
                            "status": ["Finished"] * 99 + ["Did not start"]})
    season = pd.DataFrame({"circuit": ["Spa"] * 4, "team": ["A", "A", "B", "B"],
                           "laps_completed": [44, 44, 10, 44],
                           "status": ["Finished", "Finished", "Retired", "Finished"]})
    dnf = fit_dnf(history, season, "Monza")
    assert abs(dnf["p_first_lap"] - 2 / 99) < 0.01, dnf["p_first_lap"]
    assert dnf["team_hazard"]["B"] > dnf["team_hazard"]["A"] > 0, dnf["team_hazard"]
    print(f"self-check passed: Monaco sc_rate {monaco['sc_rate']:.2f}, red_rate {monaco['red_rate']:.2f}, "
          f"first-lap {dnf['p_first_lap']:.3f}, hazards {dnf['team_hazard']}")


if __name__ == "__main__":
    demo()
