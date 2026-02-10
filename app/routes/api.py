from flask import Blueprint, request, jsonify, session
from app.services.data_provider import DataProvider
from app.services.ai_analyzer import AIAnalyzer
from app.models.analysis import AnalysisLog, StockTradeSignal, RecommendationCache, User, Task, Portfolio, Transaction, Account, CashFlow
from app.services.model_config import get_models_for_frontend
from app.services.task_service import task_service
from app.services.email_validator import email_validator
from app import db
import json
import hashlib
import re
import uuid
import math
import pandas as pd
from datetime import datetime, timedelta

api_bp = Blueprint('api', __name__)
ai_analyzer = AIAnalyzer()


@api_bp.route('/health', methods=['GET'])
def health_check():
    """Lightweight health check endpoint to keep the service alive"""
    return jsonify({'status': 'ok', 'timestamp': datetime.utcnow().isoformat()}), 200

def update_cash_balance(user_id, currency, amount, transaction_type, trade_date, notes=''):
    """
    更新现金余额
    :param user_id: 用户ID
    :param currency: 币种
    :param amount: 金额（正数）
    :param transaction_type: 'BUY' 表示入金，'SELL' 表示出金
    :param trade_date: 交易日期
    :param notes: 备注
    :return: 是否成功
    """
    # 查找或创建现金持仓
    cash_portfolio = Portfolio.query.filter_by(
        user_id=user_id,
        symbol='CASH',
        asset_type='CASH',
        currency=currency
    ).first()
    
    if not cash_portfolio:
        # 创建现金持仓
        cash_portfolio = Portfolio(
            user_id=user_id,
            symbol='CASH',
            asset_type='CASH',
            currency=currency,
            total_quantity=0,
            avg_cost=1,  # 现金成本固定为1
            total_cost=0
        )
        db.session.add(cash_portfolio)
        db.session.flush()
    
    # 检查余额是否足够（出金时）
    if transaction_type == 'SELL' and cash_portfolio.total_quantity < amount:
        return False, f'现金余额不足，当前余额: {cash_portfolio.total_quantity:.2f}'
    
    # 更新现金持仓
    if transaction_type == 'BUY':
        # 入金
        cash_portfolio.total_quantity += amount
        cash_portfolio.total_cost += amount
    else:
        # 出金
        cash_portfolio.total_quantity -= amount
        cash_portfolio.total_cost -= amount
    
    # 创建现金交易记录
    cash_transaction = Transaction(
        portfolio_id=cash_portfolio.id,
        user_id=user_id,
        transaction_type=transaction_type,
        trade_date=trade_date,
        price=1,  # 现金价格固定为1
        quantity=amount,
        amount=amount,
        notes=notes,
        source='auto'  # 标记为自动生成
    )
    db.session.add(cash_transaction)
    
    return True, 'success'

def get_or_create_account(user_id, currency):
    """
    获取或创建账户（处理并发创建的唯一约束冲突）
    :param user_id: 用户ID
    :param currency: 币种
    :return: Account对象，如果失败返回None
    """
    # 先尝试查询
    account = Account.query.filter_by(user_id=user_id, currency=currency).first()
    if account:
        return account
    
    # 如果不存在，尝试创建
    try:
        account = Account(
            user_id=user_id,
            currency=currency,
            total_deposit=0,
            total_withdrawal=0,
            realized_profit_loss=0
        )
        db.session.add(account)
        db.session.commit()
        return account
    except Exception as e:
        # 如果创建失败（可能是并发创建导致唯一约束冲突），回滚并重新查询
        db.session.rollback()
        account = Account.query.filter_by(user_id=user_id, currency=currency).first()
        if account:
            return account
        # 如果仍然不存在，记录错误并返回None
        print(f"⚠️ 无法创建或获取账户 (user_id={user_id}, currency={currency}): {str(e)}")
        return None

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

def get_user_portfolio_context(user_id, current_symbol, asset_type):
    """
    Get user's complete portfolio information for AI analysis context.
    Returns structured portfolio data including:
    - Total portfolio value
    - List of holdings with their percentages
    - Detailed information for the current symbol (if held)
    """
    from app.services.data_provider import batch_fetcher
    
    if not user_id:
        return None
    
    # Get all user's portfolios
    portfolios = Portfolio.query.filter_by(user_id=user_id).all()
    
    if not portfolios:
        return None
    
    # Calculate total portfolio value
    total_value = 0
    holdings = []
    current_symbol_portfolio = None
    
    for portfolio in portfolios:
        if portfolio.quantity > 0:
            # Get current price
            current_price = batch_fetcher.get_cached_current_price(
                portfolio.symbol, 
                asset_type=portfolio.asset_type,
                currency=portfolio.currency
            )
            
            if current_price:
                position_value = portfolio.quantity * current_price
                total_value += position_value
                
                holding_info = {
                    'symbol': portfolio.symbol,
                    'asset_type': portfolio.asset_type,
                    'quantity': portfolio.quantity,
                    'avg_cost': portfolio.avg_cost,
                    'current_price': current_price,
                    'position_value': position_value,
                    'unrealized_pnl': (current_price - portfolio.avg_cost) * portfolio.quantity,
                    'unrealized_pnl_pct': ((current_price - portfolio.avg_cost) / portfolio.avg_cost * 100) if portfolio.avg_cost > 0 else 0
                }
                
                holdings.append(holding_info)
                
                # Check if this is the current symbol being analyzed
                if portfolio.symbol == current_symbol and portfolio.asset_type == asset_type:
                    current_symbol_portfolio = portfolio
    
    # Calculate percentages
    for holding in holdings:
        holding['percentage'] = (holding['position_value'] / total_value * 100) if total_value > 0 else 0
    
    # Sort by position value (descending)
    holdings.sort(key=lambda x: x['position_value'], reverse=True)
    
    # Build context structure
    context = {
        'total_value': total_value,
        'holdings_count': len(holdings),
        'holdings_summary': [
            {
                'symbol': h['symbol'],
                'asset_type': h['asset_type'],
                'percentage': h['percentage'],
                'unrealized_pnl_pct': h['unrealized_pnl_pct']
            }
            for h in holdings
        ]
    }
    
    # Add detailed info for current symbol if held
    if current_symbol_portfolio:
        # Get transaction history for this symbol
        transactions = Transaction.query.filter_by(
            portfolio_id=current_symbol_portfolio.id,
            user_id=user_id
        ).order_by(Transaction.trade_date.asc()).all()
        
        context['current_symbol_detail'] = {
            'symbol': current_symbol,
            'quantity': current_symbol_portfolio.quantity,
            'avg_cost': current_symbol_portfolio.avg_cost,
            'current_price': next((h['current_price'] for h in holdings if h['symbol'] == current_symbol), None),
            'position_value': next((h['position_value'] for h in holdings if h['symbol'] == current_symbol), None),
            'percentage': next((h['percentage'] for h in holdings if h['symbol'] == current_symbol), 0),
            'unrealized_pnl': next((h['unrealized_pnl'] for h in holdings if h['symbol'] == current_symbol), 0),
            'unrealized_pnl_pct': next((h['unrealized_pnl_pct'] for h in holdings if h['symbol'] == current_symbol), 0),
            'transactions': [
                {
                    'date': t.trade_date.strftime('%Y-%m-%d'),
                    'type': t.transaction_type,
                    'price': t.price,
                    'quantity': t.quantity,
                    'notes': t.notes
                }
                for t in transactions
            ]
        }
    
    return context

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
        'include_etf': data.get('include_etf', 'false'),
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
    
    # 没有缓存，调用 AI 生成推荐（Agent 模式）
    print(f"[Recommend] No cache found, calling AI for {today}")
    result = ai_analyzer.recommend_stocks_with_agent(criteria, model_name=model_name, language=language)
    
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
    
    result = ai_analyzer.analyze_portfolio_item_with_agent(data, model_name=model_name, language=language)
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
    search_type = request.args.get('type', 'ALL')
    if not query:
        return jsonify([])
    
    results = DataProvider.search_symbol(query, search_type=search_type)
    return jsonify(results)

