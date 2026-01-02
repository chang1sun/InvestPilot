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
        csv_data = "Date,Open,High,Low,Close,Volume,MA5,MA20,RSI\n"
        for d in enriched_data:
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
            position_context = f"""
    **CURRENT SYSTEM STATE (CRITICAL - READ FIRST)**:
    - The system IS CURRENTLY HOLDING this asset.
    - Quantity: {current_position.get('quantity', 'Unknown')}
    - Avg Cost: {current_position.get('avg_cost', 'Unknown')}
    - Last Buy Date: {current_position['date']}
    - Last Buy Price: {current_position['price']}
    
    **MANDATORY INSTRUCTION FOR EXISTING POSITION**:
    1. You MUST acknowledge this existing position.
    2. Your primary task is to decide: **HOLD** or **SELL** (or **BUY MORE**).
    3. If you recommend SELLING, specify the price and quantity (percentage).
    """
        else:
            position_context = """
    **CURRENT SYSTEM STATE**:
    - The system currently has NO open position (Cash).
    - Your task is to identify potential NEW BUY signals or remain in Cash (Wait).
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
2. **Entry**: Buy on confirmed trend reversals or strong breakouts supported by Volume or Macro catalysts.
3. **Exit**: Sell on technical breakdown or clear trend exhaustion.

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
   - **RESPECT CURRENT STATE**: If "CURRENT SYSTEM STATE" indicates a HOLDING position, your analysis for the latest dates must focus on whether to HOLD or SELL. Do not suggest a new BUY until the existing one is closed.
   - If the last action is a BUY and no Sell signal has occurred, mark status as "HOLDING".
5. **Latest Data Handling**: If the latest data point is today (incomplete candle), use it as the current price for decision making.

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
            "reason": "Brief technical rationale for BUY (e.g. MA Golden Cross).",
            "sell_reason": "Brief technical rationale for SELL (e.g. Trend exhaustion, Stop loss)."
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
            # 处理 current_action
            current_action = result.get('current_action')
            if current_action:
                action_type = current_action.get('action')
                if action_type in ['BUY', 'SELL']:
                    signals.append({
                        "type": action_type,
                        "date": kline_data[-1]['date'], # 使用最新日期
                        "price": current_action.get('price'),
                        "reason": current_action.get('reason'),
                        "quantity_percent": current_action.get('quantity_percent')
                    })

            for trade in result.get('trades', []):
                signals.append({
                    "type": "BUY",
                    "date": trade['buy_date'],
                    "price": trade['buy_price'],
                    "reason": trade['reason']
                })
                if trade['status'] == 'CLOSED' and trade['sell_date']:
                    # 使用 AI 给出的原因，如果有 sell_reason 则优先使用，否则使用 reason
                    sell_reason = trade.get('sell_reason') or trade.get('reason', 'Close position')
                    signals.append({
                        "type": "SELL",
                        "date": trade['sell_date'],
                        "price": trade['sell_price'],
                        "reason": sell_reason
                    })
            
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
        else:
            asset_instruction = """
        **ASSET FOCUS: STOCKS (EQUITIES)**
        - Recommend stocks from various sectors and market caps.
        - Focus on earnings growth, valuation, and sector trends.
        - Consider fundamental metrics like P/E, revenue growth, and profitability.
        - DO NOT recommend crypto, commodities, or bonds.
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
        current_date = datetime.now().strftime('%Y-%m-%d')
        current_date_full = datetime.now().strftime('%Y年%m月%d日') if language == 'zh' else datetime.now().strftime('%B %d, %Y')
        
        search_instruction = f"""
        1. **MANDATORY: Use built-in Web-Search tool or any other similar function to find real-time market trends, sector rotation, and breaking news affecting asset prices as of {current_date} (TODAY).
        2. **CRITICAL**: For every recommended asset, you MUST use Search to find its **current real-time price** (or latest close as of {current_date}). Do NOT guess prices. Do NOT use prices from 2024 or earlier.
        3. **DATE VERIFICATION**: When searching for market data, ensure you are getting information from {current_date} or the most recent trading day. Reject any data that appears to be from 2024 or earlier."""
        prompt = f"""
        You are a professional financial advisor and quantitative analyst.
        
        ═══════════════════════════════════════════════════════════════
        ⚠️  CRITICAL INSTRUCTION - READ THIS FIRST ⚠️
        ═══════════════════════════════════════════════════════════════
        
        📅 CURRENT DATE: {current_date} ({current_date_full})
        ⚠️  IMPORTANT: Today is {current_date}. You MUST provide recommendations based on the LATEST market data as of {current_date}. 
        ⚠️  DO NOT use outdated data from 2024 or earlier. All prices, news, and market information MUST be current as of {current_date}.
        
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
        3. Select 10 {asset_type} assets that currently show strong technical setups or fundamental catalysts.
        4. **VERIFY EACH RECOMMENDATION**: Before adding any asset to your list, confirm it is a {asset_type}.
        5. Assign a recommendation strength: "High Confidence" (⭐⭐⭐), "Medium" (⭐⭐), or "Speculative" (⭐).
        6. **LANGUAGE**: {lang_instruction}
        
        ⚠️  FINAL REMINDER: Your recommendations MUST be 100% {asset_type} assets. No exceptions.
        
        Output Format (JSON):
        {{
            "market_overview": "Brief summary of current {asset_type} market sentiment.",
            "recommendations": [
                {{
                    "symbol": "Ticker (e.g. {self._get_example_symbol(asset_type)})",
                    "name": "Asset Name",
                    "price": "Current Price (Approx)",
                    "level": "⭐⭐⭐",
                    "reason": "Detailed reason citing recent news or technical breakout."
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
        avg_price = holding_data.get('avg_price')
        percentage = holding_data.get('percentage')
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
        - Portfolio Weight: {percentage}%
        
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
            quantity = portfolio.get('total_quantity', 0)  # Use total_quantity from Portfolio model
            avg_price = portfolio.get('avg_cost', 0)  # Use avg_cost from Portfolio model
            
            # Calculate current value based on asset type
            # For CASH, current value = quantity (no price needed)
            # For other assets, current value = quantity * avg_price (using cost as proxy for current value)
            if asset_type == 'CASH':
                current_value = quantity
            else:
                current_value = quantity * avg_price
            
            position_cost = portfolio.get('total_cost', quantity * avg_price)
            total_cost += position_cost
            total_value += current_value
            
            positions.append({
                'symbol': symbol,
                'asset_type': asset_type,
                'quantity': quantity,
                'avg_price': avg_price,
                'current_value': current_value,
                'cost': position_cost,
                'pnl': current_value - position_cost,
                'pnl_pct': ((current_value - position_cost) / position_cost * 100) if position_cost > 0 else 0
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
            portfolio_summary += f"""
