"""Per-driver per-compound tyre degradation, fit on lap rows (decision 4).

The model for one clean lap is

    lap_time = intercept[race, driver]
             + progress * lap_number
             + offset[compound]
             + slope[driver, compound] * tyre_age

Three things to understand about it:

**Why the progress term exists.** Two effects move lap time monotonically
through a stint and they point opposite ways. Tyres age and lap times rise.
The car burns fuel and the track rubbers in, so lap times fall. Fit tyre_age
on its own and they partly cancel, leaving a degradation slope biased toward
flat, which would tell the pit optimiser that extending a stint is cheap and
make it systematically under-stop. The progress term absorbs the downward
effects so the tyre slope is left alone.

**Why it is called progress and not fuel.** It captures fuel burn and track
evolution together. Both are monotonic in lap number and nothing in the data
separates them, so naming it "fuel" would claim physics this does not have.
It is pooled across every driver and race: fuel burn is close to a shared
constant, and pooling pins it down on all 11,000 rows at once.

**Why it is identified at all.** Within one stint tyre_age = lap_number minus
the stint start, perfectly collinear, so nothing could separate them. They
decouple across stints, because tyre_age resets to 1 while lap_number keeps
climbing. 232 of 252 driver-races in 2026 ran two or more stints.

**Why the compound offset is a prior and not a fit.** A slope says how fast a
tyre decays, not that a new soft is quicker than a new hard. The optimiser
needs that speed to weigh against degradation. It cannot be estimated from
race laps: teams pick compounds strategically, so the choice is driven by the
same unobserved things that drive lap time (fuel, traffic, track state,
pushing versus managing). Fitting it anyway on 2026 returns a SOFT that is
0.21s SLOWER than a HARD and degrades less, which is backwards on both
counts, and per-race offsets swing from -1.26s to +0.57s with no consistent
ordering. Fixed effects cannot repair endogeneity in the regressor.

So COMPOUND_OFFSETS is an assumption with a number on it, not evidence. The
fitted values are still returned as "fitted_offsets" so the gap between
assumption and data stays visible. This is the single least defensible
parameter in the simulator and the first thing to attack if the pit optimiser
misbehaves: the honest fix is low-fuel practice long runs, not more race laps.

Per-race-per-driver intercepts absorb circuit speed and how quick the car
was that weekend, so neither leaks into the slope.

Small cells are shrunk toward their compound's mean slope, so a driver with
seven laps on softs cannot contribute a wild number to the optimiser.

    conda run -n gridcast python scripts/degradation.py
"""

import numpy as np
import pandas as pd

DRY = ("SOFT", "MEDIUM", "HARD")
# ponytail: seconds per lap quicker than a hard of the same age. A prior, not
# a fit, for the reason in the docstring. Roughly the nominal one-step Pirelli
# delta. Tune this first if the optimiser picks silly compounds; replace it
# with practice long-run pace when there is time to build that.
COMPOUND_OFFSETS = {"SOFT": -0.6, "MEDIUM": -0.3, "HARD": 0.0}
# Cell size at which a slope counts half its own laps, half the compound mean.
SHRINK_LAPS = 50


def usable(laps: pd.DataFrame) -> pd.DataFrame:
    """Clean dry laps with everything the fit needs actually present."""
    rows = laps[laps["is_clean"] & laps["compound"].isin(DRY)]
    return rows.dropna(subset=["lap_time", "tyre_age", "lap_number"])


def fit(laps: pd.DataFrame) -> dict:
    rows = usable(laps).copy()
    rows["cell"] = rows["driver"] + "/" + rows["compound"]
    rows["race_driver"] = rows["round"].astype(str) + "/" + rows["driver"]

    intercepts = pd.get_dummies(rows["race_driver"], prefix="ic", dtype=float)
    # One column per driver-compound, holding tyre_age on that cell's rows
    # and zero elsewhere, so each cell gets its own slope.
    slopes = pd.get_dummies(rows["cell"], prefix="sl", dtype=float)
    slopes = slopes.mul(rows["tyre_age"].to_numpy(), axis=0)
    progress = pd.DataFrame({"progress": rows["lap_number"].astype(float)})
    # HARD is the reference, so offsets read as seconds against a hard tyre.
    offsets = pd.get_dummies(rows["compound"], prefix="off", dtype=float)
    offsets = offsets.drop(columns=["off_HARD"])

    design = pd.concat([intercepts, progress, offsets, slopes], axis=1)
    beta, *_ = np.linalg.lstsq(design.to_numpy(), rows["lap_time"].to_numpy(),
                               rcond=None)
    weights = pd.Series(beta, index=design.columns)

    raw = {name[3:]: weights[name] for name in slopes.columns}
    counts = rows.groupby("cell").size()
    return {
        "progress": float(weights["progress"]),
        "offsets": dict(COMPOUND_OFFSETS),
        "fitted_offsets": {"HARD": 0.0,
                           **{name[4:]: float(weights[name])
                              for name in offsets.columns}},
        "slopes": shrink(raw, counts),
        "raw_slopes": raw,
        "n_laps": len(rows),
    }