@api_bp.route('/current-price', methods=['GET'])
def get_current_price():
    from app.services.data_provider import batch_fetcher
    
    symbol = request.args.get('symbol', '')
    asset_type = request.args.get('asset_type')
    currency = request.args.get('currency')  #  新增：获取货币参数
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
    
    # Use cached version to reduce API calls
    price = batch_fetcher.get_cached_current_price(symbol, asset_type=asset_type, currency=currency)
    if price is None:
        return jsonify({'error': 'Could not fetch current price'}), 404
    
    return jsonify({'symbol': symbol, 'price': price})

@api_bp.route('/analyze', methods=['POST'])
def analyze():
    from app.services.data_provider import batch_fetcher
    
    data = request.json
    symbol = data.get('symbol')
    asset_type = data.get('asset_type', 'STOCK')
    is_cn_fund = data.get('is_cn_fund', False)  #  新增：是否为中国基金
    model_name = data.get('model', 'gemini-3-flash-preview') # Default to 2.5 Flash
    language = data.get('language', 'zh')
    
    if not symbol:
        return jsonify({'error': 'Symbol is required'}), 400
        
    # 1. Get K-line Data (Use cached version to reduce API calls)
    kline_data = batch_fetcher.get_cached_kline_data(symbol, period="3y", interval="1d", is_cn_fund=is_cn_fund)
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
    
    # Get user information for agent mode
    user = User.query.filter_by(username='default_user').first()
    user_id = user.id if user else None
    
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
        analysis_result = ai_analyzer.analyze(
            symbol, 
            kline_data, 
            model_name=model_name, 
            language=language
        )
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
        # Agent mode: AI fetches its own data via tool calls
        full_analysis = ai_analyzer.analyze_with_agent(
            symbol, 
            model_name=model_name, 
            language=language,
            asset_type=asset_type,
            user_id=user_id
        )
        
        if full_analysis.get('source') == 'ai_agent':
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
            # Agent mode: AI fetches its own data via tool calls
            fresh_analysis = ai_analyzer.analyze_with_agent(
                symbol, 
                model_name=model_name, 
                language=language,
                asset_type=asset_type,
                user_id=user_id
            )
            
            if fresh_analysis.get('source') == 'ai_agent':
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
    
    # Get current user for checking adopted signals
    user = get_user_from_request()
    user_id = user.id if user else None
    
    db_signals = StockTradeSignal.query.filter_by(
        symbol=symbol,
        model_name=model_name,
        asset_type=asset_type
    ).order_by(StockTradeSignal.date.asc()).all()
    
    # Get user's real transactions for this symbol
    user_transactions = []
    if user_id:
        portfolio = Portfolio.query.filter_by(
            user_id=user_id,
            symbol=symbol,
            asset_type=asset_type
        ).first()
        if portfolio:
            user_transactions = Transaction.query.filter_by(
                portfolio_id=portfolio.id,
                user_id=user_id
            ).order_by(Transaction.trade_date.asc()).all()
    
    # Reconstruct 'trades' (pair of Buy/Sell) from signals for the UI
    reconstructed_trades = []
    current_position = None # {date, price, reason}
    
    ui_signals = []
    user_trade_signals = []  # User's real transactions for chart display
    
    # Process AI signals
    for s in db_signals:
        date_str = s.date.strftime('%Y-%m-%d')
        
        # Add to signals list for chart
        ui_signals.append({
            "type": s.signal_type,
            "date": date_str,
            "price": s.price,
            "reason": s.reason,
            "adopted": s.adopted,
            "signal_id": s.id
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
    
    # Process user's real transactions for chart display
    for trans in user_transactions:
        user_trade_signals.append({
            "type": trans.transaction_type,
            "date": trans.trade_date.strftime('%Y-%m-%d'),
            "price": trans.price,
            "quantity": trans.quantity,
            "notes": trans.notes,
            "source": trans.source,
            "transaction_id": trans.id
        })
    
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
        "user_transactions": user_trade_signals,  # User's real transactions
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
    from app import r
    import time
    
    # Check cache first (cache for 5 minutes for real-time feel)
    cache_key = 'market_indices'
    try:
        cached = r.get(cache_key)
        if cached:
            return jsonify(json.loads(cached))
    except:
        pass
    
    # Add delay to prevent race condition with trending_stocks endpoint
    time.sleep(2)  # 2 second delay to stagger API calls
    
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
    
    # Extract all symbols for batch fetching
    all_symbols = [idx['symbol'] for idx in indices]
    
    # Batch fetch all historical data in one API call
    from app.services.data_provider import batch_fetcher
    batch_data = batch_fetcher.batch_fetch_history(all_symbols, period='5d', interval='1d')
    
    for index_info in indices:
        try:
            symbol = index_info['symbol']
            used_symbol = symbol
            
            # Get data from batch fetch results
            hist = batch_data.get(symbol, pd.DataFrame())
            
            # Check if data is available
            if hist.empty or len(hist) < 2:
                print(f"Warning: No data for {symbol}, skipping...")
                continue
            
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
    except Exception as e:
        print(f"⚠️ Failed to cache market indices: {e}")
    
    return jsonify(result)

@api_bp.route('/trending', methods=['GET'])
def get_trending_stocks():
    """Get trending stocks from various markets by volume"""
    from app import r
    
    # Check cache first (cache for 60 minutes to reduce API calls)
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
    
    # Combine all symbols for batch fetching
    all_symbols = us_symbols + cn_symbols + hk_symbols
    
    # Market mapping
    symbol_market = {}
    for symbol in us_symbols:
        symbol_market[symbol] = 'US'
    for symbol in cn_symbols:
        symbol_market[symbol] = 'CN'
    for symbol in hk_symbols:
        symbol_market[symbol] = 'HK'
    
    # Batch fetch all historical data in one API call
    from app.services.data_provider import batch_fetcher
    batch_data = batch_fetcher.batch_fetch_history(all_symbols, period='5d', interval='1d')
    
    def process_stock_data(symbol, market, hist):
        """Process stock data from batch fetch results"""
        try:
            if hist.empty or len(hist) < 2:
                return None
            
            # Get current price and change
            current_price = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2]
            
            if pd.isna(current_price) or pd.isna(prev_close) or prev_close == 0:
                change_pct = 0.0
            else:
                change_pct = ((current_price - prev_close) / prev_close) * 100
                if pd.isna(change_pct) or math.isinf(change_pct):
                    change_pct = 0.0
            
            # Get volume (use latest day)
            volume = hist['Volume'].iloc[-1] if 'Volume' in hist.columns else 0
            if pd.isna(volume):
                volume = 0
            
            # Skip if volume is too low or zero
            if volume < 100000:
                return None
            
            volume_str = f"{volume/1e6:.1f}M" if volume >= 1e6 else f"{volume/1e3:.1f}K"
            
            # Get stock name from local list (avoiding info API calls)
            from app.services.data_provider import POPULAR_STOCKS
            stock_info = next((s for s in POPULAR_STOCKS if s['symbol'] == symbol), None)
            name = stock_info['name'] if stock_info else symbol
            
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
            print(f"Error processing {symbol}: {e}")
            return None
    
    # Process data from all markets
    for symbol in all_symbols:
        market = symbol_market[symbol]
        hist = batch_data.get(symbol, pd.DataFrame())
        data = process_stock_data(symbol, market, hist)
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
    
    # Cache for 60 minutes
    try:
        r.setex(cache_key, 3600, json.dumps(result))
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
    
    # Get news from different sources using yfinance
    try:
        # Fetch news for major indices to represent global market news
        # S&P 500, Nasdaq, Dow Jones, Gold, Oil
        tickers = ["^GSPC", "^IXIC", "^DJI", "GC=F", "CL=F"]
        
        for symbol in tickers:
            try:
                ticker = yf.Ticker(symbol)
                news = ticker.news
                
                for item in news:
                    try:
                        # Parse timestamp
                        published_time = datetime.fromtimestamp(item.get('providerPublishTime', 0))
                        time_ago = get_time_ago(published_time)
                        
                        title = item.get('title', '')
                        
                        # Determine news type based on title keywords
                        news_type = 'news'
                        icon = '📰'
                        
                        title_lower = title.lower()
                        if any(word in title_lower for word in ['earnings', 'revenue', 'profit', 'report']):
                            news_type = 'earnings'
                            icon = '📊'
                        elif any(word in title_lower for word in ['surge', 'plunge', 'jump', 'drop', 'rally', 'crash']):
                            news_type = 'market'
                            icon = '📈'
                        elif any(word in title_lower for word in ['fed', 'rate', 'policy', 'central bank']):
                            news_type = 'policy'
                            icon = '🏛️'
                        
                        news_items.append({
                            'title': title,
                            'source': item.get('publisher', 'Unknown'),
                            'time_ago': time_ago,
                            'published': published_time.isoformat(),
                            'url': item.get('link', '#'),
                            'type': news_type,
                            'icon': icon,
                            'id': item.get('uuid')
                        })
                    except Exception as e:
                        print(f"Error processing news item: {e}")
                        continue
            except Exception as e:
                print(f"Error fetching news for {symbol}: {e}")
                continue

    except Exception as e:
        print(f"Error fetching market news: {e}")

    # Remove duplicates by URL or ID
    seen_ids = set()
    unique_news = []
    for item in news_items:
        # Use ID or URL as identifier
        identifier = item.get('id') or item.get('url', '')
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

@api_bp.route('/auth/register', methods=['POST'])
def register():
    """用户注册"""
    data = request.json
    nickname = data.get('nickname', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()
    email_confirmed = data.get('email_confirmed', False)  # 用户是否已确认邮箱
    
    # 验证输入
    if not nickname or len(nickname) < 1:
        return jsonify({'error': '昵称不能为空'}), 400
    
    if not email:
        return jsonify({'error': '邮箱不能为空'}), 400
    
    if not password or len(password) < 6:
        return jsonify({'error': '密码长度至少为6位'}), 400
    
    # 邮箱验证（使用 Rapid Email Verifier API）
    validation_result = email_validator.validate_email(email)
    if not validation_result['valid']:
        return jsonify({'error': validation_result['reason']}), 400
    
    # 检查是否需要二次确认（PROBABLY_VALID 状态）
    details = validation_result.get('details', {})
    status = details.get('status', '')
    typo_suggestion = details.get('typoSuggestion', '')
    score = details.get('score', 100)
    
    # 如果是 PROBABLY_VALID 状态且用户未确认，要求用户确认
    if status == 'PROBABLY_VALID' and not email_confirmed:
        return jsonify({
            'success': False,
            'need_confirmation': True,
            'email': email,
            'typo_suggestion': typo_suggestion,
            'score': score,
            'message': '检测到邮箱可能存在拼写错误，请确认是否继续使用此邮箱'
        }), 200
    
    # 检查邮箱是否已存在
    existing_user = User.query.filter_by(email=email).first()
    if existing_user:
        return jsonify({'error': '该邮箱已被注册'}), 400
    
    # 创建新用户
    user = User(
        nickname=nickname,
        email=email
    )
    user.set_password(password)
    user.generate_session_id()
    
    db.session.add(user)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'user': user.to_dict(),
        'message': '注册成功'
    })

