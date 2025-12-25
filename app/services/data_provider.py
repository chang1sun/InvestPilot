import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import json
import requests

# New assets support
POPULAR_ASSETS = [
    # Crypto
    {"symbol": "BTC-USD", "name": "Bitcoin USD", "type": "CRYPTO"},
    {"symbol": "ETH-USD", "name": "Ethereum USD", "type": "CRYPTO"},
    {"symbol": "SOL-USD", "name": "Solana USD", "type": "CRYPTO"},
    {"symbol": "DOGE-USD", "name": "Dogecoin USD", "type": "CRYPTO"},
    # Commodities
    {"symbol": "GC=F", "name": "Gold Futures", "type": "COMMODITY"},
    {"symbol": "CL=F", "name": "Crude Oil Futures", "type": "COMMODITY"},
    {"symbol": "SI=F", "name": "Silver Futures", "type": "COMMODITY"},
    # Bonds
    {"symbol": "^TNX", "name": "Treasury Yield 10 Years", "type": "BOND"},
    {"symbol": "^IRX", "name": "Treasury Yield 13 Weeks", "type": "BOND"},
    {"symbol": "^TYX", "name": "Treasury Yield 30 Years", "type": "BOND"},
]

# Static list of popular stocks for fallback/demo
POPULAR_STOCKS = [
    # US Stocks
    {"symbol": "AAPL", "name": "Apple Inc.", "type": "STOCK"},
    {"symbol": "MSFT", "name": "Microsoft Corporation", "type": "STOCK"},
    {"symbol": "NVDA", "name": "NVIDIA Corporation", "type": "STOCK"},
    {"symbol": "GOOGL", "name": "Alphabet Inc.", "type": "STOCK"},
    {"symbol": "AMZN", "name": "Amazon.com, Inc.", "type": "STOCK"},
    {"symbol": "TSLA", "name": "Tesla, Inc.", "type": "STOCK"},
    {"symbol": "META", "name": "Meta Platforms, Inc.", "type": "STOCK"},
    {"symbol": "AMD", "name": "Advanced Micro Devices, Inc.", "type": "STOCK"},
    {"symbol": "NFLX", "name": "Netflix, Inc.", "type": "STOCK"},
    {"symbol": "INTC", "name": "Intel Corporation", "type": "STOCK"},
    {"symbol": "BABA", "name": "Alibaba Group Holding Limited", "type": "STOCK"},
    {"symbol": "BIDU", "name": "Baidu, Inc.", "type": "STOCK"},
    {"symbol": "JD", "name": "JD.com, Inc.", "type": "STOCK"},
    {"symbol": "PDD", "name": "PDD Holdings Inc.", "type": "STOCK"},
    {"symbol": "TCEHY", "name": "Tencent Holdings Limited (ADR)", "type": "STOCK"},
    # Hong Kong Stocks
    {"symbol": "0700.HK", "name": "Tencent Holdings Limited", "type": "STOCK"},
    {"symbol": "9988.HK", "name": "Alibaba Group Holding Limited", "type": "STOCK"},
    {"symbol": "3690.HK", "name": "Meituan", "type": "STOCK"},
    {"symbol": "1810.HK", "name": "Xiaomi Corporation", "type": "STOCK"},
    {"symbol": "1211.HK", "name": "BYD Company Limited", "type": "STOCK"},
    {"symbol": "0941.HK", "name": "China Mobile Limited", "type": "STOCK"},
    {"symbol": "0005.HK", "name": "HSBC Holdings plc", "type": "STOCK"},
    {"symbol": "1299.HK", "name": "AIA Group Limited", "type": "STOCK"},
    # A-Share Stocks (Shanghai: .SS, Shenzhen: .SZ)
    {"symbol": "600519.SS", "name": "贵州茅台 (Kweichow Moutai)", "type": "STOCK"},
    {"symbol": "000858.SZ", "name": "五粮液 (Wuliangye Yibin)", "type": "STOCK"},
    {"symbol": "601318.SS", "name": "中国平安 (Ping An Insurance)", "type": "STOCK"},
    {"symbol": "600036.SS", "name": "招商银行 (China Merchants Bank)", "type": "STOCK"},
    {"symbol": "000333.SZ", "name": "美的集团 (Midea Group)", "type": "STOCK"},
    {"symbol": "300750.SZ", "name": "宁德时代 (CATL)", "type": "STOCK"},
    {"symbol": "002594.SZ", "name": "比亚迪 (BYD Company)", "type": "STOCK"},
    {"symbol": "600900.SS", "name": "长江电力 (China Yangtze Power)", "type": "STOCK"},
    {"symbol": "601012.SS", "name": "隆基绿能 (LONGi Green Energy)", "type": "STOCK"},
    {"symbol": "000001.SZ", "name": "平安银行 (Ping An Bank)", "type": "STOCK"},
]

