"""
Agent Tools for AI Function Calling
Defines tools that AI models can call during analysis to fetch real-time data.
"""

import json
from datetime import datetime, timedelta
from app.services.data_provider import DataProvider, batch_fetcher
from app.utils.quant_math import calculate_indicators


# ============================================================
# Tool Definitions (Schema for LLM function calling)
# ============================================================

TOOL_DEFINITIONS = [
    {
        "name": "get_realtime_price",
        "description": "Get the latest real-time price and daily change for a financial asset (stock, crypto, commodity, bond, or Chinese fund).",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Ticker symbol. IMPORTANT — format varies by market: US stocks: ticker only (e.g. AAPL, TSLA, MSFT); HK stocks: 4-digit code + '.HK' (e.g. 0700.HK, 9988.HK, 0005.HK — always 4 digits, pad with leading zeros); A-shares Shanghai: 6-digit code + '.SS' (e.g. 600519.SS, 601318.SS); A-shares Shenzhen: 6-digit code + '.SZ' (e.g. 000858.SZ, 300750.SZ); Crypto: symbol + '-USD' (e.g. BTC-USD, ETH-USD); Commodities: Yahoo Finance format (e.g. GC=F for gold, CL=F for oil); Chinese funds: 6-digit fund code only (e.g. 015283)."
                },
                "asset_type": {
                    "type": "string",
                    "enum": ["STOCK", "CRYPTO", "COMMODITY", "BOND", "FUND_CN"],
                    "description": "The type of asset"
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "get_kline_data",
        "description": "Get historical K-line (OHLCV) data for a symbol. Use this to analyze price trends, support/resistance levels, and patterns.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Ticker symbol. Format: US stocks (AAPL), HK stocks 4-digit+'.HK' (0700.HK), A-shares '.SS'/'.SZ' (600519.SS, 000858.SZ), Crypto (BTC-USD), Commodities (GC=F), CN funds 6-digit (015283)."
                },
                "period": {
                    "type": "string",
                    "enum": ["1mo", "3mo", "6mo", "1y", "3y"],
                    "description": "Time period for historical data. Default: 3mo for short-term, 1y for swing trading."
                },
                "asset_type": {
                    "type": "string",
                    "enum": ["STOCK", "CRYPTO", "COMMODITY", "BOND", "FUND_CN"],
                    "description": "The type of asset"
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "calculate_technical_indicators",
        "description": "Calculate technical indicators (MA5, MA20, RSI14) for a single symbol. For multiple symbols, use batch_calculate_technical_indicators instead.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Ticker symbol (must match the exact symbol used in get_kline_data). Format: US stocks (AAPL), HK stocks 4-digit+'.HK' (0700.HK), A-shares '.SS'/'.SZ' (600519.SS, 000858.SZ), Crypto (BTC-USD), CN funds 6-digit (015283)."
                },
                "period": {
                    "type": "string",
                    "enum": ["1mo", "3mo", "6mo", "1y", "3y"],
                    "description": "Period of data to analyze (should match get_kline_data call)"
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "batch_calculate_technical_indicators",
        "description": "Calculate technical indicators (MA5, MA20, RSI14) for multiple symbols in a single call. Much more efficient than calling calculate_technical_indicators repeatedly.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of ticker symbols (max 10). Use correct format for each market: US stocks (AAPL), HK stocks 4-digit+'.HK' (0700.HK), A-shares '.SS'/'.SZ' (600519.SS, 000858.SZ), Crypto (BTC-USD), CN funds 6-digit (015283)."
                },
                "period": {
                    "type": "string",
                    "enum": ["1mo", "3mo", "6mo", "1y", "3y"],
                    "description": "Period of data to analyze. Default: 3mo"
                }
            },
            "required": ["symbols"]
        }
    },
    {
        "name": "get_portfolio_holdings",
        "description": "Get the user's current portfolio holdings including all positions, quantities, average costs, and allocation percentages. Use this to understand the user's investment context.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_transaction_history",
        "description": "Get the user's transaction history for a specific symbol. Shows all buy/sell records with dates, prices, and quantities.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "Ticker symbol to get transactions for. Format: US stocks (AAPL), HK stocks 4-digit+'.HK' (0700.HK), A-shares '.SS'/'.SZ' (600519.SS, 000858.SZ), Crypto (BTC-USD), CN funds 6-digit (015283)."
                }
            },
            "required": ["symbol"]
        }
    },
    {
        "name": "get_exchange_rate",
        "description": "Get the current exchange rate between two currencies.",
        "parameters": {
            "type": "object",
            "properties": {
                "from_currency": {
                    "type": "string",
                    "description": "Source currency code (e.g., CNY, HKD, EUR)"
                },
                "to_currency": {
                    "type": "string",
                    "description": "Target currency code (default: USD)"
                }
            },
            "required": ["from_currency"]
        }
    },
    {
        "name": "compare_assets",
        "description": "Compare real-time prices and recent performance of multiple assets side by side. Useful for sector analysis or finding alternatives.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of ticker symbols to compare (max 10). Use correct format for each market: US stocks (AAPL), HK stocks 4-digit+'.HK' (0700.HK), A-shares '.SS'/'.SZ' (600519.SS, 000858.SZ), Crypto (BTC-USD), Commodities (GC=F)."
                }
            },
            "required": ["symbols"]
        }
    },
    {
        "name": "batch_get_realtime_prices",
        "description": "Get real-time prices for multiple symbols in a single call. Much more efficient than calling get_realtime_price repeatedly. Use this when you need to check prices for many assets at once.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of ticker symbols (max 20). Use correct format for each market: US stocks (AAPL), HK stocks 4-digit+'.HK' (0700.HK), A-shares '.SS'/'.SZ' (600519.SS, 000858.SZ), Crypto (BTC-USD), Commodities (GC=F), CN funds 6-digit (015283)."
                },
                "asset_type": {
                    "type": "string",
                    "enum": ["STOCK", "CRYPTO", "COMMODITY", "BOND", "FUND_CN"],
                    "description": "The type of assets (applied to all symbols)"
                }
            },
            "required": ["symbols"]
        }
    },
    {
        "name": "search_market_news",
        "description": "Search the web for latest market news, hot stocks, sector trends, and catalysts. Use this tool FIRST before any price/kline tools to discover which assets are worth analyzing. This is essential for a news-driven recommendation approach.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for market news. Examples: 'HK stock market news today 2024-01-15', 'US tech stocks hot this week', 'A-share semiconductor sector catalysts', 'crypto market breaking news'. Be specific about market, sector, and timeframe."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "batch_get_kline_data",
        "description": "Get historical K-line data for multiple symbols in a single call. Much more efficient than calling get_kline_data repeatedly. Returns summary statistics and recent data for each symbol.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbols": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of ticker symbols (max 10). Use correct format for each market: US stocks (AAPL), HK stocks 4-digit+'.HK' (0700.HK), A-shares '.SS'/'.SZ' (600519.SS, 000858.SZ), Crypto (BTC-USD), Commodities (GC=F), CN funds 6-digit (015283)."
                },
                "period": {
                    "type": "string",
                    "enum": ["1mo", "3mo", "6mo", "1y"],
                    "description": "Time period for historical data. Default: 1mo"
                },
                "asset_type": {
                    "type": "string",
                    "enum": ["STOCK", "CRYPTO", "COMMODITY", "BOND", "FUND_CN"],
                    "description": "The type of assets (applied to all symbols)"
                }
            },
            "required": ["symbols"]
        }
    }
]


