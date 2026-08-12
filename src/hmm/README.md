# HMM Regime Detector & Trend Quality Tools

Standalone advisory tools using Hidden Markov Models (HMMs) — no changes to the existing trading system.

## Prerequisites

All Python dependencies (`hmmlearn`, `scikit-learn`, `yfinance`, `numpy`, `pandas`) are provided by the Nix environment. Enter it:

```bash
cd /path/to/aria-lite
nix develop
```

From there, all commands below assume you're inside the Nix shell.

---

## Quick Reference

| Goal | Command |
|------|---------|
| Train market regime model | `make hmm-train-regime` |
| Predict current regime | `make hmm-predict-regime` |
| Train trend models for portfolio | `make hmm-train-trend-all` |
| Train trend for specific tickers | `make hmm-train-trend TICKERS="NVDA AMD"` |
| Predict trend (single) | `make hmm-predict-trend TICKERS="NVDA"` |
| Predict trend (compare) | `make hmm-predict-trend TICKERS="NVDA AMD MU" COMPARE=1` |
| Predict all portfolio trends | `make hmm-predict-trend-all` |

---

## 1. Market Regime Detection

Detects **Bull / Bear / Sideways** regimes from SPY returns and VIX levels.

### 1.1 Training

```bash
python src/hmm/train_regime.py
```

Trains a 3-state Gaussian HMM on 10 years of SPY + VIX daily data. Saves model parameters to `data/hmm_regime_params.pkl`.

Options:
- `--years 15` — use more/fewer years of training data
- `--states 4` — use more states (default: 3)
- `--save-path data/my_params.pkl` — custom save path

Re-run periodically (every 6–12 months) to keep the model current.

### 1.2 Prediction

```bash
python src/hmm/predict_regime.py
```

Loads the trained model, fetches the last 60 trading days of SPY + VIX, and prints:

```
  Current State:  BULL (82% confidence)
  State persistence:  91% chance same state tomorrow
  Portfolio guidance:  Full capital deployment, momentum strategies favored
```

Options:
- `--lookback 30` — use fewer/more recent days (default: 60)
- `--params-path data/custom_params.pkl` — custom model path

### 1.3 Regime Change Response (manual)

| Transition | Action |
|---|---|
| **BULL → BEAR** | Reduce position sizes, raise cash, tighten stops |
| **BULL → SIDEWAYS** | Shorten hold periods, take profits faster |
| **SIDEWAYS → BULL** | Increase deployment, widen stops, let winners run |
| **BEAR → SIDEWAYS** | Start re-deploying cautiously, look for breakouts |

---

## 2. Per-Ticker Trend Quality

Assesses trend quality for individual stocks using per-ticker 3-state HMMs.

### 2.1 Training

Train models for specific tickers:

```bash
python src/hmm/train_trend.py NVDA AMD MU
```

Train models for all portfolio tickers:

```bash
python src/hmm/train_trend.py --all
```

Each ticker produces a model file at `data/hmm_trend_params/<TICKER>.pkl`.

Options:
- `--years 3` — fewer years of training data (default: 5)
- `--save-dir data/custom_dir` — custom output directory

Re-run quarterly, or when a ticker's behavior changes structurally.

### 2.2 Prediction

Single ticker report:

```bash
python src/hmm/predict_trend.py NVDA
```

Output:
```
  Ticker:  NVDA
  State:   STRONG_UPTREND (94% confidence)
  Trend age:         63 trading days
  Persistence:       96% chance same state tomorrow
  Quality grade:     A (score: 3.72)
```

Compare multiple tickers in a table:

```bash
python src/hmm/predict_trend.py NVDA AMD MU --compare
```

All portfolio tickers:

```bash
python src/hmm/predict_trend.py --all
```

### 2.3 Quality Grade

| Grade | Score Range | Meaning |
|-------|-------------|---------|
| A | 3.5–4.0 | Strong, persistent trend |
| B | 2.5–3.5 | Good quality trend |
| C | 1.5–2.5 | Moderate/weakening trend |
| D | 0.5–1.5 | Weak trend |
| F | < 0.5 | No clear trend |

**Formula components:** Confidence (30%) + Persistence (30%) + Volatility tightness (20%) + Trend age (20%).

---

## 3. Complete Workflow

### Daily Routine

```bash
nix develop

# 1. Check market regime
python src/hmm/predict_regime.py
# → "BULL 82%" → proceed with full deployment

# 2. Check which stocks have clean trends
python src/hmm/predict_trend.py --all --compare
# → Focus on A/B grades, skip C/D/F

# 3. Run existing system
make ratings
```

### Monthly / Quarterly Maintenance

```bash
# Retrain trend models
python src/hmm/train_trend.py --all

# Retrain regime model (every 6-12 months)
python src/hmm/train_regime.py
```

---

## 4. File Layout

```
src/hmm/
├── __init__.py            # Package init
├── portfolio.py           # Shared CURRENT_PORTFOLIO ticker list
├── train_regime.py        # Market regime HMM training
├── predict_regime.py      # Market regime HMM prediction
├── train_trend.py         # Per-ticker trend HMM training
├── predict_trend.py       # Per-ticker trend HMM prediction
└── README.md              # This file

data/
├── hmm_regime_params.pkl  # Trained regime model (created by train_regime.py)
└── hmm_trend_params/      # Per-ticker trend models (created by train_trend.py)
    ├── NVDA.pkl
    ├── AMD.pkl
    └── ...

tests/
├── test_hmm_regime_train.py
├── test_hmm_regime_predict.py
├── test_hmm_trend_train.py
└── test_hmm_trend_predict.py
```

---

## 5. Running Tests

```bash
# From within nix develop
python -m pytest tests/test_hmm_*.py -v
```

> **Note:** `pytest` is not included in the Nix devShell by default. Install it temporarily with:
> ```bash
> nix shell nixpkgs#python312Packages.pytest -c python -m pytest tests/test_hmm_*.py -v
> ```
> Or add it to the `buildInputs` in `flake.nix`.