class DataProvider:
    @staticmethod
    def search_symbol(query):
        """
        Search for a stock symbol. 
        Tries Yahoo Finance API first, then falls back to local static list.
        """
        results = []
        query_upper = query.upper()
        
        # 1. Try Local Search First (Fastest & Reliable)
        # Combine all local assets
        all_local_assets = POPULAR_ASSETS + POPULAR_STOCKS
        
        for asset in all_local_assets:
            if query_upper in asset['symbol'] or query_upper in asset['name'].upper():
                # Ensure type is present (default to STOCK if missing, though we added it above)
                if 'type' not in asset:
                    asset['type'] = 'STOCK'
                results.append(asset)
        
        # If local search yields enough results, just return them to save API calls
        if len(results) >= 5:
            return results

        # 2. Try Yahoo Finance API
        try:
            # Yahoo Finance Autocomplete API
            url = "https://query2.finance.yahoo.com/v1/finance/search"
            params = {
                "q": query,
                "quotesCount": 10,
                "newsCount": 0,
                "enableFuzzyQuery": "true",
                "enableCb": "false"
            }
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

            response = requests.get(url, params=params, headers=headers, timeout=3)
            
            if response.status_code == 200:
                data = response.json()
                quotes = data.get("quotes", [])
                
                api_results = []
                for q in quotes:
                    symbol = q.get("symbol")
                    shortname = q.get("shortname") or q.get("longname") or symbol
                    exch = q.get("exchDisp") or q.get("exchange")
                    quote_type = q.get("quoteType", "EQUITY") # Default to EQUITY
                    
                    # Map Yahoo quoteType to our types
                    asset_type = "STOCK"
                    if quote_type == "CRYPTOCURRENCY":
                        asset_type = "CRYPTO"
                    elif quote_type == "FUTURE":
                        asset_type = "COMMODITY"
                    elif quote_type == "INDEX":
                        # Some bonds/rates appear as INDEX or similar
                        if symbol.startswith("^"):
                            asset_type = "BOND" # Simplified assumption for now
                        else:
                            asset_type = "INDEX"
                    elif quote_type == "ETF":
                        asset_type = "STOCK" # Treat ETF as stock for now, or separate if needed
                    
                    if symbol:
                        api_results.append({
                            "symbol": symbol,
                            "name": f"{shortname} ({exch})",
                            "type": asset_type
                        })
                
                # Merge API results with local results (deduplicate by symbol)
                existing_symbols = {r['symbol'] for r in results}
                for r in api_results:
                    if r['symbol'] not in existing_symbols:
                        results.append(r)
                        
                return results
            else:
                print(f"Yahoo Search API returned status: {response.status_code}")

        except Exception as e:
            print(f"Search API Error: {e}")
            
        # 3. Final Fallback (if nothing found anywhere)
        if not results:
             # Smart suffix detection for A-shares and HK stocks
             if query_upper.isdigit():
                 # If 4 digits, could be HK stock
                 if len(query_upper) == 4:
                     results.append({"symbol": f"{query_upper}.HK", "name": f"港股 {query_upper}", "type": "STOCK"})
                 # If 6 digits, likely A-share
                 elif len(query_upper) == 6:
                     # Shanghai (60xxxx) or Shenzhen (00xxxx, 30xxxx)
                     if query_upper.startswith('6'):
                         results.append({"symbol": f"{query_upper}.SS", "name": f"沪市 {query_upper}", "type": "STOCK"})
                     elif query_upper.startswith(('0', '3')):
                         results.append({"symbol": f"{query_upper}.SZ", "name": f"深市 {query_upper}", "type": "STOCK"})
                     else:
                         results.append({"symbol": query_upper, "name": query_upper, "type": "STOCK"})
                 else:
                     results.append({"symbol": query_upper, "name": query_upper, "type": "STOCK"})
             else:
                 results.append({"symbol": query_upper, "name": query_upper, "type": "STOCK"})
            
        return results

    @staticmethod
    def get_kline_data(symbol, period="3y", interval="1d"):
        """
        Get K-line data for a symbol. Fetch 3 years to allow broad context.
        """
        try:
            ticker = yf.Ticker(symbol)
            # Fetch history - changed default to 3y
            # yfinance 内部使用 requests，超时由底层库处理
            hist = ticker.history(period=period, interval=interval)
            
            if hist.empty:
                print(f"Warning: Empty data for {symbol}, possibly delisted or invalid symbol")
                return None

            # Reset index to make Date a column
            hist.reset_index(inplace=True)
            
            # Format data for frontend
            # ECharts expects: [Date, Open, Close, Low, High, Volume] (Standard candlestick)
            # But we will return a list of dicts for clarity or a list of lists
            
            data = []
            for _, row in hist.iterrows():
                # Handle different date formats from yfinance
                dt = row['Date']
                if isinstance(dt, pd.Timestamp):
                    date_str = dt.strftime('%Y-%m-%d')
                else:
                    date_str = str(dt)[:10]
                    
                data.append({
                    "date": date_str,
                    "open": round(row['Open'], 4),
                    "high": round(row['High'], 4),
                    "low": round(row['Low'], 4),
                    "close": round(row['Close'], 4),
                    "volume": int(row['Volume'])
                })
                
            return data
        except Exception as e:
            error_msg = str(e)
            # 检查是否是已知的问题（退市、无效代码等）
            if "delisted" in error_msg.lower() or "no price data" in error_msg.lower():
                print(f"Warning: {symbol} possibly delisted; no price data found (period={period})")
            elif "timeout" in error_msg.lower() or "curl" in error_msg.lower():
                print(f"Warning: Network timeout/error fetching {symbol}: {error_msg}")
            else:
                print(f"Error fetching data for {symbol}: {error_msg}")
            return None