# ============================================================
# Tool Execution Functions
# ============================================================

class AgentToolExecutor:
    """
    Executes tool calls from AI models.
    Maintains context (user_id, current symbol, etc.) for data access.
    """

    def __init__(self, user_id=None, current_symbol=None, asset_type="STOCK", provider=None):
        self.user_id = user_id
        self.current_symbol = current_symbol
        self.asset_type = asset_type
        self.provider = provider  # Current model provider: gemini/qwen/openai/anthropic
        self._tool_call_log = []  # Track all tool calls for UI display
        self._trace = []  # Chronological trace: thinking + tool_call entries

    @property
    def tool_calls(self):
        """Return the log of all tool calls made during this session"""
        return self._tool_call_log

    @property
    def trace(self):
        """Return the chronological agent trace (thinking + tool_call interleaved)"""
        return self._trace

    def add_thinking(self, text):
        """Record model thinking / reasoning text into the trace timeline."""
        if text and text.strip():
            self._trace.append({
                "type": "thinking",
                "content": text.strip(),
                "timestamp": datetime.now().isoformat()
            })

    def execute(self, tool_name, arguments):
        """
        Execute a tool call and return the result.
        
        Args:
            tool_name: Name of the tool to execute
            arguments: Dict of arguments for the tool
            
        Returns:
            String result to feed back to the AI model
        """
        start_time = datetime.now()

        try:
            if tool_name == "get_realtime_price":
                result = self._get_realtime_price(**arguments)
            elif tool_name == "get_kline_data":
                result = self._get_kline_data(**arguments)
            elif tool_name == "calculate_technical_indicators":
                result = self._calculate_technical_indicators(**arguments)
            elif tool_name == "batch_calculate_technical_indicators":
                result = self._batch_calculate_technical_indicators(**arguments)
            elif tool_name == "get_portfolio_holdings":
                result = self._get_portfolio_holdings()
            elif tool_name == "get_transaction_history":
                result = self._get_transaction_history(**arguments)
            elif tool_name == "get_exchange_rate":
                result = self._get_exchange_rate(**arguments)
            elif tool_name == "compare_assets":
                result = self._compare_assets(**arguments)
            elif tool_name == "batch_get_realtime_prices":
                result = self._batch_get_realtime_prices(**arguments)
            elif tool_name == "search_market_news":
                result = self._search_market_news(**arguments)
            elif tool_name == "batch_get_kline_data":
                result = self._batch_get_kline_data(**arguments)
            else:
                result = json.dumps({"error": f"Unknown tool: {tool_name}"})

            elapsed = (datetime.now() - start_time).total_seconds()

            # Build the log entry
            log_entry = {
                "tool": tool_name,
                "arguments": arguments,
                "result_preview": result[:200] + "..." if len(result) > 200 else result,
                "elapsed_seconds": round(elapsed, 2),
                "timestamp": start_time.isoformat()
            }

            # Log to both flat list and trace timeline
            self._tool_call_log.append(log_entry)
            self._trace.append({
                "type": "tool_call",
                **log_entry
            })

            return result

        except Exception as e:
            error_result = json.dumps({"error": str(e)})
            log_entry = {
                "tool": tool_name,
                "arguments": arguments,
                "result_preview": error_result,
                "elapsed_seconds": round((datetime.now() - start_time).total_seconds(), 2),
                "timestamp": start_time.isoformat(),
                "error": True
            }
            self._tool_call_log.append(log_entry)
            self._trace.append({
                "type": "tool_call",
                **log_entry
            })
            return error_result

    def _get_realtime_price(self, symbol, asset_type=None):
        """Get real-time price for a symbol"""
        effective_type = asset_type or self.asset_type

        # Determine currency based on asset type
        currency = None
        if effective_type == "FUND_CN":
            currency = "CNY"

        price = batch_fetcher.get_cached_current_price(
            symbol, asset_type=effective_type, currency=currency
        )
        daily_change = batch_fetcher.get_cached_daily_change(
            symbol, asset_type=effective_type, currency=currency
        )

        if price is None:
            return json.dumps({"error": f"Could not fetch price for {symbol}"})

        return json.dumps({
            "symbol": symbol,
            "price": price,
            "daily_change_percent": daily_change,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "currency": currency or "USD"
        })

    def _get_kline_data(self, symbol, period="3mo", asset_type=None):
        """Get K-line historical data"""
        effective_type = asset_type or self.asset_type
        is_cn_fund = effective_type == "FUND_CN"

        data = batch_fetcher.get_cached_kline_data(
            symbol, period=period, interval="1d", is_cn_fund=is_cn_fund
        )

        if not data:
            return json.dumps({"error": f"Could not fetch kline data for {symbol}"})

        # Return summary + recent data points to save tokens
        total_points = len(data)
        # For the AI, provide last 60 points with full detail
        recent = data[-60:] if total_points > 60 else data

        # Calculate basic statistics
        closes = [d["close"] for d in data]
        high_price = max(d["high"] for d in data)
        low_price = min(d["low"] for d in data)
        avg_volume = sum(d["volume"] for d in data) / len(data) if data[0].get("volume") else 0

        summary = {
            "symbol": symbol,
            "period": period,
            "total_data_points": total_points,
            "date_range": f"{data[0]['date']} to {data[-1]['date']}",
            "price_range": {"high": high_price, "low": low_price},
            "latest_close": data[-1]["close"],
            "avg_volume": round(avg_volume),
            "recent_data": recent
        }

        return json.dumps(summary)

    def _calculate_technical_indicators(self, symbol, period="3mo"):
        """Calculate technical indicators for a symbol"""
        effective_type = self.asset_type
        is_cn_fund = effective_type == "FUND_CN"

        data = batch_fetcher.get_cached_kline_data(
            symbol, period=period, interval="1d", is_cn_fund=is_cn_fund
        )

        if not data:
            return json.dumps({"error": f"No data available for {symbol}"})

        enriched = calculate_indicators(data)

        # Return last 30 data points with indicators
        recent = enriched[-30:]
        # Build a compact CSV-like summary
        lines = ["Date,Close,MA5,MA20,RSI"]
        for d in recent:
            lines.append(
                f"{d['date']},{d['close']:.4f},{d.get('MA5', 0):.4f},{d.get('MA20', 0):.4f},{d.get('RSI', 0):.2f}"
            )

        # Add analysis hints
        latest = recent[-1] if recent else {}
        prev = recent[-2] if len(recent) > 1 else {}

        analysis_hints = {}
        if latest.get("MA5") and latest.get("MA20"):
            if latest["MA5"] > latest["MA20"] and prev.get("MA5", 0) <= prev.get("MA20", 0):
                analysis_hints["ma_signal"] = "Golden Cross (MA5 crossed above MA20)"
            elif latest["MA5"] < latest["MA20"] and prev.get("MA5", 0) >= prev.get("MA20", 0):
                analysis_hints["ma_signal"] = "Death Cross (MA5 crossed below MA20)"
            elif latest["MA5"] > latest["MA20"]:
                analysis_hints["ma_signal"] = "Bullish (MA5 above MA20)"
            else:
                analysis_hints["ma_signal"] = "Bearish (MA5 below MA20)"

        if latest.get("RSI"):
            rsi = latest["RSI"]
            if rsi > 70:
                analysis_hints["rsi_signal"] = f"Overbought (RSI={rsi:.1f})"
            elif rsi < 30:
                analysis_hints["rsi_signal"] = f"Oversold (RSI={rsi:.1f})"
            else:
                analysis_hints["rsi_signal"] = f"Neutral (RSI={rsi:.1f})"

        return json.dumps({
            "symbol": symbol,
            "indicators_csv": "\n".join(lines),
            "analysis_hints": analysis_hints,
            "latest": {
                "date": latest.get("date"),
                "close": latest.get("close"),
                "MA5": round(latest.get("MA5", 0), 4),
                "MA20": round(latest.get("MA20", 0), 4),
                "RSI": round(latest.get("RSI", 0), 2)
            }
        })

    def _get_portfolio_holdings(self):
        """Get user's portfolio holdings"""
        if not self.user_id:
            return json.dumps({"error": "No user context available", "holdings": []})

        from app.models.analysis import Portfolio

        portfolios = Portfolio.query.filter_by(user_id=self.user_id).all()
        if not portfolios:
            return json.dumps({"holdings": [], "total_positions": 0})

        holdings = []
        total_value = 0

        for p in portfolios:
            if p.total_quantity <= 0 and p.asset_type != "CASH":
                continue

            current_price = None
            if p.asset_type != "CASH":
                try:
                    currency = p.currency if p.currency else "USD"
                    current_price = batch_fetcher.get_cached_current_price(
                        p.symbol, asset_type=p.asset_type, currency=currency
                    )
                except:
                    pass

            if p.asset_type == "CASH":
                position_value = p.total_quantity
            elif current_price:
                position_value = current_price * p.total_quantity
            else:
                position_value = p.total_cost

            total_value += position_value

            holding = {
                "symbol": p.symbol,
                "asset_type": p.asset_type,
                "currency": p.currency or "USD",
                "quantity": float(p.total_quantity),
                "avg_cost": float(p.avg_cost),
                "current_price": float(current_price) if current_price else None,
                "position_value": round(position_value, 2),
                "unrealized_pnl": round(position_value - p.total_cost, 2) if p.asset_type != "CASH" else 0,
                "unrealized_pnl_pct": round(
                    (position_value - p.total_cost) / p.total_cost * 100, 2
                ) if p.total_cost > 0 and p.asset_type != "CASH" else 0
            }
            holdings.append(holding)

        # Calculate allocation percentages
        for h in holdings:
            h["allocation_pct"] = round(h["position_value"] / total_value * 100, 1) if total_value > 0 else 0

        # Sort by position value
        holdings.sort(key=lambda x: x["position_value"], reverse=True)

        return json.dumps({
            "total_value": round(total_value, 2),
            "total_positions": len(holdings),
            "holdings": holdings
        })

    def _get_transaction_history(self, symbol):
        """Get transaction history for a specific symbol"""
        if not self.user_id:
            return json.dumps({"error": "No user context available", "transactions": []})

        from app.models.analysis import Portfolio, Transaction

        portfolio = Portfolio.query.filter_by(
            user_id=self.user_id, symbol=symbol
        ).first()

        if not portfolio:
            return json.dumps({
                "symbol": symbol,
                "transactions": [],
                "message": "No position found for this symbol"
            })

        transactions = Transaction.query.filter_by(
            portfolio_id=portfolio.id, user_id=self.user_id
        ).order_by(Transaction.trade_date.asc()).all()

        tx_list = []
        for t in transactions:
            tx_list.append({
                "date": t.trade_date.strftime("%Y-%m-%d"),
                "type": t.transaction_type,
                "price": float(t.price),
                "quantity": float(t.quantity),
                "amount": float(t.amount),
                "notes": t.notes or ""
            })

        return json.dumps({
            "symbol": symbol,
            "current_quantity": float(portfolio.total_quantity),
            "avg_cost": float(portfolio.avg_cost),
            "total_cost": float(portfolio.total_cost),
            "transactions": tx_list
        })

    def _get_exchange_rate(self, from_currency, to_currency="USD"):
        """Get exchange rate"""
        rate = batch_fetcher.get_cached_exchange_rate(from_currency, to_currency)
        return json.dumps({
            "from": from_currency,
            "to": to_currency,
            "rate": rate,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
        })

    def _compare_assets(self, symbols):
        """Compare multiple assets side by side"""
        if len(symbols) > 10:
            symbols = symbols[:10]

        results = []
        for sym in symbols:
            price = batch_fetcher.get_cached_current_price(sym)
            daily_change = batch_fetcher.get_cached_daily_change(sym)

            results.append({
                "symbol": sym,
                "price": price,
                "daily_change_percent": daily_change
            })

        return json.dumps({
            "comparison": results,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
        })

    def _batch_get_realtime_prices(self, symbols, asset_type=None):
        """Get real-time prices for multiple symbols in one call"""
        if len(symbols) > 20:
            symbols = symbols[:20]

        effective_type = asset_type or self.asset_type
        currency = "CNY" if effective_type == "FUND_CN" else None

        results = []
        for sym in symbols:
            price = batch_fetcher.get_cached_current_price(
                sym, asset_type=effective_type, currency=currency
            )
            daily_change = batch_fetcher.get_cached_daily_change(
                sym, asset_type=effective_type, currency=currency
            )
            results.append({
                "symbol": sym,
                "price": price,
                "daily_change_percent": daily_change,
            })

        return json.dumps({
            "prices": results,
            "count": len(results),
            "currency": currency or "USD",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
        })

    def _search_market_news(self, query):
        """Search web for market news. Prioritizes the same provider as the calling model."""
        import os
        result_text = None

        search_prompt = (
            f"Search the web and provide a comprehensive summary of the latest news for: {query}\n\n"
            f"Focus on:\n"
            f"1. Specific stock/asset names mentioned in news (with ticker symbols if possible)\n"
            f"2. Key catalysts: earnings, policy changes, analyst upgrades/downgrades, sector trends\n"
            f"3. Market sentiment and notable price movements\n"
            f"4. Any breaking news or upcoming events\n\n"
            f"Be specific: include company names, ticker symbols, numbers, dates, and sources."
        )

        # Build search strategy order: current provider first, then fallbacks
        strategies = self._build_search_strategies(search_prompt)

        for name, search_fn in strategies:
            if result_text:
                break
            try:
                result_text = search_fn()
                if result_text:
                    print(f"  [search_market_news] ✅ {name} search succeeded ({len(result_text)} chars)")
            except Exception as e:
                print(f"  [search_market_news] {name} search failed: {e}")

        if not result_text:
            return json.dumps({
                "error": "Web search unavailable. No search API keys configured.",
                "query": query,
                "suggestion": "Proceed with available financial data tools instead."
            })

        return json.dumps({
            "query": query,
            "news_summary": result_text,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "note": "Use the stock symbols and catalysts found above to guide your tool calls for price/kline data."
        })

    def _build_search_strategies(self, search_prompt):
        """Build ordered list of (name, callable) search strategies based on current provider."""
        import os

        def gemini_search():
            gemini_key = os.getenv('GEMINI_API_KEY')
            if not gemini_key:
                return None
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gemini_key)
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=search_prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                )
            )
            return response.text

        def qwen_search():
            qwen_key = os.getenv('QWEN_API_KEY')
            if not qwen_key:
                return None
            from openai import OpenAI
            client = OpenAI(
                api_key=qwen_key,
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
            )
            response = client.chat.completions.create(
                model="qwen-plus",
                messages=[{"role": "user", "content": search_prompt}],
                extra_body={
                    "enable_search": True,
                    "search_options": {
                        "forced_search": True,
                        "search_strategy": "pro"
                    }
                }
            )
            return response.choices[0].message.content

        def openai_search():
            openai_key = os.getenv('OPENAI_API_KEY')
            if not openai_key:
                return None
            from openai import OpenAI
            client = OpenAI(api_key=openai_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": search_prompt}],
                tools=[{"type": "web_search"}]
            )
            return response.choices[0].message.content

        # Map provider to its native search function
        provider_search_map = {
            "gemini": ("Gemini", gemini_search),
            "qwen": ("Qwen", qwen_search),
            "openai": ("OpenAI", openai_search),
        }

        # All available strategies in default fallback order
        all_strategies = [("Gemini", gemini_search), ("Qwen", qwen_search), ("OpenAI", openai_search)]

        # If we know the current provider, put its search first
        if self.provider and self.provider in provider_search_map:
            primary = provider_search_map[self.provider]
            fallbacks = [s for s in all_strategies if s[0] != primary[0]]
            strategies = [primary] + fallbacks
            print(f"  [search_market_news] Provider={self.provider}, search order: {[s[0] for s in strategies]}")
        else:
            strategies = all_strategies
            print(f"  [search_market_news] No provider set, using default search order: {[s[0] for s in strategies]}")

        return strategies

    def _batch_get_kline_data(self, symbols, period="1mo", asset_type=None):
        """Get K-line data for multiple symbols in one call"""
        if len(symbols) > 10:
            symbols = symbols[:10]

        effective_type = asset_type or self.asset_type
        is_cn_fund = effective_type == "FUND_CN"

        results = []
        for sym in symbols:
            data = batch_fetcher.get_cached_kline_data(
                sym, period=period, interval="1d", is_cn_fund=is_cn_fund
            )

            if not data:
                results.append({
                    "symbol": sym,
                    "error": f"Could not fetch kline data for {sym}"
                })
                continue

            # Provide compact summary + last 20 data points to save tokens
            closes = [d["close"] for d in data]
            high_price = max(d["high"] for d in data)
            low_price = min(d["low"] for d in data)
            recent = data[-20:] if len(data) > 20 else data

            # Calculate simple trend metrics
            if len(closes) >= 5:
                pct_5d = round((closes[-1] - closes[-5]) / closes[-5] * 100, 2)
            else:
                pct_5d = None

            if len(closes) >= 20:
                pct_20d = round((closes[-1] - closes[-20]) / closes[-20] * 100, 2)
            else:
                pct_20d = None

            results.append({
                "symbol": sym,
                "period": period,
                "total_data_points": len(data),
                "date_range": f"{data[0]['date']} to {data[-1]['date']}",
                "latest_close": data[-1]["close"],
                "price_range": {"high": high_price, "low": low_price},
                "change_5d_pct": pct_5d,
                "change_20d_pct": pct_20d,
                "recent_data": recent
            })

        return json.dumps({
            "results": results,
            "count": len(results),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
        })

    def _batch_calculate_technical_indicators(self, symbols, period="3mo"):
        """Calculate technical indicators for multiple symbols in one call"""
        if len(symbols) > 10:
            symbols = symbols[:10]

        effective_type = self.asset_type
        is_cn_fund = effective_type == "FUND_CN"

        results = []
        for sym in symbols:
            data = batch_fetcher.get_cached_kline_data(
                sym, period=period, interval="1d", is_cn_fund=is_cn_fund
            )

            if not data:
                results.append({
                    "symbol": sym,
                    "error": f"No data available for {sym}"
                })
                continue

            enriched = calculate_indicators(data)

            # Return last 10 data points with indicators (compact for batch)
            recent = enriched[-10:]
            
            # Build compact summary
            latest = recent[-1] if recent else {}
            prev = recent[-2] if len(recent) > 1 else {}

            # Generate analysis hints
            analysis_hints = {}
            if latest.get("MA5") and latest.get("MA20"):
                if latest["MA5"] > latest["MA20"] and prev.get("MA5", 0) <= prev.get("MA20", 0):
                    analysis_hints["ma_signal"] = "Golden Cross"
                elif latest["MA5"] < latest["MA20"] and prev.get("MA5", 0) >= prev.get("MA20", 0):
                    analysis_hints["ma_signal"] = "Death Cross"
                elif latest["MA5"] > latest["MA20"]:
                    analysis_hints["ma_signal"] = "Bullish"
                else:
                    analysis_hints["ma_signal"] = "Bearish"

            if latest.get("RSI"):
                rsi = latest["RSI"]
                if rsi > 70:
                    analysis_hints["rsi_signal"] = f"Overbought ({rsi:.1f})"
                elif rsi < 30:
                    analysis_hints["rsi_signal"] = f"Oversold ({rsi:.1f})"
                else:
                    analysis_hints["rsi_signal"] = f"Neutral ({rsi:.1f})"

            results.append({
                "symbol": sym,
                "period": period,
                "latest": {
                    "date": latest.get("date"),
                    "close": latest.get("close"),
                    "MA5": round(latest.get("MA5", 0), 2),
                    "MA20": round(latest.get("MA20", 0), 2),
                    "RSI": round(latest.get("RSI", 0), 1)
                },
                "analysis_hints": analysis_hints,
                "recent_10d": [
                    {
                        "date": d["date"],
                        "close": round(d["close"], 2),
                        "MA5": round(d.get("MA5", 0), 2),
                        "MA20": round(d.get("MA20", 0), 2),
                        "RSI": round(d.get("RSI", 0), 1)
                    }
                    for d in recent
                ]
            })

        return json.dumps({
            "results": results,
            "count": len(results),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M")
        })


