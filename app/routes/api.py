from flask import Blueprint, request, jsonify, session
from app.services.data_provider import DataProvider
from app.services.ai_analyzer import AIAnalyzer
from app.models.analysis import AnalysisLog, StockTradeSignal, RecommendationCache, User, Task
from app.services.model_config import get_models_for_frontend
from app.services.task_service import task_service
from app import db
import json
import hashlib
import re
import uuid
from datetime import datetime, timedelta

api_bp = Blueprint('api', __name__)
ai_analyzer = AIAnalyzer()

@api_bp.route('/models', methods=['GET'])
def get_models():
    """Get available models for frontend"""
    models = get_models_for_frontend()
    return jsonify(models)

def get_analysis_status(symbol, model_name):
    """Helper to get the latest analyzed date for a symbol and model"""
    latest_signal = StockTradeSignal.query.filter_by(
        symbol=symbol,
        model_name=model_name
    ).order_by(StockTradeSignal.date.desc()).first()
    return latest_signal.date if latest_signal else None

def get_current_position(symbol, model_name):
    """
    Replay history to find if we are currently holding a position for a specific model.
    Returns dict {date, price, reason} or None.
    """
    signals = StockTradeSignal.query.filter_by(
        symbol=symbol,
        model_name=model_name
    ).order_by(StockTradeSignal.date.asc()).all()
    position = None
    for s in signals:
        if s.signal_type == 'BUY':
            # Only open position if we don't have one (simple FIFO/One-at-a-time assumption for now)
            if position is None:
                position = {
                    'date': s.date.strftime('%Y-%m-%d'),
                    'price': s.price,
                    'reason': s.reason
                }
        elif s.signal_type == 'SELL':
            if position:
                position = None # Closed
    return position

@api_bp.route('/recommend', methods=['POST'])
def recommend():
    """
    推荐结果带缓存（一天内的请求走缓存，提升响应速度并降低 API 成本）
    """
    data = request.json
    model_name = data.get('model', 'gemini-3-flash-preview')
    language = data.get('language', 'zh')
    
    criteria = {
        'market': data.get('market', 'Any'),
        'asset_type': data.get('asset_type', 'STOCK'),
        'capital': data.get('capital', 'Any'),
        'risk': data.get('risk', 'Any'),
        'frequency': data.get('frequency', 'Any')
    }
    
    # 生成筛选条件的哈希值（用于区分不同的查询）
    criteria_str = json.dumps(criteria, sort_keys=True)
    criteria_hash = hashlib.md5(f"{criteria_str}_{model_name}_{language}".encode()).hexdigest()
    
    # 获取当前日期
    today = datetime.utcnow().date()
    
    # 检查是否有当天的缓存
    cached = RecommendationCache.query.filter_by(
        cache_date=today,
        model_name=model_name,
        language=language,
        criteria_hash=criteria_hash
    ).first()
    
    if cached and cached.recommendation_result:
        print(f"[Recommend] Using cached result for {today}")
        try:
            cached_result = json.loads(cached.recommendation_result)
            cached_result['_cached'] = True  # 添加缓存标识
            return jsonify(cached_result)
        except json.JSONDecodeError as e:
            print(f"JSON decode error for cached recommendation: {e}, regenerating...")
            db.session.delete(cached)
            db.session.commit()
    
    # 没有缓存，调用 AI 生成推荐
    print(f"[Recommend] No cache found, calling AI for {today}")
    result = ai_analyzer.recommend_stocks(criteria, model_name=model_name, language=language)
    
    # 保存到缓存（使用 upsert 模式：如果已存在则更新，否则插入）
    try:
        existing_cache = RecommendationCache.query.filter_by(
            cache_date=today,
            model_name=model_name,
            language=language,
            criteria_hash=criteria_hash
        ).first()
        
        if existing_cache:
            # 更新现有缓存
            existing_cache.recommendation_result = json.dumps(result)
            existing_cache.created_at = datetime.utcnow()
            db.session.commit()
            print(f"[Recommend] Result updated in cache for {today}")
        else:
            # 创建新缓存
            new_cache = RecommendationCache(
                cache_date=today,
                model_name=model_name,
                language=language,
                criteria_hash=criteria_hash,
                recommendation_result=json.dumps(result)
            )
            db.session.add(new_cache)
            db.session.commit()
            print(f"[Recommend] Result cached for {today}")
    except Exception as e:
        db.session.rollback()
        print(f"Cache save error: {e}")
    
    result['_cached'] = False  # 添加缓存标识
    return jsonify(result)

@api_bp.route('/portfolio_advice', methods=['POST'])
def portfolio_advice():
    data = request.json
    model_name = data.get('model', 'gemini-3-flash-preview')
    language = data.get('language', 'zh')
    
    result = ai_analyzer.analyze_portfolio_item(data, model_name=model_name, language=language)
    return jsonify(result)

