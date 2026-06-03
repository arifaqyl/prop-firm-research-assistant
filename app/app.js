const fallbackData = {
  runtime: {
    payload_mode: "offline_fallback",
    live_market_data: false,
    refresh_source: "Static fallback embedded in app/app.js",
    why_not_realtime: "The FastAPI server is not reachable, so the page is showing offline demo data."
  },
  symbol: "AAPL",
  asset_type: "stock",
  latest_price: 190,
  primary_horizon: "swing",
  probabilities: { up: 0.68, down: 0.18, neutral: 0.14 },
  data_health: { age_hours: 0, stale: false, warnings: [] },
  subagents: {
    analyst_reports: [
      { role: "market_analyst", stance: "bullish", confidence: "high", score: 4.2, summary: "Technical regime and execution cleanliness support the setup.", evidence: ["regime=trending_up", "atr=3.00", "spread_bps=4.0"] },
      { role: "sentiment_analyst", stance: "neutral", confidence: "medium", score: 2.3, summary: "Market-intel is unavailable in the offline demo, so sentiment stays neutral.", evidence: ["news_status=unavailable"], warnings: ["market-intel snapshot unavailable"] },
      { role: "news_analyst", stance: "neutral", confidence: "medium", score: 2.4, summary: "No recent headline activity is loaded in the offline demo.", evidence: ["latest_headline=none"], warnings: ["no recent headline activity to support the call"] },
      { role: "fundamentals_analyst", stance: "bullish", confidence: "medium", score: 3.4, summary: "No earnings proximity warning; fundamentals do not block the setup.", evidence: ["asset_type=stock", "earnings_proximity=False"] }
    ],
    research_debate: {
      manager: { role: "research_manager", stance: "bullish", confidence: "high", score: 7.1, summary: "Research manager favors the bull case after debate.", evidence: [] }
    },
    trader_proposal: {
      action: "Buy",
      entry_price: 190,
      stop_loss: 184,
      position_sizing: "use risk engine sizing; cap risk per trade before order submission",
      reasoning: "Trader translates research stance bullish into Buy with ATR-based risk levels. Target: 199.00."
    },
    risk_debate: {
      aggressive: { role: "aggressive_risk", stance: "bullish", confidence: "high", score: 4, summary: "Aggressive risk voice supports taking the trade when the analyzer edge exists.", evidence: ["expected_edge=0.0180"] },
      neutral: { role: "neutral_risk", stance: "neutral", confidence: "medium", score: 2, summary: "Neutral risk voice balances model edge against context freshness.", evidence: ["market_intel_warnings=2"], warnings: ["market-intel snapshot unavailable"] },
      conservative: { role: "conservative_risk", stance: "neutral", confidence: "medium", score: 3, summary: "Conservative risk voice looks for reasons to block or reduce the trade.", evidence: ["spread_bps=4.0"] },
      manager: { role: "portfolio_manager", stance: "bullish", confidence: "high", score: 5, summary: "Risk manager allows the proposal to proceed to portfolio gate.", evidence: [] }
    },
    portfolio_decision: {
      rating: "Buy",
      direction_call: "bullish",
      confidence: "high",
      approved_for_execution: true,
      executive_summary: "Portfolio manager approves Buy with risk-engine sizing and audit logging.",
      thesis: "Decision is backed by research stance=bullish, trader action=Buy, and risk stance=bullish.",
      price_target: 199,
      invalidation_level: 184,
      warnings: []
    },
    memory_reflection: "Record this AAPL decision with model=research-v1, prompt=v1."
  },
  paper_order: {
    approved: true,
    stage: "order",
    sizing: { quantity: 83, notional: 15770, risk_dollars: 500, reductions: [] },
    order: { status: "filled", filled_quantity: 83, average_fill_price: 190.038 },
    execution_quality: { realized_slippage_bps: 2, missed_quantity: 0, filled_quantity: 83 }
  },
  portfolio: { equity: 100000, cash: 84226.85, gross_exposure: 15773.15, net_exposure: 15773.15, kill_switch_active: false },
  audit: {
    chain_valid: true,
    event_count: 6,
    events: [
      { event_type: "subagent_analysis_completed", timestamp: "demo", hash: "demo00000001" },
      { event_type: "analyzer_signal_received", timestamp: "demo", hash: "demo00000002" },
      { event_type: "confidence_gate_evaluated", timestamp: "demo", hash: "demo00000003" },
      { event_type: "sizing_decision", timestamp: "demo", hash: "demo00000004" },
      { event_type: "risk_decision", timestamp: "demo", hash: "demo00000005" },
      { event_type: "order_result", timestamp: "demo", hash: "demo00000006" }
    ]
  },
  telegram_preview: "AAPL AI Trading Desk\nRating: Buy | Direction: bullish | Confidence: high\nExecution approved: yes\n\nTrader: Buy @ 190\nStop: 184 | Target: 199\nRisk voice: bullish (high)\n\nSubagents:\n- Market, sentiment, news, fundamentals analysts\n- Bull/bear researchers\n- Trader\n- Aggressive/neutral/conservative risk\n- Portfolio manager",
  source_map: {
    subagents: "src/prop_firm_ai/subagents.py",
    risk: "src/prop_firm_ai/risk.py",
    oms: "src/prop_firm_ai/oms.py",
    dashboard_payload: "src/prop_firm_ai/dashboard.py",
    telegram: "src/prop_firm_ai/telegram.py",
    static_app: "app/index.html"
  }
};

let currentSymbol = "AAPL";
const HISTORY_KEY = "propFirmAiSignalHistoryV1";

function apiBase() {
  if (window.location.protocol === "file:") {
    return "http://127.0.0.1:8010";
  }
  return window.location.origin;
}

