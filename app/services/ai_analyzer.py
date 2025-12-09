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

    def analyze(self, symbol, kline_data, model_name="gemini-2.5-flash", language="zh", current_position=None):
        """
        Analyze K-line data using AI models to find buy/sell points.
        Supports: Gemini, GPT, Claude, Grok, Qwen
        :param current_position: Optional dict { 'date': 'YYYY-MM-DD', 'price': float, 'reason': str } indicating last BUY signal.
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

        # Build Position Context
        position_context = ""
        if current_position:
            position_context = f"""
    **CURRENT SYSTEM STATE (CRITICAL - READ FIRST)**:
    - The system IS CURRENTLY HOLDING this stock.
    - Last Buy Date: {current_position['date']}
    - Last Buy Price: {current_position['price']}
    - Original Reason: {current_position.get('reason', 'N/A')}
    
    **MANDATORY INSTRUCTION FOR EXISTING POSITION**:
    1. You MUST acknowledge this existing BUY at the start of your history analysis.
    2. Do NOT recommend a new BUY until this position is closed (SOLD).
    3. Your primary task for the latest data points is to decide: **HOLD** or **SELL**.
    4. If the position is still valid (trend intact), output the last trade as "HOLDING".
    5. If a sell signal occurred AFTER the buy date, output the SELL trade.
    """
        else:
            position_context = """
    **CURRENT SYSTEM STATE**:
    - The system currently has NO open position (Cash).
    - Your task is to identify potential NEW BUY signals or remain in Cash (Wait).
    """

        prompt = f"""
You are a professional **Macro-Quant Strategist** specializing in **Low-Frequency Swing Trading**.
Your goal is to generate alpha by combining **Technical Precision** (Price/Volume/Indicators) with **Macro/Fundamental Insight**.

**CORE PHILOSOPHY:**
"Price action reflects all known information, but understanding the Macro Context explains the 'Why' behind the moves."

**TASK:**
Analyze the historical data for stock ({symbol}) to identify high-probability Buying and Selling points.

**ANALYSIS FRAMEWORK:**
1. **Quantitative (70%)**: Rigorous analysis of Price, Volume, and Trends (MA5, MA20, RSI) provided in the data.
2. **Macro & Fundamental (30%)**:
   - Use your **internal knowledge** about this specific stock ({symbol}) and its sector/industry.
   - Consider current global macro trends (e.g., Interest Rates, Tech Cycles, Geopolitics) relevant to this asset.
   - If the stock is unknown to you, infer "Smart Money" sentiment strictly from Volume/Price divergence.

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
            "reason": "Brief technical rationale (e.g. MA Golden Cross)."
        }}
    ]
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
            for trade in result.get('trades', []):
                signals.append({
                    "type": "BUY",
                    "date": trade['buy_date'],
                    "price": trade['buy_price'],
                    "reason": trade['reason']
                })
                if trade['status'] == 'CLOSED' and trade['sell_date']:
                    signals.append({
                        "type": "SELL",
                        "date": trade['sell_date'],
                        "price": trade['sell_price'],
                        "reason": "Close position"
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

    def analyze_incremental(self, symbol, kline_data, last_analyzed_date, model_name="gemini-2.5-flash", language="zh"):
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


    def recommend_stocks(self, criteria, model_name="gemini-2.5-flash", language="zh"):
        """
        Recommend stocks based on criteria and live market data.
        Uses Google Search for models that support it.
        """
        # Get model adapter
        adapter = self._get_adapter(model_name)
        if not adapter or not adapter.is_available():
            return {"error": "API Key Unavailable", "recommendations": []}
        
        config = get_model_config(model_name)
        supports_search = config.get('supports_search', False)
        
        lang_instruction = "Respond in Chinese (Simplified)." if language == 'zh' else "Respond in English."
        
        # Adjust prompt based on search capability
        search_instruction = ""
        if supports_search:
            search_instruction = """
        1. **MANDATORY: Use Google Search or Web Search** to find real-time market trends, sector rotation (US, HK, or A-shares), and breaking news affecting stock prices TODAY.
        2. **CRITICAL**: For every recommended stock, you MUST use Search to find its **current real-time price** (or latest close). Do NOT guess prices."""
        else:
            search_instruction = """
        1. Based on your training data and market knowledge, identify promising stocks with strong technical or fundamental catalysts.
        2. Provide approximate current prices based on your latest knowledge."""

        prompt = f"""
        You are a professional financial advisor and quantitative analyst.
        Task: Recommend 10 promising stocks for purchase in the near future (next 1-4 weeks).
        
        User Criteria:
        - Capital Size: {criteria.get('capital', 'Not specified')}
        - Risk Tolerance: {criteria.get('risk', 'Not specified')}
        - Trading Frequency: {criteria.get('frequency', 'Not specified')}
        
        Instructions:
        {search_instruction}
        3. Select 10 stocks that currently show strong technical setups or fundamental catalysts.
        4. Ensure the recommendations are diverse if no specific market is implied, or focus on the most actionable ones.
        5. Assign a recommendation strength: "High Confidence" (⭐⭐⭐), "Medium" (⭐⭐), or "Speculative" (⭐).
        6. **LANGUAGE**: {lang_instruction}
        
        Output Format (JSON):
        {{
            "market_overview": "Brief summary of current market sentiment (e.g., Bullish on Tech, Bearish on Energy).",
            "recommendations": [
                {{
                    "symbol": "Ticker (e.g. NVDA, 0700.HK)",
                    "name": "Company Name",
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
            print(f"  Supports search: {supports_search}")
            print(f"  Criteria: capital={criteria.get('capital')}, risk={criteria.get('risk')}, frequency={criteria.get('frequency')}")
            
            # Use unified adapter interface
            text, usage = adapter.generate(prompt, use_search=supports_search)
            
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

    def analyze_portfolio_item(self, holding_data, model_name="gemini-2.5-flash", language="zh"):
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
        
        lang_instruction = "Respond in Chinese (Simplified)." if language == 'zh' else "Respond in English."
        
        search_instruction = ""
        if supports_search:
            search_instruction = "1. **Use Google Search or Web Search** to check the latest price and news for " + symbol + "."
        else:
            search_instruction = "1. Based on your knowledge, analyze the current situation for " + symbol + "."
        
        prompt = f"""
        You are a portfolio manager. A client holds {symbol}.
        
        Holding Details:
        - Symbol: {symbol}
        - Average Buy Price: {avg_price}
        - Portfolio Weight: {percentage}
        
        Instructions:
        {search_instruction}
        2. Analyze if they should Hold, Buy More, or Sell based on current price vs avg price and market outlook.
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

    def translate_text(self, text, target_language="en", model_name="gemini-2.5-flash"):
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
