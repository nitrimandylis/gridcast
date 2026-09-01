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

![model](https://img.shields.io/badge/model-plackett__luce-d90429?style=flat-square&labelColor=111111) ![language](https://img.shields.io/badge/language-python_3.12-555555?style=flat-square&labelColor=111111) ![data](https://img.shields.io/badge/data-fastf1-555555?style=flat-square&labelColor=111111) ![timestamps](https://img.shields.io/badge/timestamps-git_history-d90429?style=flat-square&labelColor=111111) ![overtaking model](https://img.shields.io/badge/overtaking_model-0_(for_now)-555555?style=flat-square&labelColor=111111)

</div>

---

## 🏁 What is this

gridcast predicts Formula 1 races. Before each Grand Prix it publishes, for every driver, a full probability distribution over finishing positions: P(win), P(podium), P(points), and the whole 22-way matrix underneath. Each prediction is committed to this repo as JSON before the race starts, which makes the commit history the timestamp proof. There is no editing a forecast after Sunday.

The model is Plackett-Luce: every driver gets a strength, a linear function of grid position and season pace history, and the race is drawn position by position with softmax probabilities. It is fit by maximum likelihood on the 2026 season only, because the 2026 regulation change made earlier car data worthless. The whole thing is plain numpy and scipy, small enough to read in one sitting.

Scoring is walk-forward ranked probability score against the baseline "you finish where you start". The current model beats it, 0.1340 to 0.1655, which sounds undramatic until you notice most published F1 predictors never report a number at all (the ones that do are usually leaking the race result into the features).

```console
nick@gridcast:~$ python scripts/predict.py "Italian Grand Prix" thursday
[✓] trained on rounds 1-12. sampled 20,000 race outcomes.
[i] wrote predictions/2026-r13-thursday.json. commit before lights out.
```

## 📊 The pipeline

| | stage | what it actually does |
|---|---|---|
| 01 | **lap cleaning** | drops in-laps, out-laps, the first two racing laps and anything under yellow, then takes each driver's median clean pace per race |
| 02 | **plackett-luce fit** | two weights, learned from finishing orders with scipy. no boosted tree, no library model, nothing to hide behind |
| 03 | **two calls per weekend** | thursday from season-average grid, saturday from the real one. each trained as its own fit so the calibration stays honest |
| 04 | **walk-forward backtest** | every test race predicted only from races before it, scored with ranked probability score against the grid-order baseline |
| 05 | **prediction json** | the full P(driver, position) matrix plus headlines and metadata, committed before the race. what was never written cannot be scored |

## 🚀 Run it

Needs conda and about ten minutes of FastF1 downloads on first run.

```bash
git clone https://github.com/nitrimandylis/gridcast.git
cd gridcast
conda env create -f environment.yml
conda run -n gridcast python scripts/build_data.py
conda run -n gridcast python scripts/backtest.py
```

The backtest prints per-race and mean RPS for the baseline and both calls. Lower is better, and the baseline is harder to beat than it looks.

## 🔩 Under the hood

| file | path | job |
|---|---|---|
| data gates | `scripts/gates.py` | the three fastf1 checks the plan depends on. run once, before believing anything |
| data build | `scripts/build_data.py` | every completed 2026 race to one cleaned row per driver per race |
| model | `scripts/model.py` | plackett-luce likelihood, fit, and the position-matrix sampler. self-check under `__main__` |
| backtest | `scripts/backtest.py` | walk-forward scoring, the number phase 2 has to beat |
| predict | `scripts/predict.py` | trains fresh on everything and writes the prediction json for a named event |
| predictions | `predictions/` | the record. one json per call, committed before each race |

**Stack:** python 3.12 · fastf1 · numpy · scipy · conda

---

<div align="center">

**[Nick Trimandylis](https://github.com/nitrimandylis)**

`WRONG IN PUBLIC, ON PURPOSE`

</div>