@api_bp.route('/auth/login', methods=['POST'])
def login():
    """用户登录"""
    data = request.json
    email = data.get('email', '').strip()
    password = data.get('password', '').strip()
    session_id = data.get('session_id')  # 用于自动登录
    
    # 自动登录：如果有session_id，尝试查找用户
    if session_id:
        user = User.query.filter_by(session_id=session_id).first()
        if user:
            user.last_login = datetime.utcnow()
            db.session.commit()
            return jsonify({
                'success': True,
                'user': user.to_dict(),
                'message': '自动登录成功'
            })
    
    # 验证输入
    if not email:
        return jsonify({'error': '邮箱不能为空'}), 400
    
    if not password:
        return jsonify({'error': '密码不能为空'}), 400
    
    # 查找用户
    user = User.query.filter_by(email=email).first()
    if not user:
        return jsonify({'error': '邮箱或密码错误'}), 401
    
    # 验证密码
    if not user.check_password(password):
        return jsonify({'error': '邮箱或密码错误'}), 401
    
    # 生成新的会话ID
    user.generate_session_id()
    user.last_login = datetime.utcnow()
    db.session.commit()
    
    return jsonify({
        'success': True,
        'user': user.to_dict(),
        'message': '登录成功'
    })

@api_bp.route('/auth/logout', methods=['POST'])
def logout():
    """用户注销"""
    data = request.json
    session_id = data.get('session_id')
    
    if not session_id:
        return jsonify({'error': '未登录'}), 401
    
    user = User.query.filter_by(session_id=session_id).first()
    if user:
        # 清除会话ID
        user.session_id = None
        db.session.commit()
    
    return jsonify({
        'success': True,
        'message': '注销成功'
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
    is_cn_fund = data.get('is_cn_fund', False)  #  新增：是否为中国基金
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
        'is_cn_fund': is_cn_fund,  #  新增：传递中国基金标志
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
        'include_etf': data.get('include_etf', 'false'),
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

# ========== 虚拟持仓管理 API ==========

@api_bp.route('/portfolios', methods=['GET'])
def get_portfolios():
    """获取用户的所有持仓（快速返回基础数据，不含实时价格和名称）"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    # 获取所有持仓，但过滤掉数量为0的非现金持仓
    all_portfolios = Portfolio.query.filter_by(user_id=user.id).all()
    portfolios = [p for p in all_portfolios if p.total_quantity > 0 or p.asset_type == 'CASH']
    
    # 引入 batch_fetcher
    from app.services.data_provider import batch_fetcher
    
    # 只返回基础数据，不获取实时价格和名称
    portfolios_data = []
    for p in portfolios:
        portfolio_dict = p.to_dict()
        
        # 使用 symbol 作为默认名称
        portfolio_dict['name'] = p.symbol
        
        # 获取汇率
        exchange_rate = 1.0
        currency = p.currency.upper() if p.currency else 'USD'
        
        if currency != 'USD':
            try:
                exchange_rate = batch_fetcher.get_cached_exchange_rate(currency, 'USD')
            except Exception as e:
                print(f"Failed to get exchange rate for {currency}: {e}")
        
        portfolio_dict['exchange_rate'] = exchange_rate
        portfolio_dict['currency'] = currency
        
        # 使用成本价作为当前价格（快速返回）
        if p.asset_type == 'CASH':
            portfolio_dict['current_price'] = 1.0
            portfolio_dict['current_value'] = p.total_quantity
            portfolio_dict['profit_loss'] = 0.0
            portfolio_dict['profit_loss_percent'] = 0.0
            portfolio_dict['value_in_usd'] = p.total_quantity * exchange_rate
        else:
            portfolio_dict['current_price'] = p.avg_cost
            portfolio_dict['current_value'] = p.total_cost
            portfolio_dict['profit_loss'] = 0.0
            portfolio_dict['profit_loss_percent'] = 0.0
            portfolio_dict['value_in_usd'] = p.total_cost * exchange_rate
        
        portfolios_data.append(portfolio_dict)
    
    # 获取 USD 到 CNY 的汇率
    usd_to_cny = 1.0
    try:
        usd_to_cny = batch_fetcher.get_cached_exchange_rate('USD', 'CNY')
    except Exception as e:
        print(f"Failed to get USD to CNY rate: {e}")

    return jsonify({
        'portfolios': portfolios_data,
        'rates': {
            'USD_CNY': usd_to_cny
        }
    })

@api_bp.route('/portfolios/refresh', methods=['GET'])
def refresh_portfolios():
    """异步刷新持仓数据（获取最新价格和标的名称）"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    # 获取所有持仓，但过滤掉数量为0的非现金持仓
    all_portfolios = Portfolio.query.filter_by(user_id=user.id).all()
    portfolios = [p for p in all_portfolios if p.total_quantity > 0 or p.asset_type == 'CASH']
    
    # 引入 batch_fetcher
    from app.services.data_provider import batch_fetcher
    
    # 为每个持仓添加实时价格和盈亏信息
    portfolios_with_price = []
    for p in portfolios:
        portfolio_dict = p.to_dict()
        
        #  获取标的全名
        try:
            name = DataProvider.get_symbol_name(
                p.symbol, 
                asset_type=p.asset_type,
                currency=p.currency
            )
            portfolio_dict['name'] = name if name else p.symbol
        except Exception as e:
            print(f"Failed to get name for {p.symbol}: {e}")
            portfolio_dict['name'] = p.symbol
        
        # 获取汇率
        exchange_rate = 1.0
        currency = p.currency.upper() if p.currency else 'USD'
        
        if currency != 'USD':
            try:
                exchange_rate = batch_fetcher.get_cached_exchange_rate(currency, 'USD')
            except Exception as e:
                print(f"Failed to get exchange rate for {currency}: {e}")
        
        portfolio_dict['exchange_rate'] = exchange_rate
        portfolio_dict['currency'] = currency
        
        # 现金资产不需要获取实时价格
        if p.asset_type == 'CASH':
            portfolio_dict['current_price'] = 1.0
            portfolio_dict['current_value'] = p.total_quantity
            portfolio_dict['profit_loss'] = 0.0
            portfolio_dict['profit_loss_percent'] = 0.0
            portfolio_dict['value_in_usd'] = p.total_quantity * exchange_rate
            portfolio_dict['daily_change_percent'] = 0.0
        else:
            # 获取实时价格
            try:
                current_price = batch_fetcher.get_cached_current_price(
                    p.symbol, 
                    asset_type=p.asset_type,
                    currency=currency
                )
                
                if current_price:
                    portfolio_dict['current_price'] = float(current_price)
                    current_value = current_price * p.total_quantity
                    portfolio_dict['current_value'] = current_value
                    portfolio_dict['profit_loss'] = current_value - p.total_cost
                    portfolio_dict['profit_loss_percent'] = ((current_value - p.total_cost) / p.total_cost * 100) if p.total_cost > 0 else 0
                    portfolio_dict['value_in_usd'] = current_value * exchange_rate
                else:
                    portfolio_dict['current_price'] = p.avg_cost
                    portfolio_dict['current_value'] = p.total_cost
                    portfolio_dict['profit_loss'] = 0.0
                    portfolio_dict['profit_loss_percent'] = 0.0
                    portfolio_dict['value_in_usd'] = p.total_cost * exchange_rate
                
                # 获取今日涨跌幅
                try:
                    daily_change = batch_fetcher.get_cached_daily_change(
                        p.symbol,
                        asset_type=p.asset_type,
                        currency=currency
                    )
                    portfolio_dict['daily_change_percent'] = daily_change if daily_change is not None else 0.0
                except Exception as e:
                    print(f"Failed to get daily change for {p.symbol}: {e}")
                    portfolio_dict['daily_change_percent'] = 0.0
                    
            except Exception as e:
                print(f"Failed to get price for {p.symbol}: {e}")
                portfolio_dict['current_price'] = p.avg_cost
                portfolio_dict['current_value'] = p.total_cost
                portfolio_dict['profit_loss'] = 0.0
                portfolio_dict['profit_loss_percent'] = 0.0
                portfolio_dict['value_in_usd'] = p.total_cost * exchange_rate
                portfolio_dict['daily_change_percent'] = 0.0
        
        portfolios_with_price.append(portfolio_dict)
    
    # 获取 USD 到 CNY 的汇率
    usd_to_cny = 1.0
    try:
        usd_to_cny = batch_fetcher.get_cached_exchange_rate('USD', 'CNY')
    except Exception as e:
        print(f"Failed to get USD to CNY rate: {e}")

    return jsonify({
        'portfolios': portfolios_with_price,
        'rates': {
            'USD_CNY': usd_to_cny
        }
    })

@api_bp.route('/portfolios/<int:portfolio_id>', methods=['GET'])
def get_portfolio(portfolio_id):
    """获取单个持仓详情（包含交易记录）"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    portfolio = Portfolio.query.filter_by(id=portfolio_id, user_id=user.id).first()
    if not portfolio:
        return jsonify({'error': '持仓不存在'}), 404
    
    portfolio_dict = portfolio.to_dict()
    portfolio_dict['transactions'] = [t.to_dict() for t in portfolio.transactions]
    
    return jsonify(portfolio_dict)

@api_bp.route('/portfolios', methods=['POST'])
def create_portfolio():
    """创建新持仓（首次买入）"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    data = request.json
    symbol = data.get('symbol')
    asset_type = data.get('asset_type', 'STOCK')
    currency = data.get('currency', 'USD')
    
    if not symbol:
        return jsonify({'error': '标的代码不能为空'}), 400
    
    # 检查是否已存在
    existing = Portfolio.query.filter_by(
        user_id=user.id,
        symbol=symbol,
        asset_type=asset_type,
        currency=currency
    ).first()
    
    if existing:
        return jsonify({'error': '该持仓已存在'}), 400
    
    # 创建持仓
    portfolio = Portfolio(
        user_id=user.id,
        symbol=symbol,
        asset_type=asset_type,
        currency=currency,
        total_quantity=0,
        avg_cost=0,
        total_cost=0
    )
    
    db.session.add(portfolio)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'portfolio': portfolio.to_dict()
    })

