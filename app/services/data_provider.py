import yfinance as yf
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta, timezone
import json
import requests
from typing import List, Dict, Optional, Tuple
import threading
import time
from functools import wraps


class RateLimiter:
    """Rate limiter to control API request frequency."""
    
    def __init__(self, max_calls: int = 2, time_window: int = 60):
        """
        Initialize rate limiter.
        
        Args:
            max_calls: Maximum number of calls allowed in time window
            time_window: Time window in seconds
        """
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []
        self.lock = threading.Lock()
    
    def acquire(self):
        """Acquire permission to make a request. Will block if rate limit exceeded."""
        with self.lock:
            now = time.time()
            # Remove calls outside the time window
            self.calls = [call_time for call_time in self.calls if now - call_time < self.time_window]
            
            # If we've hit the limit, wait
            if len(self.calls) >= self.max_calls:
                sleep_time = self.time_window - (now - self.calls[0]) + 1
                if sleep_time > 0:
                    print(f"⏳ Rate limit reached, waiting {sleep_time:.1f}s before next request...")
                    time.sleep(sleep_time)
                    # Clear old calls after wait
                    self.calls = []
            
            # Record this call
            self.calls.append(now)
    
    def reset(self):
        """Reset the rate limiter."""
        with self.lock:
            self.calls = []


