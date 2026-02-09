import re
import os
import json
import time
from flask import current_app
from app.utils.quant_math import calculate_indicators
from datetime import datetime
from app.services.technical_strategy import TechnicalStrategy
from app.services.model_adapters import get_adapter
from app.services.model_config import get_model_config


# ============================================================
# Shared Constants for Agent Prompts
# ============================================================

# ============================================================
# Unified Investment Philosophy (shared across all prompts)
# ============================================================
INVESTMENT_PHILOSOPHY = """
**INVESTMENT PHILOSOPHY — Catalyst-Driven Trend Following with Macro Timing**

You pursue **high win-rate AND high reward-to-risk** trades by requiring triple confirmation before entry:

1. **Catalyst (WHY now?)** — A concrete, recent event or structural shift that can move the price:
   news, earnings, policy, sector rotation, fund flows, or macro regime change.
   A trade without a catalyst is a gamble.

2. **Technicals (WHEN to act?)** — Price-volume structure confirms the catalyst is being priced in:
   trend alignment (MA5 > MA20 > MA60 for longs), volume expansion on breakout,
   momentum (RSI 40-70 for entries, divergence for exits), and key support/resistance levels.
   A catalyst without technical confirmation is premature.

3. **Valuation & Macro Anchor (HOW MUCH upside?)** — Valuation percentile, historical range,
   sector comps, or macro positioning provides the margin of safety and defines the reward target.
   Overvalued assets with catalysts are traps; undervalued assets with catalysts are opportunities.

**RISK FRAMEWORK**:
- Minimum reward-to-risk ratio: 2:1 (prefer 3:1)
- Position sizing by conviction: HIGH 50-70%, MEDIUM 30-50%, LOW 15-30%
- Timeframe: 2 weeks to 2 months (swing to position trading)
- Stop-loss: Always define invalidation level; no "hope-based" holding
- Portfolio-level: No single position > 30% of total portfolio; sector concentration < 50%
"""

# ============================================================
# Signal type definitions (6 actions, bilingual)
# ============================================================
SIGNAL_DEFINITIONS_EN = """
**ACTION SIGNAL TYPES** (use EXACTLY one of these):
- **BUY**: Open a NEW position (only when currently EMPTY / no holding)
- **ADD**: Increase an EXISTING position (only when already HOLDING)
- **REDUCE**: Partially sell an existing position (only when HOLDING, sell 25-75%)
- **SELL**: Fully close / liquidate the entire position (only when HOLDING, sell 100%)
- **HOLD**: Keep the current position unchanged, no action needed (only when HOLDING)
- **WAIT**: Stay on the sidelines, do not open a position (only when EMPTY)

⚠️ CRITICAL RULES:
- If user is EMPTY (no position): only BUY or WAIT are valid.
- If user is HOLDING: only ADD, REDUCE, SELL, or HOLD are valid.
- NEVER output BUY when user already holds the asset — use ADD instead.
- NEVER output WAIT when user already holds the asset — use HOLD instead.
"""

SIGNAL_DEFINITIONS_ZH = """
**操作信号类型**（必须使用以下其中一种）：
- **BUY**（买入/建仓）：开立新仓位（仅在当前空仓时使用）
- **ADD**（加仓）：增加现有持仓（仅在已持有时使用）
- **REDUCE**（减仓）：部分卖出现有持仓（仅在已持有时使用，卖出 25-75%）
- **SELL**（平仓/清仓）：全部卖出，完全平仓（仅在已持有时使用，卖出 100%）
- **HOLD**（持有）：维持当前仓位不变（仅在已持有时使用）
- **WAIT**（等待/观望）：暂不建仓，继续观察（仅在空仓时使用）

⚠️ 关键规则：
- 如果用户当前空仓（无持仓）：只能输出 BUY 或 WAIT。
- 如果用户当前持仓中：只能输出 ADD、REDUCE、SELL 或 HOLD。
- 用户已持有时，绝不能输出 BUY —— 应使用 ADD。
- 用户已持有时，绝不能输出 WAIT —— 应使用 HOLD。
"""

# Asset type → (role, asset_name, macro_focus)
ASSET_ROLE_MAP = {
    'STOCK': (
        "Equity Strategist",
        "stock",
        "earnings growth, PE/PB percentile vs 5-year range, sector rotation signals, institutional fund flows, and index-level sentiment (VIX, breadth)"
    ),
    'CRYPTO': (
        "Digital Asset Strategist",
        "cryptocurrency",
        "on-chain metrics (active addresses, exchange flows), BTC dominance, regulatory catalysts, macro liquidity (DXY, real yields), and market sentiment (Fear & Greed Index)"
    ),
    'COMMODITY': (
        "Commodities Strategist",
        "commodity",
        "supply/demand balance (inventories, production data), geopolitical risk premium, Dollar Index (DXY), central bank policy impact, seasonal patterns, and COT positioning"
    ),
    'BOND': (
        "Fixed Income Strategist",
        "bond",
        "central bank rate path, inflation trajectory (CPI/PCE), yield curve shape (2s10s spread), credit spreads, Treasury supply/demand, and economic cycle positioning"
    ),
    'FUND_CN': (
        "Chinese Fund Strategist",
        "Chinese fund",
        "fund manager's strategy consistency, NAV trend vs benchmark, sector allocation drift, A-share market regime (value/growth rotation), policy catalysts (PBOC, fiscal stimulus), and northbound/southbound fund flows"
    ),
}