async function loadData(symbol = currentSymbol) {
  try {
    const response = await fetch(`${apiBase()}/api/dashboard/live?symbol=${encodeURIComponent(symbol)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("API unavailable");
    const data = await response.json();
    return { data, connection: "api", loadedAt: new Date(), error: null };
  } catch (error) {
    return { data: fallbackData, connection: "offline", loadedAt: new Date(), error };
  }
}

async function loadScan() {
  const symbols = "AAPL,NVDA,BTC-USD,ETH-USD";
  try {
    const response = await fetch(`${apiBase()}/api/scan?symbols=${encodeURIComponent(symbols)}`, { cache: "no-store" });
    if (!response.ok) throw new Error("Scanner unavailable");
    return await response.json();
  } catch (error) {
    return {
      cards: [{
        symbol: fallbackData.symbol,
        latest_price: fallbackData.latest_price,
        trade_call: { action: "BUY", confidence: "high", reason: "Offline fallback demo only.", probability: 0.68 },
        probabilities: fallbackData.probabilities,
        data_health: fallbackData.data_health,
        features: { regime: "demo", atr: 3, spread_bps: 4 }
      }],
      error
    };
  }
}

async function loadSimulation() {
  const symbols = "AAPL,NVDA,BTC-USD,ETH-USD";
  const direction = document.getElementById("simDirection")?.value || "";
  const regime = document.getElementById("simRegime")?.value || "";
  const excludeCrypto = document.getElementById("simExcludeCrypto")?.checked || false;

  const params = new URLSearchParams({
    symbols,
    range_: "5y",
    horizon: "15",
    lookback: "80",
    max_trades: "5000"
  });
  if (direction) params.set("direction", direction);
  if (regime) params.set("regime", regime);
  if (excludeCrypto) params.set("exclude_crypto", "true");

  const response = await fetch(`${apiBase()}/api/paper/simulate?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Simulation unavailable");
  return response.json();
}

function arbitrageParams() {
  const binanceSymbol = document.getElementById("binanceSymbolInput")?.value.trim().toUpperCase() || "BTCUSDT";
  const polymarketToken = document.getElementById("polymarketTokenInput")?.value.trim() || "";
  const params = new URLSearchParams({ binance_symbol: binanceSymbol });
  if (polymarketToken) params.set("polymarket_token_id", polymarketToken);
  return params;
}

async function loadArbitrage() {
  const response = await fetch(`${apiBase()}/api/arbitrage/scan?${arbitrageParams().toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Arbitrage scanner unavailable");
  return response.json();
}

async function loadPolymarketMarkets() {
  const query = document.getElementById("polymarketSearchInput")?.value.trim() || "bitcoin";
  const response = await fetch(`${apiBase()}/api/arbitrage/polymarket-markets?query=${encodeURIComponent(query)}&limit=8`, { cache: "no-store" });
  if (!response.ok) throw new Error("Polymarket market search unavailable");
  return response.json();
}

async function loadWebsocketProbe() {
  const params = arbitrageParams();
  params.set("sample_seconds", "2");
  params.set("max_events", "5");
  const response = await fetch(`${apiBase()}/api/arbitrage/stream-snapshot?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Websocket probe unavailable");
  return response.json();
}

async function loadMicrostructureProbe() {
  const params = arbitrageParams();
  params.set("sample_seconds", "2");
  params.set("max_events", "10");
  const response = await fetch(`${apiBase()}/api/arbitrage/microstructure?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Microstructure probe unavailable");
  return response.json();
}

async function loadCatalystVeto() {
  const query = catalystQueryForSymbol(currentSymbol);
  const response = await fetch(`${apiBase()}/api/news/veto?query=${encodeURIComponent(query)}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Catalyst veto unavailable");
  return response.json();
}

function catalystQueryForSymbol(symbol) {
  const normalized = String(symbol || "").trim().toUpperCase();
  if (normalized.endsWith("-USD")) {
    return `${normalized.replace("-USD", "")} crypto market news catalyst ETF flows regulation exchange inflows`;
  }
  if (normalized.endsWith("=X")) {
    return `${normalized.replace("=X", "")} forex central bank inflation rates macro catalyst`;
  }
  if (normalized === "GC=F" || normalized === "GLD" || normalized === "GOLD") {
    return "gold real yields dollar fed inflation macro catalyst";
  }
  return `${normalized} earnings guidance outlook analyst rating stock catalyst`;
}

async function loadMacroContext() {
  const response = await fetch(`${apiBase()}/api/macro/context`, { cache: "no-store" });
  if (!response.ok) throw new Error("Macro context unavailable");
  return response.json();
}

async function loadOptionsGex() {
  const symbol = document.getElementById("gexSymbolInput")?.value.trim().toUpperCase() || "SPY";
  const expirations = document.getElementById("gexExpiryInput")?.value.trim() || "2";
  const params = new URLSearchParams({ symbol, max_expirations: expirations });
  const response = await fetch(`${apiBase()}/api/macro/options-gex?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Options GEX unavailable");
  return response.json();
}

async function loadSecFilings() {
  const params = new URLSearchParams({
    symbol: currentSymbol,
    forms: "8-K,10-Q,10-K,6-K,20-F",
    limit: "6"
  });
  const response = await fetch(`${apiBase()}/api/fundamentals/sec-filings?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error("SEC filings unavailable");
  return response.json();
}

async function loadOpenSourceStack() {
  const response = await fetch(`${apiBase()}/api/open-source/strategies`, { cache: "no-store" });
  if (!response.ok) throw new Error("Open source strategy stack unavailable");
  return response.json();
}

async function loadHybridGate() {
  const params = arbitrageParams();
  params.set("symbol", currentSymbol);
  params.set("sample_seconds", "1");
  params.set("max_events", "3");
  const response = await fetch(`${apiBase()}/api/hybrid/gate?${params.toString()}`, { cache: "no-store" });
  if (!response.ok) throw new Error("Hybrid gate unavailable");
  return response.json();
}

function pct(value) {
  return `${Math.round((value || 0) * 100)}%`;
}

function money(value) {
  return `$${Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function roleName(role) {
  return String(role || "").split("_").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ");
}

function assetTypeForSymbol(symbol) {
  const normalized = String(symbol || "").trim().toUpperCase();
  if (normalized.endsWith("-USD")) return "crypto";
  if (normalized.endsWith("=X")) return "forex";
  if (["GC=F", "GLD", "GOLD", "SLV"].includes(normalized)) return "gold";
  return "stock";
}

function setText(id, value) {
  document.getElementById(id).textContent = value ?? "n/a";
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#039;"
  }[char]));
}

function compactNumber(value) {
  return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 2, notation: Math.abs(value || 0) > 999999 ? "compact" : "standard" });
}

function readHistory() {
  try {
    return JSON.parse(localStorage.getItem(HISTORY_KEY) || "[]");
  } catch {
    return [];
  }
}

function writeHistory(history) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(history.slice(0, 10)));
}

function rememberSignal(data) {
  const call = data.trade_call || {};
  const history = readHistory();
  const record = {
    at: new Date().toISOString(),
    symbol: data.symbol,
    action: call.action || "NO TRADE",
    confidence: call.confidence || "low",
    price: data.latest_price,
    invalidation: call.invalidation_level || call.stop || null,
    reason: call.reason || "",
    probability: call.probability || 0,
    data_stale: data.data_health?.stale || false
  };
  const recentDuplicate = history[0]
    && history[0].symbol === record.symbol
    && history[0].action === record.action
    && Math.abs(new Date(history[0].at).getTime() - new Date(record.at).getTime()) < 30000;
  if (!recentDuplicate) {
    writeHistory([record, ...history]);
  }
}

function renderHistory() {
  const history = readHistory();
  setText("historyStatus", `${history.length} local calls`);
  document.getElementById("signalHistory").innerHTML = (history.length ? history : [{
    symbol: "None yet",
    action: "WAITING",
    confidence: "n/a",
    price: 0,
    invalidation: null,
    reason: "Run the analyzer to start building local signal history.",
    at: new Date().toISOString()
  }]).map((item) => `
    <li>
      <strong>${escapeHtml(item.symbol)} | ${escapeHtml(item.action)} | ${escapeHtml(item.confidence)}</strong>
      <p>${new Date(item.at).toLocaleString()} | Price ${money(item.price)} | Invalidation ${item.invalidation ? money(item.invalidation) : "n/a"}</p>
      <p>${escapeHtml(item.reason)}</p>
    </li>
  `).join("");
}

function renderRegimeSummary(scan) {
  const summary = scan?.regime_summary;
  if (!summary) {
    setText("regimeHeadline", "No regime scan available");
    setText("actionableCount", "0");
    setText("freshnessCount", "0 / 0");
    return;
  }
  const calls = summary.call_counts || {};
  setText("regimeHeadline", summary.headline);
  setText("actionableCount", `${(calls.BUY || 0) + (calls.SELL || 0)} trades`);
  setText("freshnessCount", `${summary.fresh_symbols} fresh / ${summary.stale_symbols} stale`);
}

function renderScanner(scan) {
  const cards = scan?.cards || [];
  setText("scannerStatus", `${cards.length} markets scanned`);
  document.getElementById("scannerCards").innerHTML = cards.map((card) => {
    const call = card.trade_call || {};
    const action = call.action || "NO TRADE";
    const className = action.toLowerCase().replace(/\s+/g, "-");
    const tier = card.attention_tier || "ignore";
    return `
      <article class="scanner-card ${tier}">
        <header>
          <strong>${escapeHtml(card.symbol)}</strong>
          <span class="call-pill ${className}">${escapeHtml(action)}</span>
        </header>
        <p><strong>${money(card.latest_price)}</strong> | ${escapeHtml(call.confidence || "low")} confidence | rank ${compactNumber(card.rank_score)}</p>
        <p>Up ${pct(card.probabilities?.up)} / Down ${pct(card.probabilities?.down)} / Neutral ${pct(card.probabilities?.neutral)}</p>
        <p class="invalidation-line">Invalidation: ${call.invalidation_level || call.stop ? money(call.invalidation_level || call.stop) : "n/a"}</p>
        <p>Regime: ${escapeHtml(card.features?.regime)} | ATR: ${compactNumber(card.features?.atr)} | Spread: ${compactNumber(card.features?.spread_bps)} bps</p>
        <p>${escapeHtml(call.reason || "No evidence summary available.")}</p>
      </article>
    `;
  }).join("");
}

function renderSimulation(simulation) {
  const portfolio = simulation?.portfolio || {};
  setText("simWinRate", pct(portfolio.win_rate));
  setText("simTrades", compactNumber(portfolio.trades));
  setText("simTotalR", `${compactNumber(portfolio.total_r)}R`);
  setText("simAverageR", `${compactNumber(portfolio.average_r)}R`);
  const warnings = simulation?.warnings || [];
  setText("simWarning", warnings[0] || "Historical paper replay complete.");
  const results = simulation?.results || [];
  document.getElementById("simulationResults").innerHTML = results.map((item) => {
    const positive = (item.total_r || 0) > 0;
    if (item.error) {
      return `<article class="simulation-card negative"><strong>${escapeHtml(item.symbol)}</strong><div><span>Error</span>${escapeHtml(item.error)}</div></article>`;
    }
    return `
      <article class="simulation-card ${positive ? "positive" : "negative"}">
        <strong>${escapeHtml(item.symbol)}</strong>
        <div><span>Win rate</span>${pct(item.win_rate)}</div>
        <div><span>Trades</span>${compactNumber(item.trades)}</div>
        <div><span>Total R</span>${compactNumber(item.total_r)}R</div>
        <div><span>Avg R</span>${compactNumber(item.average_r)}R</div>
        <div><span>Max DD</span>${compactNumber(item.max_drawdown_r)}R</div>
        <div><span>Summary</span>${escapeHtml(item.summary)}</div>
      </article>
    `;
  }).join("");

  // Render walk-forward splits
  const walkForward = portfolio.walk_forward || {};
  const wfBox = document.getElementById("simWalkForward");
  if (wfBox && Object.keys(walkForward).length) {
    wfBox.style.display = "block";
    document.getElementById("simWalkForwardRows").innerHTML = Object.entries(walkForward).map(([phase, card]) => `
      <tr>
        <td style="text-transform: capitalize; font-weight: 600;">${phase.replace("_", " ")}</td>
        <td>${card.trades}</td>
        <td>${card.wins}</td>
        <td>${card.losses}</td>
        <td>${pct(card.win_rate)}</td>
        <td class="${card.total_r >= 0 ? "good" : "bad"}" style="font-weight:600;">${card.total_r >= 0 ? "+" : ""}${card.total_r.toFixed(2)}R</td>
        <td>${card.average_r.toFixed(4)}R</td>
        <td class="${card.max_drawdown_r < 0 ? "bad" : ""}">${card.max_drawdown_r.toFixed(2)}R</td>
      </tr>
    `).join("");
  } else if (wfBox) {
    wfBox.style.display = "none";
  }

  // Render scorecards
  const scorecards = portfolio.scorecards || {};
  const scBox = document.getElementById("simScorecards");
  if (scBox && Object.keys(scorecards).length) {
    scBox.style.display = "block";
    document.getElementById("simScorecardRows").innerHTML = Object.entries(scorecards).map(([segment, card]) => `
      <tr>
        <td style="text-transform: capitalize; font-weight: 600;">${segment.replace("_", " ")}</td>
        <td>${card.trades}</td>
        <td>${card.wins}</td>
        <td>${card.losses}</td>
        <td>${pct(card.win_rate)}</td>
        <td class="${card.total_r >= 0 ? "good" : "bad"}" style="font-weight:600;">${card.total_r >= 0 ? "+" : ""}${card.total_r.toFixed(2)}R</td>
        <td>${card.average_r.toFixed(4)}R</td>
        <td class="${card.max_drawdown_r < 0 ? "bad" : ""}">${card.max_drawdown_r.toFixed(2)}R</td>
      </tr>
    `).join("");
  } else if (scBox) {
    scBox.style.display = "none";
  }

  // Render equity curve SVG
  const equity = portfolio.equity_curve || [];
  const chartBox = document.getElementById("simEquityChart");
  if (chartBox) {
    if (equity.length < 2) {
      chartBox.style.display = "none";
    } else {
      chartBox.style.display = "block";
      const width = 900;
      const height = 220;
      const pad = 36;
      const minEq = Math.min(...equity, 0);
      const maxEq = Math.max(...equity, 1);
      const range = maxEq - minEq || 1;
      const x = (index) => pad + (index / (equity.length - 1)) * (width - pad * 2);
      const y = (val) => pad + ((maxEq - val) / range) * (height - pad * 2 - 40);
      const path = equity.map((val, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(2)},${y(val).toFixed(2)}`).join(" ");
      const color = equity.at(-1) >= 0 ? "var(--green)" : "var(--red)";
      chartBox.innerHTML = `
        <h3 style="margin: 12px 16px 4px; font-size: 14px; color: var(--ink);">Portfolio Cumulative Equity Curve</h3>
        <svg viewBox="0 0 ${width} ${height}" style="display: block; width: 100%; height: 170px;">
          <line x1="${pad}" y1="${y(0)}" x2="${width - pad}" y2="${y(0)}" stroke="rgba(32,35,31,0.2)" stroke-dasharray="4" />
          <path d="${path}" fill="none" stroke="${color}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" />
          <circle cx="${x(equity.length - 1).toFixed(2)}" cy="${y(equity.at(-1)).toFixed(2)}" r="5.5" fill="${color}" />
          <text x="${width - 180}" y="28" fill="var(--ink)" font-size="14" font-weight="bold">Final Equity: ${equity.at(-1).toFixed(2)}R</text>
        </svg>
      `;
    }
  }
}

function renderConfluence(data) {
  const matrix = data.subagents?.confluence_matrix || [];
  const approved = data.subagents?.confluence_approved;
  const hasDirectionalTarget = matrix.some((item) => ["bullish", "bearish"].includes(item.required));
  setText("confluenceStatus", !hasDirectionalTarget ? "waiting for edge" : approved ? "all green" : "veto active");
  const rows = hasDirectionalTarget ? matrix : [{
    role: "market_analyst",
    stance: "no_edge",
    required: "directional_edge",
    approved: false,
    summary: "Confluence is not evaluated until the analyzer produces a bullish or bearish edge.",
  }];
  document.getElementById("confluenceMatrix").innerHTML = rows.map((item) => `
    <article class="confluence-row">
      <strong>${roleName(item.role)}</strong>
      <div>
        <span>${escapeHtml(formatConfluenceState(item.stance, item.required))}</span>
        <p>${escapeHtml(item.summary)}</p>
      </div>
      <i class="confluence-light ${item.approved ? "green" : ""}"></i>
    </article>
  `).join("");
}

function formatConfluenceState(stance, required) {
  if (required === "directional_edge") {
    return "Waiting for a directional edge";
  }
  if (stance === "no_edge" && required === "no_edge") {
    return "No directional edge";
  }
  return `${stance} vs required ${required}`;
}

function renderCatalystVeto(data) {
  setText("catalystVerdict", data?.verdict || "NO_TRADE");
  setText("catalystConfidence", data?.confidence == null ? "n/a" : pct(data.confidence));
  const configuredProvider = data?.configured_llm_provider || "auto";
  const activeProvider = data?.active_llm_provider || data?.llm_provider || null;
  setText("catalystLlm", activeProvider ? `${activeProvider} active` : `${configuredProvider} closed`);
  setText("catalystPrompt", data?.prompt_version || "n/a");
  const sources = data?.sources || [];
  const attempts = Array.isArray(data?.llm_attempts) ? data.llm_attempts : [];
  const attemptsLabel = attempts.length
    ? attempts.map((attempt) => `${attempt.provider}:${attempt.status}`).join(", ")
    : "none";
  document.getElementById("catalystVeto").innerHTML = `
    <article class="spread-row">
      <strong>${escapeHtml(data?.status || "unknown")}</strong>
      <div>
        <span>${escapeHtml(data?.reason || "No catalyst check has run yet.")}</span>
        <p>News: ${escapeHtml(data?.news_provider || "unknown")} | Configured LLM: ${escapeHtml(configuredProvider)} | Active LLM: ${escapeHtml(activeProvider || "none")}</p>
        <p>Keyword fallback: ${escapeHtml(data?.keyword_verdict || "n/a")} | ${escapeHtml(data?.keyword_reason || "n/a")}</p>
        <p>LLM attempts: ${escapeHtml(attemptsLabel)}</p>
      </div>
      <span>${escapeHtml(data?.verdict || "NO_TRADE")}</span>
    </article>
    ${(data?.evidence || []).slice(0, 3).map((item) => `
      <article class="spread-row">
        <strong>Evidence</strong>
        <div><span>${escapeHtml(item)}</span></div>
        <span>LLM</span>
      </article>
    `).join("")}
    ${sources.slice(0, 4).map((source) => `
      <article class="spread-row">
        <strong>Source</strong>
        <div>
          <span>${escapeHtml(source.title || "untitled")}</span>
          <p>${escapeHtml(source.url || "")}</p>
        </div>
        <span>RAG</span>
      </article>
    `).join("")}
  `;
}

function renderMacroContext(data) {
  const signals = data?.signals || {};
  const series = data?.series || {};
  const warnings = data?.warnings || [];
  setText("macroGoldBias", signals.gold_macro_bias || "unknown");
  setText("macroRiskBias", signals.risk_asset_bias || "unknown");
  setText("macroProvider", data?.mode || "unknown");
  setText("macroWarnings", `${warnings.length}`);
  document.getElementById("macroContext").innerHTML = `
    <article class="spread-row">
      <strong>Macro Read</strong>
      <div>
        <span>Gold ${escapeHtml(signals.gold_macro_bias || "unknown")} | Risk ${escapeHtml(signals.risk_asset_bias || "unknown")}</span>
        <p>${escapeHtml((signals.reasons || []).join(" | ") || data?.rule || "No macro reasons available.")}</p>
      </div>
      <span>${escapeHtml(data?.mode || "free")}</span>
    </article>
    ${Object.values(series).map((item) => `
      <article class="spread-row">
        <strong>${escapeHtml(item.series_id)}</strong>
        <div>
          <span>${escapeHtml(item.label)}: ${compactNumber(item.latest_value)} | 1D ${compactNumber(item.day_change)} | 1M ${compactNumber(item.month_change)}</span>
          <p>${escapeHtml(item.latest_date)} | obs ${compactNumber(item.observations)}</p>
        </div>
        <span>FRED</span>
      </article>
    `).join("")}
  `;
}

function renderSecFilings(data) {
  const secPanel = document.getElementById("secFilingsPanel")?.closest(".panel");
  const assetType = assetTypeForSymbol(currentSymbol);
  if (assetType !== "stock") {
    if (secPanel) secPanel.style.display = "none";
    return;
  }
  if (secPanel) secPanel.style.display = "";
  setText("secCompany", data?.company_name || data?.symbol || "n/a");
  setText("secCik", data?.cik || "n/a");
  setText("secEventRisk", data?.filing_signal?.event_risk || "n/a");
  setText("secStatus", data?.status || "unknown");
  const filings = data?.filings || [];
  const warnings = data?.warnings || [];
  document.getElementById("secFilingsPanel").innerHTML = `
    <article class="spread-row">
      <strong>${escapeHtml(data?.status || "unknown")}</strong>
      <div>
        <span>${escapeHtml(data?.filing_signal?.headline || "No filing context yet.")}</span>
        <p>Forms: ${escapeHtml((data?.forms_requested || []).join(", ") || "n/a")}</p>
      </div>
      <span>${filings.length} filings</span>
    </article>
    ${warnings.map((item) => `
      <article class="spread-row">
        <strong>Warning</strong>
        <div><span>${escapeHtml(item)}</span></div>
        <span>SEC</span>
      </article>
    `).join("")}
    ${filings.map((filing) => `
      <article class="spread-row">
        <strong>${escapeHtml(filing.form || "form")}</strong>
        <div>
          <span>${escapeHtml(filing.description || filing.primary_document || "SEC filing")}</span>
          <p>${escapeHtml(filing.filing_date || "unknown date")} | ${escapeHtml(filing.accession_number || "no accession")}</p>
        </div>
        <span>SEC</span>
      </article>
    `).join("")}
  `;
}

function renderOpenSourceStack(data) {
  const repos = data?.repos || [];
  const highPriority = repos.filter((item) => item.priority === "high").length;
  const liveReady = repos.filter((item) => item.status_here === "live_ready").length;
  setText("ossRepoCount", String(repos.length));
  setText("ossHighPriority", String(highPriority));
  setText("ossLiveReady", String(liveReady));
  setText("ossMode", data?.mode || "unknown");
  document.getElementById("openSourcePanel").innerHTML = repos.map((item) => `
    <article class="spread-row">
      <strong>${escapeHtml(item.name)}</strong>
      <div>
        <span>${escapeHtml(item.why_it_matters || "")}</span>
        <p>${escapeHtml(item.fit || "unknown fit")} | ${escapeHtml(item.status_here || "unknown status")} | ${escapeHtml(item.how_to_use_here || "")}</p>
      </div>
      <span><a href="${escapeHtml(item.repo_url)}" target="_blank" rel="noreferrer">Repo</a></span>
    </article>
  `).join("");
}

function renderOptionsGex(data) {
  const warnings = data?.warnings || [];
  setText("gexRegime", data?.gamma_regime || "unknown");
  setText("gexNet", data?.net_gex == null ? "n/a" : compactNumber(data.net_gex));
  setText("gexSpot", data?.spot == null ? "n/a" : money(data.spot));
  setText("gexStatus", data?.status || "unknown");
  document.getElementById("optionsGex").innerHTML = `
    <article class="spread-row">
      <strong>${escapeHtml(data?.symbol || "SPY")}</strong>
      <div>
        <span>${escapeHtml(data?.gamma_regime || "unknown")} | calls ${compactNumber(data?.call_gex)} | puts ${compactNumber(data?.put_gex)}</span>
        <p>Basis ${escapeHtml(data?.exposure_basis || "unknown")} | ${escapeHtml(data?.rule || warnings.join(" | ") || "Approximate options gamma exposure.")}</p>
      </div>
      <span>${escapeHtml(data?.decision || "NO_TRADE")}</span>
    </article>
    ${(data?.expirations || []).map((item) => `
      <article class="spread-row">
        <strong>${escapeHtml(item.expiration)}</strong>
        <div>
          <span>DTE ${compactNumber(item.days_to_expiry)} | net ${compactNumber(item.net_gex)}</span>
          <p>Call GEX ${compactNumber(item.call_gex)} | Put GEX ${compactNumber(item.put_gex)}</p>
        </div>
        <span>Yahoo</span>
      </article>
    `).join("")}
    ${warnings.map((warning) => `
      <article class="spread-row">
        <strong>Warning</strong>
        <div><span>${escapeHtml(warning)}</span></div>
        <span>check</span>
      </article>
    `).join("")}
  `;
}

function renderHybridGate(data) {
  setText("hybridDecision", data?.decision || "NO_TRADE");
  setText("hybridBrain", data?.brain_approved ? "approved" : "blocked");
  setText("hybridOpportunity", data?.opportunity_found ? "found" : "none");
  setText("hybridLive", data?.approved_for_live ? "approved" : "disabled");
  const gates = data?.gates || {};
  const summaryBlockers = data?.brain_approved
    ? (data?.blockers || [])
    : ["Research layer not approved yet.", ...["analyzer", "catalyst", "timeframe", "confluence"].flatMap((name) => gates[name]?.blockers || [])];
  const visibleGateNames = data?.brain_approved
    ? Object.keys(gates)
    : ["analyzer", "catalyst", "timeframe", "confluence"].filter((name) => gates[name]);
  document.getElementById("hybridGate").innerHTML = `
    <article class="spread-row">
      <strong>${escapeHtml(data?.symbol || currentSymbol)}</strong>
      <div>
        <span>${escapeHtml(data?.rule || "All gates must pass before execution.")}</span>
        <p>${escapeHtml(summaryBlockers.slice(0, 4).join(" | ") || "No blockers reported.")}</p>
      </div>
      <span>${escapeHtml(data?.decision || "NO_TRADE")}</span>
    </article>
    ${visibleGateNames.map((name) => {
      const gate = gates[name];
      return `
      <article class="spread-row">
        <strong>${roleName(name)}</strong>
        <div>
          <span>${gate.approved ? "PASS" : gate.status === "skipped" ? "SKIP" : "BLOCK"} | ${escapeHtml(gate.status || gate.decision || "unknown")}</span>
          <p>${escapeHtml((gate.blockers || gate.warnings || []).slice(0, 3).join(" | ") || gate.reason || (gate.status === "skipped" ? "Skipped because no directional edge exists." : "Gate reported no blocker."))}</p>
        </div>
        <span class="${gate.approved ? 'good' : gate.status === 'skipped' ? '' : 'bad'}">${gate.approved ? 'PASS' : gate.status === 'skipped' ? 'SKIP' : 'BLOCK'}</span>
      </article>
    `;
    }).join("")}
    ${data?.brain_approved ? "" : `
      <article class="spread-row">
        <strong>Execution Layer</strong>
        <div>
          <span>Deferred until research passes</span>
          <p>Latency, stat-arb, and live execution checks stay hidden until the analyzer, catalyst, timeframe, and confluence gates approve the setup.</p>
        </div>
        <span>WAIT</span>
      </article>
    `}
  `;
}

function renderArbitrage(data) {
  const latency = data?.latency || {};
  const binance = latency.binance || {};
  const statarb = data?.statarb || {};
  setText("binanceLatency", binance.latency_ms == null ? "n/a" : `${compactNumber(binance.latency_ms)} ms`);
  setText("polyLatency", "off");
  setText("latencyGap", "n/a");
  setText("wsEvents", `0 ws / ${compactNumber(statarb.actionable_count)} pairs`);
  const pairs = statarb.pairs || [];
  document.getElementById("spreadScanner").innerHTML = `
    <article class="spread-row">
      <strong>Binance</strong>
      <div>
        <span>${escapeHtml(binance.symbol)} bid ${money(binance.bid)} / ask ${money(binance.ask)}</span>
        <p>${escapeHtml(binance.source || "source unavailable")} | monitor only for crypto execution quality.</p>
      </div>
      <span>${escapeHtml(latency.decision || "NO_TRADE")}</span>
    </article>
    <article class="spread-row">
      <strong>Pair Watch</strong>
      <div>
        <span>${compactNumber(pairs.length)} tracked spreads | ${compactNumber(statarb.actionable_count)} actionable</span>
        <p>${escapeHtml(statarb.rule || "Watching normalized spreads across selected symbols.")}</p>
      </div>
      <span>watch</span>
    </article>
    ${pairs.map((pair) => `
      <article class="spread-row">
        <strong>${escapeHtml(pair.pair)}</strong>
        <div>
          <span>z=${compactNumber(pair.z_score)} | spread=${compactNumber(pair.spread)} | obs=${compactNumber(pair.observations)}</span>
          <p>${escapeHtml(pair.signal)}${pair.warning ? ` | ${escapeHtml(pair.warning)}` : ""}</p>
        </div>
        <span>${escapeHtml(pair.decision)}</span>
      </article>
    `).join("")}
  `;
}

function renderPolymarketMarkets(data) {
  const markets = data?.markets || [];
  document.getElementById("polymarketMarkets").innerHTML = `
    <article class="spread-row">
      <strong>Polymarket Search</strong>
      <div>
        <span>${escapeHtml(data?.status || "unknown")} | ${markets.length} tokenized markets</span>
        <p>${escapeHtml((data?.warnings || []).join(" | ") || data?.source || "No source available.")}</p>
      </div>
      <span>${escapeHtml(data?.decision || "NO_TRADE")}</span>
    </article>
    ${markets.map((market) => `
      <article class="spread-row">
        <strong>${escapeHtml(market.market_id)}</strong>
        <div>
          <span>${escapeHtml(market.question || market.event_title || "untitled market")}</span>
          <p>YES ${market.best_yes_price ?? "n/a"} | NO ${market.best_no_price ?? "n/a"} | liq ${compactNumber(market.liquidity)} | 24h ${compactNumber(market.volume_24h)}</p>
          <p>YES token: ${escapeHtml(market.yes_token_id || "n/a")}</p>
        </div>
        <button class="use-token" type="button" data-token="${escapeHtml(market.yes_token_id || "")}">Use YES</button>
      </article>
    `).join("")}
  `;
}

function renderWebsocketProbe(data) {
  const events = data?.events || [];
  const candidate = data?.lag_candidate || {};
  setText("wsEvents", `${events.length} ws / ${document.getElementById("wsEvents").textContent.split("/").at(1)?.trim() || "0 arb"}`);
  document.getElementById("websocketScanner").innerHTML = `
    <article class="spread-row">
      <strong>WebSocket Probe</strong>
      <div>
        <span>${escapeHtml(data.status)} | ${events.length} normalized events</span>
        <p>${(data.warnings || []).map(escapeHtml).join(" | ")}</p>
      </div>
      <span>${escapeHtml(data.decision || "NO_TRADE")}</span>
    </article>
    <article class="spread-row">
      <strong>Execution Readiness</strong>
      <div>
        <span>${escapeHtml(candidate.decision || "OBSERVE_ONLY")} | true p ${pct(candidate.true_probability_estimate)}</span>
        <p>Impulse ${candidate.binance_impulse_bps == null ? "n/a" : `${compactNumber(candidate.binance_impulse_bps)} bps`} | ${escapeHtml((candidate.blockers || []).join(" | ") || "observable candidate, still monitor-only")}</p>
      </div>
      <span>${candidate.execution_allowed ? "armed" : "monitor"}</span>
    </article>
    ${(data.streams || []).map((stream) => `
      <article class="spread-row">
        <strong>${escapeHtml(stream.venue)}</strong>
        <div>
          <span>${escapeHtml(stream.symbol)} | ${escapeHtml(stream.status)} | ${compactNumber(stream.duration_ms)} ms</span>
          <p>${escapeHtml(stream.error || stream.source)}</p>
        </div>
        <span>${compactNumber((stream.events || []).length)} events</span>
      </article>
    `).join("")}
    ${events.slice(0, 5).map((event) => `
      <article class="spread-row">
        <strong>${escapeHtml(event.venue)}</strong>
        <div>
          <span>${escapeHtml(event.symbol)} ${escapeHtml(event.event_type)} bid ${event.bid ?? "n/a"} / ask ${event.ask ?? "n/a"}</span>
          <p>${escapeHtml(event.received_at)}${event.depth_imbalance == null ? "" : ` | L2 imbalance ${compactNumber(event.depth_imbalance)} | bid depth ${compactNumber(event.bid_depth_notional)} / ask depth ${compactNumber(event.ask_depth_notional)}`}</p>
        </div>
        <span>${event.spread == null ? "n/a" : compactNumber(event.spread)}</span>
      </article>
    `).join("")}
  `;
}

function renderMicrostructure(data) {
  const analytics = data?.analytics || {};
  const quote = analytics.avellaneda_stoikov || {};
  document.getElementById("microstructurePanel").innerHTML = `
    <article class="spread-row">
      <strong>Microstructure</strong>
      <div>
        <span>${escapeHtml(data?.status || "unknown")} | toxicity ${escapeHtml(analytics.toxicity || "unknown")} | fair p ${pct(analytics.fair_probability)}</span>
        <p>OFI ${compactNumber(analytics.ofi)} | VPIN proxy ${compactNumber(analytics.vpin_proxy)} | logit ${compactNumber(analytics.logit_probability)} | edge ${analytics.microprice_edge_bps == null ? "n/a" : `${compactNumber(analytics.microprice_edge_bps)} bps`}</p>
      </div>
      <span>${escapeHtml(data?.decision || "NO_TRADE")}</span>
    </article>
    <article class="spread-row">
      <strong>Microprice</strong>
      <div>
        <span>micro ${analytics.microprice == null ? "n/a" : money(analytics.microprice)} | mid ${analytics.midpoint == null ? "n/a" : money(analytics.midpoint)}</span>
        <p>${escapeHtml((analytics.blockers || []).join(" | ") || "No toxicity blocker from VPIN proxy.")}</p>
      </div>
      <span>observe</span>
    </article>
    <article class="spread-row">
      <strong>A-S Quote</strong>
      <div>
        <span>bid ${quote.bid_quote == null ? "n/a" : money(quote.bid_quote)} | ask ${quote.ask_quote == null ? "n/a" : money(quote.ask_quote)}</span>
        <p>reservation ${quote.reservation_price == null ? "n/a" : money(quote.reservation_price)} | half-spread ${compactNumber(quote.half_spread)} | ${escapeHtml(quote.rule || "Monitor only.")}</p>
      </div>
      <span>no orders</span>
    </article>
  `;
}

async function refreshArbitrage() {
  setText("binanceLatency", "running");
  setText("polyLatency", "running");
  setText("latencyGap", "running");
  setText("wsEvents", "running");
  try {
    renderArbitrage(await loadArbitrage());
  } catch (error) {
    document.getElementById("spreadScanner").innerHTML = `<article class="spread-row"><strong>Error</strong><div>${escapeHtml(error.message)}</div><span>NO_TRADE</span></article>`;
  }
}

async function searchPolymarketMarkets() {
  document.getElementById("polymarketMarkets").innerHTML = "";
  try {
    renderPolymarketMarkets(await loadPolymarketMarkets());
  } catch (error) {
    renderPolymarketMarkets({ status: "error", decision: "NO_TRADE", warnings: [error.message], markets: [] });
  }
}

async function probeWebsocket() {
  setText("wsEvents", "probing");
  document.getElementById("websocketScanner").innerHTML = "";
  try {
    renderWebsocketProbe(await loadWebsocketProbe());
  } catch (error) {
    document.getElementById("websocketScanner").innerHTML = `<article class="spread-row"><strong>WebSocket Error</strong><div>${escapeHtml(error.message)}</div><span>NO_TRADE</span></article>`;
  }
}

async function refreshCatalyst() {
  setText("catalystVerdict", "checking");
  setText("catalystConfidence", "checking");
  setText("catalystLlm", "checking");
  setText("catalystPrompt", "checking");
  document.getElementById("catalystVeto").innerHTML = "";
  try {
    renderCatalystVeto(await loadCatalystVeto());
  } catch (error) {
    renderCatalystVeto({ status: "error", verdict: "NO_TRADE", reason: error.message, llm_used: false, sources: [] });
  }
}

async function refreshMacroContext() {
  setText("macroGoldBias", "loading");
  setText("macroRiskBias", "loading");
  setText("macroProvider", "loading");
  setText("macroWarnings", "loading");
  document.getElementById("macroContext").innerHTML = "";
  try {
    renderMacroContext(await loadMacroContext());
  } catch (error) {
    renderMacroContext({ mode: "error", signals: {}, series: {}, warnings: [error.message], rule: error.message });
  }
}

async function refreshOptionsGex() {
  setText("gexRegime", "loading");
  setText("gexNet", "loading");
  setText("gexSpot", "loading");
  setText("gexStatus", "loading");
  document.getElementById("optionsGex").innerHTML = "";
  try {
    renderOptionsGex(await loadOptionsGex());
  } catch (error) {
    renderOptionsGex({ symbol: "SPY", status: "error", decision: "NO_TRADE", warnings: [error.message] });
  }
}

async function refreshSecFilings() {
  const secPanel = document.getElementById("secFilingsPanel")?.closest(".panel");
  if (assetTypeForSymbol(currentSymbol) !== "stock") {
    if (secPanel) secPanel.style.display = "none";
    return;
  }
  if (secPanel) secPanel.style.display = "";
  setText("secStatus", "checking");
  document.getElementById("secFilingsPanel").innerHTML = "";
  try {
    renderSecFilings(await loadSecFilings());
  } catch (error) {
    renderSecFilings({ status: "error", symbol: currentSymbol, warnings: [error.message], filings: [], filing_signal: { event_risk: "unknown", headline: error.message } });
  }
}

async function refreshOpenSourceStack() {
  setText("ossMode", "checking");
  document.getElementById("openSourcePanel").innerHTML = "";
  try {
    renderOpenSourceStack(await loadOpenSourceStack());
  } catch (error) {
    renderOpenSourceStack({ mode: "error", repos: [] });
  }
}

async function refreshHybridGate() {
  setText("hybridDecision", "running");
  setText("hybridBrain", "running");
  setText("hybridOpportunity", "running");
  setText("hybridLive", "checking");
  document.getElementById("hybridGate").innerHTML = "";
  try {
    renderHybridGate(await loadHybridGate());
  } catch (error) {
    renderHybridGate({ symbol: currentSymbol, decision: "NO_TRADE", blockers: [error.message], gates: {} });
  }
}

async function probeMicrostructure() {
  document.getElementById("microstructurePanel").innerHTML = "";
  try {
    renderMicrostructure(await loadMicrostructureProbe());
  } catch (error) {
    renderMicrostructure({ status: "error", decision: "NO_TRADE", analytics: { blockers: [error.message] } });
  }
}

async function runSimulation() {
  setText("simWinRate", "running");
  setText("simTrades", "running");
  setText("simTotalR", "running");
  setText("simAverageR", "running");
  setText("simWarning", "Fetching historical candles and replaying gated paper trades...");
  document.getElementById("simulationResults").innerHTML = "";
  try {
    renderSimulation(await loadSimulation());
  } catch (error) {
    setText("simWarning", `Simulation failed: ${error.message}`);
  }
}

function renderChart(data) {
  const chart = data.chart || { candles: [] };
  const candles = chart.candles || [];
  setText("chartMeta", `${chart.provider_symbol || data.symbol} | ${chart.interval || "n/a"} | ${candles.length} candles`);
  const box = document.getElementById("priceChart");
  if (candles.length < 2) {
    box.innerHTML = "<div class=\"empty-chart\">No chart candles available.</div>";
    return;
  }
  const width = 900;
  const height = 330;
  const pad = 28;
  const closes = candles.map((candle) => Number(candle.close));
  const volumes = candles.map((candle) => Number(candle.volume || 0));
  const minPrice = Math.min(...closes);
  const maxPrice = Math.max(...closes);
  const maxVolume = Math.max(...volumes, 1);
  const priceRange = maxPrice - minPrice || 1;
  const x = (index) => pad + (index / (candles.length - 1)) * (width - pad * 2);
  const y = (price) => pad + ((maxPrice - price) / priceRange) * (height - pad * 2 - 55);
  const path = closes.map((close, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(2)},${y(close).toFixed(2)}`).join(" ");
  const color = closes.at(-1) >= closes[0] ? "var(--green)" : "var(--red)";
  const volumeBars = candles.map((candle, index) => {
    const barHeight = Math.max(2, (Number(candle.volume || 0) / maxVolume) * 42);
    return `<rect x="${x(index).toFixed(2)}" y="${height - pad - barHeight}" width="4" height="${barHeight}" fill="rgba(35,120,135,0.28)" />`;
  }).join("");
  box.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(data.symbol)} price chart">
      <line x1="${pad}" y1="${pad}" x2="${pad}" y2="${height - pad}" stroke="rgba(32,35,31,0.22)" />
      <line x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" stroke="rgba(32,35,31,0.22)" />
      ${volumeBars}
      <path d="${path}" fill="none" stroke="${color}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
      <circle cx="${x(candles.length - 1).toFixed(2)}" cy="${y(closes.at(-1)).toFixed(2)}" r="6" fill="${color}" />
      <text x="${pad}" y="20" fill="var(--muted)" font-size="13">${money(maxPrice)}</text>
      <text x="${pad}" y="${height - 54}" fill="var(--muted)" font-size="13">${money(minPrice)}</text>
      <text x="${width - 180}" y="24" fill="var(--ink)" font-size="15">Last ${money(closes.at(-1))}</text>
    </svg>
  `;
}

function renderEvidence(data) {
  const evidence = data.evidence || {};
  const renderList = (id, items) => {
    document.getElementById(id).innerHTML = (items && items.length ? items : ["No evidence in this bucket."]).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  };
  renderList("bullishEvidence", evidence.bullish);
  renderList("bearishEvidence", evidence.bearish);
  renderList("conflictingEvidence", [...(evidence.conflicting || []), ...(evidence.warnings || [])]);
  setText("evidenceStatus", `${(evidence.raw_inputs || []).length} raw inputs`);
}

function renderDataSources(data) {
  const sources = data.data_sources || [];
  setText("sourceStatus", `${sources.length} sources`);
  document.getElementById("dataSources").innerHTML = sources.map((source) => `
    <article class="source-card">
      <strong>${escapeHtml(source.name)} <span class="${source.status === "live" || source.status === "computed" ? "good" : ""}">${escapeHtml(source.status)}</span></strong>
      <p>${escapeHtml(source.source)}</p>
      <p>Provider symbol: <strong>${escapeHtml(source.provider_symbol)}</strong> | Size: <strong>${compactNumber(source.rows)} bars</strong></p>
      <p>Latest: <em>${escapeHtml(source.latest_candle_at)}</em></p>
      <div class="field-tags">
        ${(source.fields || []).map((field) => `<span class="field-tag">${escapeHtml(field)}</span>`).join("")}
      </div>
    </article>
  `).join("");
}

function renderFeatures(data) {
  const features = data.features || {};
  const entries = [
    ["Regime", features.regime],
    ["Sample size", features.sample_size],
    ["Brier skill", features.brier_skill_score],
    ["ATR", features.atr],
    ["Spread bps", features.spread_bps],
    ["Avg daily volume", features.average_daily_volume],
    ["Expected edge", features.expected_edge],
    ["Model", features.model_version],
    ["Prompt", features.prompt_version],
    ["Earnings flag", features.earnings_proximity_flag],
    ["RSI (14)", features.rsi !== undefined && features.rsi !== null ? features.rsi : "n/a"],
    ["MACD Line", features.macd ? features.macd.macd : "n/a"],
    ["MACD Signal", features.macd ? features.macd.signal : "n/a"],
    ["MACD Hist", features.macd ? features.macd.histogram : "n/a"]
  ];
  setText("featureStatus", `${entries.length} fields`);
  document.getElementById("featureGrid").innerHTML = entries.map(([label, value]) => `
    <div><span>${escapeHtml(label)}</span><strong>${escapeHtml(typeof value === "number" ? compactNumber(value) : value)}</strong></div>
  `).join("");
}

function renderPipeline(data) {
  const pipeline = document.getElementById("pipeline");
  const agents = [
    ...data.subagents.analyst_reports,
    data.subagents.research_debate.manager,
    { role: "trader", stance: data.subagents.trader_proposal.action, confidence: "medium", score: 3.8, summary: data.subagents.trader_proposal.reasoning, evidence: [] },
    data.subagents.risk_debate.manager,
    { role: "portfolio_manager", stance: data.subagents.portfolio_decision.direction_call, confidence: data.subagents.portfolio_decision.confidence, score: 4.5, summary: data.subagents.portfolio_decision.executive_summary, evidence: [] }
  ];

  pipeline.innerHTML = agents.map((agent) => `
    <article class="agent">
      <strong>${roleName(agent.role)}</strong>
      <p>${agent.stance} | ${agent.confidence}</p>
      <p>${agent.summary}</p>
      <div class="score"><i style="width:${Math.min(100, (agent.score || 0) * 20)}%"></i></div>
    </article>
  `).join("");
}

function renderRisk(data) {
  const risk = data.subagents.risk_debate;
  const reports = [risk.aggressive, risk.neutral, risk.conservative, risk.manager];
  document.getElementById("riskDebate").innerHTML = reports.map((report) => `
    <article class="report">
      <strong>${roleName(report.role)}: ${report.stance}</strong>
      <p>${report.summary}</p>
      <p>${(report.warnings || []).join(" | ")}</p>
    </article>
  `).join("");
  setText("riskManager", risk.manager.stance);
}

function renderAudit(data) {
  setText("auditCount", `${data.audit.event_count} events`);
  document.getElementById("auditList").innerHTML = data.audit.events.map((event) => `
    <li><strong>${event.event_type}</strong><p>${event.timestamp} | ${event.hash}</p></li>
  `).join("");
}

function renderSourceMap(data) {
  const descriptions = {
    subagents: "Coordinates multi-agent debate pipelines (Research, News, Fundamentals).",
    risk: "Enforces drawdown limits, sector limits, and net/gross exposure controls.",
    oms: "Simulates orders fill quality, calculates slippage, and updates positions.",
    dashboard_payload: "Constructs visual feeds, feature matrix, and telemetry streams.",
    telegram: "Formats daily digests, buy/sell alerts, and risk warnings.",
    market_data: "Computes ADX, Bollinger Bands, Keltner Channels, and RSI oscillators.",
    static_app: "Serves the dark cyber-desk dashboard visualizer frontend."
  };

  document.getElementById("sourceMap").innerHTML = Object.entries(data.source_map).map(([key, path]) => `
    <article class="agent-module-card">
      <div class="module-header">
        <span class="module-title">${roleName(key)}</span>
        <span class="module-badge status-active">Online</span>
      </div>
      <p class="module-desc">${descriptions[key] || "Active module inside the Prop-Firm AI stack."}</p>
      <div class="module-footer">
        <span class="module-path">Source: ${escapeHtml(path)}</span>
      </div>
    </article>
  `).join("");
}

function render(payload) {
  const { data, scan, connection, loadedAt, error } = payload;
  const decision = data.subagents.portfolio_decision;
  const call = data.trade_call || {};
  setText("symbol", data.symbol);
  setText("direction", call.action || decision.direction_call);
  setText("rating", decision.rating);
  setText("execution", decision.approved_for_execution ? "approved" : "blocked");
  setText("invalidation", call.invalidation_level || call.stop ? money(call.invalidation_level || call.stop) : "n/a");
  setText("price", money(data.latest_price));
  setText("horizon", data.primary_horizon);
  setText("chainStatus", data.audit.chain_valid ? "Audit chain valid" : "Audit chain broken");
  setText("killSwitch", data.portfolio.kill_switch_active ? "Kill switch active" : "Kill switch clear");
  setText("dataStatus", data.data_health.stale ? "Data stale" : "Data fresh");
  setText("apiStatus", connection === "api" ? "API connected" : "Offline demo");
  setText("marketMode", data.runtime.live_market_data ? "Live market data" : "Demo market data");

  const freeModeActive = data.runtime.free_mode;
  setText("freeMode", freeModeActive ? "Free Mode: Active" : "Free Mode: Off");

  setText("runtimeText", `${data.runtime.refresh_source}. ${data.runtime.why_not_realtime || ""}`);
  setText("lastRefresh", `Last refresh: ${loadedAt.toLocaleTimeString()}`);

  document.getElementById("chainStatus").className = data.audit.chain_valid ? "good" : "bad";
  document.getElementById("killSwitch").className = data.portfolio.kill_switch_active ? "bad" : "good";
  document.getElementById("dataStatus").className = data.data_health.stale ? "bad" : "good";
  document.getElementById("apiStatus").className = connection === "api" ? "good" : "bad";
  document.getElementById("marketMode").className = data.runtime.live_market_data ? "good" : "bad";
  document.getElementById("freeMode").className = freeModeActive ? "good" : "bad";

  if (error) {
    console.info("Dashboard using offline fallback:", error.message);
  }

  setText("upProb", pct(data.probabilities.up));
  setText("downProb", pct(data.probabilities.down));
  setText("neutralProb", pct(data.probabilities.neutral));
  document.getElementById("upBar").style.width = pct(data.probabilities.up);
  document.getElementById("downBar").style.width = pct(data.probabilities.down);
  document.getElementById("neutralBar").style.width = pct(data.probabilities.neutral);

  setText("orderStatus", data.paper_order.order.status || data.paper_order.stage || "blocked");
  setText("orderQty", data.paper_order.sizing.quantity || 0);
  setText("notional", money(data.paper_order.sizing.notional || 0));
  setText("riskDollars", money(data.paper_order.sizing.risk_dollars || 0));
  setText("slippage", `${data.paper_order.execution_quality.realized_slippage_bps || 0} bps`);

  renderRegimeSummary(scan);
  renderScanner(scan);
  renderChart(data);
  renderEvidence(data);
  renderFeatures(data);
  renderConfluence(data);
}

async function refresh() {
  const [payload, scan] = await Promise.all([loadData(currentSymbol), loadScan()]);
  render({ ...payload, scan });
}

document.getElementById("refreshNow").addEventListener("click", refresh);
document.getElementById("runSimulation").addEventListener("click", runSimulation);
document.getElementById("refreshArbitrage").addEventListener("click", refreshArbitrage);
document.getElementById("probeWebsocket").addEventListener("click", probeWebsocket);
document.getElementById("probeMicrostructure").addEventListener("click", probeMicrostructure);
document.getElementById("refreshCatalyst").addEventListener("click", refreshCatalyst);
document.getElementById("refreshMacro").addEventListener("click", refreshMacroContext);
document.getElementById("refreshGex").addEventListener("click", refreshOptionsGex);
document.getElementById("refreshSecFilings").addEventListener("click", refreshSecFilings);
document.getElementById("refreshHybridGate").addEventListener("click", refreshHybridGate);
document.getElementById("symbolForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  currentSymbol = document.getElementById("symbolInput").value.trim().toUpperCase() || "AAPL";
  await refresh();
  await refreshCatalyst();
  await refreshSecFilings();
  await refreshHybridGate();
});

document.querySelectorAll("[data-symbol]").forEach((button) => {
  button.addEventListener("click", async () => {
    currentSymbol = button.dataset.symbol;
    document.getElementById("symbolInput").value = currentSymbol;
    await refresh();
    await refreshCatalyst();
    await refreshSecFilings();
    await refreshHybridGate();
  });
});

refresh();
refreshArbitrage();
probeMicrostructure();
refreshCatalyst();
refreshMacroContext();
refreshOptionsGex();
refreshSecFilings();
refreshHybridGate();
setInterval(refresh, 15000);