@api_bp.route('/translate', methods=['POST'])
def translate():
    data = request.json
    text = data.get('text')
    target_lang = data.get('target_lang', 'en')
    model_name = data.get('model', 'gemini-3-flash-preview')
    
    if not text:
        return jsonify({"error": "No text provided"}), 400
        
    result = ai_analyzer.translate_text(text, target_language=target_lang, model_name=model_name)
    return jsonify(result)

@api_bp.route('/search', methods=['GET'])
def search():
    query = request.args.get('q', '')
    if not query:
        return jsonify([])
    
    results = DataProvider.search_symbol(query)
    return jsonify(results)

@api_bp.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    symbol = data.get('symbol')
    asset_type = data.get('asset_type', 'STOCK')
    model_name = data.get('model', 'gemini-3-flash-preview') # Default to 2.5 Flash
    language = data.get('language', 'zh')
    
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
        
    # 1. Get K-line Data (Always fetch fresh market data)
    kline_data = DataProvider.get_kline_data(symbol)
    if not kline_data:
        return jsonify({'error': 'Could not fetch data for symbol'}), 404
    
    # Determine the market data range
    market_dates = [d['date'] for d in kline_data]
    if not market_dates:
        return jsonify({'error': 'Empty market data'}), 404
        
    latest_market_date_str = market_dates[-1]
    latest_market_date = datetime.strptime(latest_market_date_str, '%Y-%m-%d').date()
    
    # --- 检查 MySQL 是否已有当天的分析记录 ---
    existing_log = AnalysisLog.query.filter_by(
        symbol=symbol,
        market_date=latest_market_date,
        model_name=model_name,
        language=language
    ).first()
    
    if existing_log and existing_log.analysis_result:
        print(f"[{symbol}] Using cached analysis from MySQL for {latest_market_date_str}")
        try:
            cached_data = json.loads(existing_log.analysis_result)
            return jsonify(cached_data)
        except json.JSONDecodeError as e:
            print(f"JSON decode error for existing log: {e}, re-analyzing...")
            # 如果 JSON 损坏，删除旧记录并重新分析
            db.session.delete(existing_log)
            db.session.commit()

    # 2. Check DB for existing signals
    # We want to ensure "Model-specific History" consistency.
    # Each model maintains its own separate trading history.
    
    latest_analyzed_date = get_analysis_status(symbol, model_name)
    current_position_state = get_current_position(symbol, model_name)
    
    analysis_result = {
        "analysis_summary": "AI Analysis based on historical data.",
        "trades": [],
        "signals": [],
        "source": "ai_model" # Default assumption
    }
    
    # LOGIC:
    # Case A: No history -> Run Full Initialization (Last 3 Years)
    # Case B: History exists but stale -> Run Incremental (Gap days)
    # Case C: History up to date -> Just read DB
    
    # If using Local Strategy, we skip DB persistence logic for now as per request "Global history... from AI"
    # But user said "System produced history... global". 
    # Let's enforce this logic for AI models. Local strategy is deterministic anyway.
    
    if model_name == "local-strategy":
        analysis_result = ai_analyzer.analyze(symbol, kline_data, model_name=model_name, language=language)
        return jsonify({
            'symbol': symbol,
            'kline_data': kline_data,
            'analysis': analysis_result,
            'source': 'local'
        })

    # --- AI PERSISTENCE LOGIC ---
    
    new_signals = []
    should_cache = True  # 默认允许缓存（从DB读取历史数据时）
    
    if not latest_analyzed_date:
        print(f"[{symbol}] No history found. Running full initialization...")
        # Run full analysis
        # We use the existing 'analyze' method which generates a full report
        # But we need to parse it into signals and save to DB
        full_analysis = ai_analyzer.analyze(
            symbol, 
            kline_data, 
            model_name=model_name, 
            language=language,
            current_position=current_position_state
        )
        
        if full_analysis.get('source') == 'ai_model':
            # AI 分析成功，保存信号到 DB（按模型分开存储）
            for sig in full_analysis.get('signals', []):
                try:
                    # Check if signal already exists (shouldn't for new init, but safe check)
                    sig_date = datetime.strptime(sig['date'], '%Y-%m-%d').date()
                    exists = StockTradeSignal.query.filter_by(
                        symbol=symbol,
                        date=sig_date,
                        model_name=model_name,
                        asset_type=asset_type
                    ).first()
                    if not exists:
                        new_signal = StockTradeSignal(
                            symbol=symbol,
                            date=sig_date,
                            price=sig['price'],
                            signal_type=sig['type'], # BUY/SELL
                            reason=sig.get('reason', ''),
                            source='ai',
                            model_name=model_name,
                            asset_type=asset_type
                        )
                        db.session.add(new_signal)
                except Exception as e:
                    print(f"Error saving signal: {e}")
            try:
                db.session.commit()
                print(f"[{symbol}] Full history saved.")
            except Exception as e:
                db.session.rollback()
                print(f"DB Commit Error: {e}")
        else:
            # AI 失败，降级到本地策略，不缓存本次结果
            should_cache = False
            print(f"[{symbol}] AI analysis failed, local strategy used. Will not cache.")
    
    else:
        # Check for gap
        # If latest_market_date > latest_analyzed_date
        # We need to fill the gap.
        # However, generating day-by-day signals for a long gap is slow.
        # For simplicity and robustness, if gap is small (< 5 days), we do incremental?
        # Or just run the standard analysis again but ONLY save the new signals?
        # User requirement: "History data is global... do not change old data".
        # So we must NOT overwrite old signals.
        
        print(f"[{symbol}] Found history up to {latest_analyzed_date}. Market date: {latest_market_date}")
        
        if latest_market_date > latest_analyzed_date:
            print(f"[{symbol}] Incremental update needed.")
            # For the purpose of this task, we will re-run the analysis to get the "latest" view
            # BUT we will only extract and save signals that are NEWer than latest_analyzed_date.
            # This ensures we don't rewrite history, but we append new history.
            
            # Optimization: We could pass only recent data to AI context if the gap is small, 
            # but the current 'analyze' prompt expects full context.
            # Let's run 'analyze' (it takes ~5s) and filter results.
            
            fresh_analysis = ai_analyzer.analyze(
                symbol, 
                kline_data, 
                model_name=model_name, 
                language=language,
                current_position=current_position_state
            )
            
            if fresh_analysis.get('source') == 'ai_model':
                # AI 分析成功，保存新信号到 DB（按模型分开存储）
                for sig in fresh_analysis.get('signals', []):
                    sig_date = datetime.strptime(sig['date'], '%Y-%m-%d').date()
                    if sig_date > latest_analyzed_date:
                        # This is a NEW signal
                        try:
                            new_signal = StockTradeSignal(
                                symbol=symbol,
                                date=sig_date,
                                price=sig['price'],
                                signal_type=sig['type'],
                                reason=sig.get('reason', ''),
                                source='ai',
                                model_name=model_name,
                                asset_type=asset_type
                            )
                            db.session.add(new_signal)
                            print(f"[{symbol}] New signal added for {model_name}: {sig_date} {sig['type']}")
                        except Exception as e:
                            print(f"Error adding signal: {e}")
                try:
                    db.session.commit()
                except Exception as e:
                    db.session.rollback()
            else:
                # AI 失败，降级到本地策略，不缓存本次结果
                should_cache = False
                print(f"[{symbol}] AI analysis failed during incremental update, local strategy used. Will not cache.")

    # 3. Construct Final Response from DB
    # Now we read the "Model-specific History" from DB to ensure consistency for each model
    
    db_signals = StockTradeSignal.query.filter_by(
        symbol=symbol,
        model_name=model_name,
        asset_type=asset_type
    ).order_by(StockTradeSignal.date.asc()).all()
    
    # Reconstruct 'trades' (pair of Buy/Sell) from signals for the UI
    reconstructed_trades = []
    current_position = None # {date, price, reason}
    
    ui_signals = []
    
    for s in db_signals:
        date_str = s.date.strftime('%Y-%m-%d')
        
        # Add to signals list for chart
        ui_signals.append({
            "type": s.signal_type,
            "date": date_str,
            "price": s.price,
            "reason": s.reason
        })
        
        # Logic to pair trades
        if s.signal_type == 'BUY':
            if current_position is None:
                current_position = {
                    'buy_date': date_str,
                    'buy_price': s.price,
                    'buy_reason': s.reason
                }
        elif s.signal_type == 'SELL':
            if current_position:
                # Close position
                buy_price = current_position['buy_price']
                sell_price = s.price
                ret_pct = ((sell_price - buy_price) / buy_price) * 100
                
                # Calculate days
                d1 = datetime.strptime(current_position['buy_date'], '%Y-%m-%d')
                d2 = s.date
                days = (datetime.combine(d2, datetime.min.time()) - d1).days
                
                reconstructed_trades.append({
                    "buy_date": current_position['buy_date'],
                    "buy_price": round(buy_price, 2),
                    "sell_date": date_str,
                    "sell_price": round(sell_price, 2),
                    "status": "CLOSED",
                    "holding_period": f"{days} days",
                    "return_rate": f"{ret_pct:+.2f}%",
                    "reason": s.reason # Use sell reason
                })
                current_position = None
                
    # Handle open position
    if current_position:
        # Get latest price from kline_data
        latest_close = kline_data[-1]['close']
        latest_date_str = kline_data[-1]['date']
        
        buy_price = current_position['buy_price']
        curr_ret = ((latest_close - buy_price) / buy_price) * 100
        
        d1 = datetime.strptime(current_position['buy_date'], '%Y-%m-%d')
        d2 = datetime.strptime(latest_date_str, '%Y-%m-%d')
        days = (d2 - d1).days
        
        reconstructed_trades.append({
            "buy_date": current_position['buy_date'],
            "buy_price": round(buy_price, 2),
            "sell_date": None,
            "sell_price": None,
            "status": "HOLDING",
            "holding_period": f"{days} days",
            "return_rate": f"{curr_ret:+.2f}% (Open)",
            "reason": current_position['buy_reason']
        })
        
    # Sort desc for UI
    reconstructed_trades.sort(key=lambda x: x['buy_date'], reverse=True)
    
    # Construct final analysis result
    # We might need a summary. We can fetch the latest summary from AnalysisLog or just use a generic one.
    # Or we can generate a quick summary if needed. 
    # For now, reusing the summary from the fresh analysis (if we ran it) or a placeholder.
    
    summary_text = f"Model-specific History Loaded ({model_name}). "
    if 'fresh_analysis' in locals():
        summary_text = fresh_analysis.get('analysis_summary', summary_text)
    elif 'full_analysis' in locals():
        summary_text = full_analysis.get('analysis_summary', summary_text)
    else:
        # Try to get from latest AnalysisLog as fallback for summary text (filter by model)
        last_log = AnalysisLog.query.filter_by(
            symbol=symbol,
            model_name=model_name
        ).order_by(AnalysisLog.created_at.desc()).first()
        if last_log and last_log.analysis_result:
            try:
                summary_text = json.loads(last_log.analysis_result).get('analysis_summary', summary_text)
            except:
                pass

    final_result = {
        "analysis_summary": summary_text,
        "trades": reconstructed_trades,
        "signals": ui_signals,
        "source": "ai_model_history"
    }

    final_response = {
        'symbol': symbol,
        'kline_data': kline_data,
        'analysis': final_result,
        'source': 'ai_database'
    }
    
    # --- 保存到 MySQL AnalysisLog（当天的分析缓存） ---
    # 只有当数据来自 AI 分析时才缓存，本地策略降级的结果不缓存
    if should_cache:
        try:
            # 检查是否已存在（理论上不应该，因为前面已经检查过了）
            existing = AnalysisLog.query.filter_by(
                symbol=symbol,
                market_date=latest_market_date,
                model_name=model_name,
                language=language
            ).first()
            
            if not existing:
                new_log = AnalysisLog(
                    symbol=symbol,
                    market_date=latest_market_date,
                    model_name=model_name,
                    language=language,
                    analysis_result=json.dumps(final_response)
                )
                db.session.add(new_log)
                db.session.commit()
                print(f"[{symbol}] Analysis result saved to MySQL for {latest_market_date_str}")
            else:
                # 更新已有记录
                existing.analysis_result = json.dumps(final_response)
                existing.created_at = datetime.utcnow()
                db.session.commit()
                print(f"[{symbol}] Analysis result updated in MySQL for {latest_market_date_str}")
        except Exception as e:
            db.session.rollback()
            print(f"MySQL Save Error: {e}")
    else:
        print(f"[{symbol}] Skipping cache due to local strategy fallback.")

    return jsonify(final_response)

