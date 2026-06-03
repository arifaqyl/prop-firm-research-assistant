# Paper Trading Simulation Report

Run date: 2026-06-01

## Scope

This was a historical paper replay using the current heuristic analyzer, confidence gate, and Yahoo Finance daily candles. It is not broker-grade live paper execution yet. It does include spread/slippage assumptions and stop-first handling when target and stop are both touched in the same candle.

Universe tested:

- AAPL
- MSFT
- NVDA
- TSLA
- AMD
- META
- GOOGL
- AMZN
- GLD
- GOLD
- BTC-USD
- ETH-USD

Main configuration used for the most robust read:

- Range: 5 years
- Interval: 1 day
- Lookback: 80 bars
- Holding horizon: 10 bars
- Max trades cap: removed for full replay

## Main Result

Full universe, 5-year, 10-bar horizon:

| Metric | Result |
|---|---:|
| Trades | 14,919 |
| Wins | 7,194 |
| Losses | 7,725 |
| Win rate | 48.22% |
| Total R | +386.62R |
| Average R/trade | +0.0259R |
| Best symbol | GLD |
| Worst symbol | AMZN |

Important interpretation: the raw win rate is below 50%, but the system is slightly positive because winners are larger than losers in some slices. This does not mean it is ready for live trading.

## Symbol Ranking

5-year, 10-bar horizon:

| Symbol | Trades | Win Rate | Total R | Avg R | Profit Factor | Max DD |
|---|---:|---:|---:|---:|---:|---:|
| GLD | 1,131 | 52.79% | +174.47R | +0.154R | 1.3953 | -42.99R |
| NVDA | 1,153 | 52.73% | +150.54R | +0.131R | 1.3352 | -47.12R |
| MSFT | 1,150 | 51.83% | +116.43R | +0.101R | 1.2649 | -71.28R |
| META | 1,155 | 50.13% | +101.22R | +0.088R | 1.2217 | -84.29R |
| GOLD | 1,139 | 50.57% | +56.23R | +0.049R | 1.1086 | -104.37R |
| GOOGL | 1,144 | 49.74% | +51.53R | +0.045R | 1.1128 | -73.64R |
| AMD | 1,158 | 46.63% | +19.32R | +0.017R | 1.0381 | -88.71R |
| TSLA | 1,159 | 45.99% | -11.85R | -0.010R | 0.9764 | -78.43R |
| AAPL | 1,147 | 47.17% | -14.38R | -0.013R | 0.9723 | -82.98R |
| BTC-USD | 1,726 | 45.13% | -71.47R | -0.041R | 0.9017 | -146.08R |
| ETH-USD | 1,720 | 45.00% | -83.91R | -0.049R | 0.8846 | -134.99R |
| AMZN | 1,137 | 44.15% | -101.50R | -0.089R | 0.8078 | -120.86R |

## What Actually Has Edge

The useful edge is concentrated. The broad system is not strong enough to trade every signal.

| Filter | Trades | Win Rate | Total R | Avg R |
|---|---:|---:|---:|---:|
| All trades | 14,919 | 48.22% | +386.62R | +0.026R |
| BUY only | 9,240 | 51.33% | +827.24R | +0.090R |
| SELL only | 5,679 | 43.16% | -440.62R | -0.078R |
| Trending-up regime only | 2,651 | 54.55% | +465.46R | +0.176R |
| Trending-up + BUY only | 2,622 | 54.88% | +474.17R | +0.181R |
| Exclude crypto | 11,473 | 49.17% | +541.99R | +0.047R |
| Top stable symbols only | 6,872 | 51.30% | +650.41R | +0.095R |
| Top stable symbols + BUY only | 4,673 | 54.93% | +791.42R | +0.169R |
| Top stable symbols + trending-up BUY | 2,158 | 55.10% | +413.23R | +0.191R |

Top stable symbols in this run:

- GLD
- NVDA
- MSFT
- META
- GOLD
- GOOGL

## Regime Finding

5-year, 10-bar horizon:

| Regime | Trades | Approx Win Rate | Total R | Avg R |
|---|---:|---:|---:|---:|
| Trending up | 2,651 | 54.55% | +465.46R | +0.176R |
| High volatility | 11,539 | 47.15% | +22.51R | +0.002R |
| Ranging | 93 | 44.09% | -10.46R | -0.112R |
| Trending down | 636 | 41.82% | -90.89R | -0.143R |

The current analyzer should not be trusted equally across regimes. Trending-up is the only clearly strong regime in this replay.

## Decision

Do not promote this to live trading.

Recommended next paper-trading rule:

- Allow only BUY trades.
- Prefer trending-up regime.
- Exclude crypto until the microstructure/arbitrage system has its own separate validation.
- Treat SELL signals as research-only until a separate short model proves positive expectancy.
- Keep GLD, NVDA, MSFT, META, GOLD, and GOOGL as the first focused paper universe.

## Next Build Changes

1. Add simulator filters to the API and dashboard:
   - direction filter
   - regime filter
   - symbol group filter
   - crypto on/off

2. Add separate scorecards:
   - all trades
   - long-only
   - short-only
   - trending-up only
   - high-volatility only

3. Add walk-forward split reporting:
   - train window
   - validation window
   - out-of-sample window

4. Add equity curve and drawdown chart.

5. Add a rule that the system cannot paper-execute a slice unless its historical expectancy is positive after fees/slippage and its drawdown is inside risk limits.

## Bottom Line

The current analyzer has a small broad edge, but the real signal is narrower:

Long-only, trending-up, selected liquid symbols performed much better than unrestricted trading.

The biggest weakness is short selling. SELL signals were clearly negative in this replay and should be blocked from paper execution until redesigned.
