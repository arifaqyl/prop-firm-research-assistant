# Free/API-Light Open-Source Trading Stack Research

Run date: 2026-06-01

## Short Verdict

The Twitter list is useful, but none of these tools make live trading truly "free." The code can be free. Public market data can be free. Local LLMs can be free. But live execution still needs broker/exchange credentials, and many high-quality data feeds eventually cost money.

For this project, the best direction is not to replace our app with one repo. The best direction is to borrow patterns:

- AutoHedge: director -> quant -> risk -> execution pipeline.
- Vibe-Trading: many finance skills, swarm presets, local-first workflows, MCP-style tools.
- Fincept Terminal: broad free terminal/research surface.
- TradingAgents: structured analyst/researcher/trader/risk debate.

## What To Use From Each

| Repo | Usefulness For Us | Free/API Notes | What To Borrow |
|---|---|---|---|
| AutoHedge | Medium | Open source, but live Solana trading needs wallet/private keys and Jupiter setup. Optional OpenAI/Anthropic keys. | Clean 4-stage pipeline: Director, Quant, Risk, Execution. |
| Vibe-Trading | High | Repo says core research tools can work with zero API keys for HK/US/crypto, but swarms need an LLM key unless using a local model. | Finance skills, alpha zoo, swarm presets, MCP-style tool interface, security boundaries. |
| Fincept Terminal | Medium/High | Good for local research terminal. Some connectors are free; premium feeds still optional. | Terminal-style research UX and broad connector idea. |
| TradingAgents | High | Already close to our subagent design. LLM cost depends on provider; can be adapted to local models. | Analyst/researcher/trader/risk debate structure. |

## Best Free Stack For Our App

Data:

- Yahoo Finance chart endpoint: no key, already used, but unofficial and not broker-grade.
- Binance public REST/WebSocket: no key for public market data; already used for L2 depth.
- Polymarket public CLOB book/market stream: no key for public books; trading requires wallet/auth and legal/geographic compliance.
- Google News RSS: no key, now added as fallback for catalyst RAG.
- SEC EDGAR: no key with proper user-agent; useful for fundamentals.
- FRED: free key if we want official macro.
- Stooq: no-key historical daily data fallback for equities/indices.

LLM:

- Free/local: Ollama with Qwen/Llama/Mistral-style models.
- Paid/hosted optional: Claude/OpenAI only when keys are configured.

Execution:

- Keep paper-only until validated.
- Use broker/exchange keys only after paper execution proves stable.
- Live mode must stay disabled unless risk config, audit logging, reconciliation, and kill switch are active.

## Changes Already Made From This Research

- The catalyst veto no longer depends only on Tavily.
- If no Tavily key exists, it can fetch no-key Google News RSS.
- If no Claude key exists, it can use local Ollama when `OLLAMA_BASE_URL` is configured.
- If no LLM is configured, it shows keyword/news context but keeps the gate closed with `NO_TRADE`.

## Recommended Next Build

1. Add a `FREE_MODE=true` config flag in the UI and API health output.
2. Add SEC EDGAR no-key company filings for fundamentals agent evidence.
3. Add Stooq as a backup daily data provider when Yahoo fails.
4. Add Ollama health check endpoint so the dashboard can show whether the local catalyst classifier is available.
5. Add a local-model prompt regression test pack so small models do not silently drift.

## Bottom Line

The best no-paid-API version is:

- Public market data.
- Public news RSS.
- Local Ollama classifier.
- Paper execution.
- Hard risk gates.

That is not as powerful as paid institutional feeds, but it is the right free-first foundation.