- {pos['symbol']} ({pos['asset_type']}):
  * Quantity: {pos['quantity']}
  * Avg Price: ${pos['avg_price']:.2f}
  * Current Value: ${pos['current_value']:,.2f}
  * P&L: ${pos['pnl']:,.2f} ({pos['pnl_pct']:+.2f}%)
  * Weight: {weight:.1f}%
"""
        
        lang_instruction = "请用中文（简体）回答。" if language == 'zh' else "Respond in English."
        
        search_instruction = ""
        if supports_search:
            search_instruction = "1. **使用Google搜索或网络搜索**获取这些资产的最新市场信息、新闻和价格。"
        else:
            search_instruction = "1. 基于你的知识，分析这些资产的当前市场状况。"
        
        prompt = f"""
你是一位经验丰富的投资大师，拥有数十年的投资经验和深厚的市场洞察力。现在，一位客户向你展示了他的完整投资组合，请你作为专业的投资顾问，对整个持仓进行全面的分析和评价。

{portfolio_summary}

**分析要求：**
{search_instruction}
2. 从以下维度进行全面评估：
   - **资产配置合理性**：评估不同资产类型的配置比例是否合理，是否过于集中或分散
   - **风险评估**：分析整体持仓的风险水平，包括市场风险、集中度风险、流动性风险等
   - **收益表现**：评价当前的盈亏状况，分析哪些持仓表现良好，哪些需要关注
   - **市场环境适应性**：结合当前宏观经济环境和市场趋势，评估持仓的适应性
   - **优化建议**：提供具体的调整建议，包括增持、减持或平仓的标的

3. 给出整体评级：
   - "优秀"：配置合理，风险可控，收益良好
   - "良好"：整体不错，但有改进空间
   - "一般"：存在明显问题，需要调整
   - "较差"：配置不合理，风险较高
   - "危险"：严重问题，需要立即调整

4. **语言要求**：{lang_instruction}

**输出格式（JSON）：**
{{
    "overall_rating": "良好",
    "total_score": 75,
    "risk_level": "中等",
    "asset_allocation_analysis": "资产配置分析...",
    "performance_analysis": "收益表现分析...",
    "risk_analysis": "风险评估...",
    "market_outlook": "市场展望...",
    "recommendations": [
        {{
            "symbol": "标的代码",
            "action": "增持/减持/持有/平仓",
            "reason": "具体原因"
        }}
    ],
    "summary": "总体评价和核心建议..."
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