class AIAnalyzer:
    def __init__(self):
        # Legacy: keep for backward compatibility
        self.client = None
        # New: model adapter cache
        self._adapters = {}
    
    def _get_adapter(self, model_id):
        """Get or create model adapter"""
        if model_id not in self._adapters:
            try:
                self._adapters[model_id] = get_adapter(model_id)
            except Exception as e:
                print(f"Failed to get adapter for {model_id}: {e}")
                return None
        return self._adapters[model_id]

    # ============================================================
    # Agent-mode shared helpers
    # ============================================================

    def _check_agent_support(self, model_name):
        """
        Check if a model supports agent (tool calling) mode.

        Returns:
            Tuple of (supports_tools: bool, config: dict, adapter: BaseModelAdapter or None)
        """
        config = get_model_config(model_name)
        if not config or not config.get('supports_tools', False):
            return False, config, None
        adapter = self._get_adapter(model_name)
        if not adapter or not adapter.is_available():
            return False, config, None
        return True, config, adapter

    def _create_tool_executor(self, user_id=None, symbol=None, asset_type="STOCK", provider=None):
        """Create an AgentToolExecutor with the given context."""
        from app.services.agent_tools import AgentToolExecutor
        return AgentToolExecutor(
            user_id=user_id,
            current_symbol=symbol,
            asset_type=asset_type,
            provider=provider
        )

    def _get_tool_descriptions_text(self):
        """Build a human-readable list of available tools for inclusion in prompts."""
        from app.services.agent_tools import TOOL_DEFINITIONS
        return "\n".join(
            f"- **{t['name']}**: {t['description']}" for t in TOOL_DEFINITIONS
        )

    def _build_position_info(self, current_position, language="zh"):
        """Build position context string for agent prompts."""
        if current_position:
            return f"""\n**CURRENT POSITION STATE**: HOLDING
- Quantity: {current_position.get('quantity', 'Unknown')}
- Average Cost: {current_position.get('avg_cost', current_position.get('price', 'Unknown'))}
- Last Buy Date: {current_position.get('date', 'Unknown')}
- Your primary task: Decide whether to HOLD, SELL, or BUY MORE.
"""
        return """\n**CURRENT POSITION STATE**: EMPTY (No open position)
- Your primary task: Identify whether now is a good time to BUY, or recommend WAIT.
- Be SELECTIVE: Only recommend BUY when you see multiple confirming signals with favorable risk/reward.
"""

    def _parse_json_response(self, text):
        """Extract and parse JSON from an LLM response string."""
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            text = json_match.group(0)
        else:
            text = text.replace('```json', '').replace('```', '').strip()
        return json.loads(text)

    def _run_agent(self, adapter, prompt, tool_executor, label="Agent",
                   max_iterations=None, **log_extra):
        """
        Execute an agent-mode call: generate_with_tools, timing, logging.

        Args:
            adapter: ModelAdapter instance
            prompt: Prompt string
            tool_executor: AgentToolExecutor instance
            label: Log label
            max_iterations: Override default tool call iteration limit
            **log_extra: Extra key=value pairs to print in the log header

        Returns:
            Tuple of (response_text, usage_dict, elapsed_seconds)

        Raises:
            ValueError: If the response is empty
        """
        start_time = time.time()
        print(f"\n{'='*60}")
        print(f"[{label}] Starting agent-mode call")
        if max_iterations:
            print(f"  max_iterations: {max_iterations}")
        for k, v in log_extra.items():
            print(f"  {k}: {v}")

        gen_kwargs = {}
        if max_iterations:
            gen_kwargs['max_iterations'] = max_iterations
        text, usage = adapter.generate_with_tools(prompt, tool_executor, **gen_kwargs)
        elapsed = time.time() - start_time

        if not text:
            raise ValueError(f"Empty response from AI agent ({label})")

        print(f"[{label}] \u2705 Completed")
        print(f"  Time: {elapsed:.2f}s | Tool calls: {len(tool_executor.tool_calls)}")
        if usage:
            print(f"  Tokens: in={usage.get('input_tokens','N/A')}, out={usage.get('output_tokens','N/A')}")
        print(f"{'='*60}\n")

        return text, usage, elapsed

    def _agent_error_result(self, error_msg, tool_executor, language="zh"):
        """Build a standard error result dict for agent failures."""
        friendly = "AI Agent 服务暂时不可用" if language == 'zh' else "AI Agent service temporarily unavailable"
        return {
            "error": friendly,
            "signals": [],
            "trades": [],
            "source": "error",
            "tool_calls": tool_executor.tool_calls if tool_executor else [],
            "agent_trace": tool_executor.trace if tool_executor else [],
            "agent_error": error_msg
        }

    def _merge_thinking_to_trace(self, result, tool_executor):
        """
        Extract 'thinking_process' from the LLM's JSON response and merge it
        into the agent_trace timeline.  The thinking steps are interleaved with
        existing tool_call entries by order: each thinking step is placed before
        the next tool_call that follows it in the timeline.
        
        If reasoning_content / native thinking was already captured (non-empty
        thinking entries in trace), the JSON thinking_process is treated as a
        supplementary summary appended at the end.
        """
        thinking_steps = result.pop('thinking_process', None)
        if not thinking_steps or not isinstance(thinking_steps, list):
            return

        # Check if we already have native thinking entries from the API
        existing_thinking = [e for e in tool_executor.trace if e.get('type') == 'thinking']

        if existing_thinking:
            # Native thinking already captured — add JSON thinking as a final summary
            # only if it has materially different content
            return

        # No native thinking was captured — weave JSON thinking into the trace
        # Strategy: interleave thinking steps before tool_call entries
        old_trace = list(tool_executor._trace)
        new_trace = []
        thinking_idx = 0
        tool_call_count = 0

        for entry in old_trace:
            if entry.get('type') == 'tool_call':
                # Insert the next thinking step before this tool call
                if thinking_idx < len(thinking_steps):
                    new_trace.append({
                        "type": "thinking",
                        "content": thinking_steps[thinking_idx],
                        "timestamp": entry.get('timestamp', datetime.now().isoformat())
                    })
                    thinking_idx += 1
                new_trace.append(entry)
                tool_call_count += 1
            else:
                new_trace.append(entry)

        # Append any remaining thinking steps at the end (post-tool-call reasoning)
        while thinking_idx < len(thinking_steps):
            new_trace.append({
                "type": "thinking",
                "content": thinking_steps[thinking_idx],
                "timestamp": datetime.now().isoformat()
            })
            thinking_idx += 1

        tool_executor._trace = new_trace

    def analyze(self, symbol, kline_data, model_name="gemini-3-flash-preview", language="zh", current_position=None, asset_type="STOCK", portfolio_context=None, symbol_name=None):
        """
        Analyze K-line data. For 'local-strategy', runs deterministic technical analysis.
        For all AI models, delegates to agent mode (analyze_with_agent).
        """
        if not kline_data:
            return {"error": "No K-line data provided", "signals": [], "trades": []}

        # Local strategy: deterministic MA+RSI analysis, no LLM needed
        if model_name == "local-strategy":
            enriched_data = calculate_indicators(kline_data)
            reason = "用户手动选择" if language == 'zh' else "User manually selected"
            return TechnicalStrategy.analyze(enriched_data, error_msg=reason, language=language)

        # All AI models use agent mode (function calling)
        return self.analyze_with_agent(
            symbol, model_name=model_name, language=language,
            asset_type=asset_type, symbol_name=symbol_name
        )

    def analyze_with_agent(self, symbol, model_name="gemini-3-flash-preview", language="zh",
                           asset_type="STOCK", symbol_name=None, user_id=None):
        """
        Agent-mode K-line analysis using function calling.
        The AI model actively calls tools to fetch real-time price, kline,
        technical indicators, and portfolio/position data on its own.
        No data is pre-fetched or pre-passed — all context comes from tool calls.
        """
        supports, config, adapter = self._check_agent_support(model_name)
        if not supports:
            raise ValueError(f"Model {model_name} does not support tool calling")

        tool_executor = self._create_tool_executor(user_id, symbol, asset_type, provider=config.get('provider'))
        lang_instruction = "Respond in Chinese (Simplified)." if language == 'zh' else "Respond in English."
        role, asset_name, focus = ASSET_ROLE_MAP.get(asset_type, ASSET_ROLE_MAP['STOCK'])
        tool_descriptions = self._get_tool_descriptions_text()

        prompt = f"""You are a professional **{role}** with access to real-time market data tools.

{INVESTMENT_PHILOSOPHY}

**ASSET**: {symbol}{f' ({symbol_name})' if symbol_name else ''} [{asset_type}]
**DATE**: {datetime.now().strftime('%Y-%m-%d')}

**YOUR AVAILABLE TOOLS**:
{tool_descriptions}

**ANALYSIS WORKFLOW** (follow this order):
1. Call `search_market_news` to find recent news, catalysts, and macro context for {symbol}
2. Call `get_realtime_price` to get the current price of {symbol}
3. Call `get_kline_data` with period="6mo" to get price history for trend and valuation context
4. Call `calculate_technical_indicators` to get MA, RSI, and momentum analysis
5. Call `get_portfolio_holdings` to check if user holds {symbol} and understand portfolio context
6. If user holds {symbol}, call `get_transaction_history` for {symbol} to review trade history
7. Optional: `compare_assets` or `get_exchange_rate` if needed

**EFFICIENCY TIP**: If analyzing multiple symbols, use `batch_calculate_technical_indicators` instead of calling `calculate_technical_indicators` repeatedly.

**THREE-CHECKPOINT DECISION FRAMEWORK** (all three must be evaluated):

CHECK 1 — Catalyst (from `search_market_news`):
- What recent event, news, or structural shift affects {symbol}?
- Is the catalyst forward-looking (not yet priced in) or backward-looking (already reflected)?
- Rate catalyst strength: STRONG (earnings beat, major policy, sector breakout) / MODERATE (analyst upgrade, sector tailwind) / WEAK (no clear catalyst) / NEGATIVE (headwinds)

CHECK 2 — Technicals (from kline + indicators):
- Trend: Is MA5 > MA20? Is price above/below key moving averages?
- Momentum: RSI position (40-70 = healthy uptrend zone), momentum direction
- Volume: Is volume confirming the price move? Expansion on breakout? Contraction on pullback?
- Structure: Key support/resistance levels, chart patterns
- Rate technicals: BULLISH / NEUTRAL / BEARISH

CHECK 3 — Valuation & Macro Anchor (from price history + fundamentals + news):
- Where is the current price relative to its 6-month range? (bottom 20% = cheap, top 20% = expensive)
- {focus}
- What is the macro backdrop? (risk-on vs risk-off, sector cycle position)
- Rate valuation: ATTRACTIVE / FAIR / STRETCHED

{"""**ENTRY DECISION MATRIX (for BUY/ADD — when EMPTY or adding to HOLDING)**:
| Catalyst | Technicals | Valuation | Decision (EMPTY → BUY / HOLDING → ADD) |
|----------|------------|-----------|----------|
| STRONG   | BULLISH    | ATTRACTIVE| HIGH conviction (50-70%) |
| STRONG   | BULLISH    | FAIR      | MEDIUM conviction (30-50%) |
| STRONG   | NEUTRAL    | ATTRACTIVE| MEDIUM conviction (30-50%), wait for technical trigger |
| MODERATE | BULLISH    | ATTRACTIVE| MEDIUM conviction (30-40%) |
| STRONG   | BEARISH    | any       | WAIT/HOLD — catalyst not confirmed by price action |
| WEAK     | BULLISH    | any       | WAIT/HOLD — rally without fundamental support is fragile |
| any      | any        | STRETCHED | CAUTION — limited upside, define tight stop |