@api_bp.route('/market_indices', methods=['GET'])
def get_market_indices():
    """Get major market indices for dashboard"""
    import yfinance as yf
    from app import r
    
    # Check cache first (cache for 5 minutes for real-time feel)
    cache_key = 'market_indices'
    try:
        cached = r.get(cache_key)
        if cached:
            return jsonify(json.loads(cached))
    except:
        pass
    
    # Define major indices with their symbols and metadata
    indices = [
        {'symbol': '^GSPC', 'name': 'S&P 500', 'name_zh': '标普500', 'market': 'US', 'icon': '🇺🇸'},
        {'symbol': '^NDX', 'name': 'NASDAQ 100', 'name_zh': '纳斯达克100', 'market': 'US', 'icon': '🇺🇸'},
        {'symbol': '^HSI', 'name': 'Hang Seng Index', 'name_zh': '恒生指数', 'market': 'HK', 'icon': '🇭🇰'},
        {'symbol': '3033.HK', 'name': 'Hang Seng Tech', 'name_zh': '恒生科技ETF', 'market': 'HK', 'icon': '🇭🇰'},
        {'symbol': '^N225', 'name': 'Nikkei 225', 'name_zh': '日经225', 'market': 'JP', 'icon': '🇯🇵'},
        {'symbol': '^KS11', 'name': 'KOSPI', 'name_zh': 'KOSPI', 'market': 'KR', 'icon': '🇰🇷'},
        {'symbol': '000001.SS', 'name': 'SSE Index', 'name_zh': '上证指数', 'market': 'CN', 'icon': '🇨🇳'},
        {'symbol': '399006.SZ', 'name': 'ChiNext', 'name_zh': '创业板指', 'market': 'CN', 'icon': '🇨🇳'},
        {'symbol': 'GC=F', 'name': 'Gold', 'name_zh': '黄金', 'market': 'COMMODITY', 'icon': '🥇'},
        {'symbol': 'CL=F', 'name': 'Crude Oil', 'name_zh': '原油', 'market': 'COMMODITY', 'icon': '🛢️'},
        {'symbol': 'BTC-USD', 'name': 'Bitcoin', 'name_zh': '比特币', 'market': 'CRYPTO', 'icon': '₿'}
    ]
    
    result = []
    
    for index_info in indices:
        try:
            symbol = index_info['symbol']
            # Try multiple symbol formats for HSTECH if primary fails
            hist = None
            used_symbol = symbol
            
            # Current price and change
            current_price = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2]
            change = current_price - prev_close
            change_pct = (change / prev_close) * 100
            
            # Get today's high and low
            today_high = hist['High'].iloc[-1]
            today_low = hist['Low'].iloc[-1]
            
            # Get volume if available
            volume = hist['Volume'].iloc[-1] if 'Volume' in hist.columns else 0
            volume_str = ''
            if volume > 0:
                if volume >= 1e9:
                    volume_str = f"{volume/1e9:.2f}B"
                elif volume >= 1e6:
                    volume_str = f"{volume/1e6:.1f}M"
                else:
                    volume_str = f"{volume/1e3:.1f}K"
            
            # Generate trend data for sparkline (last 5 days)
            trend_points = []
            min_price = hist['Close'].min()
            max_price = hist['Close'].max()
            price_range = max_price - min_price if max_price != min_price else 1
            
            for i, price in enumerate(hist['Close']):
                x = i * 25
                y = 40 - ((price - min_price) / price_range * 35)
                trend_points.append(f"{x},{y:.1f}")
            
            # Format price based on asset type
            if index_info['market'] == 'CRYPTO':
                price_str = f"${current_price:,.2f}"
                decimals = 2
            elif index_info['market'] == 'COMMODITY':
                if 'Gold' in index_info['name']:
                    price_str = f"${current_price:,.2f}"
                else:
                    price_str = f"${current_price:.2f}"
                decimals = 2
            elif index_info['market'] in ['CN', 'HK']:
                price_str = f"{current_price:,.2f}"
                decimals = 2
            else:
                price_str = f"{current_price:,.2f}"
                decimals = 2
            
            result.append({
                'symbol': used_symbol,
                'name': index_info['name'],
                'name_zh': index_info['name_zh'],
                'market': index_info['market'],
                'icon': index_info['icon'],
                'price': price_str,
                'price_raw': float(round(current_price, decimals)),
                'change': float(round(change, decimals)),
                'change_pct': float(round(change_pct, 2)),
                'high': float(round(today_high, decimals)),
                'low': float(round(today_low, decimals)),
                'volume': volume_str,
                'trend_data': ' '.join(trend_points),
                'is_up': 1 if change >= 0 else 0
            })
            
        except Exception as e:
            print(f"Error fetching {index_info['name_zh']} ({index_info['symbol']}): {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            continue
    
    # Cache for 5 minutes
    try:
        r.setex(cache_key, 300, json.dumps(result))
        print(f"✅ Market indices cached: {len(result)} indices")
    except Exception as e:
        print(f"⚠️ Failed to cache market indices: {e}")
    
    # Debug: Print which indices were successfully fetched
    fetched_symbols = [r['symbol'] for r in result]
    print(f"📊 Successfully fetched indices: {fetched_symbols}")
    
    return jsonify(result)

@api_bp.route('/trending', methods=['GET'])
def get_trending_stocks():
    """Get trending stocks from various markets by volume"""
    import yfinance as yf
    from app import r
    
    # Check cache first (cache for 30 minutes)
    cache_key = 'trending_stocks'
    try:
        cached = r.get(cache_key)
        if cached:
            return jsonify(json.loads(cached))
    except:
        pass
    
    trending_stocks = []
    
    # US Market: Get top stocks from major indices
    us_symbols = [
        # Tech giants and popular stocks
        'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META', 'TSLA', 'NVDA', 'AMD',
        # Financial and other popular
        'JPM', 'V', 'WMT', 'UNH', 'DIS', 'NFLX', 'BABA', 'PFE'
    ]
    
    # CN Market: Popular A-share stocks
    cn_symbols = [
        '600519.SS', '601318.SS', '600036.SS', '600276.SS',  # 贵州茅台、中国平安、招商银行、恒瑞医药
        '000858.SZ', '000333.SZ', '002594.SZ', '300750.SZ',  # 五粮液、美的集团、比亚迪、宁德时代
        '600887.SS', '601012.SS', '600900.SS', '601888.SS'   # 伊利股份、隆基绿能、长江电力、中国中免
    ]
    
    # HK Market: Popular HK stocks
    hk_symbols = [
        '0700.HK', '9988.HK', '3690.HK', '2318.HK',  # 腾讯、阿里、美团、平安
        '1810.HK', '0941.HK', '1211.HK', '2382.HK',  # 小米、中国移动、比亚迪、舜宇光学
        '0175.HK', '1398.HK', '0388.HK', '0005.HK'   # 吉利汽车、工商银行、港交所、汇丰控股
    ]
    
    def fetch_stock_data(symbol, market):
        """Fetch stock data with volume"""
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(period='5d')
            
            if hist.empty or len(hist) < 2:
                return None
            
            # Get current price and change
            current_price = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2]
            change_pct = ((current_price - prev_close) / prev_close) * 100
            
            # Get volume (use latest day)
            volume = hist['Volume'].iloc[-1]
            
            # Skip if volume is too low or zero
            if volume < 100000:
                return None
            
            volume_str = f"{volume/1e6:.1f}M" if volume >= 1e6 else f"{volume/1e3:.1f}K"
            
            # Get stock name from info (with fallback)
            try:
                info = ticker.info
                name = info.get('shortName') or info.get('longName') or symbol
                # Clean up name (remove suffixes)
                if '(' in name:
                    name = name.split('(')[0].strip()
                if len(name) > 20:
                    name = name[:20]
            except:
                name = symbol
            
            # Format price based on market
            if market == 'US':
                price_str = f"${current_price:.2f}"
                exchange = 'NASDAQ'
            elif market == 'CN':
                price_str = f"¥{current_price:.2f}"
                exchange = 'SSE' if '.SS' in symbol else 'SZSE'
            else:  # HK
                price_str = f"HK${current_price:.2f}"
                exchange = 'HKEX'
            
            # Generate mini trend data (last 5 days)
            trend_points = []
            min_price = hist['Close'].min()
            max_price = hist['Close'].max()
            price_range = max_price - min_price if max_price != min_price else 1
            
            for i, price in enumerate(hist['Close']):
                x = 10 + i * 20
                y = 35 - ((price - min_price) / price_range * 25)
                trend_points.append(f"{x},{y:.1f}")
            
            return {
                'symbol': symbol,
                'name': name,
                'price': price_str,
                'change': round(change_pct, 2),
                'volume': volume_str,
                'volume_raw': volume,  # For sorting
                'market': exchange,
                'trendData': ' '.join(trend_points)
            }
            
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
            return None
    
    # Fetch data from all markets
    print("Fetching US market trending stocks...")
    for symbol in us_symbols:
        data = fetch_stock_data(symbol, 'US')
        if data:
            trending_stocks.append(data)
    
    print("Fetching CN market trending stocks...")
    for symbol in cn_symbols:
        data = fetch_stock_data(symbol, 'CN')
        if data:
            trending_stocks.append(data)
    
    print("Fetching HK market trending stocks...")
    for symbol in hk_symbols:
        data = fetch_stock_data(symbol, 'HK')
        if data:
            trending_stocks.append(data)
    
    # Sort by volume (highest first) and take top 12
    trending_stocks.sort(key=lambda x: x['volume_raw'], reverse=True)
    top_stocks = trending_stocks[:12]
    
    # Remove volume_raw from final result
    for stock in top_stocks:
        stock.pop('volume_raw', None)
    
    # Select diverse stocks: aim for 8 total, try to include different markets
    us_stocks = [s for s in top_stocks if s['market'] in ['NASDAQ', 'NYSE']]
    cn_stocks = [s for s in top_stocks if s['market'] in ['SSE', 'SZSE']]
    hk_stocks = [s for s in top_stocks if s['market'] == 'HKEX']
    
    # Pick 3-4 from each market if available
    result = []
    result.extend(us_stocks[:4])
    result.extend(cn_stocks[:2])
    result.extend(hk_stocks[:2])
    
    # If we don't have 8, fill with remaining top volume stocks
    if len(result) < 8:
        for stock in top_stocks:
            if stock not in result and len(result) < 8:
                result.append(stock)
    
    # Ensure we have at least some stocks
    if len(result) == 0:
        print("Warning: No stocks fetched, using fallback")
        result = [
            {'symbol': 'AAPL', 'name': 'Apple', 'price': '$195', 'change': 1.5, 'volume': '45M', 'market': 'NASDAQ', 'trendData': '10,28 30,25 50,30 70,27 90,32'},
            {'symbol': 'TSLA', 'name': 'Tesla', 'price': '$245', 'change': -1.2, 'volume': '95M', 'market': 'NASDAQ', 'trendData': '10,15 30,18 50,22 70,25 90,20'}
        ]
    
    print(f"Returning {len(result)} trending stocks")
    
    # Cache for 30 minutes (shorter than before for more freshness)
    try:
        r.setex(cache_key, 1800, json.dumps(result))
    except:
        pass
    
    return jsonify(result)

