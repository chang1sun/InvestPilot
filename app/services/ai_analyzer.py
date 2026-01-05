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
    
    def _get_forbidden_assets(self, asset_type):
        """Get list of forbidden asset types for the prompt"""
        all_types = {
            'STOCK': 'Stocks, Equities, Company shares',
            'CRYPTO': 'Cryptocurrencies, Digital currencies, Tokens',
            'COMMODITY': 'Commodities, Futures, Raw materials',
            'BOND': 'Bonds, Fixed income, Treasuries'
        }
        forbidden = [desc for type_key, desc in all_types.items() if type_key != asset_type]
        return ', '.join(forbidden)
    
    def _get_allowed_assets(self, asset_type):
        """Get description of allowed assets"""
        descriptions = {
            'STOCK': 'Stocks, Equities, Company shares (e.g., AAPL, TSLA, MSFT)',
            'CRYPTO': 'Cryptocurrencies, Digital currencies, Tokens (e.g., BTC-USD, ETH-USD, SOL-USD)',
            'COMMODITY': 'Commodities, Futures, Raw materials (e.g., GC=F, CL=F, SI=F)',
            'BOND': 'Bonds, Fixed income, Treasuries (e.g., ^TNX, ^IRX, ^TYX)'
        }
        return descriptions.get(asset_type, 'Unknown asset type')
    
    def _get_example_symbol(self, asset_type):
        """Get example symbol for the asset type"""
        examples = {
            'STOCK': 'AAPL, TSLA, MSFT',
            'CRYPTO': 'BTC-USD, ETH-USD, SOL-USD',
            'COMMODITY': 'GC=F, CL=F, SI=F',
            'BOND': '^TNX, ^IRX, ^TYX'
        }
        return examples.get(asset_type, 'SYMBOL')

    def analyze(self, symbol, kline_data, model_name="gemini-3-flash-preview", language="zh", current_position=None, asset_type="STOCK"):
        """
        Analyze K-line data using AI models to find buy/sell points.
        Supports: Gemini, GPT, Claude, Grok, Qwen
        :param current_position: Optional dict { 'date': 'YYYY-MM-DD', 'price': float, 'reason': str } indicating last BUY signal.
        :param asset_type: STOCK, CRYPTO, COMMODITY, BOND
        """
        if not kline_data:
            return {"error": "No K-line data provided", "signals": [], "trades": []}

        # 1. Preprocess data: Add indicators to help the LLM (also used for local strategy)
        enriched_data = calculate_indicators(kline_data)
        
        # --- DIRECT LOCAL STRATEGY ---
        # If user specifically selected "local-strategy", skip LLM entirely.
        if model_name == "local-strategy":
            reason = "用户手动选择" if language == 'zh' else "User manually selected"
            return TechnicalStrategy.analyze(enriched_data, error_msg=reason, language=language)

        # Get model adapter
        adapter = self._get_adapter(model_name)
        if not adapter or not adapter.is_available():
            reason = "API Key 缺失" if language == 'zh' else "API Key missing"
            return TechnicalStrategy.analyze(enriched_data, error_msg=reason, language=language)
        
        # 2. Prepare Prompt for LLM
        # Limit data to recent history to focus attention and save tokens (last 100 candles for swing trading)
        recent_data = enriched_data[-100:] if len(enriched_data) > 100 else enriched_data
        
        csv_data = "Date,Open,High,Low,Close,Volume,MA5,MA20,RSI\n"
        for d in recent_data:
            csv_data += f"{d['date']},{d['open']},{d['high']},{d['low']},{d['close']},{d['volume']},{d['MA5']:.2f},{d['MA20']:.2f},{d['RSI']:.2f}\n"

        # Language specific instruction
        lang_instruction = "Respond in Chinese (Simplified)." if language == 'zh' else "Respond in English."

        # Asset Type Specific Context
        if asset_type == "CRYPTO":
            role_desc = "You are a professional **Crypto Asset Analyst** specializing in **Swing Trading**."
            macro_focus = "Focus on On-chain data, Market Sentiment, Regulatory news, and Bitcoin correlation. Avoid traditional equity metrics like P/E ratio or dividends."
            asset_name = "cryptocurrency"
        elif asset_type == "COMMODITY":
            role_desc = "You are a professional **Commodities Trader**."
            macro_focus = "Focus on Supply/Demand dynamics, Geopolitics, Dollar Index (DXY), and Inventory reports. Consider seasonal patterns and production data."
            asset_name = "commodity"
        elif asset_type == "BOND":
            role_desc = "You are a professional **Fixed Income Strategist**."
            macro_focus = "Focus on Central Bank Policy, Inflation Data (CPI/PPI), Yield Curve, and Economic Cycle. Analyze interest rate expectations and credit spreads."
            asset_name = "bond"
        else: # STOCK
            role_desc = "You are a professional **Macro-Quant Strategist** specializing in **Low-Frequency Swing Trading**."
            macro_focus = "Consider current global macro trends (e.g., Interest Rates, Tech Cycles, Geopolitics) relevant to this stock. Analyze fundamentals like earnings, valuation, and sector rotation."
            asset_name = "stock"

        # Build Position Context
        position_context = ""
        if current_position:
            qty_info = f"- Quantity: {current_position.get('quantity')}" if current_position.get('quantity') else ""
            cost_info = f"- Avg Cost: {current_position.get('avg_cost')}" if current_position.get('avg_cost') else ""
            
            position_context = f"""
    **CURRENT SYSTEM STATE (CRITICAL - READ FIRST)**:
    - The system IS CURRENTLY HOLDING this asset.
    {qty_info}
    {cost_info}
    - Last Buy Date: {current_position.get('date', 'Unknown')}
    - Last Buy Price: {current_position.get('price', 'Unknown')}
    
    **MANDATORY INSTRUCTION FOR EXISTING POSITION**:
    1. You MUST acknowledge this existing position.
    2. Your primary task is to decide: **HOLD** or **SELL** (or **BUY MORE**).
    3. If you recommend SELLING, specify the price and quantity (percentage).
    """
        else:
            position_context = f"""
    **CURRENT SYSTEM STATE (CRITICAL - READ FIRST)**:
    - The system currently has NO open position (100% Cash).
    - You are actively looking for HIGH-PROBABILITY BUY opportunities.
    
    **MANDATORY INSTRUCTION FOR EMPTY POSITION**:
    1. Your PRIMARY task is to identify NEW BUY signals based on the data.
    2. Be PROACTIVE: If technical indicators show a clear trend reversal, breakout, or oversold bounce with volume confirmation, you SHOULD recommend a BUY.
    3. Only recommend WAIT if:
       - The trend is clearly bearish with no reversal signs.
       - The {asset_name} is in a consolidation phase with no clear direction.
       - Risk/reward is unfavorable (e.g., near resistance with weak momentum).
    4. When recommending BUY, specify the entry price and suggested position size (quantity_percent: 30-100).
    5. Remember: The goal is to CAPTURE TRENDS, not to avoid all risk. Calculated risk-taking is part of swing trading.
    """

        prompt = f"""
{role_desc}
Your goal is to generate alpha by combining **Technical Precision** (Price/Volume/Indicators) with **Macro/Fundamental Insight**.

**ASSET TYPE**: {asset_type} ({asset_name})
**IMPORTANT**: This is a {asset_name} analysis. Use {asset_name}-specific terminology and avoid metrics that don't apply to this asset class.

**CORE PHILOSOPHY:**
"Price action reflects all known information, but understanding the Macro Context explains the 'Why' behind the moves."

**TASK:**
Analyze the historical data for this {asset_type} ({symbol}) to identify high-probability Buying and Selling points.

**ANALYSIS FRAMEWORK:**
1. **Quantitative (70%)**: Rigorous analysis of Price, Volume, and Trends (MA5, MA20, RSI) provided in the data.
2. **Macro & Fundamental (30%)**:
   - Use your **internal knowledge** about this specific {asset_name} ({symbol}).
   - {macro_focus}
   - If the asset is unknown to you, infer "Smart Money" sentiment strictly from Volume/Price divergence.

**STRATEGY GUIDELINES: SWING TRADING**
1. **Timeframe**: Aim for multi-week trends (2 weeks to 1 month). Avoid daily noise.
2. **Entry Philosophy**: 
   - When EMPTY: Be OPPORTUNISTIC. Look for clear technical setups (trend reversals, breakouts, oversold bounces).
   - When HOLDING: Be DISCIPLINED. Protect profits and cut losses based on technical breakdown.
3. **Risk Management**: 
   - For BUY signals: Suggest position size (30-100% of available capital based on conviction).
   - For SELL signals: Specify exit percentage (25-100% based on severity).
4. **Conviction Levels**:
   - HIGH (100% position): Strong trend + volume + macro tailwind.
   - MEDIUM (50-70%): Good setup but some uncertainty.
   - LOW (30-40%): Speculative or early-stage signal.

{position_context}

**ANALYSIS INPUTS:**
- **Price Data**: Open, High, Low, Close, Volume.
- **Indicators**: MA5 (Short-term), MA20 (Medium-term), RSI (Momentum).

**INSTRUCTIONS:**
1. **Trend Analysis**: Assess the trend direction using MA alignment and Price Action.
2. **Volume Analysis**: Confirm moves with volume (e.g., high volume on breakout).
3. **Holistic Reasoning**: In your "reason" and "analysis_summary", you MUST weave in macro/sector logic where appropriate (e.g., "Tech sector correction," "Oversold bounce amidst positive sector news").
4. **Trade Identification**:
   - List specific TRADES based on historical data.
   - **RESPECT CURRENT STATE**: 
     * If HOLDING: Focus on whether to HOLD, SELL, or BUY MORE.
     * If EMPTY: Evaluate if current market conditions warrant a NEW BUY. Be proactive but not reckless.
   - If the last action is a BUY and no Sell signal has occurred, mark status as "HOLDING".
5. **Current Action (MANDATORY)**:
   - You MUST provide a "current_action" based on the LATEST data point.
   - For EMPTY positions: Choose between "BUY" (with conviction level via quantity_percent) or "WAIT" (with clear reason why not buying).
   - For HOLDING positions: Choose between "HOLD", "SELL", or "BUY MORE".
   - **CRITICAL**: If you see a valid technical setup (e.g., MA crossover, RSI reversal from oversold, breakout with volume), you SHOULD recommend BUY. Don't be overly cautious.
6. **Latest Data Handling**: If the latest data point is today (incomplete candle), use it as the current price for decision making.

**LANGUAGE**: {lang_instruction}

**OUTPUT FORMAT (Strict JSON)**:
{{
    "analysis_summary": "Strategic summary integrating Technical Trend, Volume Profile, and Macro/Sector Outlook.",
    "trades": [
        {{
            "buy_date": "YYYY-MM-DD",
            "buy_price": 123.45,
            "sell_date": "YYYY-MM-DD", 
            "sell_price": 145.67, 
            "status": "CLOSED", 
            "holding_period": "15 days",
            "return_rate": "+18.0%",
            "reason": "Brief rationale for BUY",
            "sell_reason": "Brief rationale for SELL"
        }}
    ],
    "current_action": {{
        "action": "BUY" | "SELL" | "HOLD" | "WAIT",
        "price": 123.45,
        "quantity_percent": 50,
        "reason": "Brief reason for the action."
    }}
}}
Return ONLY the JSON.
Data:
{csv_data}
"""
        try:
            # Start timing
            start_time = time.time()
            config = get_model_config(model_name)
            print(f"\n{'='*60}")
            print(f"[LLM DEBUG] Starting analysis")
            print(f"  Symbol: {symbol}")
            print(f"  Model: {model_name}")
            print(f"  Provider: {config.get('provider', 'unknown')}")
            print(f"  Language: {language}")
            print(f"  Data points: {len(kline_data)}")
            print(f"  Position: {'HOLDING' if current_position else 'EMPTY'}")
            
            # Use unified adapter interface
            text, usage = adapter.generate(prompt)
            
            # End timing
            elapsed_time = time.time() - start_time
            
            if not text:
                raise ValueError("Empty response from AI model")

            # Robust JSON extraction using regex
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
            else:
                # Attempt cleanup just in case
                text = text.replace('```json', '').replace('```', '').strip()
            
            result = json.loads(text)
            
            signals = []
            # 处理 current_action - 只有 BUY/SELL 才添加到 signals（在 K 线图上显示）
            # WAIT/HOLD 不添加到 signals，而是保留在 current_action 中供摘要显示
            current_action = result.get('current_action')
            if current_action:
                action_type = current_action.get('action')
                if action_type in ['BUY', 'SELL']:  # 只有 BUY/SELL 才在 K 线图上显示
                    signal_data = {
                        "type": action_type,
                        "date": kline_data[-1]['date'], # 使用最新日期
                        "price": current_action.get('price') or kline_data[-1].get('close'),
                        "reason": current_action.get('reason'),
                        "is_current": True  # 标记为当前建议
                    }
                    if current_action.get('quantity_percent'):
                        signal_data['quantity_percent'] = current_action.get('quantity_percent')
                    signals.append(signal_data)

            # 注意：AI 输出的 trades 只是对历史数据的回顾分析，不是实际建议
            # 因此不添加到 signals 中（不在 K 线图上显示）
            # 真实的用户交易记录由前端从 user_transactions 读取并显示为"真买"/"真卖"
            
            result['signals'] = signals
            result['source'] = 'ai_model'
            
            # Print success log
            print(f"[LLM DEBUG] ✅ Analysis completed successfully")
            print(f"  Total time: {elapsed_time:.2f}s")
            print(f"  Trades found: {len(result.get('trades', []))}")
            print(f"  Signals found: {len(signals)}")
            print(f"  Response length: {len(text)} chars")
            if usage:
                print(f"  Token usage: input={usage.get('input_tokens', 'N/A')}, output={usage.get('output_tokens', 'N/A')}")
            print(f"{'='*60}\n")
            
            return result
            
        except Exception as e:
            error_msg = str(e)
            elapsed_time = time.time() - start_time if 'start_time' in locals() else 0
            
            print(f"[LLM DEBUG] ❌ Analysis failed")
            print(f"  Total time: {elapsed_time:.2f}s")
            print(f"  Error: {error_msg}")
            print(f"  Fallback: Using local strategy (MA+RSI)")
            print(f"{'='*60}\n")
            
            # Handle 429 Resource Exhausted specifically
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                if language == 'zh':
                    friendly_msg = "API 配额已用尽"
                else:
                    friendly_msg = "API quota exhausted"
                return TechnicalStrategy.analyze(enriched_data, error_msg=friendly_msg, language=language)
            
            # Generic error handling
            if language == 'zh':
                friendly_msg = "AI 服务暂时不可用"
            else:
                friendly_msg = "AI service temporarily unavailable"
            return TechnicalStrategy.analyze(enriched_data, error_msg=friendly_msg, language=language)

    def analyze_incremental(self, symbol, kline_data, last_analyzed_date, model_name="gemini-3-flash-preview", language="zh"):
        """
        Analyze ONLY the new data points since last_analyzed_date.
        Uses full history context but only outputs signals for new dates.
        """
        if not self.client:
             self._configure_client()
             
        # Filter new data
        # We need to provide enough context (e.g., 60 days) + new data
        # But we only want signals for dates > last_analyzed_date
        
        # This implementation is tricky because the standard prompt asks for FULL history trades.
        # To "patch" history, we can either:
        # 1. Ask AI to analyze just the recent window and output signals for specific dates.
        # 2. Run full analysis (as done in api.py currently) and filter.
        
        # Since I implemented the logic in api.py to call 'analyze' and filter, 
        # this method might be redundant if we just reuse 'analyze'.
        # However, for efficiency, a targeted prompt is better if the gap is small.
        # But given 1M token context, sending full history is fine and more accurate for trends.
        
        # For now, we will rely on the `analyze` method to generate the full view, 
        # and the API layer handles the persistence filtering.
        # This avoids maintaining two different complex prompts.
        pass


    def recommend_stocks(self, criteria, model_name="gemini-3-flash-preview", language="zh"):
        """
        Recommend stocks based on criteria and live market data.
        Uses Google Search for models that support it.
        """
        # Get model adapter
        adapter = self._get_adapter(model_name)
        if not adapter or not adapter.is_available():
            return {"error": "API Key Unavailable", "recommendations": []}
        
        config = get_model_config(model_name)
        
        lang_instruction = "Respond in Chinese (Simplified)." if language == 'zh' else "Respond in English."
        
        asset_type = criteria.get('asset_type', 'STOCK')
        include_etf = criteria.get('include_etf', 'false') == 'true'
        
        # Asset Type Instruction
        asset_instruction = ""
        if asset_type == 'CRYPTO':
            asset_instruction = """
        **ASSET FOCUS: CRYPTOCURRENCIES**
        - Recommend top cryptocurrencies or tokens (e.g., BTC-USD, ETH-USD, SOL-USD).
        - Focus on On-chain activity, adoption trends, and technical breakouts.
        - Consider market cap, liquidity, and regulatory environment.
        - DO NOT recommend stocks or other asset types.
        """
        elif asset_type == 'COMMODITY':
            asset_instruction = """
        **ASSET FOCUS: COMMODITIES**
        - Recommend commodities (Gold GC=F, Oil CL=F, Silver SI=F, etc.) or related ETFs/Futures.
        - Focus on Supply/Demand imbalances, inventory levels, and Macro trends.
        - Consider seasonal patterns, geopolitical risks, and currency impacts.
        - DO NOT recommend stocks or other asset types.
        """
        elif asset_type == 'BOND':
            asset_instruction = """
        **ASSET FOCUS: BONDS / FIXED INCOME**
        - Recommend Government Bonds (US Treasuries like ^TNX, ^IRX, ^TYX) or High-Grade Corporate Bond ETFs.
        - Focus on Yield levels, Interest Rate Policy, and Economic Data.
        - Consider duration risk, credit quality, and yield curve positioning.
        - DO NOT recommend stocks or other asset types.
        """
        elif asset_type == 'FUND_CN':
            asset_instruction = """
        **ASSET FOCUS: CHINESE FUNDS (中国基金)**
        - Recommend Chinese mutual funds or ETFs (e.g., 015283, 159941, 510300).
        - Focus on fund performance, management quality, and investment themes.
        - Consider fund type (equity, bond, hybrid), expense ratio, and historical returns.
        - Provide 6-digit fund codes (e.g., 015283 for 恒生科技ETF联接).
        - DO NOT recommend individual stocks, crypto, or other asset types.
        """
        else:
            # Stock-specific instruction with ETF toggle
            etf_instruction = ""
            if include_etf:
                etf_instruction = "\n        - You MAY include ETFs (Exchange-Traded Funds) alongside individual stocks.\n        - ETFs should be relevant to current market themes or sector opportunities."
            else:
                etf_instruction = "\n        - Focus ONLY on individual stocks. DO NOT recommend ETFs.\n        - Recommend specific company stocks, not index funds or ETFs."
            
            asset_instruction = f"""
        **ASSET FOCUS: STOCKS (EQUITIES)**
        - Recommend stocks from various sectors and market caps.
        - Focus on earnings growth, valuation, and sector trends.
        - Consider fundamental metrics like P/E, revenue growth, and profitability.
        - DO NOT recommend crypto, commodities, or bonds.{etf_instruction}
        """

        # 处理市场选择
        market = criteria.get('market', 'Any')
        market_instruction = ""
        if market == 'US':
            market_instruction = """
        **MARKET FOCUS: US MARKETS ONLY**
        - Focus exclusively on US listed assets.
        """
        elif market == 'HK':
            market_instruction = """
        **MARKET FOCUS: HONG KONG MARKETS ONLY**
        - Focus exclusively on Hong Kong listed assets.
        """
        elif market == 'A':
            market_instruction = """
        **MARKET FOCUS: A-SHARES (MAINLAND CHINA) ONLY**
        - Focus exclusively on A-shares market.
        """
        else:
            market_instruction = """
        **MARKET FOCUS: ALL MARKETS**
        - You can recommend assets from any major global market.
        """
        
        # Get current date for prompt
        now = datetime.now()
        current_date = now.strftime('%Y-%m-%d')
        current_date_full = now.strftime('%Y年%m月%d日') if language == 'zh' else now.strftime('%B %d, %Y')
        outdated_year = now.year - 2
        
        search_instruction = f"""
        1. **MANDATORY: Use built-in Web-Search tool or any other similar function to find real-time market trends, sector rotation, and breaking news affecting asset prices as of {current_date} (TODAY).
        2. **CRITICAL**: For every recommended asset, you MUST use Search to find its **current real-time price** (or latest close as of {current_date}). Do NOT guess prices. Do NOT use prices from {outdated_year} or earlier.
        3. **DATE VERIFICATION**: When searching for market data, ensure you are getting information from {current_date} or the most recent trading day. Reject any data that appears to be from {outdated_year} or earlier."""
        prompt = f"""
        You are a professional financial advisor and quantitative analyst.
        
        ═══════════════════════════════════════════════════════════════
        ⚠️  CRITICAL INSTRUCTION - READ THIS FIRST ⚠️
        ═══════════════════════════════════════════════════════════════
        
        📅 CURRENT DATE: {current_date} ({current_date_full})
        ⚠️  IMPORTANT: Today is {current_date}. You MUST provide recommendations based on the LATEST market data as of {current_date}. 
        ⚠️  DO NOT use outdated data from {outdated_year} or earlier. All prices, news, and market information MUST be current as of {current_date}.
        
        ASSET TYPE REQUIREMENT: {asset_type}
        
        You MUST recommend ONLY {asset_type} assets. 
        
        ❌ DO NOT recommend:
        {self._get_forbidden_assets(asset_type)}
        
        ✅ ONLY recommend: {self._get_allowed_assets(asset_type)}
        
        If you recommend ANY asset that is NOT a {asset_type}, your response will be REJECTED.
        
        ═══════════════════════════════════════════════════════════════
        
        Task: Recommend 10 promising {asset_type} assets for purchase in the near future (next 1-4 weeks) based on market conditions as of {current_date}.
        
        {market_instruction}
        {asset_instruction}
        
        User Criteria:
        - Asset Type: {asset_type} (MANDATORY - DO NOT DEVIATE)
        - Market: {criteria.get('market', 'Any (All markets)')}
        - Capital Size: {criteria.get('capital', 'Not specified')}
        - Risk Tolerance: {criteria.get('risk', 'Not specified')}
        - Trading Frequency: {criteria.get('frequency', 'Not specified')}
        
        Instructions:
        {search_instruction}
        3. Analyze 10 {asset_type} assets based on current market conditions.
        4. **VERIFY EACH RECOMMENDATION**: Before adding any asset to your list, confirm it is a {asset_type}.
        5. **RATING SYSTEM** - Assign a recommendation level based on current market conditions:
           - ⭐⭐⭐ (High Confidence): Strong buy signal, favorable conditions
           - ⭐⭐ (Medium): Moderate opportunity, some risks
           - ⭐ (Speculative): High risk, speculative play
           - ⚠️ (Caution): Neutral/Wait, unclear direction
           - 🔻 (Avoid): Negative outlook, recommend avoiding or selling
           
           **IMPORTANT**: You MUST provide exactly 10 assets, but they don't all need to be positive recommendations.
           If market conditions are poor (bear market, black swan events, political instability), you SHOULD include
           negative ratings (⚠️ or 🔻) to warn users about risks. This is MORE valuable than forcing positive ratings.
        
        6. **LANGUAGE**: {lang_instruction}
        
        ⚠️  FINAL REMINDER: Your recommendations MUST be 100% {asset_type} assets. No exceptions.
        
        Output Format (JSON):
        {{
            "market_overview": "Brief summary of current {asset_type} market sentiment and overall conditions.",
            "recommendations": [
                {{
                    "symbol": "Ticker (e.g. {self._get_example_symbol(asset_type)})",
                    "name": "Asset Name",
                    "price": "Current Price (Approx)",
                    "level": "⭐⭐⭐ or ⭐⭐ or ⭐ or ⚠️ or 🔻",
                    "reason": "Detailed reason citing recent news, technical analysis, or risk factors. For negative ratings, explain why to avoid."
                }}
            ]
        }}
        """
        
        try:
            # Start timing
            start_time = time.time()
            print(f"\n{'='*60}")
            print(f"[LLM DEBUG] Starting stock recommendation")
            print(f"  Model: {model_name}")
            print(f"  Provider: {config.get('provider', 'unknown')}")
            print(f"  Language: {language}")
            print(f"  Asset Type: {asset_type}")
            print(f"  Supports search: {True}")
            print(f"  Criteria: market={criteria.get('market')}, asset_type={asset_type}, capital={criteria.get('capital')}, risk={criteria.get('risk')}, frequency={criteria.get('frequency')}")
            
            # Use unified adapter interface
            text, usage = adapter.generate(prompt, use_search=True)
            
            # End timing
            elapsed_time = time.time() - start_time
            
            if not text:
                raise ValueError(f"Empty response from {model_name} (likely blocked or search-only output)")

            # Robust JSON extraction using regex
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
            else:
                text = text.replace('```json', '').replace('```', '').strip()

            result = json.loads(text)
            
            # Print success log
            print(f"[LLM DEBUG] ✅ Recommendation completed successfully")
            print(f"  Total time: {elapsed_time:.2f}s")
            print(f"  Recommendations: {len(result.get('recommendations', []))}")
            print(f"  Response length: {len(text)} chars")
            if usage:
                print(f"  Token usage: input={usage.get('input_tokens', 'N/A')}, output={usage.get('output_tokens', 'N/A')}")
            print(f"{'='*60}\n")
            
            return result
        except Exception as e:
            elapsed_time = time.time() - start_time if 'start_time' in locals() else 0
            print(f"[LLM DEBUG] ❌ Recommendation failed")
            print(f"  Total time: {elapsed_time:.2f}s")
            print(f"  Error: {str(e)}")
            print(f"{'='*60}\n")
            # Fallback mock data if search fails or quota exceeded
            return {
                "market_overview": "Market data unavailable (Error). Showing sample data.",
                "recommendations": [
                    {"symbol": "MOCK", "name": "Sample Stock", "price": "100.00", "level": "⭐", "reason": f"Error: {str(e)}"}
                ]
            }

    def analyze_portfolio_item(self, holding_data, model_name="gemini-3-flash-preview", language="zh"):
        """
        Analyze a specific holding and provide advice (Buy/Sell/Hold).
        """
        # Get model adapter
        adapter = self._get_adapter(model_name)
        if not adapter or not adapter.is_available():
            return {"error": "API Key Unavailable", "symbol": holding_data.get('symbol')}
        
        config = get_model_config(model_name)
        supports_search = config.get('supports_search', False)
            
        symbol = holding_data.get('symbol')
        avg_price = holding_data.get('avg_price', 'Unknown')
        percentage_val = holding_data.get('percentage')
        percentage_str = f"{percentage_val}%" if percentage_val is not None else "Unknown"
        asset_type = holding_data.get('asset_type', 'STOCK')
        
        lang_instruction = "Respond in Chinese (Simplified)." if language == 'zh' else "Respond in English."
        
        # Asset-specific analysis guidance
        asset_guidance = ""
        if asset_type == "CRYPTO":
            asset_guidance = """
        **CRYPTO ANALYSIS GUIDANCE**:
        - Focus on on-chain metrics, adoption trends, and regulatory news.
        - Consider market sentiment, whale movements, and exchange flows.
        - Avoid traditional equity metrics (P/E, dividends, etc.).
        - Assess volatility risk and correlation with Bitcoin.
        """
        elif asset_type == "COMMODITY":
            asset_guidance = """
        **COMMODITY ANALYSIS GUIDANCE**:
        - Focus on supply/demand fundamentals and inventory levels.
        - Consider geopolitical risks, weather patterns, and production data.
        - Analyze dollar strength (DXY) impact on commodity prices.
        - Assess seasonal trends and storage costs.
        """
        elif asset_type == "BOND":
            asset_guidance = """
        **BOND ANALYSIS GUIDANCE**:
        - Focus on interest rate expectations and central bank policy.
        - Consider inflation data (CPI/PPI) and economic growth indicators.
        - Analyze yield curve positioning and duration risk.
        - Assess credit quality and default risk (if corporate bonds).
        """
        else:  # STOCK
            asset_guidance = """
        **STOCK ANALYSIS GUIDANCE**:
        - Focus on earnings growth, valuation metrics (P/E, P/S), and profitability.
        - Consider sector trends, competitive positioning, and management quality.
        - Analyze dividend yield and payout sustainability (if applicable).
        - Assess technical levels and institutional ownership.
        """
        
        search_instruction = ""
        if supports_search:
            search_instruction = f"1. **Use Google Search or Web Search** to check the latest price and news for this {asset_type} ({symbol})."
        else:
            search_instruction = f"1. Based on your knowledge, analyze the current situation for this {asset_type} ({symbol})."
        
        prompt = f"""
        You are a portfolio manager analyzing a client's {asset_type} holding.
        
        **ASSET TYPE**: {asset_type}
        **IMPORTANT**: Use {asset_type}-specific analysis framework. Do not apply stock-specific metrics to non-stock assets.
        
        Holding Details:
        - Symbol: {symbol}
        - Asset Type: {asset_type}
        - Average Buy Price: {avg_price}
        - Portfolio Weight: {percentage_str}
        
        {asset_guidance}
        
        Instructions:
        {search_instruction}
        2. Analyze if they should Hold, Buy More, or Sell based on:
           - Current price vs average buy price
           - Market outlook for this {asset_type}
           - Risk/reward at current levels
           - Portfolio weight appropriateness
        3. Provide a rating: "Strong Buy", "Buy", "Hold", "Sell", "Strong Sell".
        4. **LANGUAGE**: {lang_instruction}
        
        Output Format (JSON):
        {{
            "symbol": "{symbol}",
            "current_price": "Latest price found",
            "rating": "Hold",
            "action": "Detailed advice (e.g. 'Hold for recovery', 'Cut losses', 'Take profit').",
            "analysis": "Reasoning based on news and valuation."
        }}
        """
        
        try:
            # Start timing
            start_time = time.time()
            print(f"\n{'='*60}")
            print(f"[LLM DEBUG] Starting portfolio diagnosis")
            print(f"  Model: {model_name}")
            print(f"  Provider: {config.get('provider', 'unknown')}")
            print(f"  Language: {language}")
            print(f"  Symbol: {symbol}")
            print(f"  Avg Price: {avg_price}, Weight: {percentage}%")
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
            print(f"[LLM DEBUG] ✅ Portfolio diagnosis completed successfully")
            print(f"  Total time: {elapsed_time:.2f}s")
            print(f"  Rating: {result.get('rating', 'N/A')}")
            print(f"  Response length: {len(text)} chars")
            if usage:
                print(f"  Token usage: input={usage.get('input_tokens', 'N/A')}, output={usage.get('output_tokens', 'N/A')}")
            print(f"{'='*60}\n")
            
            return result
        except Exception as e:
            elapsed_time = time.time() - start_time if 'start_time' in locals() else 0
            print(f"[LLM DEBUG] ❌ Portfolio diagnosis failed")
            print(f"  Total time: {elapsed_time:.2f}s")
            print(f"  Error: {str(e)}")
            print(f"{'='*60}\n")
            return {
                "symbol": symbol,
                "rating": "Unknown",
                "action": "Error analyzing position.",
                "analysis": str(e)
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
        
        prompt = f"""
You are an experienced investment master with decades of experience and deep market insight. A client has shown you their complete investment portfolio. Please act as a professional investment advisor to conduct a comprehensive analysis and evaluation of the entire holding.

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

4. Evaluate comprehensively from the following dimensions:
   - **Asset Allocation**: Evaluate if the allocation across different asset types is reasonable, or if it's too concentrated/diversified.
   - **Risk Assessment**: Analyze the overall risk level, including market risk, concentration risk, liquidity risk, etc.
   - **Performance**: Evaluate current P&L, identifying which positions are performing well and which need attention.
   - **Market Adaptability**: Assess the portfolio's adaptability in the context of the current macro environment and market trends.
   - **Optimization Suggestions**: Provide specific adjustment suggestions, including Buy More, Sell, Hold, or Close positions.

5. Provide an Overall Rating:
   - "Excellent": Reasonable allocation, controlled risk, good returns.
   - "Good": Overall good, but room for improvement.
   - "Fair": Obvious issues, needs adjustment.
   - "Poor": Unreasonable allocation, high risk.
   - "Critical": Serious issues, needs immediate adjustment.

6. **Language Requirement**: {lang_instruction}

**Output Format (JSON):**
{{
    "overall_rating": "Good",
    "total_score": 75,
    "risk_level": "Medium",
    "asset_allocation_analysis": "Analysis of asset allocation...",
    "performance_analysis": "Analysis of performance...",
    "risk_analysis": "Risk assessment...",
    "market_outlook": "Market outlook...",
    "recommendations": [
        {{
            "symbol": "Symbol (e.g., 015283)",
            "asset_name": "REAL asset name found via search (e.g., 恒生科技ETF联接)",
            "action": "Buy More/Sell/Hold/Close",
            "reason": "Specific reason based on actual asset information"
        }}
    ],
    "summary": "Overall evaluation and core suggestions..."
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