@api_bp.route('/portfolios/<int:portfolio_id>', methods=['PUT'])
def update_portfolio(portfolio_id):
    """更新持仓信息（主要用于编辑现金余额）"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    portfolio = Portfolio.query.filter_by(id=portfolio_id, user_id=user.id).first()
    if not portfolio:
        return jsonify({'error': '持仓不存在'}), 404
    
    data = request.json
    
    # 只允许更新现金账户的余额
    if portfolio.asset_type == 'CASH':
        if 'total_quantity' in data:
            try:
                new_balance = float(data['total_quantity'])
                if new_balance < 0:
                    return jsonify({'error': '余额不能为负数'}), 400
                portfolio.total_quantity = new_balance
                portfolio.total_cost = new_balance  # 现金的成本等于余额
                db.session.commit()
                return jsonify({
                    'success': True,
                    'portfolio': portfolio.to_dict()
                })
            except ValueError:
                return jsonify({'error': '余额格式错误'}), 400
    else:
        return jsonify({'error': '只能编辑现金账户余额'}), 403

@api_bp.route('/portfolios/<int:portfolio_id>', methods=['DELETE'])
def delete_portfolio(portfolio_id):
    """删除持仓（会级联删除所有交易记录）"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    portfolio = Portfolio.query.filter_by(id=portfolio_id, user_id=user.id).first()
    if not portfolio:
        return jsonify({'error': '持仓不存在'}), 404
    
    db.session.delete(portfolio)
    db.session.commit()
    
    return jsonify({'success': True})