@api_bp.route('/market_news', methods=['GET'])
def get_market_news():
    """Get latest market news and insights"""
    import yfinance as yf
    from app import r
    
    # Check cache first (cache for 15 minutes)
    cache_key = 'market_news'
    try:
        cached = r.get(cache_key)
        if cached:
            print(f"Using cached market news")
            return jsonify(json.loads(cached))
    except:
        print(f"Error checking market news cache")
        pass
    
    news_items = []
    # Major market indices and popular stocks for news
    news_symbols = ['^GSPC', '^DJI', '^IXIC', 'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META']
    
    for symbol in news_symbols:
        try:
            ticker = yf.Ticker(symbol)
            ticker_news = ticker.news
            
            if ticker_news and len(ticker_news) > 0:
                for item in ticker_news[:2]:  # Top 2 news per symbol
                    # Extract content from nested structure
                    content = item.get('content', {})
                    
                    # Parse timestamp from pubDate
                    pub_date_str = content.get('pubDate', '')
                    try:
                        # Parse ISO format: 2025-12-24T18:05:42Z
                        published_time = datetime.fromisoformat(pub_date_str.replace('Z', '+00:00'))
                    except:
                        published_time = datetime.now()
                    
                    time_ago = get_time_ago(published_time)
                    
                    # Determine news type based on title keywords
                    title = content.get('title', '')
                    news_type = 'news'
                    icon = '📰'
                    
                    if any(word in title.lower() for word in ['earnings', 'revenue', 'profit', 'quarter', '财报', '业绩']):
                        news_type = 'earnings'
                        icon = '📊'
                    elif any(word in title.lower() for word in ['upgrade', 'downgrade', 'target', 'rating', 'analyst', '评级', '目标价']):
                        news_type = 'rating'
                        icon = '🎯'
                    elif any(word in title.lower() for word in ['merger', 'acquisition', 'deal', 'buy', '并购', '收购']):
                        news_type = 'deal'
                        icon = '🤝'
                    elif any(word in title.lower() for word in ['dividend', 'payout', '分红', '派息']):
                        news_type = 'dividend'
                        icon = '💰'
                    elif any(word in title.lower() for word in ['surge', 'rally', 'soar', 'jump', '暴涨', '大涨']):
                        news_type = 'bullish'
                        icon = '🚀'
                    elif any(word in title.lower() for word in ['drop', 'fall', 'plunge', 'sink', '暴跌', '下挫']):
                        news_type = 'bearish'
                        icon = '📉'
                    
                    # Extract related symbols from title
                    related = [symbol.replace('^', '')]
                    
                    # Get thumbnail URL
                    thumbnail_url = ''
                    thumbnail = content.get('thumbnail', {})
                    if thumbnail and 'resolutions' in thumbnail and thumbnail['resolutions']:
                        thumbnail_url = thumbnail['resolutions'][0].get('url', '')
                    
                    # Get canonical URL
                    canonical_url = content.get('canonicalUrl', {}).get('url', '')
                    
                    news_items.append({
                        'id': item.get('id', ''),
                        'title': title,
                        'publisher': content.get('provider', {}).get('displayName', 'Unknown'),
                        'link': canonical_url,
                        'published': published_time.isoformat(),
                        'time_ago': time_ago,
                        'type': news_type,
                        'icon': icon,
                        'related_symbols': related,
                        'thumbnail': thumbnail_url
                    })
        except Exception as e:
            print(f"Error fetching news for {symbol}: {e}")
            continue
    
    # Remove duplicates by UUID or link
    seen_ids = set()
    unique_news = []
    for item in news_items:
        # Use UUID if available, otherwise use link as identifier
        identifier = item['id'] if item['id'] else item['link']
        if identifier and identifier not in seen_ids:
            seen_ids.add(identifier)
            unique_news.append(item)
    
    # Sort by publish time (newest first) and limit to 10
    unique_news.sort(key=lambda x: x['published'], reverse=True)
    result = unique_news[:10]
    
    # Cache for 15 minutes
    try:
        r.setex(cache_key, 900, json.dumps(result))
    except:
        pass
    
    return jsonify(result)

