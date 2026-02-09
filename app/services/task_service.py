import threading
import uuid
import json
from datetime import datetime
from app import db
from app.models.analysis import Task
from app.services.ai_analyzer import AIAnalyzer
from app.services.data_provider import DataProvider

class TaskService:
    """异步任务服务"""
    
    def __init__(self):
        self.ai_analyzer = AIAnalyzer()
        self._running_tasks = {}  # {task_id: thread}
        self._task_stop_flags = {}  # {task_id: stop_flag}
    
    def create_task(self, user_id, task_type, task_params):
        """创建新任务"""
        task_id = str(uuid.uuid4())
        
        # 创建任务记录
        task = Task(
            task_id=task_id,
            user_id=user_id,
            task_type=task_type,
            status='running',
            task_params=json.dumps(task_params),
            started_at=datetime.utcnow()
        )
        
        db.session.add(task)
        db.session.commit()
        
        # 创建停止标志
        stop_flag = threading.Event()
        self._task_stop_flags[task_id] = stop_flag
        
        # 启动后台任务
        thread = threading.Thread(
            target=self._execute_task,
            args=(task_id, task_type, task_params, stop_flag),
            daemon=True
        )
        thread.start()
        self._running_tasks[task_id] = thread
        
        return task_id
    
    def _execute_task(self, task_id, task_type, task_params, stop_flag):
        """执行任务（后台线程）"""
        from app import create_app
        app = create_app()
        with app.app_context():
            try:
                task = Task.query.filter_by(task_id=task_id).first()
                if not task:
                    return
                
                if task_type == 'kline_analysis':
                    result = self._execute_kline_analysis(task_params, stop_flag, task.user_id)
                elif task_type == 'portfolio_diagnosis':
                    result = self._execute_portfolio_diagnosis(task_params, stop_flag)
                elif task_type == 'stock_recommendation':
                    result = self._execute_stock_recommendation(task_params, stop_flag)
                else:
                    raise ValueError(f"Unknown task type: {task_type}")
                
                # 检查是否被终止
                if stop_flag.is_set():
                    task.status = 'terminated'
                    task.completed_at = datetime.utcnow()
                    db.session.commit()
                    return
                
                # 保存结果
                task.status = 'completed'
                result_json = json.dumps(result)
                task.task_result = result_json
                task.completed_at = datetime.utcnow()
                try:
                    db.session.commit()
                except Exception as commit_error:
                    # 如果提交失败（可能是数据太大），回滚并标记为失败
                    db.session.rollback()
                    task.status = 'failed'
                    error_msg = f"Failed to save result: {str(commit_error)}"
                    if len(error_msg) > 65535:
                        error_msg = error_msg[:65500] + "... (truncated)"
                    task.error_message = error_msg
                    task.completed_at = datetime.utcnow()
                    db.session.commit()
                    print(f"Task {task_id} failed to save result: {commit_error}")
                    return
                
            except Exception as e:
                # 保存错误信息
                # 先回滚之前的错误事务
                db.session.rollback()
                try:
                    task = Task.query.filter_by(task_id=task_id).first()
                    if task:
                        task.status = 'failed'
                        # 截断错误信息，避免过长
                        error_msg = str(e)
                        if len(error_msg) > 65535:  # TEXT 字段最大长度
                            error_msg = error_msg[:65500] + "... (truncated)"
                        task.error_message = error_msg
                        task.completed_at = datetime.utcnow()
                        db.session.commit()
                except Exception as save_error:
                    db.session.rollback()
                    print(f"Failed to save error for task {task_id}: {save_error}")
                print(f"Task {task_id} failed: {e}")
            finally:
                # 清理
                self._running_tasks.pop(task_id, None)
                self._task_stop_flags.pop(task_id, None)
    
    def _execute_kline_analysis(self, params, stop_flag, user_id=None):
        """执行K线分析任务（Agent 模式，AI 自行拉取所需数据）"""
        from app.models.analysis import Portfolio, Transaction, AnalysisLog
        from datetime import datetime
        
        symbol = params.get('symbol')
        asset_type = params.get('asset_type', 'STOCK')
        is_cn_fund = params.get('is_cn_fund', False)
        model_name = params.get('model', 'gemini-3-flash-preview')
        language = params.get('language', 'zh')
        
        # 获取资产名称（特别是基金名称，用于 prompt 中的标识）
        symbol_name = None
        if is_cn_fund or asset_type == 'FUND_CN':
            symbol_name = DataProvider.get_symbol_name(symbol, asset_type='FUND_CN')
            if symbol_name:
                print(f"📝 Found fund name: {symbol_name} for {symbol}")
        
        if stop_flag.is_set():
            return None
        
        # Agent mode: AI will fetch kline, portfolio, and position data via tool calls
        print(f"🤖 [Agent Mode] Using agent mode for {symbol} with {model_name}")
        analysis_result = self.ai_analyzer.analyze_with_agent(
            symbol,
            model_name=model_name,
            language=language,
            asset_type=asset_type,
            symbol_name=symbol_name,
            user_id=user_id
        )
        
        # Fetch kline data for frontend chart rendering (AI already fetched its own via tools)
        from app.services.data_provider import batch_fetcher
        kline_data = batch_fetcher.get_cached_kline_data(
            symbol, period="3y", interval="1d",
            is_cn_fund=(asset_type == 'FUND_CN')
        )
        if not kline_data:
            kline_data = []
        
        # Build user transaction history for frontend display
        reconstructed_trades = []
        user_transactions = []
        if user_id:
            real_portfolio = Portfolio.query.filter_by(user_id=user_id, symbol=symbol).first()
            if real_portfolio:
                real_transactions = Transaction.query.filter_by(
                    portfolio_id=real_portfolio.id
                ).order_by(Transaction.trade_date.asc()).all()
                
                buy_queue = []
                for t in real_transactions:
                    date_str = t.trade_date.strftime('%Y-%m-%d')
                    user_transactions.append({
                        "type": t.transaction_type,
                        "date": date_str,
                        "price": float(t.price),
                        "reason": t.notes or 'Manual Trade'
                    })
                    
                    if t.transaction_type == 'BUY':
                        buy_queue.append({
                            'date': date_str,
                            'price': float(t.price),
                            'quantity': float(t.quantity),
                            'reason': t.notes or 'Manual Buy'
                        })
                    elif t.transaction_type == 'SELL':
                        sell_qty = float(t.quantity)
                        while sell_qty > 0 and buy_queue:
                            buy_record = buy_queue[0]
                            matched_qty = min(sell_qty, buy_record['quantity'])
                            buy_price = buy_record['price']
                            sell_price = float(t.price)
                            ret_pct = ((sell_price - buy_price) / buy_price) * 100
                            d1 = datetime.strptime(buy_record['date'], '%Y-%m-%d')
                            d2 = t.trade_date
                            days = (datetime.combine(d2, datetime.min.time()) - d1).days
                            reconstructed_trades.append({
                                "buy_date": buy_record['date'],
                                "buy_price": buy_price,
                                "sell_date": date_str,
                                "sell_price": sell_price,
                                "status": "CLOSED",
                                "holding_period": f"{days} days",
                                "return_rate": f"{ret_pct:+.2f}%",
                                "reason": buy_record['reason'],
                                "sell_reason": t.notes or 'Manual Sell'
                            })
                            sell_qty -= matched_qty
                            buy_record['quantity'] -= matched_qty
                            if buy_record['quantity'] <= 0.000001:
                                buy_queue.pop(0)
                
                # Process open positions
                if kline_data:
                    latest_close = kline_data[-1]['close']
                    latest_date_str = kline_data[-1]['date']
                    for b in buy_queue:
                        buy_price = b['price']
                        curr_ret = ((latest_close - buy_price) / buy_price) * 100
                        d1 = datetime.strptime(b['date'], '%Y-%m-%d')
                        d2 = datetime.strptime(latest_date_str, '%Y-%m-%d')
                        days = (d2 - d1).days
                        reconstructed_trades.append({
                            "buy_date": b['date'],
                            "buy_price": b['price'],
                            "sell_date": None,
                            "sell_price": None,
                            "status": "HOLDING",
                            "holding_period": f"{days} days",
                            "return_rate": f"{curr_ret:+.2f}% (Open)",
                            "reason": b['reason']
                        })
                
                reconstructed_trades.sort(key=lambda x: x['buy_date'], reverse=True)
        
        # Mark AI signals adopted by user
        ai_signals = analysis_result.get('signals', [])
        for signal in ai_signals:
            signal['adopted'] = False
            for user_trans in user_transactions:
                if (signal.get('type') == user_trans['type'] and
                        signal.get('date') == user_trans['date']):
                    try:
                        price_diff = abs(signal['price'] - user_trans['price']) / user_trans['price']
                        if price_diff < 0.05:
                            signal['adopted'] = True
                            break
                    except (TypeError, ZeroDivisionError):
                        pass
        
        final_result = {
            "analysis_summary": analysis_result.get('analysis_summary', ''),
            "trades": reconstructed_trades,
            "signals": ai_signals,
            "user_transactions": user_transactions,
            "source": "user_real_data",
            "ai_suggestion": ai_signals,
            "current_action": analysis_result.get('current_action'),
            "is_fallback": analysis_result.get('is_fallback', False),
            "fallback_reason": analysis_result.get('fallback_reason', ''),
            "tool_calls": analysis_result.get('tool_calls', []),
            "agent_trace": analysis_result.get('agent_trace', []),
            "agent_mode": analysis_result.get('source') == 'ai_agent',
            "agent_fallback": analysis_result.get('agent_fallback', False)
        }
        
        return {
            'symbol': symbol,
            'asset_type': asset_type,
            'kline_data': kline_data,
            'analysis': final_result,
            'source': 'user_real_data'
        }
    def _execute_portfolio_diagnosis(self, params, stop_flag):
        """执行持仓诊断任务（Agent 模式）"""
        if stop_flag.is_set():
            return None
        
        model_name = params.get('model', 'gemini-3-flash-preview')
        language = params.get('language', 'zh')

        # Full portfolio analysis or single item
        portfolios = params.get('portfolios')
        if portfolios and isinstance(portfolios, list):
            result = self.ai_analyzer.analyze_full_portfolio(
                portfolios, model_name=model_name, language=language
            )
        else:
            print(f"🤖 [Agent Mode] Using agent mode for portfolio diagnosis with {model_name}")
            result = self.ai_analyzer.analyze_portfolio_item_with_agent(
                params, model_name=model_name, language=language,
                user_id=params.get('user_id')
            )
        
        return result
    
    def _execute_stock_recommendation(self, params, stop_flag):
        """执行股票推荐任务（Agent 模式）"""
        if stop_flag.is_set():
            return None
        
        model_name = params.get('model', 'gemini-3-flash-preview')
        language = params.get('language', 'zh')

        criteria = {
            'market': params.get('market', 'Any'),
            'asset_type': params.get('asset_type', 'STOCK'),
            'include_etf': params.get('include_etf', 'false'),
            'capital': params.get('capital', 'Any'),
            'risk': params.get('risk', 'Any'),
            'frequency': params.get('frequency', 'Any')
        }

        print(f"🤖 [Agent Mode] Using agent mode for stock recommendation with {model_name}")
        result = self.ai_analyzer.recommend_stocks_with_agent(
            criteria, model_name=model_name, language=language
        )
        
        return result
    
    def terminate_task(self, task_id, user_id):
        """终止任务"""
        task = Task.query.filter_by(task_id=task_id, user_id=user_id).first()
        if not task:
            return False
        
        if task.status != 'running':
            return False
        
        # 设置停止标志
        stop_flag = self._task_stop_flags.get(task_id)
        if stop_flag:
            stop_flag.set()
        
        # 更新任务状态
        task.status = 'terminated'
        task.completed_at = datetime.utcnow()
        db.session.commit()
        
        return True
    
    def get_task(self, task_id, user_id):
        """获取任务信息"""
        task = Task.query.filter_by(task_id=task_id, user_id=user_id).first()
        return task.to_dict() if task else None
    
    def get_user_tasks(self, user_id, status=None):
        """获取用户的所有任务"""
        query = Task.query.filter_by(user_id=user_id)
        if status:
            query = query.filter_by(status=status)
        tasks = query.order_by(Task.created_at.desc()).all()
        return [task.to_dict() for task in tasks]

# 全局任务服务实例
task_service = TaskService()