**EXIT DECISION MATRIX (for REDUCE/SELL — only when HOLDING)**:
- Catalyst deterioration (earnings miss, policy reversal): SELL (close 100%)
- Technical breakdown (price < MA20, rising volume on decline): REDUCE 30-50%
- Valuation stretched + momentum fading: REDUCE 25-50%, raise stop
- Take profit: Price reached target or +20% from entry with momentum slowing: REDUCE or SELL

**POSITION AWARENESS** (determine from tool calls):
- After calling `get_portfolio_holdings`, determine if user is HOLDING or EMPTY for {symbol}.
- If HOLDING: choose from ADD / REDUCE / SELL / HOLD only. NEVER use BUY or WAIT.
- If EMPTY: choose from BUY / WAIT only. NEVER use ADD, REDUCE, SELL, or HOLD.""" if language == 'en' else """**建仓/加仓决策矩阵（空仓 → BUY 买入 / 持仓中 → ADD 加仓）**：
| 催化剂 | 技术面 | 估值 | 决策 |
|--------|--------|------|------|
| 强     | 看涨   | 有吸引力 | 高信心（50-70%仓位）|
| 强     | 看涨   | 合理     | 中等信心（30-50%仓位）|
| 强     | 中性   | 有吸引力 | 中等信心（30-50%），等待技术面确认 |
| 中等   | 看涨   | 有吸引力 | 中等信心（30-40%仓位）|
| 强     | 看跌   | 任意     | WAIT/HOLD — 催化剂未被价格行动确认 |
| 弱     | 看涨   | 任意     | WAIT/HOLD — 缺乏基本面支撑的上涨不可靠 |
| 任意   | 任意   | 偏高     | 谨慎 — 上行空间有限，设置严格止损 |

**减仓/平仓决策矩阵（仅在持仓时适用）**：
- 催化剂恶化（财报不及预期、政策逆转）：SELL 平仓（清仓 100%）
- 技术面破位（价格跌破 MA20、放量下跌）：REDUCE 减仓 30-50%
- 估值偏高 + 动能衰减：REDUCE 减仓 25-50%，上移止损
- 止盈：价格触及目标位或自入场以来涨幅 +20% 且动能放缓：REDUCE 减仓或 SELL 平仓

