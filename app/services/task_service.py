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
                    result = self._execute_kline_analysis(task_params, stop_flag)
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
    
    def _execute_kline_analysis(self, params, stop_flag):
        """执行K线分析任务（支持增量/全量分析）"""
        from app.models.analysis import StockTradeSignal, AnalysisLog
        from datetime import datetime
        
        symbol = params.get('symbol')
        model_name = params.get('model', 'gemini-2.5-flash')
        language = params.get('language', 'zh')
        
        # 检查停止标志
        if stop_flag.is_set():
            return None
        
        # 获取K线数据
        kline_data = DataProvider.get_kline_data(symbol)
        if not kline_data:
            raise ValueError(f"Could not fetch data for symbol {symbol}")
        
        # 检查停止标志
        if stop_flag.is_set():
            return None
        
        # 确定市场数据范围
        market_dates = [d['date'] for d in kline_data]
        if not market_dates:
            raise ValueError(f"Empty market data for {symbol}")
        
        latest_market_date_str = market_dates[-1]
        latest_market_date = datetime.strptime(latest_market_date_str, '%Y-%m-%d').date()
        
        # 检查MySQL是否已有当天的分析记录（缓存）
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
                return cached_data
            except json.JSONDecodeError as e:
                print(f"JSON decode error for existing log: {e}, re-analyzing...")
                db.session.delete(existing_log)
                db.session.commit()
        
        # 获取分析状态（从StockTradeSignal表）
        latest_signal = StockTradeSignal.query.filter_by(
            symbol=symbol,
            model_name=model_name
        ).order_by(StockTradeSignal.date.desc()).first()
        latest_analyzed_date = latest_signal.date if latest_signal else None
        
        # 获取当前持仓状态
        signals = StockTradeSignal.query.filter_by(
            symbol=symbol,
            model_name=model_name
        ).order_by(StockTradeSignal.date.asc()).all()
        current_position_state = None
        for s in signals:
            if s.signal_type == 'BUY':
                if current_position_state is None:
                    current_position_state = {
                        'date': s.date.strftime('%Y-%m-%d'),
                        'price': s.price,
                        'reason': s.reason
                    }
            elif s.signal_type == 'SELL':
                if current_position_state:
                    current_position_state = None
        
        # 检查停止标志
        if stop_flag.is_set():
            return None
        
        # 增量/全量逻辑
        new_signals = []
        should_cache = True
        
        if model_name == "local-strategy":
            # 本地策略：直接分析，不保存历史
            analysis_result = self.ai_analyzer.analyze(
                symbol,
                kline_data,
                model_name=model_name,
                language=language,
                current_position=current_position_state
            )
            return {
                'symbol': symbol,
                'kline_data': kline_data,
                'analysis': analysis_result,
                'source': 'local'
            }
        
        # AI模型：增量/全量逻辑
        if not latest_analyzed_date:
            # Case A: 没有历史 -> 全量分析
            print(f"[{symbol}] No history found. Running full initialization...")
            full_analysis = self.ai_analyzer.analyze(
                symbol,
                kline_data,
                model_name=model_name,
                language=language,
                current_position=current_position_state
            )
            
            if full_analysis.get('source') == 'ai_model':
                # 保存所有信号到DB
                for sig in full_analysis.get('signals', []):
                    try:
                        sig_date = datetime.strptime(sig['date'], '%Y-%m-%d').date()
                        exists = StockTradeSignal.query.filter_by(
                            symbol=symbol,
                            date=sig_date,
                            model_name=model_name
                        ).first()
                        if not exists:
                            new_signal = StockTradeSignal(
                                symbol=symbol,
                                date=sig_date,
                                price=sig['price'],
                                signal_type=sig['type'],
                                reason=sig.get('reason', ''),
                                source='ai',
                                model_name=model_name
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
                should_cache = False
                print(f"[{symbol}] AI analysis failed, local strategy used. Will not cache.")
        else:
            # Case B: 有历史 -> 增量分析（仅保存新信号）
            print(f"[{symbol}] Found history up to {latest_analyzed_date}. Market date: {latest_market_date}")
            
            if latest_market_date > latest_analyzed_date:
                print(f"[{symbol}] Incremental update needed.")
                fresh_analysis = self.ai_analyzer.analyze(
                    symbol,
                    kline_data,
                    model_name=model_name,
                    language=language,
                    current_position=current_position_state
                )
                
                if fresh_analysis.get('source') == 'ai_model':
                    # 只保存新信号（日期 > latest_analyzed_date）
                    for sig in fresh_analysis.get('signals', []):
                        sig_date = datetime.strptime(sig['date'], '%Y-%m-%d').date()
                        if sig_date > latest_analyzed_date:
                            try:
                                new_signal = StockTradeSignal(
                                    symbol=symbol,
                                    date=sig_date,
                                    price=sig['price'],
                                    signal_type=sig['type'],
                                    reason=sig.get('reason', ''),
                                    source='ai',
                                    model_name=model_name
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
                    should_cache = False
                    print(f"[{symbol}] AI analysis failed during incremental update, local strategy used. Will not cache.")
        
        # 检查停止标志
        if stop_flag.is_set():
            return None
        
        # 从DB重新构建最终结果（确保历史一致性）
        db_signals = StockTradeSignal.query.filter_by(
            symbol=symbol,
            model_name=model_name
        ).order_by(StockTradeSignal.date.asc()).all()
        
        # 重建trades和signals
        reconstructed_trades = []
        current_position = None
        ui_signals = []
        
        for s in db_signals:
            date_str = s.date.strftime('%Y-%m-%d')
            ui_signals.append({
                "type": s.signal_type,
                "date": date_str,
                "price": s.price,
                "reason": s.reason
            })
            
            if s.signal_type == 'BUY':
                if current_position is None:
                    current_position = {
                        'buy_date': date_str,
                        'buy_price': s.price,
                        'buy_reason': s.reason
                    }
            elif s.signal_type == 'SELL':
                if current_position:
                    buy_price = current_position['buy_price']
                    sell_price = s.price
                    ret_pct = ((sell_price - buy_price) / buy_price) * 100
                    
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
                        "reason": s.reason
                    })
                    current_position = None
        
        # 处理持仓中
        if current_position:
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
        
        reconstructed_trades.sort(key=lambda x: x['buy_date'], reverse=True)
        
        # 获取摘要
        summary_text = f"Model-specific History Loaded ({model_name}). "
        if 'fresh_analysis' in locals():
            summary_text = fresh_analysis.get('analysis_summary', summary_text)
        elif 'full_analysis' in locals():
            summary_text = full_analysis.get('analysis_summary', summary_text)
        else:
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
        
        # 保存到AnalysisLog缓存
        if should_cache:
            try:
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
                    existing.analysis_result = json.dumps(final_response)
                    existing.created_at = datetime.utcnow()
                    db.session.commit()
                    print(f"[{symbol}] Analysis result updated in MySQL for {latest_market_date_str}")
            except Exception as e:
                db.session.rollback()
                print(f"MySQL Save Error: {e}")
        
        return final_response
    
    def _execute_portfolio_diagnosis(self, params, stop_flag):
        """执行持仓诊断任务"""
        if stop_flag.is_set():
            return None
        
        result = self.ai_analyzer.analyze_portfolio_item(
            params,
            model_name=params.get('model', 'gemini-2.5-flash'),
            language=params.get('language', 'zh')
        )
        
        return result
    
    def _execute_stock_recommendation(self, params, stop_flag):
        """执行股票推荐任务"""
        if stop_flag.is_set():
            return None
        
        criteria = {
            'market': params.get('market', 'Any'),
            'capital': params.get('capital', 'Any'),
            'risk': params.get('risk', 'Any'),
            'frequency': params.get('frequency', 'Any')
        }
        
        result = self.ai_analyzer.recommend_stocks(
            criteria,
            model_name=params.get('model', 'gemini-2.5-flash'),
            language=params.get('language', 'zh')
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

