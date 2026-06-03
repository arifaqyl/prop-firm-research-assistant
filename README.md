# Prop Firm AI Trading System

This is a safety-first implementation scaffold for the v4 plan:

- Research analyzer confidence gates
- Paper order management system
- Position sizing
- Portfolio risk controls
- Kill switch
- Execution quality tracking
- Immutable audit chain
- FastAPI endpoints for paper orders, risk, portfolio, execution quality, and audit
- AI-Trader-inspired signal publishing, signal quality scoring, market-intel snapshots, and heartbeat polling
- TradingAgents-inspired specialist subagent pipeline: analysts, bull/bear researchers, trader, risk debate, and portfolio manager
- Yahoo Finance chart adapter for symbol-driven live candle analysis
- Static visual dashboard and Telegram-style summary preview

Live trading is disabled by default. The current implementation is meant for analyzer validation and paper execution.

This public repository is sanitized for open-source sharing:

- no API keys or local secrets are committed
- no private deployment scripts are included in version control
- local/runtime paths in the docs are examples, not required exact paths

## Visual App

Run the API, then open:

```text
http://127.0.0.1:8000/app/
```

You can still open the static file directly for offline viewing:

```text
app/index.html
```

The dashboard visualizes:

- Main AI desk decision
- Buy/sell/no-trade scanner across a default watchlist
- Heat-ranked watchlist with actionable/watch/ignore tiers
- Market-regime summary banner across the scanned symbols
- Prominent invalidation level beside the trade call
- Local signal history for the last 10 calls viewed in the browser
- Live OHLCV price chart from the active data provider
- Data-source audit showing which provider, symbol, rows, timestamps, and fields were used
- Computed features including regime, ATR, spread, expected edge, sample size, model version, and prompt version
- Evidence board split into bullish, bearish, conflicting, warnings, and raw inputs
- Up/down/neutral probabilities
- Subagent pipeline
- Risk debate
- Paper order and execution quality
- Paper trading simulation over historical Yahoo candles with win rate, total R, average R, max drawdown, and symbol ranking
- AI confluence matrix where Market, News, and Fundamentals must all agree or execution becomes `NO TRADE`
- Multi-timeframe macro gate for 1D, 1H, and 1m alignment
- Monitor-only arbitrage scanner for Binance top-of-book, Binance L2 depth websockets, optional Polymarket CLOB token orderbook, lag-candidate scoring, and pair-spread stat-arb z-scores
- Audit trail
- Telegram preview
- Source map showing where the subagents live

## Claude Review Incorporated

The latest UI pass incorporated the highest-impact review items:

- Scanner cards are ranked by signal strength minus uncertainty, stale-data penalty, spread penalty, and calibration bonus.
- The top banner summarizes dominant regime, actionable calls, no-trade calls, and fresh/stale data counts.
- Invalidation level is visible next to the direction call and inside every scanner card.
- The subagent pipeline is collapsed behind a reasoning toggle so the trading decision stays front and center.
- A local signal-history panel records the last 10 viewed calls for fast trust/debug checks.

Still not built from the review:

- LightGBM supervised model, walk-forward validation, real Brier skill, and calibration curves.
- Alpha Vantage news velocity, earnings calendar, and broker-grade liquidity feeds.
- True signal outcome resolution and persistent signal-history database.
- Broker-grade Polygon/Databento quotes/trades and micro-live execution.

## Hybrid Alpha Lab

The app now includes a safer monitor-only version of the requested hybrid architecture:

- `macro.py`: pulls 1D, 1H, and 1m market snapshots and hard-blocks micro-trades unless all three point the same way.
- `macro.py`: pulls no-key FRED CSV macro context for 10Y real yield, 10Y treasury yield, effective fed funds, VIX, and broad dollar index.
- `macro.py`: pulls no-key Yahoo options chains and estimates approximate gamma exposure (GEX) by expiration.
- `macro.py`: includes an optional Tavily + Claude 3.5 Haiku RAG veto, plus a free-mode fallback using no-key Google News RSS and optional local Ollama.
- `macro.py`: stores a catalyst `prompt_version`, model name, sources, evidence, risks, keyword fallback, and LLM status with every veto response.
- Free-mode rule: if no Claude or local Ollama classifier is configured, the dashboard can show fetched news context, but the catalyst gate remains `NO_TRADE`.
- `subagents.py`: Market, News, and Fundamentals now have confluence veto power; all three must match the required direction.
- `micro.py`: reads Binance top-of-book via public REST and Binance L2 depth via `@depth5@100ms` websocket probes.
- `micro.py`: reads Polymarket CLOB orderbook only when a `token_id` is supplied; otherwise it stays in token-required monitor mode.
- `micro.py`: discovers active Polymarket markets and YES/NO CLOB token IDs through the no-key Gamma API.
- `micro.py`: includes an asyncio websocket probe that collects live Binance L2 depth events and can subscribe to Polymarket's market channel with `assets_ids`.
- `micro.py`: computes monitor-only microstructure analytics: microprice, OFI, VPIN-style toxicity proxy, logit probability, and Avellaneda-Stoikov quote guidance.
- `micro.py`: scores monitor-only lag candidates from Binance impulse versus Polymarket YES ask, but always returns `execution_allowed: false`.
- `statarb.py`: monitors GLD/GOLD and BTC/ETH normalized spread z-scores and flags pair-trade watch above +/-2 standard deviations.
- `hybrid_gate.py`: fuses analyzer confidence, catalyst veto, multi-timeframe alignment, subagent confluence, lag-sniper status, and stat-arb status into one auditable decision.
- The dashboard shows a Hybrid Execution Gate, AI Confluence Matrix, Catalyst RAG Veto, Free Macro Context, Options GEX, Polymarket market discovery, Live Spread Scanner, microstructure analytics, Binance/Polymarket inputs, L2 imbalance, lag-candidate status, and a Probe Websockets button.

No arbitrage endpoint places orders. Everything in this section is observation/paper mode until authenticated broker/CLOB execution, compliance checks, and live risk controls are explicitly added.

If the FastAPI server is running, the dashboard reads `GET /api/dashboard/live?symbol=AAPL`. If not, it uses an offline demo payload.

Important: this is provider-backed live analysis, not broker-grade execution data. The current adapter uses Yahoo Finance 5-minute chart candles and a deterministic heuristic model. For production prop execution, replace or supplement this with Polygon.io/Databento trades and quotes, broker account state, authenticated risk config, and audited live-order approvals.

The dashboard now shows this explicitly:

- `API connected` vs `Offline demo`
- `Live market data` vs `Demo market data`
- Last refresh time

## What Was Adapted From HKUDS/AI-Trader

The scaffold borrows architectural ideas from `HKUDS/AI-Trader` without copying its platform model directly:

- Signal types: strategy, operation, and discussion-style feed shapes
- Signal quality scoring: verifiability, evidence, specificity, novelty, and risk completeness
- Heartbeat as the primary notification path instead of relying only on WebSockets
- Read-only market-intel snapshots as context before publishing or trading
- Agent-friendly API surfaces that can publish strategy analysis or realtime paper operations

## What Was Adapted From TauricResearch/TradingAgents

TradingAgents contributes the specialist-team pattern:

- Analyst team: market, sentiment, news, and fundamentals reports
- Research debate: bull researcher vs bear researcher with a research-manager decision
- Trader proposal: action, entry, stop, and sizing guidance
- Risk debate: aggressive, neutral, and conservative risk voices
- Portfolio manager: final rating, execution approval, invalidation, and memory reflection

The local implementation is deterministic today, which keeps tests stable. The shape is ready for LLM-backed subagents later.

This project keeps stricter prop-style controls: confidence gates, risk gates, audit logging, kill switch behavior, and live trading disabled by default.

## Run Local On Your PC

Recommended local path:

```powershell
winget install Ollama.Ollama
ollama pull qwen2.5:7b
ollama serve
```

Then start the app:

```powershell
cd prop-firm-ai
.\run-local.ps1
```

The included script is configured for a Windows local-first setup. If you prefer different runtime paths, edit `run-local.ps1`.