**持仓状态感知**（通过工具调用确定）：
- 调用 `get_portfolio_holdings` 后，判断用户对 {symbol} 是【持仓中】还是【空仓】。
- 如果【持仓中】：只能从 ADD（加仓）/ REDUCE（减仓）/ SELL（平仓）/ HOLD（持有）中选择。绝不能使用 BUY 或 WAIT。
- 如果【空仓】：只能从 BUY（买入建仓）/ WAIT（观望等待）中选择。绝不能使用 ADD、REDUCE、SELL 或 HOLD。"""}

**LANGUAGE**: {lang_instruction}

{SIGNAL_DEFINITIONS_ZH if language == 'zh' else SIGNAL_DEFINITIONS_EN}

**OUTPUT FORMAT**: Provide your final answer as a JSON object:
{{
    "thinking_process": [
        "Step 1: ...",
        "Step 2: ...",
        "..."
    ],
    "analysis_summary": "...",
    "trades": [],
    "current_action": {{
        "action": "BUY" | "ADD" | "REDUCE" | "SELL" | "HOLD" | "WAIT",
        "price": <current price from tool>,
        "quantity_percent": <15-70 for BUY/ADD, 25-100 for REDUCE/SELL>,
        "reason": "..."
    }}
}}

**IMPORTANT**:
- "thinking_process" is REQUIRED — capture your reasoning at EACH step. Base ALL on REAL DATA from tool calls.
- The "action" field MUST respect position state: use BUY/WAIT when empty, ADD/REDUCE/SELL/HOLD when holding.
- Return ONLY JSON.
"""

        try:
            text, usage, elapsed = self._run_agent(
                adapter, prompt, tool_executor, label="KlineAgent",
                Symbol=symbol, Model=model_name, Asset=asset_type
            )

            result = self._parse_json_response(text)
            self._merge_thinking_to_trace(result, tool_executor)

            # Extract signals from current_action
            signals = []
            current_action = result.get('current_action')
            if current_action and current_action.get('action') in ['BUY', 'ADD', 'REDUCE', 'SELL']:
                # Map action to chart signal type: BUY/ADD → BUY (green), REDUCE/SELL → SELL (red)
                chart_type = 'BUY' if current_action['action'] in ['BUY', 'ADD'] else 'SELL'
                signal = {
                    "type": chart_type,
                    "position_action": current_action['action'],  # Precise action for display
                    "date": datetime.now().strftime('%Y-%m-%d'),
                    "price": current_action.get('price'),
                    "reason": current_action.get('reason'),
                    "is_current": True
                }
                if current_action.get('quantity_percent'):
                    signal['quantity_percent'] = current_action['quantity_percent']
                signals.append(signal)

            result['signals'] = signals
            result['source'] = 'ai_agent'
            result['tool_calls'] = tool_executor.tool_calls
            result['agent_trace'] = tool_executor.trace
            return result

        except Exception as e:
            print(f"[KlineAgent] ❌ Failed: {e}, falling back to local strategy")
            # Fallback: local technical strategy
            enriched_data = []
            try:
                from app.services.data_provider import batch_fetcher
                kline_data = batch_fetcher.get_cached_kline_data(
                    symbol, period="3y", interval="1d",
                    is_cn_fund=(asset_type == "FUND_CN")
                )
                if kline_data:
                    enriched_data = calculate_indicators(kline_data)
            except Exception as fetch_err:
                print(f"[KlineAgent] Data fetch also failed: {fetch_err}")

            if enriched_data:
                result = TechnicalStrategy.analyze(
                    enriched_data,
                    error_msg="AI Agent 服务暂时不可用" if language == 'zh' else "AI Agent unavailable",
                    language=language
                )
                result['agent_fallback'] = True
                result['agent_error'] = str(e)
                result['tool_calls'] = tool_executor.tool_calls
                result['agent_trace'] = tool_executor.trace
                return result

            return self._agent_error_result(str(e), tool_executor, language)

    def recommend_stocks_with_agent(self, criteria, model_name="gemini-3-flash-preview", language="zh"):
        """
        Agent-mode market recommendation using function calling.
        The AI proactively fetches real-time market data via tools to inform its picks.
        """
        supports, config, adapter = self._check_agent_support(model_name)
        if not supports:
            raise ValueError(f"Model {model_name} does not support tool calling")

        asset_type = criteria.get('asset_type', 'STOCK')
        tool_executor = self._create_tool_executor(asset_type=asset_type, provider=config.get('provider'))
        lang_instruction = "Respond in Chinese (Simplified)." if language == 'zh' else "Respond in English."
        tool_descriptions = self._get_tool_descriptions_text()
        role, asset_name, focus = ASSET_ROLE_MAP.get(asset_type, ASSET_ROLE_MAP['STOCK'])

        current_date = datetime.now().strftime('%Y-%m-%d')
        market = criteria.get('market', 'Any')

        prompt = f"""You are a professional **{role}** with access to real-time market data tools AND web search.

{INVESTMENT_PHILOSOPHY}

**DATE**: {current_date}
**TASK**: Recommend 10 promising {asset_type} assets for purchase in the next 2 weeks to 2 months.

**CRITERIA**:
- Asset Type: {asset_type} (MANDATORY — only recommend this type)
- Market: {market}
- Capital Size: {criteria.get('capital', 'Not specified')}
- Risk Tolerance: {criteria.get('risk', 'Not specified')}
- Trading Frequency: {criteria.get('frequency', 'Not specified')}
- Include ETF: {criteria.get('include_etf', 'false')}

**YOUR AVAILABLE TOOLS**:
{tool_descriptions}

**⚠️ CRITICAL METHODOLOGY — "Catalyst-First, Triple-Verified" (MANDATORY)**:
You MUST follow a **top-down, catalyst-driven** approach with triple verification.
Do NOT start by picking well-known blue-chip stocks — that is "drawing the target after shooting the arrow".

**MANDATORY WORKFLOW** (follow this exact order):

**Phase 1 — Catalyst Discovery (use `search_market_news` FIRST)**:
1. Call `search_market_news`: "{market} {asset_type} market news today {current_date}" — headlines, policy, earnings, sector rotation
2. Call `search_market_news`: "{market} {asset_type} hot stocks this week catalysts" — specific assets with real catalysts
3. Call `search_market_news`: sector/thematic trends, e.g., "AI semiconductor EV sector news {current_date}" — identify 2-3 hot themes

**Phase 2 — Candidate Screening (based on Phase 1)**:
4. Compile 15-20 candidate symbols **specifically mentioned in news** or in hot sectors discovered
5. Use `batch_get_realtime_prices` to check current prices

**Phase 3 — Technical + Valuation Verification**:
6. Use `batch_get_kline_data` (period="6mo") to assess trend AND price position within range
7. Use `batch_calculate_technical_indicators` for top candidates to confirm entry timing (MUCH more efficient than calling calculate_technical_indicators repeatedly)
8. For each candidate, evaluate:
   - **Technical score**: trend direction, volume confirmation, momentum
   - **Valuation position**: where is price vs 6-month high/low? (bottom 30% = attractive, top 20% = stretched)
   - **Catalyst quality**: is it forward-looking or already priced in?

**ANTI-PATTERN WARNING**: Every recommended asset MUST trace back to a specific recent catalyst discovered through `search_market_news`. "Well-known company" is NOT a reason.

**EFFICIENCY TIP**: Use batch tools — `batch_get_realtime_prices` (up to 20), `batch_get_kline_data` (up to 10), and `batch_calculate_technical_indicators` (up to 10).

**SYMBOL FORMAT GUIDE** (use exact format or data fetch will fail):
- US stocks: AAPL, TSLA, MSFT, NVDA
- HK stocks: 4-digit + '.HK' → 0700.HK, 9988.HK (always 4 digits, pad zeros)
- A-shares Shanghai: 6-digit + '.SS' → 600519.SS, 601318.SS
- A-shares Shenzhen: 6-digit + '.SZ' → 000858.SZ, 300750.SZ
- Crypto: symbol + '-USD' → BTC-USD, ETH-USD
- Commodities: GC=F (gold), CL=F (oil), SI=F (silver)
- Chinese funds: 6-digit code → 015283, 000001

**MACRO & ASSET FOCUS**: {focus}

{"""**RATING SYSTEM** (based on triple-confirmation strength):
- ⭐⭐⭐ (High Conviction): Strong catalyst (not priced in) + bullish technicals + attractive valuation position → high win-rate AND high reward potential
- ⭐⭐ (Medium): Two of three confirmations strong, one neutral → reasonable risk/reward
- ⭐ (Speculative): Strong catalyst but early-stage or technically unconfirmed → high reward potential but lower win-rate
- ⚠️ (Caution): Catalyst may be priced in, or valuation stretched, or technicals unfavorable
- 🔻 (Avoid): Negative catalyst, bearish technicals, or valuation trap""" if language == 'en' else """**评级系统**（基于三重确认强度）：
- ⭐⭐⭐（高信心）：强催化剂（尚未被定价）+ 技术面看涨 + 估值有吸引力 → 高胜率且高赔率
- ⭐⭐（中等）：三项中两项强势、一项中性 → 风险回报合理
- ⭐（投机）：催化剂强但处于早期阶段或技术面尚未确认 → 高赔率但胜率偏低
- ⚠️（谨慎）：催化剂可能已被定价，或估值偏高，或技术面不利
- 🔻（回避）：负面催化剂、技术面看跌、或估值陷阱"""}

**LANGUAGE**: {lang_instruction}

**OUTPUT FORMAT** (JSON):
{{
    "thinking_process": [
        "Step 1: News search found these key catalysts and themes: [specifics]...",
        "Step 2: Identified candidate assets from news: [list with catalyst for each]...",
        "Step 3: Price screening — current prices and 6mo range positions...",
        "Step 4: Technical verification — trend, volume, momentum assessment...",
        "Step 5: Triple-check summary: which candidates pass Catalyst + Technicals + Valuation..."
    ],
    "market_overview": "3-5 paragraph analysis: (1) Market regime and macro backdrop — cite news; (2) Key catalysts and sector themes — specific events and dates; (3) Risk factors and headwinds; (4) Strategy recommendation for this environment. MUST reference specific news. 200+ words.",
    "recommendations": [
        {{
            "symbol": "Ticker",
            "name": "Asset Name",
            "price": "Current Price (from tool)",
            "level": "⭐⭐⭐ | ⭐⭐ | ⭐ | ⚠️ | 🔻",
            "reason": "MUST include all three dimensions (80+ words): (1) CATALYST — the specific news event/development that surfaced this pick, with date; (2) TECHNICALS — trend direction, key levels, momentum status from tool data; (3) VALUATION — price position in range, upside potential, risk/reward estimate. End with: Catalyst=[STRONG/MODERATE/WEAK], Technicals=[BULLISH/NEUTRAL/BEARISH], Valuation=[ATTRACTIVE/FAIR/STRETCHED]."
        }}
    ]
}}

**CONTENT QUALITY REQUIREMENTS**:
- Every "reason" must explicitly state all three dimensions: catalyst + technicals + valuation
- No vague language — use specific prices, percentages, dates, and news references
- "market_overview" must be grounded in actual search results, not generic commentary

**IMPORTANT**: "thinking_process" is REQUIRED. Return ONLY JSON.
"""

        try:
            text, usage, elapsed = self._run_agent(
                adapter, prompt, tool_executor, label="RecommendAgent",
                max_iterations=25,
                Model=model_name, Asset=asset_type, Market=market
            )

            result = self._parse_json_response(text)
            self._merge_thinking_to_trace(result, tool_executor)
            result['tool_calls'] = tool_executor.tool_calls
            result['agent_trace'] = tool_executor.trace
            result['source'] = 'ai_agent'
            return result

        except Exception as e:
            print(f"[RecommendAgent] ❌ Failed: {e}")
            return {
                "market_overview": f"Analysis failed: {str(e)}",
                "recommendations": [],
                "agent_fallback": True,
                "agent_error": str(e),
                "tool_calls": tool_executor.tool_calls,
                "agent_trace": tool_executor.trace
            }

    def analyze_portfolio_item_with_agent(self, holding_data, model_name="gemini-3-flash-preview",
                                           language="zh", user_id=None):
        """
        Agent-mode single-holding diagnosis using function calling.
        The AI fetches real-time data for the symbol before making its recommendation.
        """
        symbol = holding_data.get('symbol', 'UNKNOWN')
        asset_type = holding_data.get('asset_type', 'STOCK')

        supports, config, adapter = self._check_agent_support(model_name)
        if not supports:
            raise ValueError(f"Model {model_name} does not support tool calling")

        tool_executor = self._create_tool_executor(user_id, symbol, asset_type, provider=config.get('provider'))
        lang_instruction = "Respond in Chinese (Simplified)." if language == 'zh' else "Respond in English."
        tool_descriptions = self._get_tool_descriptions_text()
        role, asset_name, focus = ASSET_ROLE_MAP.get(asset_type, ASSET_ROLE_MAP['STOCK'])

        avg_price = holding_data.get('avg_price', 'Unknown')
        percentage = holding_data.get('percentage')
        percentage_str = f"{percentage}%" if percentage is not None else "Unknown"

        prompt = f"""You are a professional **{role}** with access to real-time market data tools.

{INVESTMENT_PHILOSOPHY}

**TASK**: Evaluate a client's existing {asset_type} holding and advise: HOLD, SELL (full/partial), or BUY MORE.

**HOLDING DETAILS**:
- Symbol: {symbol}
- Asset Type: {asset_type}
- Average Buy Price: {avg_price}
- Portfolio Weight: {percentage_str}

**YOUR AVAILABLE TOOLS**:
{tool_descriptions}

**ANALYSIS WORKFLOW**:
1. Call `search_market_news` to find recent news and catalysts for {symbol}
2. Call `get_realtime_price` to get current price of {symbol}
3. Call `get_kline_data` (period="6mo") to see price history and determine range position
4. Call `calculate_technical_indicators` to assess trend and momentum
5. Call `get_portfolio_holdings` to see full portfolio context and concentration risk
6. If relevant, call `get_transaction_history` for {symbol}

{"""**THREE-CHECKPOINT EVALUATION FOR EXISTING POSITIONS**:

CHECK 1 — Catalyst Status:
- Has the original investment thesis (catalyst) played out, or is it still unfolding?
- Any NEW catalysts (positive or negative) since purchase?
- Is there catalyst deterioration (earnings miss, policy reversal, competitive threat)?
- Rate: POSITIVE (thesis intact + new tailwinds) / NEUTRAL (thesis intact, no change) / NEGATIVE (thesis broken or headwinds)

CHECK 2 — Technical Health:
- Is the trend still intact? (Price above key MAs? Momentum direction?)
- Are there signs of distribution (price up on declining volume)?
- Key support levels: where does the thesis get invalidated?
- Rate: HEALTHY (uptrend intact) / WEAKENING (mixed signals) / DETERIORATING (breakdown imminent)

CHECK 3 — Valuation & P&L Context:
- Current price vs avg buy price: P&L status
- Current price position in 6-month range: is it stretched or has room to run?
- Risk/reward from current level: is asymmetry still favorable?
- Portfolio weight: is it appropriate given current conviction level?
- Rate: FAVORABLE (good risk/reward, room to run) / FAIR (balanced) / UNFAVORABLE (stretched, limited upside)

**DECISION MATRIX FOR HOLDINGS** (IMPORTANT: user IS holding this asset — NEVER use BUY or WAIT):
| Catalyst Status | Technical Health | Valuation | Decision |
|----------------|-----------------|-----------|----------|
| POSITIVE       | HEALTHY         | FAVORABLE | ADD — add to position (20-40%) |
| POSITIVE       | HEALTHY         | FAIR      | ADD (small, 10-20%) or HOLD |
| POSITIVE       | WEAKENING       | any       | HOLD — tighten stop, watch closely |
| NEUTRAL        | HEALTHY         | FAVORABLE | HOLD — ride the trend |
| NEUTRAL        | WEAKENING       | UNFAVORABLE| REDUCE 30-50% — reduce risk |
| NEGATIVE       | any             | any       | SELL (close 100%) — thesis broken |
| any            | DETERIORATING   | UNFAVORABLE| SELL (close 100%) or REDUCE (50-75%) — protect capital |""" if language == 'en' else """**持仓三维评估体系**：