def get_time_ago(dt):
    """Calculate time ago string"""
    now = datetime.utcnow()
    diff = now - dt.replace(tzinfo=None)
    
    seconds = diff.total_seconds()
    
    if seconds < 60:
        return 'Just now'
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f'{minutes}m ago'
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f'{hours}h ago'
    else:
        days = int(seconds / 86400)
        return f'{days}d ago'

# ========== 用户认证相关 API ==========

@api_bp.route('/auth/login', methods=['POST'])
def login():
    """用户登录/注册"""
    data = request.json
    nickname = data.get('nickname', '').strip()
    email = data.get('email', '').strip()
    session_id = data.get('session_id')  # 用于自动登录
    
    # 验证输入
    if not nickname or len(nickname) < 1:
        return jsonify({'error': '昵称不能为空'}), 400
    
    if not email:
        return jsonify({'error': '邮箱不能为空'}), 400
    
    # 邮箱格式验证（正则）
    email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    if not re.match(email_pattern, email):
        return jsonify({'error': '邮箱格式不正确'}), 400
    
    # 自动登录：如果有session_id，尝试查找用户
    if session_id:
        user = User.query.filter_by(session_id=session_id).first()
        if user:
            user.last_login = datetime.utcnow()
            db.session.commit()
            return jsonify({
                'success': True,
                'user': user.to_dict(),
                'is_new_user': False
            })
    
    # 新用户注册或重新登录
    # 检查邮箱是否已存在
    user = User.query.filter_by(email=email).first()
    if user:
        # 更新昵称和登录时间
        user.nickname = nickname
        user.last_login = datetime.utcnow()
        db.session.commit()
        return jsonify({
            'success': True,
            'user': user.to_dict(),
            'is_new_user': False
        })
    
    # 创建新用户
    new_session_id = str(uuid.uuid4())
    user = User(
        nickname=nickname,
        email=email,
        session_id=new_session_id
    )
    db.session.add(user)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'user': user.to_dict(),
        'is_new_user': True
    })

