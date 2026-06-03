# Quant Research Notes - 2026-06-02

## Problem Found

The original backtest path replayed `1d` candles through an intraday heuristic. That made the historical test structurally wrong:

- paper simulation defaulted to daily bars
- the signal model labeled itself `intraday`
- stops/targets and thresholds were not aligned to a daily trend horizon
- forex was mixed into the same book even though it had consistently poor expectancy
- the harness truncated each symbol at `250` trades by default, which biased the sample

## Research Used

Primary references used to guide the fix:

- Tobias J. Moskowitz, Yao Hua Ooi, Lasse Heje Pedersen, *Time Series Momentum*  
  https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf
- Brian Hurst, Yao Hua Ooi, Lasse Heje Pedersen, *A Century of Evidence on Trend-Following Investing*  
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2993026
- Alan Moreira, Tyler Muir, *Volatility Managed Portfolios*  
  https://www.nber.org/papers/w22208  
  PDF: https://www.nber.org/system/files/working_papers/w22208/w22208.pdf
- David H. Bailey, Jonathan Borwein, Marcos Lopez de Prado, Qiji Jim Zhu, *The Probability of Backtest Overfitting*  
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

## Practical Conclusions

- Daily trend/momentum should be modeled as a separate strategy, not as a stretched intraday heuristic.
- Trend and multi-month persistence are valid starting points for stocks and crypto.
- Volatility-aware risk is required. We used ATR-based stops/targets and removed the mixed long/short assumption.
- The backtest must avoid arbitrary truncation and reduce the probability of overfit by preferring simple rules over ad hoc multi-parameter tuning.

## Code Changes

- Added a daily signal path in `src/prop_firm_ai/market_data.py`.
- Kept the existing intraday path for live `5m` snapshots.
- Daily model now:
  - uses SMA 20 / SMA 100 trend filters
  - uses 21-day and 63-day return persistence
  - uses ADX and RSI as confirmation
  - treats forex as research-only / `no_edge`
  - trades the active daily book as long-only
- Backtest defaults now:
  - `range_=5y`
  - `horizon=15`
  - `max_trades=5000`
- Paper simulation defaults moved to active symbols:
  - `AAPL,NVDA,BTC-USD,ETH-USD`

## Baseline vs Current

### Old baseline

Run:

- symbols: `AAPL,NVDA,EURUSD=X,GBPUSD=X,BTC-USD,ETH-USD`
- range: `2y`
- horizon: `5`
- lookback: `80`

Result:

- portfolio: `1473` trades
- win rate: `42.16%`
- total R: `-140.47`
- average R: `-0.0954`

Worst drag:

- `EURUSD=X`: `28.70%`, `-77.73R`
- `GBPUSD=X`: `30.00%`, `-93.48R`

### Current daily trend model

Run:

- symbols: `AAPL,NVDA,BTC-USD,ETH-USD`
- range: `5y`
- horizon: `15`
- lookback: `80`
- max trades: `5000`

Result:

- portfolio: `1386` trades
- win rate: `53.03%`
- total R: `347.44`
- average R: `0.2507`

Per symbol:

- `NVDA`: `347` trades, `60.81%`, `179.61R`
- `AAPL`: `318` trades, `55.35%`, `83.44R`
- `BTC-USD`: `378` trades, `50.26%`, `50.05R`
- `ETH-USD`: `343` trades, `46.06%`, `34.34R`

## Remaining Gaps

- The live dashboard analyzer still uses the intraday `5m` path. The improved win-rate results are from the daily paper model.
- Forex still needs its own dedicated model before it should re-enter the active book.
- The strategy is stronger, but it is still a simple rules engine, not a calibrated production model.
- Walk-forward stability weakens out of sample, so this should stay paper-only until further validation.

## Recommended Next Steps

1. Split the UI between `intraday monitor` and `daily paper strategy` so the user sees which engine is speaking.
2. Add regime-specific sizing instead of flat ATR sizing.
3. Add CPCV / overfit checks before accepting any new parameter sweep.
4. Keep forex out of the active book until a separate macro/FX model exists.
5. Track per-symbol live paper journaling on the four-symbol active book only.