# ============================================================
# Helper: Convert tool definitions to provider-specific formats
# ============================================================

def get_openai_tools():
    """Convert tool definitions to OpenAI function calling format"""
    tools = []
    for tool in TOOL_DEFINITIONS:
        tools.append({
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["parameters"]
            }
        })
    return tools


def get_gemini_tools():
    """Convert tool definitions to Gemini function calling format"""
    from google.genai import types

    function_declarations = []
    for tool in TOOL_DEFINITIONS:
        # Convert JSON schema to Gemini Schema format
        props = tool["parameters"].get("properties", {})
        gemini_props = {}
        for prop_name, prop_def in props.items():
            schema_kwargs = {}
            prop_type = prop_def.get("type", "string").upper()

            if prop_type == "STRING":
                schema_kwargs["type"] = "STRING"
            elif prop_type == "NUMBER":
                schema_kwargs["type"] = "NUMBER"
            elif prop_type == "INTEGER":
                schema_kwargs["type"] = "INTEGER"
            elif prop_type == "BOOLEAN":
                schema_kwargs["type"] = "BOOLEAN"
            elif prop_type == "ARRAY":
                schema_kwargs["type"] = "ARRAY"
                items = prop_def.get("items", {})
                items_type = items.get("type", "string").upper()
                schema_kwargs["items"] = types.Schema(type=items_type)
            else:
                schema_kwargs["type"] = "STRING"

            if "description" in prop_def:
                schema_kwargs["description"] = prop_def["description"]
            if "enum" in prop_def:
                schema_kwargs["enum"] = prop_def["enum"]

            gemini_props[prop_name] = types.Schema(**schema_kwargs)

        fd = types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters=types.Schema(
                type="OBJECT",
                properties=gemini_props,
                required=tool["parameters"].get("required", [])
            ) if gemini_props else None
        )
        function_declarations.append(fd)

    return [types.Tool(function_declarations=function_declarations)]


def get_anthropic_tools():
    """Convert tool definitions to Anthropic tool use format"""
    tools = []
    for tool in TOOL_DEFINITIONS:
        tools.append({
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["parameters"]
        })
    return tools


def get_qwen_tools():
    """Qwen uses OpenAI-compatible format"""
    return get_openai_tools()