@api_bp.route('/auth/check', methods=['GET'])
def check_auth():
    """检查用户登录状态"""
    session_id = request.args.get('session_id')
    if not session_id:
        return jsonify({'authenticated': False}), 401
    
    user = User.query.filter_by(session_id=session_id).first()
    if user:
        return jsonify({
            'authenticated': True,
            'user': user.to_dict()
        })
    
    return jsonify({'authenticated': False}), 401

# ========== 任务管理相关 API ==========

def get_user_from_request():
    """从请求中获取用户"""
    session_id = request.headers.get('X-Session-ID')
    if not session_id and request.is_json and request.json:
        session_id = request.json.get('session_id')
    if not session_id:
        return None
    return User.query.filter_by(session_id=session_id).first()

@api_bp.route('/tasks/create', methods=['POST'])
def create_task():
    """创建异步任务"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    data = request.json
    task_type = data.get('task_type')  # 'kline_analysis', 'portfolio_diagnosis', 'stock_recommendation'
    task_params = data.get('task_params', {})
    
    if not task_type:
        return jsonify({'error': '任务类型不能为空'}), 400
    
    # 创建任务
    task_id = task_service.create_task(user.id, task_type, task_params)
    
    return jsonify({
        'success': True,
        'task_id': task_id
    })

@api_bp.route('/tasks/<task_id>', methods=['GET'])
def get_task(task_id):
    """获取任务状态"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    task = task_service.get_task(task_id, user.id)
    if not task:
        return jsonify({'error': '任务不存在'}), 404
    
    return jsonify(task)