def retry_on_rate_limit(max_retries: int = 3, initial_delay: float = 5.0, backoff_factor: float = 2.0):
    """
    Decorator to retry function calls on rate limit errors.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds before first retry
        backoff_factor: Multiplier for delay after each retry
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_error = None
            
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    error_str = str(e).lower()
                    is_rate_limit = any(keyword in error_str for keyword in ['rate limit', 'too many requests', 'yfratelimit'])
                    
                    if not is_rate_limit or attempt == max_retries:
                        # Not a rate limit error or max retries reached
                        if attempt > 0:
                            print(f"❌ Max retries reached or non-rate-limit error: {e}")
                        raise e
                    
                    last_error = e
                    print(f"⚠️ Rate limit hit on attempt {attempt + 1}/{max_retries + 1}, retrying in {delay:.1f}s...")
                    time.sleep(delay)
                    delay *= backoff_factor
            
            # Should not reach here, but just in case
            raise last_error
        
        return wrapper
    return decorator


# Global rate limiter instance - allows 2 requests per 60 seconds
_global_rate_limiter = RateLimiter(max_calls=2, time_window=60)
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
    _cn_fund_list_cache = None
    _cn_fund_list_cache_time = None

    @staticmethod
    def search_cn_fund(query):
        """
        Search for Chinese funds using akshare.
        """
        try:
            # Check cache (valid for 24 hours)
            now = time.time()
            if (DataProvider._cn_fund_list_cache is None or 
                DataProvider._cn_fund_list_cache_time is None or 
                now - DataProvider._cn_fund_list_cache_time > 86400):
                
                print("Fetching CN fund list from akshare...")
                # ak.fund_name_em() returns: 基金代码, 拼音缩写, 基金简称, 基金类型, 拼音全称
                df = ak.fund_name_em()
                DataProvider._cn_fund_list_cache = df
                DataProvider._cn_fund_list_cache_time = now
            
            df = DataProvider._cn_fund_list_cache
            
            if df is None or df.empty:
                return []
            
            # 不转换大小写，使用不区分大小写的匹配
            # Filter by code, name, or pinyin (case-insensitive)
            mask = (
                df['基金代码'].str.contains(query, case=False, na=False) | 
                df['基金简称'].str.contains(query, case=False, na=False) | 
                df['拼音缩写'].str.contains(query, case=False, na=False)
            )
            
            results_df = df[mask].head(20) # Limit to 20 results
            
            results = []
            for _, row in results_df.iterrows():
                results.append({
                    "symbol": row['基金代码'],
                    "name": row['基金简称'],
                    "type": "FUND_CN",
                    "market": "CN"
                })
                
            return results
            
        except Exception as e:
            print(f"Error searching CN fund: {e}")
            return []

    @staticmethod
    def get_cn_fund_price(symbol):
        """
        Get current price (net value) for a Chinese fund.
        """
        try:
            # Get fund info (net value history)
            # indicator="单位净值走势" returns columns: 净值日期, 单位净值, 日增长率, ...
            df = ak.fund_open_fund_info_em(symbol=symbol, indicator="单位净值走势", period="1月")
            
            if df is None or df.empty:
                return None
                
            # Get latest row
            latest = df.iloc[-1]
            # Assume '单位净值' is the price
            price = float(latest['单位净值'])
            return price
            
        except Exception as e:
            print(f"Error getting CN fund price for {symbol}: {e}")
            return None

    @staticmethod
    def get_cn_fund_daily_change(symbol):
        """
        Get daily change percentage for a Chinese fund.
        """
        try:
            # Get fund info (net value history)
            # indicator="单位净值走势" returns columns: 净值日期, 单位净值, 日增长率, ...
            df = ak.fund_open_fund_info_em(symbol=symbol, indicator="单位净值走势", period="1月")
            
            if df is None or df.empty:
                return None
                
            # Get latest row
            latest = df.iloc[-1]
            # Get daily change rate (日增长率)
            if '日增长率' in latest:
                daily_change = float(latest['日增长率'])
                return daily_change
            return None
            
        except Exception as e:
            print(f"Error getting CN fund daily change for {symbol}: {e}")
            return None
    
    @staticmethod
    def get_cn_fund_kline_data(symbol, period="3y"):
        """
        Get K-line data (net value history) for a Chinese fund using akshare.
        
        Args:
            symbol: Fund code (e.g., '015283')
            period: Time period - '1y', '3y', '5y', or 'all' (will filter data after fetching)
        
        Returns:
            List of dicts with date, open, high, low, close, volume
        """
        try:
            print(f"📊 Fetching CN fund K-line data for {symbol} (period={period})")
            
            # Get fund net value history
            # indicator="单位净值走势" returns: 净值日期, 单位净值, 日增长率
            # Note: akshare returns all available data, we'll filter by period later
            df = ak.fund_open_fund_info_em(symbol=symbol, indicator="单位净值走势")
            
            if df is None or df.empty:
                print(f"Warning: Empty data for CN fund {symbol}")
                return None
            
            # Filter data by period
            if period != 'all':
                period_days = {
                    '1y': 365,
                    '3y': 365 * 3,
                    '5y': 365 * 5
                }
                days = period_days.get(period, 365 * 3)
                cutoff_date = datetime.now() - timedelta(days=days)
                df['净值日期'] = pd.to_datetime(df['净值日期'])
                df = df[df['净值日期'] >= cutoff_date]
            
            # Format data for frontend (funds don't have OHLC, so we use net value for all)
            data = []
            for _, row in df.iterrows():
                try:
                    date_str = pd.to_datetime(row['净值日期']).strftime('%Y-%m-%d')
                    net_value = float(row['单位净值'])
                    
                    # For funds, we use net value as close price
                    # Set open=high=low=close since funds only have one price per day
                    data.append({
                        "date": date_str,
                        "open": round(net_value, 4),
                        "high": round(net_value, 4),
                        "low": round(net_value, 4),
                        "close": round(net_value, 4),
                        "volume": 0  # Funds don't have volume data
                    })
                except Exception as e:
                    print(f"Error parsing row for {symbol}: {e}")
                    continue
            
            print(f"✅ Fetched {len(data)} data points for CN fund {symbol}")
            return data
            
        except Exception as e:
            error_msg = str(e)
            print(f"Error fetching CN fund data for {symbol}: {error_msg}")
            return None

    @staticmethod
    def search_symbol(query, search_type='ALL'):
        """
        Search for a stock symbol. 
        Tries Yahoo Finance API first, then falls back to local static list.
        """
        if search_type == 'FUND_CN':
            return DataProvider.search_cn_fund(query)

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
    def get_symbol_name(symbol, asset_type='STOCK', currency='USD'):
        """
        Get the full name of a symbol.
        
        Args:
            symbol: Ticker symbol
            asset_type: Asset type (STOCK, FUND_CN, CRYPTO, etc.)
            currency: Currency (USD, CNY, HKD, etc.)
        
        Returns:
            String name or None if not found
        """
        try:
            # For Chinese funds
            if asset_type == 'FUND' and currency == 'CNY':
                asset_type = 'FUND_CN'
            
            if asset_type == 'FUND_CN':
                # Search in cached fund list
                if DataProvider._cn_fund_list_cache is not None:
                    df = DataProvider._cn_fund_list_cache
                    match = df[df['基金代码'] == symbol]
                    if not match.empty:
                        return match.iloc[0]['基金简称']
                # If not in cache, try to fetch
                results = DataProvider.search_cn_fund(symbol)
                if results:
                    return results[0]['name']
                return None
            
            # For stocks and other assets, use yfinance
            ticker = yf.Ticker(symbol)
            info = ticker.info
            
            # Try different name fields
            if 'longName' in info and info['longName']:
                return info['longName']
            elif 'shortName' in info and info['shortName']:
                return info['shortName']
            elif 'name' in info and info['name']:
                return info['name']
            
            return None
            
        except Exception as e:
            print(f"Error getting name for {symbol}: {e}")
            return None

    @staticmethod
    def get_kline_data(symbol, period="3y", interval="1d", is_cn_fund=False):
        """
        Get K-line data for a symbol.
        
        Args:
            symbol: Ticker symbol
            period: Time period (e.g., '3y', '1y')
            interval: Data interval (e.g., '1d')
            is_cn_fund: If True, use akshare for Chinese fund data; otherwise use yfinance
        
        Returns:
            List of dicts with OHLCV data
        """
        # If it's a Chinese fund, use akshare
        if is_cn_fund:
            return DataProvider.get_cn_fund_kline_data(symbol, period)
        
        # Otherwise, use yfinance for stocks
        try:
            # Fetch data using yfinance
            # auto_adjust=True ensures we get split/dividend adjusted prices
            hist = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
            
            if hist is None or hist.empty:
                print(f"Warning: Empty data for {symbol}, possibly delisted or invalid symbol")
                return None
            
            # Reset index to make Date a column
            hist = hist.reset_index()
            
            # Format data for frontend
            data = []
            for _, row in hist.iterrows():
                dt = row['Date']
                if isinstance(dt, pd.Timestamp):
                    date_str = dt.strftime('%Y-%m-%d')
                else:
                    date_str = str(dt)[:10]
                    
                data.append({
                    "date": date_str,
                    "open": round(float(row['Open']), 4),
                    "high": round(float(row['High']), 4),
                    "low": round(float(row['Low']), 4),
                    "close": round(float(row['Close']), 4),
                    "volume": int(row['Volume']) if 'Volume' in row else 0
                })
                
            return data
        except Exception as e:
            error_msg = str(e)
            print(f"Error fetching data for {symbol}: {error_msg}")
            return None

    @staticmethod
    def get_current_price(symbol):
        """
        Get the latest/current price for a symbol using yfinance.
        Returns the most recent close price available.
        """
        try:
            # Fetch 1 day of data
            hist = yf.Ticker(symbol).history(period="1d", auto_adjust=True)
            
            if hist is None or hist.empty:
                print(f"Warning: No current price data for {symbol}")
                return None
            
            # Get the latest close price (last row)
            latest_price = float(hist['Close'].iloc[-1])
            
            # Round to appropriate precision based on price magnitude
            if latest_price >= 100:
                return round(latest_price, 2)
            elif latest_price >= 10:
                return round(latest_price, 3)
            else:
                return round(latest_price, 4)
                
        except Exception as e:
            print(f"Error fetching current price for {symbol}: {e}")
            return None
    
    @staticmethod
    def get_daily_change_percent(symbol):
        """
        Get today's price change percentage for a symbol.
        Returns the percentage change from previous close to current price.
        """
        try:
            # Fetch 5 days of data to ensure we have previous close
            hist = yf.Ticker(symbol).history(period="5d", auto_adjust=True)
            
            if hist is None or hist.empty or len(hist) < 2:
                print(f"Warning: Insufficient data for daily change calculation for {symbol}")
                return None
            
            # Get current price (latest close) and previous close
            current_price = float(hist['Close'].iloc[-1])
            prev_close = float(hist['Close'].iloc[-2])
            
            if prev_close == 0:
                return None
            
            # Calculate percentage change
            change_percent = ((current_price - prev_close) / prev_close) * 100
            
            return round(change_percent, 2)
                
        except Exception as e:
            print(f"Error fetching daily change for {symbol}: {e}")
            return None
    
    @staticmethod
    def get_exchange_rate(from_currency, to_currency='USD'):
        """
        Get exchange rate from one currency to another using yfinance.
        
        Args:
            from_currency: Source currency code (e.g., 'CNY', 'HKD')
            to_currency: Target currency code (default: 'USD')
            
        Returns:
            Exchange rate as float, or 1.0 if same currency or error
        """
        # Ensure uppercase
        from_currency = from_currency.upper()
        to_currency = to_currency.upper()
        
        # If same currency, return 1.0
        if from_currency == to_currency:
            return 1.0
        
        try:
            # Use yfinance to get exchange rates
            # Construct symbol for yfinance
            # Common pairs: CNY=X (USD/CNY), HKD=X (USD/HKD), EURUSD=X (EUR/USD), GBPUSD=X (GBP/USD)
            
            rate = None
            
            if to_currency == 'USD':
                # Converting TO USD
                if from_currency in ['CNY', 'HKD', 'JPY']:
                    # These are usually quoted as USD/XXX (e.g. CNY=X means 1 USD = x CNY)
                    symbol = f"{from_currency}=X"
                    hist = yf.Ticker(symbol).history(period="1d")
                    if not hist.empty:
                        # Rate is USD/CNY, so we need 1/Rate for CNY->USD
                        quote = float(hist['Close'].iloc[-1])
                        if quote > 0:
                            rate = 1.0 / quote
                elif from_currency in ['EUR', 'GBP', 'AUD']:
                    # These are usually quoted as XXX/USD (e.g. EURUSD=X means 1 EUR = x USD)
                    symbol = f"{from_currency}USD=X"
                    hist = yf.Ticker(symbol).history(period="1d")
                    if not hist.empty:
                        rate = float(hist['Close'].iloc[-1])
            elif from_currency == 'USD':
                # Converting FROM USD to other currencies
                if to_currency in ['CNY', 'HKD', 'JPY']:
                    # These are usually quoted as USD/XXX (e.g. CNY=X means 1 USD = x CNY)
                    symbol = f"{to_currency}=X"
                    hist = yf.Ticker(symbol).history(period="1d")
                    if not hist.empty:
                        # Rate is USD/CNY, which is exactly what we want
                        rate = float(hist['Close'].iloc[-1])
                elif to_currency in ['EUR', 'GBP', 'AUD']:
                    # These are usually quoted as XXX/USD (e.g. EURUSD=X means 1 EUR = x USD)
                    symbol = f"{to_currency}USD=X"
                    hist = yf.Ticker(symbol).history(period="1d")
                    if not hist.empty:
                        # Rate is EUR/USD, so we need 1/Rate for USD->EUR
                        quote = float(hist['Close'].iloc[-1])
                        if quote > 0:
                            rate = 1.0 / quote
            
            if rate:
                return rate
            
            # Fallback to approximate rates if API fails or pair not handled
            print(f"Using fallback rate for {from_currency} to {to_currency}")
            if to_currency == 'USD':
                fallback_rates = {
                    'CNY': 0.14,  # 1 CNY ≈ 0.14 USD
                    'HKD': 0.128,  # 1 HKD ≈ 0.128 USD
                    'EUR': 1.10,   # 1 EUR ≈ 1.10 USD
                    'GBP': 1.27,   # 1 GBP ≈ 1.27 USD
                    'JPY': 0.0067, # 1 JPY ≈ 0.0067 USD
                }
                return fallback_rates.get(from_currency, 1.0)
            elif from_currency == 'USD':
                fallback_rates = {
                    'CNY': 7.2,    # 1 USD ≈ 7.2 CNY
                    'HKD': 7.8,    # 1 USD ≈ 7.8 HKD
                    'EUR': 0.91,   # 1 USD ≈ 0.91 EUR
                    'GBP': 0.79,   # 1 USD ≈ 0.79 GBP
                    'JPY': 149.0,  # 1 USD ≈ 149 JPY
                }
                return fallback_rates.get(to_currency, 1.0)
            return 1.0
                
        except Exception as e:
            print(f"Error getting exchange rate for {from_currency} to {to_currency}: {e}")
            # Return fallback rates
            if to_currency == 'USD':
                fallback_rates = {
                    'CNY': 0.14,
                    'HKD': 0.128,
                    'EUR': 1.10,
                    'GBP': 1.27,
                    'JPY': 0.0067,
                }
                return fallback_rates.get(from_currency, 1.0)
            elif from_currency == 'USD':
                fallback_rates = {
                    'CNY': 7.2,
                    'HKD': 7.8,
                    'EUR': 0.91,
                    'GBP': 0.79,
                    'JPY': 149.0,
                }
                return fallback_rates.get(to_currency, 1.0)
            return 1.0


class BatchFetcher:
    """
    Batch data fetcher for yfinance API calls.
    Reduces rate limit issues by fetching multiple symbols efficiently.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern to ensure only one fetcher instance"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._cache = {}
                    cls._instance._cache_timestamps = {}
                    cls._instance._cache_lock = threading.Lock()
                    # Rate limiter: allow 5 requests per 1 second (yfinance is more lenient)
                    cls._instance._rate_limiter = RateLimiter(max_calls=5, time_window=1)
        return cls._instance
    
    def _is_cache_valid(self, cache_key, ttl_seconds: int = 300) -> bool:
        """Check if cache entry is still valid"""
        if cache_key not in self._cache_timestamps:
            return False
        age = (datetime.now(timezone.utc) - self._cache_timestamps[cache_key]).total_seconds()
        return age < ttl_seconds
    
    def _update_cache(self, cache_key, data):
        """Update cache with timestamp"""
        with self._cache_lock:
            self._cache[cache_key] = data
            self._cache_timestamps[cache_key] = datetime.now(timezone.utc)
    
    def _get_from_cache(self, cache_key):
        """Get data from cache if valid"""
        with self._cache_lock:
            if self._is_cache_valid(cache_key):
                return self._cache[cache_key]
        return None
    
    @retry_on_rate_limit(max_retries=3, initial_delay=2.0, backoff_factor=2.0)
    def batch_fetch_history(
        self,
        symbols: List[str],
        period: str = "5d",
        interval: str = "1d",
        use_cache: bool = True,
        cache_ttl: int = 300
    ) -> Dict[str, pd.DataFrame]:
        """
        Batch fetch historical data for multiple symbols using yfinance.
        
        Args:
            symbols: List of ticker symbols
            period: Time period (e.g., '5d', '1mo', '3y')
            interval: Data interval (e.g., '1d', '1h', '5m')
            use_cache: Whether to use cached data
            cache_ttl: Cache time-to-live in seconds
            
        Returns:
            Dictionary mapping symbol to DataFrame
        """
        if not symbols:
            return {}
        
        # Create cache key
        cache_key = f"batch_{period}_{interval}_{'_'.join(sorted(symbols))}"
        
        # Try cache first
        if use_cache:
            cached_data = self._get_from_cache(cache_key)
            if cached_data:
                print(f"✅ Using cached batch data for {len(symbols)} symbols")
                return cached_data
        
        # Acquire rate limit permission before making API call
        self._rate_limiter.acquire()
        
        try:
            print(f"📡 Batch fetching {len(symbols)} symbols with period={period}, interval={interval}")
            
            results = {}
            
            # Use yfinance batch download
            # group_by='ticker' makes it easier to separate data
            # threads=False to avoid potential threading issues in web server environment
            print(f"    ⬇️ Downloading data for {len(symbols)} symbols...")
            data = yf.download(
                tickers=symbols, 
                period=period, 
                interval=interval, 
                group_by='ticker', 
                auto_adjust=True, 
                threads=False,
                progress=False
            )
            
            if data is None or data.empty:
                print("⚠️ Batch fetch returned empty data")
                return {symbol: pd.DataFrame() for symbol in symbols}
            
            # Process results
            if len(symbols) == 1:
                # If only one symbol, yf.download returns a simple DataFrame (not MultiIndex)
                symbol = symbols[0]
                if not data.empty:
                    # Reset index to make Date a column
                    df = data.reset_index()
                    results[symbol] = df
                else:
                    results[symbol] = pd.DataFrame()
            else:
                # For multiple symbols, data is MultiIndex with Ticker as top level
                # Check if columns are MultiIndex
                if isinstance(data.columns, pd.MultiIndex):
                    for symbol in symbols:
                        try:
                            # Extract data for this symbol
                            if symbol in data.columns.levels[0]:
                                df = data[symbol].copy()
                                # Drop rows where all columns are NaN
                                df = df.dropna(how='all')
                                
                                if not df.empty:
                                    df = df.reset_index()
                                    results[symbol] = df
                                else:
                                    results[symbol] = pd.DataFrame()
                            else:
                                results[symbol] = pd.DataFrame()
                        except Exception as e:
                            print(f"    ❌ Error processing {symbol}: {e}")
                            results[symbol] = pd.DataFrame()
                else:
                    # Sometimes yfinance returns single level columns if only one ticker was valid or found
                    # This is tricky, but let's assume if it's not MultiIndex, it might be for the single valid ticker
                    # But we passed multiple symbols...
                    # Let's try to match columns if possible, or just log warning
                    print("    ⚠️ Unexpected data format from yfinance batch download")
            
            # Count successful fetches
            successful = sum(1 for df in results.values() if not df.empty)
            print(f"✅ Batch fetch complete: {successful}/{len(symbols)} symbols fetched successfully")
            
            # Update cache
            self._update_cache(cache_key, results)
            
            return results
            
        except Exception as e:
            print(f"❌ Error in batch fetch: {e}")
            return {symbol: pd.DataFrame() for symbol in symbols}
    
    @retry_on_rate_limit(max_retries=3, initial_delay=10.0, backoff_factor=2.0)
    def get_cached_kline_data(
        self,
        symbol: str,
        period: str = "3y",
        interval: str = "1d",
        is_cn_fund: bool = False
    ) -> Optional[List[Dict]]:
        """
        Get K-line data with caching support.
        
        Args:
            symbol: Ticker symbol
            period: Time period (e.g., '5d', '1mo', '3y')
            interval: Data interval (e.g., '1d', '1h', '5m')
            is_cn_fund: If True, use akshare for Chinese fund data
            
        Returns:
            List of dicts with OHLCV data
        """
        cache_key = f"kline_{symbol}_{period}_{interval}_{'cnfund' if is_cn_fund else 'stock'}"
        
        # Try cache first (5 minutes for short periods, 1 hour for longer periods)
        ttl = 300 if period in ['1d', '5d', '1wk'] else 3600
        cached = self._get_from_cache(cache_key)
        if cached:
            return cached
        
        # Acquire rate limit permission
        self._rate_limiter.acquire()
        
        # Fetch data
        print(f"📊 Fetching K-line data for {symbol} (period={period}, interval={interval}, is_cn_fund={is_cn_fund})")
        result = DataProvider.get_kline_data(symbol, period, interval, is_cn_fund=is_cn_fund)
        
        # Update cache
        if result:
            self._update_cache(cache_key, result)
            print(f"✅ K-line data cached for {symbol}")
        else:
            print(f"⚠️ No K-line data returned for {symbol}")
        
        return result
    
    @retry_on_rate_limit(max_retries=3, initial_delay=10.0, backoff_factor=2.0)
    def get_cached_current_price(self, symbol: str, asset_type: str = None, currency: str = None) -> Optional[float]:
        """
        Get current price with caching support.
        
        Args:
            symbol: Ticker symbol
            asset_type: Asset type (optional, e.g., 'FUND', 'STOCK')
            currency: Currency code (optional, e.g., 'CNY', 'USD')
            
        Returns:
            Current price or None
        """
        cache_key = f"price_{symbol}"
        
        # Try cache first (1 minute TTL for real-time data)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        # Acquire rate limit permission
        self._rate_limiter.acquire()
        
        # Fetch data
        print(f"💰 Fetching current price for {symbol} (type={asset_type}, currency={currency})")
        
        # Determine if it's a Chinese fund: FUND type + CNY currency OR FUND_CN type
        is_cn_fund = (asset_type == 'FUND' and currency == 'CNY') or asset_type == 'FUND_CN'
        
        if is_cn_fund:
            result = DataProvider.get_cn_fund_price(symbol)
        else:
            result = DataProvider.get_current_price(symbol)
        
        # Update cache
        if result is not None:
            self._update_cache(cache_key, result)
            print(f"✅ Price cached for {symbol}: {result}")
        else:
            print(f"⚠️ No price data returned for {symbol}")
        
        return result
    
    @retry_on_rate_limit(max_retries=3, initial_delay=10.0, backoff_factor=2.0)
    def get_cached_daily_change(self, symbol: str, asset_type: str = None, currency: str = None) -> Optional[float]:
        """
        Get daily change percentage with caching support.
        
        Args:
            symbol: Ticker symbol
            asset_type: Asset type (optional, e.g., 'FUND', 'STOCK')
            currency: Currency code (optional, e.g., 'CNY', 'USD')
            
        Returns:
            Daily change percentage or None
        """
        cache_key = f"daily_change_{symbol}"
        
        # Try cache first (1 minute TTL for real-time data)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        # Acquire rate limit permission
        self._rate_limiter.acquire()
        
        # Fetch data
        print(f"📈 Fetching daily change for {symbol} (type={asset_type}, currency={currency})")
        
        # Chinese funds don't have daily change data easily available
        is_cn_fund = (asset_type == 'FUND' and currency == 'CNY') or asset_type == 'FUND_CN'
        
        if is_cn_fund:
            # For CN funds, get daily change from akshare
            result = DataProvider.get_cn_fund_daily_change(symbol)
        else:
            result = DataProvider.get_daily_change_percent(symbol)
        
        # Update cache
        if result is not None:
            self._update_cache(cache_key, result)
            print(f"✅ Daily change cached for {symbol}: {result}%")
        else:
            print(f"⚠️ No daily change data returned for {symbol}")
        
        return result
    
    @retry_on_rate_limit(max_retries=3, initial_delay=10.0, backoff_factor=2.0)
    def get_cached_exchange_rate(self, from_currency: str, to_currency: str = 'USD') -> float:
        """
        Get exchange rate with caching support.
        
        Args:
            from_currency: Source currency code
            to_currency: Target currency code
            
        Returns:
            Exchange rate
        """
        if from_currency == to_currency:
            return 1.0
            
        cache_key = f"rate_{from_currency}_{to_currency}"
        
        # Try cache first (1 hour TTL for exchange rates)
        cached = self._get_from_cache(cache_key)
        if cached is not None:
            return cached
        
        # Acquire rate limit permission
        self._rate_limiter.acquire()
        
        # Fetch data
        print(f"💱 Fetching exchange rate for {from_currency}/{to_currency}")
        result = DataProvider.get_exchange_rate(from_currency, to_currency)
        
        # Update cache
        self._update_cache(cache_key, result)
        print(f"✅ Exchange rate cached for {from_currency}/{to_currency}: {result}")
        
        return result

    def clear_cache(self, pattern: str = None):
        """
        Clear cache entries, optionally matching a pattern.
        
        Args:
            pattern: Pattern to match (e.g., 'kline_', 'price_'). If None, clears all.
        """
        with self._cache_lock:
            if pattern:
                keys_to_delete = [k for k in self._cache.keys() if pattern in k]
                for key in keys_to_delete:
                    del self._cache[key]
                    del self._cache_timestamps[key]
            else:
                self._cache.clear()
                self._cache_timestamps.clear()
        print(f"Cleared cache matching pattern: {pattern or 'all'}")

# Global instance for easy access
batch_fetcher = BatchFetcher()

