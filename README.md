```
  ██████╗ ██████╗ ██╗██████╗  ██████╗ █████╗ ███████╗████████╗
 ██╔════╝ ██╔══██╗██║██╔══██╗██╔════╝██╔══██╗██╔════╝╚══██╔══╝
 ██║  ███╗██████╔╝██║██║  ██║██║     ███████║███████╗   ██║
 ██║   ██║██╔══██╗██║██║  ██║██║     ██╔══██║╚════██║   ██║
 ╚██████╔╝██║  ██║██║██████╔╝╚██████╗██║  ██║███████║   ██║
  ╚═════╝ ╚═╝  ╚═╝╚═╝╚═════╝  ╚═════╝╚═╝  ╚═╝╚══════╝   ╚═╝
```

<div align="center">

### `F1 PROBABILITIES, COMMITTED BEFORE LIGHTS OUT`

*a race outcome model whose predictions are in the git history, so the misses are too*

![models](https://img.shields.io/badge/models-plackett__luce_%2B_monte__carlo-d90429?style=flat-square&labelColor=111111) ![language](https://img.shields.io/badge/language-python_3.12-555555?style=flat-square&labelColor=111111) ![data](https://img.shields.io/badge/data-fastf1-555555?style=flat-square&labelColor=111111) ![timestamps](https://img.shields.io/badge/timestamps-git_history-d90429?style=flat-square&labelColor=111111) ![overtaking model](https://img.shields.io/badge/overtaking_model-0_(for_now)-555555?style=flat-square&labelColor=111111)

</div>

---

## 🏁 What is this

gridcast predicts Formula 1 races. Before each Grand Prix it publishes, for every driver, a full probability distribution over finishing positions: P(win), P(podium), P(points), and the whole 22-way matrix underneath. Each prediction is committed to this repo as JSON before the race starts, which makes the commit history the timestamp proof. There is no editing a forecast after Sunday.

Two models run every weekend and both publish. The **direct model** is Plackett-Luce: every driver gets a strength, a linear function of grid position and season pace history, and the race is drawn position by position with softmax probabilities. The **simulator** runs the race lap by lap a few thousand times: per-driver pace and tyre degradation, a minimum-race-time pit strategy search, safety cars, VSCs and red flags at per-circuit rates, retirements by team, and one track-position term standing in for overtaking. Both are fit on the 2026 season only, because the 2026 regulation change made earlier car data worthless, and both are plain numpy, scipy and pandas.

Scoring is walk-forward ranked probability score against the baseline "you finish where you start". Direct model 0.1340, simulator 0.1220, baseline 0.1655 (Saturday call, rounds 4-12). That sounds undramatic until you notice most published F1 predictors never report a number at all (the ones that do are usually leaking the race result into the features). The live season is the real test: every race from Monza on is out of sample for both.

```console
nick@gridcast:~$ python scripts/predict.py "Italian Grand Prix" thursday
[✓] trained on rounds 1-12. direct: 20,000 race draws. sim: 10,000 simulated races.
[i] wrote predictions/2026-r13-thursday-direct.json and -sim.json. commit both before lights out.
```

## 📊 The pipeline

| | stage | what it actually does |
|---|---|---|
| 01 | **lap cleaning** | drops in-laps, out-laps, the first two racing laps and anything under yellow, then takes each driver's median clean pace per race |
| 02 | **plackett-luce fit** | two weights, learned from finishing orders with scipy. no boosted tree, no library model, nothing to hide behind |
| 03 | **two calls per weekend** | thursday from season-average grid, saturday from the real one. each trained as its own fit so the calibration stays honest |
| 04 | **race simulator** | lap by lap: form draw, degradation fit on 11,000 lap rows, pit plan search over 80,000 candidates, safety cars, red flags, retirements. cars do not interact, on purpose |
| 05 | **walk-forward backtest** | every test race predicted only from races before it, scored with ranked probability score against the grid-order baseline. a replay column runs the strategies teams actually used, to separate strategy error from pace error |
| 06 | **prediction json** | the full P(driver, position) matrix plus headlines and metadata, one file per model, committed before the race. what was never written cannot be scored |
| 07 | **scorecard** | `score.py` scores every prediction with a result and writes json; a static page in `site/` renders it |

## 🚀 Run it

Needs conda and about ten minutes of FastF1 downloads on first run.

```bash
git clone https://github.com/nitrimandylis/gridcast.git
cd gridcast
conda env create -f environment.yml
conda run -n gridcast python scripts/build_data.py
conda run -n gridcast python scripts/build_laps.py
conda run -n gridcast python scripts/build_race_events.py   # 2018 onward, rate limited, rerun hourly
conda run -n gridcast python scripts/build_dnf_history.py
conda run -n gridcast python scripts/backtest.py
```

The backtest prints per-race and mean RPS for the baseline, both direct calls, both sim calls and the replay control. Lower is better, and the baseline is harder to beat than it looks.

## 🔩 Under the hood

| file | path | job |
|---|---|---|
| data gates | `scripts/gates.py` | the three fastf1 checks the plan depends on. run once, before believing anything |
| data build | `scripts/build_data.py` | every completed 2026 race to one cleaned row per driver per race |
| lap table | `scripts/build_laps.py` | every 2026 lap with compound, tyre age and a clean flag, for the degradation fit and strategy replay |
| track history | `scripts/build_race_events.py`, `scripts/build_dnf_history.py` | safety cars, VSCs, red flags and retirements from 2018 on. track properties transfer across the regulation change, car properties do not |
| direct model | `scripts/model.py` | plackett-luce likelihood, fit, and the position-matrix sampler |
| degradation | `scripts/degradation.py` | per-driver per-compound tyre slopes on lap rows, with a progress term so fuel burn does not flatten them |
| hazards | `scripts/hazards.py` | per-circuit SC and VSC rates, one pooled red flag rate, first-lap and per-team retirement hazards |
| simulator | `scripts/sim.py` | pit plan search, the lap loop, events, retirements, the track-position term |
| backtest | `scripts/backtest.py` | walk-forward scoring of everything, including the replay control |
| predict | `scripts/predict.py` | trains both models fresh and writes two prediction files for a named event |
| score | `scripts/score.py` | RPS for every committed prediction with a result, written to `site/` for the page |
| predictions | `predictions/` | the record. two json files per call, committed before each race |

Every script with non-trivial logic carries a self-check under `__main__` (`score.py --check`).

**Stack:** python 3.12 · fastf1 · numpy · scipy · pandas · conda

---

<div align="center">

**[Nick Trimandylis](https://github.com/nitrimandylis)**

`WRONG IN PUBLIC, ON PURPOSE`

</div>