# ========== 交易记录管理 API ==========

@api_bp.route('/transactions', methods=['POST'])
def create_transaction():
    """添加交易记录"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    data = request.json
    symbol = data.get('symbol')
    asset_type = data.get('asset_type', 'STOCK')
    transaction_type = data.get('transaction_type')  # BUY or SELL
    trade_date_str = data.get('trade_date')
    price = data.get('price')
    quantity = data.get('quantity')
    total_amount = data.get('total_amount')
    notes = data.get('notes', '')
    source = data.get('source', 'manual')
    currency = data.get('currency', 'USD')
    
    # 验证必填字段
    if not all([symbol, transaction_type, trade_date_str, price]):
        return jsonify({'error': '缺少必填字段'}), 400
        
    if quantity is None and total_amount is None:
        return jsonify({'error': '必须提供数量或总金额'}), 400
    
    if transaction_type not in ['BUY', 'SELL']:
        return jsonify({'error': '交易类型必须是 BUY 或 SELL'}), 400
    
    try:
        price = float(price)
        if quantity is not None:
            quantity = float(quantity)
        elif total_amount is not None:
            total_amount = float(total_amount)
            if price <= 0:
                return jsonify({'error': '价格必须大于0'}), 400
            quantity = total_amount / price
            
        trade_date = datetime.strptime(trade_date_str, '%Y-%m-%d').date()
    except ValueError as e:
        return jsonify({'error': f'数据格式错误: {str(e)}'}), 400
    
    # 查找或创建持仓
    portfolio = Portfolio.query.filter_by(
        user_id=user.id,
        symbol=symbol,
        asset_type=asset_type,
        currency=currency
    ).first()
    
    if not portfolio:
        # 如果是卖出操作但没有持仓，报错
        if transaction_type == 'SELL':
            return jsonify({'error': '没有该标的的持仓，无法卖出'}), 400
        
        # 创建新持仓
        portfolio = Portfolio(
            user_id=user.id,
            symbol=symbol,
            asset_type=asset_type,
            currency=currency,
            total_quantity=0,
            avg_cost=0,
            total_cost=0
        )
        db.session.add(portfolio)
        db.session.flush()
    
    # 计算交易金额
    amount = price * quantity
    
    # 更新持仓
    if transaction_type == 'BUY':
        # 买入：扣除现金
        if asset_type != 'CASH':  # 非现金资产才需要扣除现金
            success, message = update_cash_balance(
                user_id=user.id,
                currency=currency,
                amount=amount,
                transaction_type='SELL',  # 扣除现金用SELL
                trade_date=trade_date,
                notes=f'买入 {symbol} {quantity} @ {price}'
            )
            if not success:
                db.session.rollback()
                return jsonify({'error': message}), 400
        
        new_total_cost = portfolio.total_cost + amount
        new_total_quantity = portfolio.total_quantity + quantity
        portfolio.avg_cost = new_total_cost / new_total_quantity if new_total_quantity > 0 else 0
        portfolio.total_cost = new_total_cost
        portfolio.total_quantity = new_total_quantity
    else:  # SELL
        if portfolio.total_quantity < quantity:
            return jsonify({'error': f'持仓数量不足，当前持仓: {portfolio.total_quantity}'}), 400
        
        # 按平均成本计算卖出成本
        sell_cost = portfolio.avg_cost * quantity
        
        # 计算已实现收益
        realized_pnl = amount - sell_cost
        
        # 卖出：增加现金
        if asset_type != 'CASH':  # 非现金资产才需要增加现金
            success, message = update_cash_balance(
                user_id=user.id,
                currency=currency,
                amount=amount,
                transaction_type='BUY',  # 增加现金用BUY
                trade_date=trade_date,
                notes=f'卖出 {symbol} {quantity} @ {price}'
            )
            if not success:
                db.session.rollback()
                return jsonify({'error': message}), 400
            
            # 更新账户的已实现收益
            account = Account.query.filter_by(user_id=user.id, currency=currency).first()
            if account:
                account.realized_profit_loss += realized_pnl
        
        portfolio.total_cost -= sell_cost
        portfolio.total_quantity -= quantity
        
        # 如果全部卖出，重置平均成本
        if portfolio.total_quantity == 0:
            portfolio.avg_cost = 0
            portfolio.total_cost = 0
    
    # 创建交易记录
    transaction = Transaction(
        portfolio_id=portfolio.id,
        user_id=user.id,
        transaction_type=transaction_type,
        trade_date=trade_date,
        price=price,
        quantity=quantity,
        amount=amount,
        cost_basis=sell_cost if transaction_type == 'SELL' else 0,
        realized_profit_loss=realized_pnl if transaction_type == 'SELL' else 0,
        notes=notes,
        source=source
    )
    
    db.session.add(transaction)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'transaction': transaction.to_dict(),
        'portfolio': portfolio.to_dict()
    })

@api_bp.route('/transactions/<int:transaction_id>', methods=['PUT'])
def update_transaction(transaction_id):
    """修改交易记录"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    transaction = Transaction.query.filter_by(id=transaction_id, user_id=user.id).first()
    if not transaction:
        return jsonify({'error': '交易记录不存在'}), 404
    
    # 禁止修改自动生成的交易记录（如现金变动记录）
    if transaction.source == 'auto':
        return jsonify({'error': '不能修改自动生成的交易记录'}), 403
    
    data = request.json
    portfolio = Portfolio.query.get(transaction.portfolio_id)
    
    # 先回滚原交易对持仓的影响
    if transaction.transaction_type == 'BUY':
        portfolio.total_cost -= transaction.amount
        portfolio.total_quantity -= transaction.quantity
    else:  # SELL
        sell_cost = portfolio.avg_cost * transaction.quantity
        portfolio.total_cost += sell_cost
        portfolio.total_quantity += transaction.quantity
    
    # 更新交易记录
    if 'trade_date' in data:
        try:
            transaction.trade_date = datetime.strptime(data['trade_date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'error': '日期格式错误'}), 400
    
    new_price = transaction.price
    if 'price' in data:
        try:
            new_price = float(data['price'])
            transaction.price = new_price
        except ValueError:
            return jsonify({'error': '价格格式错误'}), 400
    
    if 'quantity' in data:
        try:
            transaction.quantity = float(data['quantity'])
        except ValueError:
            return jsonify({'error': '数量格式错误'}), 400
    elif 'total_amount' in data:
        try:
            total_amount = float(data['total_amount'])
            if new_price <= 0:
                return jsonify({'error': '价格必须大于0'}), 400
            transaction.quantity = total_amount / new_price
        except ValueError:
            return jsonify({'error': '总金额格式错误'}), 400
    
    if 'notes' in data:
        transaction.notes = data['notes']
    
    # 重新计算金额
    transaction.amount = transaction.price * transaction.quantity
    
    # 应用新交易对持仓的影响
    if transaction.transaction_type == 'BUY':
        portfolio.total_cost += transaction.amount
        portfolio.total_quantity += transaction.quantity
    else:  # SELL
        if portfolio.total_quantity < transaction.quantity:
            db.session.rollback()
            return jsonify({'error': '修改后持仓数量不足'}), 400
        sell_cost = portfolio.avg_cost * transaction.quantity
        portfolio.total_cost -= sell_cost
        portfolio.total_quantity -= transaction.quantity
    
    # 重新计算平均成本
    if portfolio.total_quantity > 0:
        portfolio.avg_cost = portfolio.total_cost / portfolio.total_quantity
    else:
        portfolio.avg_cost = 0
        portfolio.total_cost = 0
    
    db.session.commit()
    
    return jsonify({
        'success': True,
        'transaction': transaction.to_dict(),
        'portfolio': portfolio.to_dict()
    })

@api_bp.route('/transactions/<int:transaction_id>', methods=['DELETE'])
def delete_transaction(transaction_id):
    """删除交易记录"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    transaction = Transaction.query.filter_by(id=transaction_id, user_id=user.id).first()
    if not transaction:
        return jsonify({'error': '交易记录不存在'}), 404
    
    # 禁止删除自动生成的交易记录（如现金变动记录）
    if transaction.source == 'auto':
        return jsonify({'error': '不能删除自动生成的交易记录'}), 403
    
    portfolio = Portfolio.query.get(transaction.portfolio_id)
    
    # 回滚交易对持仓的影响
    if transaction.transaction_type == 'BUY':
        portfolio.total_cost -= transaction.amount
        portfolio.total_quantity -= transaction.quantity
    else:  # SELL
        sell_cost = portfolio.avg_cost * transaction.quantity
        portfolio.total_cost += sell_cost
        portfolio.total_quantity += transaction.quantity
    
    # 重新计算平均成本
    if portfolio.total_quantity > 0:
        portfolio.avg_cost = portfolio.total_cost / portfolio.total_quantity
    else:
        portfolio.avg_cost = 0
        portfolio.total_cost = 0
    
    db.session.delete(transaction)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'portfolio': portfolio.to_dict()
    })

@api_bp.route('/portfolios/<symbol>/transactions', methods=['GET'])
def get_portfolio_transactions(symbol):
    """获取指定标的的所有交易记录"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    asset_type = request.args.get('asset_type', 'STOCK')
    currency = request.args.get('currency')
    
    query_params = {
        'user_id': user.id,
        'symbol': symbol,
        'asset_type': asset_type
    }
    if currency:
        query_params['currency'] = currency
    
    portfolio = Portfolio.query.filter_by(**query_params).first()
    
    if not portfolio:
        return jsonify({'transactions': []})
    
    transactions = Transaction.query.filter_by(
        portfolio_id=portfolio.id,
        user_id=user.id
    ).order_by(Transaction.trade_date.desc()).all()
    
    return jsonify({
        'transactions': [t.to_dict() for t in transactions],
        'portfolio': portfolio.to_dict()
    })

# ==================== Account & Cash Flow APIs ====================

@api_bp.route('/accounts', methods=['GET'])
def get_accounts():
    """获取用户账户信息"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    accounts = Account.query.filter_by(user_id=user.id).all()
    return jsonify({
        'accounts': [a.to_dict() for a in accounts]
    })

@api_bp.route('/accounts/<currency>', methods=['GET'])
def get_account_by_currency(currency):
    """获取指定币种的账户信息"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    account = get_or_create_account(user.id, currency)
    if not account:
        return jsonify({'error': '无法创建或获取账户'}), 500
    
    return jsonify(account.to_dict())

@api_bp.route('/cash-flows', methods=['POST'])
def create_cash_flow():
    """创建资金流水（入金/出金）"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    data = request.json
    flow_type = data.get('flow_type')  # DEPOSIT or WITHDRAWAL
    flow_date_str = data.get('flow_date')
    amount = data.get('amount')
    currency = data.get('currency', 'USD')
    notes = data.get('notes', '')
    
    # 验证必填字段
    if not all([flow_type, flow_date_str, amount]):
        return jsonify({'error': '缺少必填字段'}), 400
    
    if flow_type not in ['DEPOSIT', 'WITHDRAWAL']:
        return jsonify({'error': '流水类型必须是 DEPOSIT 或 WITHDRAWAL'}), 400
    
    try:
        amount = float(amount)
        if amount <= 0:
            return jsonify({'error': '金额必须大于0'}), 400
        flow_date = datetime.strptime(flow_date_str, '%Y-%m-%d').date()
    except ValueError as e:
        return jsonify({'error': f'数据格式错误: {str(e)}'}), 400
    
    # 查找或创建账户
    account = get_or_create_account(user.id, currency)
    if not account:
        return jsonify({'error': '无法创建或获取账户'}), 500
    
    # 检查出金时余额是否足够
    if flow_type == 'WITHDRAWAL':
        # 计算当前总资产
        portfolios = Portfolio.query.filter_by(user_id=user.id, currency=currency).all()
        total_assets = sum(p.total_quantity if p.asset_type == 'CASH' else p.total_cost for p in portfolios)
        
        if total_assets < amount:
            return jsonify({'error': f'资产不足，当前总资产: {total_assets:.2f}'}), 400
    
    # 更新账户统计
    if flow_type == 'DEPOSIT':
        account.total_deposit += amount
        # 入金时增加现金
        success, message = update_cash_balance(
            user_id=user.id,
            currency=currency,
            amount=amount,
            transaction_type='BUY',
            trade_date=flow_date,
            notes=notes or '入金'
        )
        if not success:
            db.session.rollback()
            return jsonify({'error': message}), 400
    else:  # WITHDRAWAL
        account.total_withdrawal += amount
        # 出金时扣除现金
        success, message = update_cash_balance(
            user_id=user.id,
            currency=currency,
            amount=amount,
            transaction_type='SELL',
            trade_date=flow_date,
            notes=notes or '出金'
        )
        if not success:
            db.session.rollback()
            return jsonify({'error': message}), 400
    
    # 创建资金流水记录
    cash_flow = CashFlow(
        account_id=account.id,
        user_id=user.id,
        flow_type=flow_type,
        flow_date=flow_date,
        amount=amount,
        currency=currency,
        notes=notes,
        source='manual'
    )
    
    db.session.add(cash_flow)
    db.session.commit()
    
    return jsonify({
        'success': True,
        'cash_flow': cash_flow.to_dict(),
        'account': account.to_dict()
    })

@api_bp.route('/cash-flows', methods=['GET'])
def get_cash_flows():
    """获取资金流水列表"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    currency = request.args.get('currency')
    
    query = CashFlow.query.filter_by(user_id=user.id)
    if currency:
        query = query.filter_by(currency=currency)
    
    cash_flows = query.order_by(CashFlow.flow_date.desc()).all()
    
    return jsonify({
        'cash_flows': [cf.to_dict() for cf in cash_flows]
    })

@api_bp.route('/cash-flows/<int:cash_flow_id>', methods=['DELETE'])
def delete_cash_flow(cash_flow_id):
    """删除资金流水"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    cash_flow = CashFlow.query.filter_by(id=cash_flow_id, user_id=user.id).first()
    if not cash_flow:
        return jsonify({'error': '资金流水不存在'}), 404
    
    # 禁止删除自动生成的流水
    if cash_flow.source == 'auto':
        return jsonify({'error': '不能删除自动生成的资金流水'}), 403
    
    # 回滚账户统计
    account = Account.query.get(cash_flow.account_id)
    if cash_flow.flow_type == 'DEPOSIT':
        account.total_deposit -= cash_flow.amount
        # 回滚现金
        update_cash_balance(
            user_id=user.id,
            currency=cash_flow.currency,
            amount=cash_flow.amount,
            transaction_type='SELL',
            trade_date=cash_flow.flow_date,
            notes=f'删除入金记录: {cash_flow.notes}'
        )
    else:
        account.total_withdrawal -= cash_flow.amount
        # 回滚现金
        update_cash_balance(
            user_id=user.id,
            currency=cash_flow.currency,
            amount=cash_flow.amount,
            transaction_type='BUY',
            trade_date=cash_flow.flow_date,
            notes=f'删除出金记录: {cash_flow.notes}'
        )
    
    db.session.delete(cash_flow)
    db.session.commit()
    
    return jsonify({'success': True})

@api_bp.route('/portfolio-stats', methods=['GET'])
def get_portfolio_stats():
    """获取投资组合统计信息（包含已实现和未实现收益）"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    currency = request.args.get('currency', 'USD')
    
    # 获取账户信息
    account = get_or_create_account(user.id, currency)
    if not account:
        return jsonify({'error': '无法创建或获取账户'}), 500
    
    # 获取所有持仓
    portfolios = Portfolio.query.filter_by(user_id=user.id, currency=currency).all()
    
    # 引入 batch_fetcher 用于获取实时价格
    from app.services.data_provider import batch_fetcher
    
    # 计算统计数据
    total_market_value = 0  # 总市值（包括现金）
    total_cost = 0  # 总成本（不包括现金）
    cash_balance = 0  # 现金余额
    
    # 收集价格获取失败的错误信息
    price_errors = []
    
    for p in portfolios:
        if p.asset_type == 'CASH':
            cash_balance += p.total_quantity
            total_market_value += p.total_quantity
        else:
            total_cost += p.total_cost
            try:
                current_price = batch_fetcher.get_cached_current_price(
                    p.symbol,
                    asset_type=p.asset_type,
                    currency=currency
                )
                
                if current_price:
                    # 使用实时价格计算市值
                    current_market_value = float(current_price) * p.total_quantity
                    total_market_value += current_market_value
                else:
                    # 获取价格失败，记录错误
                    error_msg = f"无法获取 {p.symbol} 的实时价格"
                    price_errors.append(error_msg)
                    print(f"⚠️ {error_msg}")
            except Exception as e:
                # 获取价格出错，记录错误
                error_msg = f"获取 {p.symbol} 实时价格时出错: {str(e)}"
                price_errors.append(error_msg)
                print(f"⚠️ {error_msg}")
    
    # 如果有价格获取失败，返回错误
    if price_errors:
        return jsonify({
            'error': '部分持仓无法获取实时价格',
            'details': price_errors,
            'failed_count': len(price_errors),
            'total_portfolios': len([p for p in portfolios if p.asset_type != 'CASH'])
        }), 500
    
    # 计算收益
    net_deposit = account.total_deposit - account.total_withdrawal  # 净入金
    unrealized_pnl = total_market_value - cash_balance - total_cost  # 未实现盈亏（非现金资产的市值 - 成本）
    realized_pnl = account.realized_profit_loss  # 已实现盈亏
    total_pnl = realized_pnl + unrealized_pnl  # 总盈亏 = 已实现 + 未实现
    
    # 计算总收益率：基于总市值和投资成本，确保未实现收益也被计入
    # 投资成本 = 净入金（如果有记录）或总成本+现金余额（如果没有入金记录）
    # 总收益率 = (当前总市值 - 投资成本) / 投资成本 * 100 = 总盈亏 / 投资成本 * 100
    investment_cost = net_deposit if net_deposit > 0 else (total_cost + cash_balance)
    
    if investment_cost > 0:
        total_return_rate = (total_pnl / investment_cost * 100)
    else:
        # 如果投资成本为0，说明没有投资，总收益率为0
        total_return_rate = 0
    
    return jsonify({
        'currency': currency,
        'net_deposit': net_deposit,  # 净入金
        'total_market_value': total_market_value,  # 总市值
        'cash_balance': cash_balance,  # 现金余额
        'total_cost': total_cost,  # 总成本（不含现金）
        'realized_pnl': realized_pnl,  # 已实现盈亏
        'unrealized_pnl': unrealized_pnl,  # 未实现盈亏
        'total_pnl': total_pnl,  # 总盈亏
        'total_return_rate': total_return_rate,  # 总收益率
        'account': account.to_dict()
    })

# ==================== AI Signal Adoption APIs ====================

@api_bp.route('/ai-signals/<int:signal_id>/adopt', methods=['POST'])
def adopt_ai_signal(signal_id):
    """标记AI建议为已采纳，并关联到用户交易"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    data = request.json
    transaction_id = data.get('transaction_id')
    
    if not transaction_id:
        return jsonify({'error': '缺少交易ID'}), 400
    
    # 验证信号存在
    signal = StockTradeSignal.query.get(signal_id)
    if not signal:
        return jsonify({'error': '信号不存在'}), 404
    
    # 验证交易存在且属于当前用户
    transaction = Transaction.query.filter_by(
        id=transaction_id,
        user_id=user.id
    ).first()
    if not transaction:
        return jsonify({'error': '交易不存在或无权限'}), 404
    
    # 更新信号状态
    signal.adopted = True
    signal.related_transaction_id = transaction_id
    signal.user_id = user.id
    
    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'signal': signal.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

@api_bp.route('/ai-signals/<int:signal_id>/unadopt', methods=['POST'])
def unadopt_ai_signal(signal_id):
    """取消标记AI建议为已采纳"""
    user = get_user_from_request()
    if not user:
        return jsonify({'error': '未登录'}), 401
    
    # 验证信号存在且属于当前用户
    signal = StockTradeSignal.query.filter_by(
        id=signal_id,
        user_id=user.id
    ).first()
    if not signal:
        return jsonify({'error': '信号不存在或无权限'}), 404
    
    # 更新信号状态
    signal.adopted = False
    signal.related_transaction_id = None
    signal.user_id = None
    
    try:
        db.session.commit()
        return jsonify({
            'success': True,
            'signal': signal.to_dict()
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


# ============================================================
# Stock Tracking API Endpoints
# ============================================================

@api_bp.route('/tracking/summary', methods=['GET'])
def tracking_summary():
    """Get tracking portfolio summary."""
    from app.services.tracking_service import tracking_service
    try:
        summary = tracking_service.get_portfolio_summary()
        return jsonify(summary)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/tracking/holdings', methods=['GET'])
def tracking_holdings():
    """Get current tracking holdings."""
    from app.services.tracking_service import tracking_service
    try:
        holdings = tracking_service.get_current_holdings()
        return jsonify({'holdings': holdings})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/tracking/transactions', methods=['GET'])
def tracking_transactions():
    """Get tracking transaction history."""
    from app.services.tracking_service import tracking_service
    limit = request.args.get('limit', 50, type=int)
    try:
        txns = tracking_service.get_transaction_history(limit=limit)
        return jsonify({'transactions': txns})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/tracking/decisions', methods=['GET'])
def tracking_decisions():
    """Get AI decision logs."""
    from app.services.tracking_service import tracking_service
    limit = request.args.get('limit', 30, type=int)
    try:
        logs = tracking_service.get_decision_logs(limit=limit)
        return jsonify({'decisions': logs})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/tracking/snapshots', methods=['GET'])
def tracking_snapshots():
    """Get daily portfolio snapshots for charting."""
    from app.services.tracking_service import tracking_service
    start_date = request.args.get('start_date', None)
    try:
        snapshots = tracking_service.get_daily_snapshots(start_date=start_date)
        return jsonify({'snapshots': snapshots})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/tracking/benchmark', methods=['GET'])
def tracking_benchmark():
    """Get portfolio vs benchmark comparison data."""
    from app.services.tracking_service import tracking_service
    start_date = request.args.get('start_date', None)
    try:
        data = tracking_service.get_benchmark_comparison(start_date=start_date)
        return jsonify(data)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/tracking/refresh-prices', methods=['POST'])
def tracking_refresh_prices():
    """Refresh current prices for all tracked stocks."""
    from app.services.tracking_service import tracking_service
    try:
        result = tracking_service.refresh_prices()
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/tracking/run-decision', methods=['POST'])
def tracking_run_decision():
    """Manually trigger an AI decision run (admin action)."""
    from app.services.tracking_service import tracking_service
    model = request.json.get('model', 'gemini-3-flash-preview') if request.is_json else 'gemini-3-flash-preview'
    try:
        result = tracking_service.run_daily_decision(model_name=model)
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@api_bp.route('/tracking/snapshot', methods=['POST'])
def tracking_take_snapshot():
    """Manually take a daily snapshot."""
    from app.services.tracking_service import tracking_service
    try:
        snapshot = tracking_service.take_daily_snapshot()
        return jsonify(snapshot) if snapshot else jsonify({'message': 'Snapshot already exists for today'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
