# Open Source Bot Integration Notes

This project does not import external trading bots directly into live execution.

It uses them in three ways:

1. Strategy reference
- `polyliquid`: market making and liquidity rewards ideas
- `polybot`: ingestion, trader analysis, replication scoring
- `CloddsBot`: cross-venue strategy catalog
- `PolyWeather`: event-specific specialist-agent pattern

2. Architecture reference
- `TradingAgents`: research-brain and debate structure
- `tradingview-mcp`: future read-only indicator/context source
- `sec-edgar-mcp`: future deep-filings source if the free SEC layer becomes too shallow

3. Safety rule
- Nothing from an external repo is treated as trade permission by itself.
- It must pass this system's freshness, calibration, regime, confidence, and risk gates.

Current additions in this repo:
- `GET /api/open-source/strategies`
- `GET /api/fundamentals/sec-filings?symbol=AAPL`

Near-term next steps:
- Add a Polymarket trader-behavior watchlist inspired by `polybot`
- Add a read-only strategy lab for latency, mean reversion, smart-money, and weather/event setups
- Add paper OMS journaling per strategy family before any execution work