@api_bp.route('/tasks', methods=['GET'])
def list_tasks():
    """获取用户的任务列表"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    status = request.args.get('status')  # 可选筛选：running, completed, terminated, failed
    tasks = task_service.get_user_tasks(user.id, status=status)
    
    return jsonify({
        'tasks': tasks,
        'total': len(tasks)
    })

@api_bp.route('/tasks/<task_id>/terminate', methods=['POST'])
def terminate_task(task_id):
    """终止任务"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    success = task_service.terminate_task(task_id, user.id)
    if not success:
        return jsonify({'error': '无法终止任务（任务不存在或已完成）'}), 400
    
    return jsonify({'success': True})

# ========== 修改原有的分析API，改为创建任务 ==========

@api_bp.route('/analyze_async', methods=['POST'])
def analyze_async():
    """异步分析股票（创建任务）"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    data = request.json
    symbol = data.get('symbol')
    asset_type = data.get('asset_type', 'STOCK')
    model_name = data.get('model', 'gemini-3-flash-preview')
    language = data.get('language', 'zh')
    
    if not symbol:
        return jsonify({'error': '股票代码不能为空'}), 400
    
    # 幂等性检查：检查是否有正在运行的相同任务
    existing_task = Task.query.filter_by(
        user_id=user.id,
        task_type='kline_analysis',
        status='running'
    ).order_by(Task.created_at.desc()).first()
    
    if existing_task:
        try:
            task_params = json.loads(existing_task.task_params) if existing_task.task_params else {}
            existing_symbol = task_params.get('symbol')
            existing_model = task_params.get('model', 'gemini-3-flash-preview')
            
            # 检查是否是相同的股票和模型
            if existing_symbol == symbol and existing_model == model_name:
                return jsonify({
                    'success': False,
                    'error': 'duplicate_task',
                    'message': f'已有正在运行的 {symbol} 分析任务',
                    'existing_task_id': existing_task.task_id,
                    'existing_task_created_at': existing_task.created_at.isoformat()
                }), 409  # 409 Conflict
        except (json.JSONDecodeError, AttributeError):
            # 如果解析失败，继续创建新任务
            pass
    
    # 创建任务
    task_id = task_service.create_task(user.id, 'kline_analysis', {
        'symbol': symbol,
        'asset_type': asset_type,
        'model': model_name,
        'language': language
    })
    
    return jsonify({
        'success': True,
        'task_id': task_id
    })

@api_bp.route('/portfolio_advice_async', methods=['POST'])
def portfolio_advice_async():
    """异步持仓诊断（创建任务）"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    data = request.json
    model_name = data.get('model', 'gemini-3-flash-preview')
    language = data.get('language', 'zh')
    
    # 创建任务
    task_id = task_service.create_task(user.id, 'portfolio_diagnosis', {
        **data,
        'model': model_name,
        'language': language
    })
    
    return jsonify({
        'success': True,
        'task_id': task_id
    })

@api_bp.route('/recommend_async', methods=['POST'])
def recommend_async():
    """异步股票推荐（创建任务）"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    data = request.json
    model_name = data.get('model', 'gemini-3-flash-preview')
    language = data.get('language', 'zh')
    
    criteria = {
        'market': data.get('market', 'Any'),
        'asset_type': data.get('asset_type', 'STOCK'),
        'capital': data.get('capital', 'Any'),
        'risk': data.get('risk', 'Any'),
        'frequency': data.get('frequency', 'Any')
    }
    
    # 创建任务
    task_id = task_service.create_task(user.id, 'stock_recommendation', {
        **criteria,
        'model': model_name,
        'language': language
    })
    
    return jsonify({
        'success': True,
        'task_id': task_id
    })
