import re
from google import genai
import os
import json
from flask import current_app
from app.utils.quant_math import calculate_indicators
from datetime import datetime
from google.genai import types
from app.services.technical_strategy import TechnicalStrategy

class AIAnalyzer:
    def __init__(self):
        # Initial try with env var, but will retry in analyze() if missing
        self.client = None
        self._configure_client()

    def _configure_client(self):
        # For the new google-genai SDK, we instantiate a Client
        try:
            api_key = os.environ.get('GEMINI_API_KEY')
            if api_key:
                self.client = genai.Client(api_key=api_key)
            else:
                self.client = None
        except Exception as e:
            print(f"Failed to configure Gemini client: {e}")
            self.client = None

    def analyze(self, symbol, kline_data, model_name="gemini-2.5-flash", language="zh"):
        """
        Analyze K-line data using Gemini to find buy/sell points.
        """
        # 1. Preprocess data: Add indicators to help the LLM (also used for local strategy)
        enriched_data = calculate_indicators(kline_data)
        
        # --- DIRECT LOCAL STRATEGY ---
        # If user specifically selected "local-strategy", skip LLM entirely.
        if model_name == "local-strategy":
            return TechnicalStrategy.analyze(enriched_data, error_msg="用户手动选择")

        # Retry configuration if client is missing
        if not self.client:
             self._configure_client()

        if not self.client:
            return TechnicalStrategy.analyze(enriched_data, error_msg="API Key 缺失，自动切换至本地模型")
        
        # 2. Prepare Prompt for LLM
        csv_data = "Date,Open,High,Low,Close,Volume,MA5,MA20,RSI\n"
        for d in enriched_data:
            csv_data += f"{d['date']},{d['open']},{d['high']},{d['low']},{d['close']},{d['volume']},{d['MA5']:.2f},{d['MA20']:.2f},{d['RSI']:.2f}\n"

        # Language specific instruction
        lang_instruction = "Respond in Chinese (Simplified)." if language == 'zh' else "Respond in English."

        prompt = f"""
You are a professional Quantitative Analyst and Trader specializing in **Low-Frequency Swing Trading**.
Your task is to analyze the historical price data of a stock ({symbol}) and identify valid Buying and Selling points based on a comprehensive analysis of **Technical Patterns, Fundamentals (Simulated), and Market Sentiment**.

**STRATEGY FOCUS: LOW FREQUENCY & SWING TRADING**
1. **Hold Duration**: Aim to hold positions for **at least 2 weeks to 1 month** to capture major trends. Avoid short-term noise.
2. **Entry**: Buy only on confirmed trend reversals or strong breakout signals.
3. **Exit**: Sell only when there is a **Strong Technical Sell Signal** (e.g., Trendline break, Major Resistance rejection, Death Cross) or significant trend exhaustion. Do not exit early on minor pullbacks.

**ANALYSIS DIMENSIONS:**
1. **Technical Analysis**: Trend (MA5/MA20), Momentum (RSI), Support/Resistance levels.
2. **Fundamental Context (Simulated)**: Consider hypothetical valuation (PE Ratio), earnings growth trends, and sector performance relevant to this stock's industry.
3. **Sentiment & News**: Factor in potential market sentiment and recent news impact (e.g., product launches, regulatory changes).

Input Data Format: Date, Open, High, Low, Close, Volume, MA5, MA20, RSI
Data Range: Last 3 years.

Instructions:
1. Analyze the trend using Moving Averages (MA5, MA20) and Price Action.
2. Identify key support/resistance levels and RSI overbought/oversold conditions.
3. List specific TRADES. Each trade must consist of a BUY signal and a subsequent SELL signal (if sold).
4. If the last action was a BUY and not yet sold, mark it as "HOLDING".
5. For each trade, provide:
    - Buy Date & Price
    - Sell Date & Price (if sold, else null)
    - Holding Period (e.g. "5 days")
    - Return Rate (percentage, e.g. "+5.2%", "-2.1%", or "Open" if holding)
    - Reason (Brief technical explanation incorporating fundamentals/sentiment where applicable)
6. **LANGUAGE**: {lang_instruction}

Output Format (Strict JSON):
{{
    "analysis_summary": "Comprehensive summary of the stock's trend, including fundamental context and sector outlook.",
    "trades": [
        {{
            "buy_date": "YYYY-MM-DD",
            "buy_price": 123.45,
            "sell_date": "YYYY-MM-DD", 
            "sell_price": 145.67, 
            "status": "CLOSED", 
            "holding_period": "15 days",
            "return_rate": "+18.0%",
            "reason": "Golden Cross entry, exited on RSI overbought."
        }},
        {{
            "buy_date": "YYYY-MM-DD",
            "buy_price": 130.00,
            "sell_date": null,
            "sell_price": null,
            "status": "HOLDING",
            "holding_period": "3 days",
            "return_rate": "Open",
            "reason": "Bounce off support level."
        }}
    ]
}}

Return ONLY the JSON.
IMPORTANT: The trades array must be sorted by buy_date in descending order (newest first).
Data:
{csv_data}
"""
        try:
            # New SDK usage: client.models.generate_content
            response = self.client.models.generate_content(
                model=model_name, 
                contents=prompt
            )
            text = response.text
            
            if not text:
                raise ValueError("Empty response from Gemini")

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
            return result
            
        except Exception as e:
            error_msg = str(e)
            print(f"Gemini Analysis Error: {error_msg}")
            
            # Handle 429 Resource Exhausted specifically
            if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                 friendly_msg = "API 请求过于频繁 (Quota Exceeded)。自动切换至本地量化策略。"
                 return TechnicalStrategy.analyze(enriched_data, error_msg=friendly_msg)
            
            return TechnicalStrategy.analyze(enriched_data, error_msg=error_msg)

    def recommend_stocks(self, criteria, model_name="gemini-2.5-flash", language="zh"):
        """
        Recommend 5 stocks based on criteria and live market data via Google Search.
        """
        if not self.client:
            self._configure_client()
        
        if not self.client:
            return {"error": "API Key Unavailable", "recommendations": []}
        
        lang_instruction = "Respond in Chinese (Simplified)." if language == 'zh' else "Respond in English."

        prompt = f"""
        You are a professional financial advisor and quantitative analyst.
        Task: Recommend 5 promising stocks for purchase in the near future (next 1-4 weeks).
        
        User Criteria:
        - Capital Size: {criteria.get('capital', 'Not specified')}
        - Risk Tolerance: {criteria.get('risk', 'Not specified')}
        - Trading Frequency: {criteria.get('frequency', 'Not specified')}
        
        Instructions:
        1. **MANDATORY: Use Google Search** to find real-time market trends, sector rotation (US, HK, or A-shares), and breaking news affecting stock prices TODAY.
        2. Select 10 stocks that currently show strong technical setups or fundamental catalysts.
        3. Ensure the recommendations are diverse if no specific market is implied, or focus on the most actionable ones.
        4. Assign a recommendation strength: "High Confidence" (⭐⭐⭐), "Medium" (⭐⭐), or "Speculative" (⭐).
        5. **LANGUAGE**: {lang_instruction}
        
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
            response = self.client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                )
            )
            # Manually parse JSON since response_mime_type can't be used with tools
            text = response.text
            
            if not text:
                raise ValueError("Empty response from Gemini (likely blocked or search-only output)")

            # Robust JSON extraction using regex
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
            else:
                text = text.replace('```json', '').replace('```', '').strip()

            return json.loads(text)
        except Exception as e:
            print(f"Recommendation Error: {e}")
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
        if not self.client:
            self._configure_client()
            
        symbol = holding_data.get('symbol')
        avg_price = holding_data.get('avg_price')
        percentage = holding_data.get('percentage')
        
        lang_instruction = "Respond in Chinese (Simplified)." if language == 'zh' else "Respond in English."
        
        prompt = f"""
        You are a portfolio manager. A client holds {symbol}.
        
        Holding Details:
        - Symbol: {symbol}
        - Average Buy Price: {avg_price}
        - Portfolio Weight: {percentage}
        
        Instructions:
        1. **Use Google Search** to check the latest price and news for {symbol}.
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
            response = self.client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                )
            )
            text = response.text
            
            if not text:
                raise ValueError("Empty response from Gemini")

            # Robust JSON extraction
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                text = json_match.group(0)
            else:
                text = text.replace('```json', '').replace('```', '').strip()

            return json.loads(text)
        except Exception as e:
             return {
                "symbol": symbol,
                "rating": "Unknown",
                "action": "Error analyzing position.",
                "analysis": str(e)
            }

    def translate_text(self, text, target_language="en", model_name="gemini-2.5-flash"):
        """
        Translate text to target language using Gemini.
        """
        if not self.client:
            self._configure_client()
            
        prompt = f"""
        Translate the following financial text to {target_language}.
        Keep technical terms accurate.
        Only return the translated text, no intro/outro.
        
        Text:
        {text}
        """
        try:
            response = self.client.models.generate_content(
                model=model_name,
                contents=prompt
            )
            return {"translation": response.text.strip()}
        except Exception as e:
            return {"error": str(e)}
