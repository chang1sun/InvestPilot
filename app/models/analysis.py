from app import db
from datetime import datetime
import uuid
import json
from sqlalchemy.dialects.mysql import LONGTEXT

class RecommendationCache(db.Model):
    __tablename__ = 'recommendation_cache'
    
    id = db.Column(db.Integer, primary_key=True)
    cache_date = db.Column(db.Date, nullable=False, index=True)  # 缓存日期
    model_name = db.Column(db.String(50), nullable=False)
    language = db.Column(db.String(10), nullable=False)
    criteria_hash = db.Column(db.String(64), nullable=False)  # 筛选条件的哈希值
    recommendation_result = db.Column(db.Text, nullable=True)  # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('cache_date', 'model_name', 'language', 'criteria_hash', name='unique_recommendation_cache'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'cache_date': self.cache_date.strftime('%Y-%m-%d'),
            'model_name': self.model_name,
            'language': self.language,
            'created_at': self.created_at.isoformat()
        }

class AnalysisLog(db.Model):
    __tablename__ = 'analysis_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False, index=True)
    market_date = db.Column(db.Date, nullable=False, index=True)  # 分析的市场数据日期（用于判断是否需要重新分析）
    model_name = db.Column(db.String(50), nullable=False)  # 使用的模型名称
    language = db.Column(db.String(10), nullable=False)  # 分析语言
    analysis_result = db.Column(LONGTEXT, nullable=True)  # JSON string (完整的分析结果，包含 kline_data，使用 LONGTEXT 支持大容量)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('symbol', 'market_date', 'model_name', 'language', name='unique_analysis'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'symbol': self.symbol,
            'market_date': self.market_date.strftime('%Y-%m-%d'),
            'model_name': self.model_name,
            'language': self.language,
            'analysis_result': self.analysis_result,
            'created_at': self.created_at.isoformat()
        }

class StockTradeSignal(db.Model):
    __tablename__ = 'stock_trade_signals'
    
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    price = db.Column(db.Float, nullable=False)
    signal_type = db.Column(db.String(10), nullable=False) # 'BUY', 'SELL', 'HOLD'
    reason = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(20), default='ai') # 'ai', 'local'
    model_name = db.Column(db.String(50), nullable=False, index=True)  # 模型名称，用于区分不同模型的结果
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('symbol', 'date', 'model_name', name='unique_symbol_date_model'),
    )

    def to_dict(self):
        return {
            'date': self.date.strftime('%Y-%m-%d'),
            'price': self.price,
            'type': self.signal_type,
            'reason': self.reason
        }

class User(db.Model):
    """临时用户模型"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), nullable=False, index=True)
    session_id = db.Column(db.String(64), nullable=False, unique=True, index=True)  # 用于自动登录
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'nickname': self.nickname,
            'email': self.email,
            'session_id': self.session_id,
            'created_at': self.created_at.isoformat(),
            'last_login': self.last_login.isoformat()
        }

class Task(db.Model):
    """异步任务模型"""
    __tablename__ = 'tasks'
    
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.String(64), nullable=False, unique=True, index=True)  # UUID
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    task_type = db.Column(db.String(50), nullable=False)  # 'kline_analysis', 'portfolio_diagnosis', 'stock_recommendation'
    status = db.Column(db.String(20), nullable=False, default='running', index=True)  # 'running', 'completed', 'terminated', 'failed'
    
    # 任务参数
    task_params = db.Column(db.Text, nullable=True)  # JSON string
    
    # 任务结果（使用 LONGTEXT 支持大容量数据，最大 4GB）
    task_result = db.Column(LONGTEXT, nullable=True)  # JSON string
    
    # 错误信息
    error_message = db.Column(db.Text, nullable=True)
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    # 关联用户
    user = db.relationship('User', backref='tasks')
    
    def to_dict(self):
        return {
            'id': self.id,
            'task_id': self.task_id,
            'user_id': self.user_id,
            'task_type': self.task_type,
            'status': self.status,
            'task_params': json.loads(self.task_params) if self.task_params else None,
            'task_result': json.loads(self.task_result) if self.task_result else None,
            'error_message': self.error_message,
            'created_at': self.created_at.isoformat(),
            'started_at': self.started_at.isoformat() if self.started_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None
        }