检查点 1 — 催化剂状态：
- 最初的投资逻辑（催化剂）是否已兑现，还是仍在演绎中？
- 买入后是否出现了新的催化剂（正面或负面）？
- 是否存在催化剂恶化（财报不及预期、政策逆转、竞争威胁）？
- 评级：积极（逻辑完好 + 新利好）/ 中性（逻辑完好，无变化）/ 消极（逻辑破坏或遇到逆风）

检查点 2 — 技术面健康度：
- 趋势是否仍然完好？（价格是否在关键均线上方？动能方向如何？）
- 是否有出货迹象（价格上涨但成交量萎缩）？
- 关键支撑位在哪里：跌破何处意味着逻辑失效？
- 评级：健康（上升趋势完好）/ 走弱（信号混乱）/ 恶化（即将破位）

检查点 3 — 估值与盈亏：
- 当前价格 vs 平均买入价格：盈亏状况
- 当前价格在 6 个月区间中的位置：是偏高还是有空间？
- 当前水平的风险收益比：非对称性是否仍有利？
- 持仓权重：在当前信心水平下，权重是否合适？
- 评级：有利（风险回报好，有上涨空间）/ 合理（平衡）/ 不利（偏高，上行空间有限）

**持仓决策矩阵**（重要：用户正在持有该资产 — 绝不能使用 BUY 或 WAIT）：
| 催化剂状态 | 技术面健康度 | 估值 | 决策 |
|-----------|------------|------|------|
| 积极 | 健康 | 有利 | ADD 加仓（20-40%）|
| 积极 | 健康 | 合理 | ADD 小幅加仓（10-20%）或 HOLD 持有 |
| 积极 | 走弱 | 任意 | HOLD 持有 — 收紧止损，密切关注 |
| 中性 | 健康 | 有利 | HOLD 持有 — 继续持有顺势而为 |
| 中性 | 走弱 | 不利 | REDUCE 减仓 30-50% — 降低风险 |
| 消极 | 任意 | 任意 | SELL 平仓（清仓 100%）— 投资逻辑已破坏 |
| 任意 | 恶化 | 不利 | SELL 平仓 或 REDUCE 减仓（50-75%）— 保护本金 |"""}

**LANGUAGE**: {lang_instruction}

**OUTPUT FORMAT** (JSON):
{{
    "thinking_process": [
        "Step 1: News search — catalyst status for {symbol}: [findings]... Rating: POSITIVE/NEUTRAL/NEGATIVE",
        "Step 2: Current price X vs avg buy price {avg_price} → P&L: X%",
        "Step 3: 6mo range [low-high], current at Xth percentile → valuation position",
        "Step 4: Technicals — MA alignment, RSI, momentum → Rating: HEALTHY/WEAKENING/DETERIORATING",
        "Step 5: Portfolio weight {percentage_str} — appropriate given conviction? Concentration risk?",
        "Step 6: Decision matrix → Catalyst(X) + Technicals(X) + Valuation(X) = [rating and action]"
    ],
    "symbol": "{symbol}",
    "current_price": "<from get_realtime_price>",
    "rating": "Strong Buy | Buy | Hold | Sell | Strong Sell",
    "current_action": {{
        "action": "ADD" | "REDUCE" | "SELL" | "HOLD",
        "price": <current price from tool>,
        "quantity_percent": <10-40 for ADD, 25-100 for REDUCE/SELL>,
        "reason": "..."
    }},
    "action": "Specific advice with position sizing (for backward compatibility).",
    "analysis": "Comprehensive reasoning integrating all three checkpoints with data from tool calls. Include invalidation level (price where thesis breaks) and target (if holding/buying)."
}}

**IMPORTANT**:
- "thinking_process" is REQUIRED — show evaluation of each checkpoint. Base ALL on REAL DATA from tool calls.
- The "action" in "current_action" MUST be one of: ADD, REDUCE, SELL, HOLD. NEVER use BUY or WAIT (user is already holding).
- Return ONLY JSON.
"""

        try:
            text, usage, elapsed = self._run_agent(
                adapter, prompt, tool_executor, label="DiagnosisAgent",
                Symbol=symbol, Model=model_name, Asset=asset_type
            )

            result = self._parse_json_response(text)
            self._merge_thinking_to_trace(result, tool_executor)
            result['tool_calls'] = tool_executor.tool_calls
            result['agent_trace'] = tool_executor.trace
            result['source'] = 'ai_agent'
            return result

        except Exception as e:
            print(f"[DiagnosisAgent] ❌ Failed: {e}")
            return {
                "symbol": symbol,
                "rating": "Unknown",
                "action": "Error analyzing position.",
                "analysis": str(e),
                "agent_fallback": True,
                "agent_error": str(e),
                "tool_calls": tool_executor.tool_calls,
                "agent_trace": tool_executor.trace
            }

    def analyze_full_portfolio(self, portfolios_data, model_name="gemini-3-flash-preview", language="zh"):
        """
        Analyze the entire portfolio and provide comprehensive investment advice.
        Acts as an investment master to evaluate the overall portfolio composition.
        """
        # Get model adapter
        adapter = self._get_adapter(model_name)
        if not adapter or not adapter.is_available():
            return {"error": "API Key Unavailable"}
        
        config = get_model_config(model_name)
        supports_search = config.get('supports_search', False)
        
        # Calculate portfolio statistics
        total_value = 0
        total_cost = 0
        positions = []
        
        for portfolio in portfolios_data:
            symbol = portfolio.get('symbol', 'N/A')
            asset_type = portfolio.get('asset_type', 'STOCK')
            quantity = portfolio.get('total_quantity', 0)
            avg_price = portfolio.get('avg_cost', 0)
            currency = portfolio.get('currency', 'USD')
            exchange_rate = portfolio.get('exchange_rate', 1.0)
            
            # CRITICAL: Use value_in_usd for accurate cross-currency portfolio analysis
            # This ensures correct weight calculation for assets in different currencies
            current_value_usd = portfolio.get('value_in_usd')
            if current_value_usd is None:
                # Fallback: calculate from current_value or quantity * avg_price
                current_value_usd = portfolio.get('current_value', quantity * avg_price)
            
            # CRITICAL FIX: Convert total_cost to USD using exchange_rate
            # Frontend provides total_cost in original currency (CNY/USD/HKD)
            # We MUST convert it to USD to match value_in_usd currency
            position_cost_original = portfolio.get('total_cost', quantity * avg_price)
            position_cost_usd = position_cost_original * exchange_rate
            
            total_cost += position_cost_usd
            total_value += current_value_usd
            
            positions.append({
                'symbol': symbol,
                'asset_type': asset_type,
                'currency': currency,
                'quantity': quantity,
                'avg_price': avg_price,
                'current_value': current_value_usd,
                'cost': position_cost_usd,  # Cost in USD
                'cost_original': position_cost_original,  # Cost in original currency
                'pnl': current_value_usd - position_cost_usd,
                'pnl_pct': ((current_value_usd - position_cost_usd) / position_cost_usd * 100) if position_cost_usd > 0 else 0
            })
        
        total_pnl = total_value - total_cost
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
        
        # Build portfolio summary
        portfolio_summary = f"""
**Portfolio Overview:**
- Total Positions: {len(positions)}
- Total Cost: ${total_cost:,.2f}
- Current Value: ${total_value:,.2f}
- Total P&L: ${total_pnl:,.2f} ({total_pnl_pct:+.2f}%)

**Position Details:**
"""
        for pos in positions:
            weight = (pos['current_value']/total_value*100) if total_value > 0 else 0
            currency_info = f" ({pos['currency']})" if pos['currency'] != 'USD' else ""
            
            # Show cost in both original currency and USD for clarity
            if pos['currency'] != 'USD':
                cost_display = f"{pos['cost_original']:,.2f} {pos['currency']} (≈ ${pos['cost']:,.2f} USD)"
            else:
                cost_display = f"${pos['cost']:,.2f}"
            
            portfolio_summary += f"""
- {pos['symbol']} ({pos['asset_type']}{currency_info}):
  * Quantity: {pos['quantity']}
  * Avg Price: {pos['avg_price']:.2f} {pos['currency']}
  * Total Cost: {cost_display}
  * Current Value (USD): ${pos['current_value']:,.2f}
  * P&L: ${pos['pnl']:,.2f} ({pos['pnl_pct']:+.2f}%)
  * Weight: {weight:.1f}%
"""
        
        lang_instruction = "Respond in Chinese (Simplified)." if language == 'zh' else "Respond in English."
        
        search_instruction = ""
        if supports_search:
            search_instruction = """1. **MANDATORY: Use Google Search or Web Search** to:
   - **Verify the REAL NAME and description of each asset** (especially for fund codes like 015283, 159941, etc.)
   - Get the latest market information, news, and current prices
   - Understand the actual investment focus of each fund/asset (e.g., tech, energy, healthcare)
   - **DO NOT guess or assume asset names based on codes alone**"""
        else:
            search_instruction = "1. Based on your knowledge, analyze the current market status of these assets. Note: Asset names may not be accurate without search capability."
        
        prompt = f"""You are a senior portfolio strategist conducting a comprehensive portfolio review.

{INVESTMENT_PHILOSOPHY}

{portfolio_summary}

**Analysis Requirements:**
{search_instruction}

2. **CRITICAL - Asset Identification**:
   - For each position, especially fund codes (e.g., 015283, 159941), you MUST search to find its REAL NAME and investment focus
   - DO NOT make assumptions about what a fund invests in based on the code number
   - Verify the actual sector/theme (e.g., "恒生科技ETF" not "光伏基金")

3. **Portfolio Weight Accuracy**:
   - The "Weight" percentages shown are calculated in USD equivalent values
   - Different currencies have been converted to USD for accurate comparison
   - Use these weights as-is; they already account for exchange rates

4. **THREE-DIMENSIONAL PORTFOLIO EVALUATION**:

   **Dimension 1 — Catalyst Health Check** (for each position):
   - Does each position still have an active, forward-looking catalyst?
   - Are there NEW catalysts (positive or negative) that change the thesis?
   - Which positions have "dead money" risk (no catalyst, sideways drift)?

   **Dimension 2 — Technical Portfolio Heat Map**:
   - Which positions are in healthy uptrends (above key MAs, good momentum)?
   - Which show technical deterioration (breaking support, fading momentum)?
   - Overall portfolio momentum: is the portfolio trending up, sideways, or down?

   **Dimension 3 — Allocation & Risk Architecture**:
   - **Concentration risk**: Any single position > 30%? Any sector > 50%?
   - **Correlation risk**: Are positions correlated (e.g., all tech, all China)?
   - **P&L asymmetry**: Are winners getting bigger and losers getting trimmed, or the reverse?
   - **Cash readiness**: Is the portfolio positioned to act on new opportunities?
   - **Macro alignment**: Does the portfolio tilt match the current macro regime?

5. **ACTIONABLE RECOMMENDATIONS** (for each position, use the Decision Matrix from Investment Philosophy):
   - For each position, state: Catalyst=[POSITIVE/NEUTRAL/NEGATIVE], Technicals=[HEALTHY/WEAKENING/DETERIORATING], Valuation=[FAVORABLE/FAIR/UNFAVORABLE]
   - Then recommend: ADD (加仓) / HOLD (持有) / REDUCE (减仓) / SELL (平仓) — with specific reasoning

6. **Overall Rating**:
   - "Excellent": Balanced allocation, active catalysts, good risk/reward, macro-aligned.
   - "Good": Overall solid, minor adjustments needed.
   - "Fair": Obvious issues — concentration, dead money, or macro misalignment.
   - "Poor": Significant risk — high concentration, deteriorating positions, no catalysts.
   - "Critical": Immediate action needed — capital at risk.

7. **Language Requirement**: {lang_instruction}

**Output Format (JSON):**
{{
    "overall_rating": "Good",
    "total_score": 75,
    "risk_level": "Medium",
    "asset_allocation_analysis": "Detailed analysis of allocation, concentration, correlation, and macro alignment.",
    "performance_analysis": "Analysis of P&L, which positions are performing and why (catalyst + technical status).",
    "risk_analysis": "Concentration risk, correlation risk, catalyst health, technical deterioration signals.",
    "market_outlook": "Current macro regime assessment and how the portfolio is positioned for it.",
    "recommendations": [
        {{
            "symbol": "Symbol (e.g., 015283)",
            "asset_name": "REAL asset name found via search",
            "action": "ADD / HOLD / REDUCE / SELL",
            "reason": "Catalyst=[X], Technicals=[X], Valuation=[X] → [specific action rationale with data]"
        }}
    ],
    "summary": "Overall evaluation: what's working, what's not, and the top 2-3 priority actions to take NOW."
}}
"""
        
        try:
            # Start timing
            start_time = time.time()
            print(f"\n{'='*60}")
            print(f"[LLM DEBUG] Starting full portfolio analysis")
            print(f"  Model: {model_name}")
            print(f"  Provider: {config.get('provider', 'unknown')}")
            print(f"  Language: {language}")
            print(f"  Total positions: {len(positions)}")
            print(f"  Total value: ${total_value:,.2f}")
            print(f"  Total P&L: ${total_pnl:,.2f} ({total_pnl_pct:+.2f}%)")
            print(f"  Supports search: {supports_search}")
            
            # Use unified adapter interface
            text, usage = adapter.generate(prompt, use_search=supports_search)
            
            # End timing
            elapsed_time = time.time() - start_time
            
            if not text:
                raise ValueError(f"Empty response from {model_name}")

            # Robust JSON extraction
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
            else:
                text = text.replace('```json', '').replace('```', '').strip()

            result = json.loads(text)
            
            # Print success log
            print(f"[LLM DEBUG] ✅ Full portfolio analysis completed successfully")
            print(f"  Total time: {elapsed_time:.2f}s")
            print(f"  Overall rating: {result.get('overall_rating', 'N/A')}")
            print(f"  Risk level: {result.get('risk_level', 'N/A')}")
            print(f"  Response length: {len(text)} chars")
            if usage:
                print(f"  Token usage: input={usage.get('input_tokens', 'N/A')}, output={usage.get('output_tokens', 'N/A')}")
            print(f"{'='*60}\n")
            
            return result
        except Exception as e:
            elapsed_time = time.time() - start_time if 'start_time' in locals() else 0
            print(f"[LLM DEBUG] ❌ Full portfolio analysis failed")
            print(f"  Total time: {elapsed_time:.2f}s")
            print(f"  Error: {str(e)}")
            print(f"{'='*60}\n")
            return {
                "overall_rating": "Unknown",
                "total_score": 0,
                "risk_level": "Unknown",
                "summary": f"分析失败: {str(e)}"
            }

    def translate_text(self, text, target_language="en", model_name="gemini-3-flash-preview"):
        """
        Translate text to target language using AI models.
        """
        # Get model adapter
        adapter = self._get_adapter(model_name)
        if not adapter or not adapter.is_available():
            return {"error": "API Key Unavailable"}
            
        prompt = f"""
        Translate the following financial text to {target_language}.
        Keep technical terms accurate.
        Only return the translated text, no intro/outro.
        
        Text:
        {text}
        """
        try:
            # Start timing
            start_time = time.time()
            config = get_model_config(model_name)
            print(f"\n{'='*60}")
            print(f"[LLM DEBUG] Starting translation")
            print(f"  Model: {model_name}")
            print(f"  Provider: {config.get('provider', 'unknown')}")
            print(f"  Target language: {target_language}")
            print(f"  Text length: {len(text)} chars")
            
            # Use unified adapter interface
            translated, usage = adapter.generate(prompt)
            translated = translated.strip()
            
            # End timing
            elapsed_time = time.time() - start_time
            
            # Print success log
            print(f"[LLM DEBUG] ✅ Translation completed successfully")
            print(f"  Total time: {elapsed_time:.2f}s")
            print(f"  Output length: {len(translated)} chars")
            if usage:
                print(f"  Token usage: input={usage.get('input_tokens', 'N/A')}, output={usage.get('output_tokens', 'N/A')}")
            print(f"{'='*60}\n")
            
            return {"translation": translated}
        except Exception as e:
            elapsed_time = time.time() - start_time if 'start_time' in locals() else 0
            print(f"[LLM DEBUG] ❌ Translation failed")
            print(f"  Total time: {elapsed_time:.2f}s")
            print(f"  Error: {str(e)}")
            print(f"{'='*60}\n")
            return {"error": str(e)}
