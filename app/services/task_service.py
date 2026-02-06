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
        """执行K线分析任务（基于真实持仓）"""
        from app.models.analysis import Portfolio, Transaction, AnalysisLog
        from datetime import datetime
        
        symbol = params.get('symbol')
        asset_type = params.get('asset_type', 'STOCK')  # 获取资产类型
        is_cn_fund = params.get('is_cn_fund', False)  #  新增：是否为中国基金
        model_name = params.get('model', 'gemini-3-flash-preview')
        language = params.get('language', 'zh')
        
        # 获取资产名称（特别是基金名称）
        symbol_name = None
        if is_cn_fund or asset_type == 'FUND_CN':
            symbol_name = DataProvider.get_symbol_name(symbol, asset_type='FUND_CN')
            if symbol_name:
                print(f"📝 Found fund name: {symbol_name} for {symbol}")
        
        # 检查停止标志
        if stop_flag.is_set():
            return None
        
        # 获取K线数据
        kline_data = DataProvider.get_kline_data(symbol, is_cn_fund=is_cn_fund)
        if not kline_data:
            raise ValueError(f"Could not fetch data for symbol {symbol}")
        
        # 检查停止标志
        if stop_flag.is_set():
            return None
            
        # 获取用户真实持仓和交易记录
        real_portfolio = None
        real_transactions = []
        if user_id:
            real_portfolio = Portfolio.query.filter_by(user_id=user_id, symbol=symbol).first()
            if real_portfolio:
                real_transactions = Transaction.query.filter_by(portfolio_id=real_portfolio.id).order_by(Transaction.trade_date.asc()).all()
        
        # 构建 current_position_state 给 AI
        current_position_state = None
        if real_portfolio and real_portfolio.total_quantity > 0:
            # 查找最后一次买入
            last_buy = None
            for t in real_transactions:
                if t.transaction_type == 'BUY':
                    last_buy = t
            
            if last_buy:
                current_position_state = {
                    'date': last_buy.trade_date.strftime('%Y-%m-%d'),
                    'price': float(last_buy.price),
                    'reason': 'User Real Position',
                    'quantity': float(real_portfolio.total_quantity),
                    'avg_cost': float(real_portfolio.avg_cost)
                }
            else:
                current_position_state = {
                    'date': real_portfolio.created_at.strftime('%Y-%m-%d'),
                    'price': float(real_portfolio.avg_cost),
                    'reason': 'User Real Position',
                    'quantity': float(real_portfolio.total_quantity),
                    'avg_cost': float(real_portfolio.avg_cost)
                }
        
        # 调用 AI 分析 — 优先使用 Agent 模式（function calling）
        from app.services.model_config import get_model_config
        model_config = get_model_config(model_name)
        use_agent = model_config and model_config.get('supports_tools', False) and model_name != 'local-strategy'
        
        if use_agent:
            print(f"🤖 [Agent Mode] Using agent mode for {symbol} with {model_name}")
            analysis_result = self.ai_analyzer.analyze_with_agent(
                symbol,
                model_name=model_name,
                language=language,
                current_position=current_position_state,
                asset_type=asset_type,
                symbol_name=symbol_name,
                user_id=user_id
            )
        else:
            print(f"📝 [Standard Mode] Using standard prompt for {symbol} with {model_name}")
            analysis_result = self.ai_analyzer.analyze(
                symbol,
                kline_data,
                model_name=model_name,
                language=language,
                current_position=current_position_state,
                asset_type=asset_type,
                symbol_name=symbol_name
            )
        
        # 构建返回给前端的数据
        reconstructed_trades = []
        user_transactions = []  #  用户真实交易（不是 AI 建议）
        
        # 配对交易逻辑
        buy_queue = []
        
        for t in real_transactions:
            date_str = t.trade_date.strftime('%Y-%m-%d')
            #  用户真实交易单独存储，不混入 AI 建议
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
        
        # 处理持仓中
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
        
        #  标记哪些 AI 建议被用户采纳了
        # 逻辑：如果 AI 建议的日期和价格与用户真实交易接近，则认为被采纳
        ai_signals = analysis_result.get('signals', [])
        for signal in ai_signals:
            signal['adopted'] = False  # 默认未采纳
            
            # 检查是否有匹配的用户交易
            for user_trans in user_transactions:
                # 同类型、同日期（或相近日期）、价格接近
                if (signal['type'] == user_trans['type'] and 
                    signal['date'] == user_trans['date']):
                    # 价格相差在 5% 以内认为是同一笔交易
                    price_diff = abs(signal['price'] - user_trans['price']) / user_trans['price']
                    if price_diff < 0.05:
                        signal['adopted'] = True
                        break
        
        final_result = {
            "analysis_summary": analysis_result.get('analysis_summary', ''),
            "trades": reconstructed_trades,
            "signals": ai_signals,  #  AI 建议信号（已标记 adopted）
            "user_transactions": user_transactions,  #  用户真实交易（独立字段）
            "source": "user_real_data",
            "ai_suggestion": ai_signals,  # 保持兼容性
            "current_action": analysis_result.get('current_action'),
            "is_fallback": analysis_result.get('is_fallback', False),
            "fallback_reason": analysis_result.get('fallback_reason', ''),
                "tool_calls": analysis_result.get('tool_calls', []),  # Agent tool call log
                "agent_trace": analysis_result.get('agent_trace', []),  # Thinking + tool call timeline
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
        """执行持仓诊断任务 — 支持 Agent 模式"""
        if stop_flag.is_set():
            return None
        
        model_name = params.get('model', 'gemini-3-flash-preview')
        language = params.get('language', 'zh')

        # Check if model supports agent mode
        from app.services.model_config import get_model_config
        model_config = get_model_config(model_name)
        use_agent = model_config and model_config.get('supports_tools', False)

        # Check if this is a full portfolio analysis or single item
        portfolios = params.get('portfolios')
        if portfolios and isinstance(portfolios, list):
            # Full portfolio analysis (not agent-ified yet — uses search)
            result = self.ai_analyzer.analyze_full_portfolio(
                portfolios, model_name=model_name, language=language
            )
        else:
            # Single item analysis
            if use_agent:
                print(f"🤖 [Agent Mode] Using agent mode for portfolio diagnosis with {model_name}")
                result = self.ai_analyzer.analyze_portfolio_item_with_agent(
                    params, model_name=model_name, language=language,
                    user_id=params.get('user_id')
                )
            else:
                print(f"📝 [Standard Mode] Using standard prompt for portfolio diagnosis")
                result = self.ai_analyzer.analyze_portfolio_item(
                    params, model_name=model_name, language=language
                )
        
        return result
    
    def _execute_stock_recommendation(self, params, stop_flag):
        """执行股票推荐任务 — 支持 Agent 模式"""
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

        # Check if model supports agent mode
        from app.services.model_config import get_model_config
        model_config = get_model_config(model_name)
        use_agent = model_config and model_config.get('supports_tools', False)

        if use_agent:
            print(f"🤖 [Agent Mode] Using agent mode for stock recommendation with {model_name}")
            result = self.ai_analyzer.recommend_stocks_with_agent(
                criteria, model_name=model_name, language=language
            )
        else:
            print(f"📝 [Standard Mode] Using standard prompt for stock recommendation")
            result = self.ai_analyzer.recommend_stocks(
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
