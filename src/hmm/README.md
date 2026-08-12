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
  Regime:  BULL (92% confidence)
  Probabilities:  BULL 92%  |  SIDEWAYS 7%  |  BEAR 1%

  Forecast:
     30d:  BULL 85%  |  SIDEWAYS 12%  |  BEAR 3%
     60d:  BULL 72%  |  SIDEWAYS 20%  |  BEAR 8%
     90d:  BULL 61%  |  SIDEWAYS 27%  |  BEAR 12%

  Persistence:  97% chance same state tomorrow
  Expected duration in current regime:  ~87 trading days

  Portfolio guidance:
    → Full capital deployment
    → Momentum strategies favored
```

The forecast is computed from the HMM transition matrix: current state probabilities × A^N. This is a genuine model-based forecast of regime persistence, not a price prediction.

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

Assesses trend quality for individual stocks using a **4-state HMM trained on multi-horizon returns** (21, 63, and 252 trading days). These are the same windows from the academic trend-following literature (Moskowitz, Ooi & Pedersen 2012; Hurst, Ooi & Pedersen 2017).

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
  State:   STRONG_UPTREND (96% confidence)

  Returns:
    1-month:   +5.3%
    3-month:   +22.1%
    12-month:  +45.2%

  Forecast:
     30d:  STRONG_UPTREND 93%  |  WEAK_UPTREND 5%  |  SIDEWAYS 2%
     60d:  STRONG_UPTREND 87%  |  WEAK_UPTREND 9%  |  SIDEWAYS 4%
     90d:  STRONG_UPTREND 81%  |  WEAK_UPTREND 12%  |  SIDEWAYS 6%

  Quality grade:  A (score: 0.88)
```

The forecast is computed from the HMM transition matrix — it shows the probability of staying in each state over time.

Compare multiple tickers in a table:

```bash
python src/hmm/predict_trend.py NVDA AMD MU --compare
```

Output:
```
Ticker  State             Conf   R_21%   R_63%  R_252%  Grade
NVDA    STRONG_UPTREND    96%   +5.3   +22.1   +45.2      A
AMD     WEAK_UPTREND      72%   +1.2   +8.4    +18.7      B
MU      SIDEWAYS          81%   -0.8   +3.2    +12.1      C
```

All portfolio tickers:

```bash
python src/hmm/predict_trend.py --all
```

### 2.3 Quality Grade

| Grade | Score Range | Meaning |
|-------|-------------|---------|
| A | 0.75–1.00 | Strong, persistent uptrend |
| B | 0.55–0.75 | Good quality uptrend |
| C | 0.35–0.55 | Moderate/weakening trend |
| D | 0.15–0.35 | Weak/no clear trend |
| F | < 0.15 | Downtrend or no trend |

**Formula:** State score (40%) × Confidence (30%) + 60-day Forecast probability (30%)

State scores: STRONG_UPTREND = 1.0, WEAK_UPTREND = 0.66, SIDEWAYS = 0.33, DOWNTREND = 0.0

---

## 3. Complete Workflow

### Daily Routine

```bash
nix develop

# 1. Check market regime + forecast
python src/hmm/predict_regime.py
# → "BULL 92%, 85% chance continues for 60 days"
# → Proceed with full TSMOM deployment

# 2. Check which stocks have clean trends
python src/hmm/predict_trend.py --all --compare
# → Focus on A/B grades, skip D/F

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

All tests should pass. If `pytest` is not available, ensure it's added to `buildInputs` in `flake.nix`.