Local app URL:

```text
http://127.0.0.1:8000/app/
```

The repo is now configured for local-first catalyst classification:

- `.env.example` defaults to `CATALYST_LLM_PROVIDER=ollama`
- default local model is `qwen2.5:7b`
- the public droplet should be treated as monitor/demo infrastructure, not your primary local-AI runtime

## Manual Run

```powershell
cd prop-firm-ai
python -m venv .venv
.\.venv\Scripts\pip install -e .[dev]
.\.venv\Scripts\uvicorn prop_firm_ai.main:app --reload
```

Optional provider config:

- Copy `.env.example` to `.env`.
- Fill only the keys you want to use.
- The app loads `.env` automatically on startup.
- `CATALYST_LLM_PROVIDER` controls the catalyst classifier path: `none`, `auto`, `anthropic`, `gemini`, `openrouter`, or `ollama`.
- Set `CATALYST_LLM_PROVIDER=ollama` for local PC mode.
- Set `CATALYST_LLM_PROVIDER=none` if you want research mode without any LLM veto.
- Use `TARGET_MARKETS=stocks,forex,crypto` to document the current runtime focus.

Useful local endpoints:

- `GET /api/dashboard/live?symbol=BTC-USD`
- `GET /api/analyze/NVDA`
- `GET /api/telegram/preview?symbol=GLD`
- `GET /api/paper/simulate?symbols=AAPL,NVDA,BTC-USD,ETH-USD&range_=5y&horizon=15&lookback=80&max_trades=5000`
- `GET /api/paper/simulate/BTC-USD?range_=5y&horizon=15&lookback=80&max_trades=5000`
- `GET /api/macro/timeframes?symbol=BTC-USD`
- `GET /api/macro/context`
- `GET /api/macro/options-gex?symbol=SPY&max_expirations=2`
- `GET /api/arbitrage/scan?binance_symbol=BTCUSDT`
- `GET /api/arbitrage/polymarket-markets?query=bitcoin&limit=8`
- `GET /api/arbitrage/microstructure?binance_symbol=BTCUSDT&sample_seconds=2&max_events=10`
- `GET /api/arbitrage/stream-snapshot?binance_symbol=BTCUSDT&sample_seconds=2&max_events=5`
- `GET /api/arbitrage/stream-snapshot?binance_symbol=BTCUSDT&polymarket_token_id=...&sample_seconds=2&max_events=5`
- `GET /api/statarb/scan?left=GLD&right=GOLD`

## Test

The core engine tests use the standard library so they can run before dev dependencies are installed:

```powershell
cd prop-firm-ai
$env:PYTHONPATH='src'
python -m unittest discover -s tests
```

## Safety Defaults

- Live orders are blocked unless `live_trading_enabled` is explicitly true.
- Stale data forces `no_edge`.
- Weak calibration or low sample size blocks trading.
- Risk controls override model confidence.
- Kill switch cancels open orders and blocks new orders.
- Every accepted or rejected trade path can be audit logged.

## AI-Trader-Inspired Endpoints

- `POST /api/signals/strategy`
- `POST /api/signals/realtime`
- `GET /api/signals/feed`
- `GET /api/signals/{signal_id}/quality`
- `POST /api/heartbeat`
- `GET /api/market-intel/overview`
- `POST /api/subagents/analyze`
- `GET /api/dashboard/demo`
- `GET /api/dashboard/live?symbol=AAPL`
- `GET /api/analyze/{symbol}`
- `GET /api/paper/simulate`
- `GET /api/paper/simulate/{symbol}`
- `GET /api/macro/timeframes`
- `GET /api/news/veto`
- `GET /api/open-source/strategies`
- `GET /api/fundamentals/sec-filings?symbol=AAPL`
- `GET /api/hybrid/gate?symbol=BTC-USD&binance_symbol=BTCUSDT&sample_seconds=1&max_events=3`
- `GET /api/arbitrage/scan`
- `GET /api/arbitrage/stream-snapshot`
- `GET /api/statarb/scan`
- `GET /api/telegram/preview`