def shrink(raw: dict[str, float], counts: pd.Series) -> dict[str, float]:
    """Pull each cell's slope toward the mean slope for its compound.

    A cell with SHRINK_LAPS laps lands halfway. Cells with hundreds of laps
    barely move, which is what we want: the shrinkage is there for the four
    driver-compound pairs that have under thirty laps.
    """
    by_compound = {}
    for compound in DRY:
        cells = [s for name, s in raw.items() if name.endswith("/" + compound)]
        by_compound[compound] = float(np.mean(cells)) if cells else 0.0

    shrunk = {}
    for name, slope in raw.items():
        n = float(counts.get(name, 0))
        target = by_compound[name.split("/")[1]]
        shrunk[name] = (n * slope + SHRINK_LAPS * target) / (n + SHRINK_LAPS)
    return shrunk


def lap_pace(model: dict, driver: str, compound: str, tyre_age: float,
             lap_number: float) -> float:
    """Everything the tyre and the race clock contribute to one lap time.

    The simulator adds the driver's own base pace on top. Returned in seconds
    relative to a new hard tyre on lap zero.
    """
    return (model["offsets"].get(compound, 0.0)
            + slope_for(model, driver, compound) * tyre_age
            + model["progress"] * lap_number)


def slope_for(model: dict, driver: str, compound: str) -> float:
    """Degradation in seconds per lap of tyre age, with a sane fallback."""
    key = f"{driver}/{compound}"
    if key in model["slopes"]:
        return model["slopes"][key]
    same = [s for name, s in model["slopes"].items()
            if name.endswith("/" + compound)]
    return float(np.mean(same)) if same else 0.0


def demo() -> None:
    """Self-check: build laps from known parameters, see if the fit finds them."""
    rng = np.random.default_rng(0)
    true_progress = -0.04
    true_slope = {"A/SOFT": 0.12, "A/HARD": 0.05,
                  "B/SOFT": 0.09, "B/HARD": 0.03}
    true_offset = {"SOFT": -0.8, "HARD": 0.0}
    rows = []
    for rnd in (1, 2):
        for driver in ("A", "B"):
            base = 90.0 + 5 * rnd + (driver == "B")
            lap = 1
            # Three stints, which is what lets the fit tell age from progress.
            for stint, compound in enumerate(["SOFT", "HARD", "SOFT"], start=1):
                for age in range(1, 19):
                    rows.append({
                        "round": rnd, "driver": driver, "lap_number": lap,
                        "stint": stint, "compound": compound, "tyre_age": age,
                        "lap_time": (base + true_progress * lap
                                     + true_offset[compound]
                                     + true_slope[f"{driver}/{compound}"] * age
                                     + rng.normal(0, 0.05)),
                        "is_clean": True,
                    })
                    lap += 1
    model = fit(pd.DataFrame(rows))

    assert abs(model["progress"] - true_progress) < 0.01, model["progress"]
    for key, want in true_slope.items():
        got = model["raw_slopes"][key]
        assert abs(got - want) < 0.01, f"{key}: fit {got:.3f}, true {want:.3f}"
    for compound, want in true_offset.items():
        got = model["fitted_offsets"][compound]
        assert abs(got - want) < 0.05, f"{compound} offset {got:.2f}, true {want}"
    assert model["offsets"] == COMPOUND_OFFSETS, "offsets ship as the prior"
    assert slope_for(model, "ZZZ", "SOFT") > 0, "fallback should still degrade"
    print(f"self-check passed on {model['n_laps']} synthetic laps: "
          f"progress {model['progress']:.3f} (true {true_progress}), "
          f"slopes within 0.01 s/lap, "
          f"soft offset {model['fitted_offsets']['SOFT']:.2f} "
          f"(true {true_offset['SOFT']})")


if __name__ == "__main__":
    demo()
