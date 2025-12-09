from app import db
from datetime import datetime

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
    analysis_result = db.Column(db.Text, nullable=True)  # JSON string (完整的分析结果，包含 kline_data)
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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('symbol', 'date', name='unique_symbol_date'),
    )

    def to_dict(self):
        return {
            'date': self.date.strftime('%Y-%m-%d'),
            'price': self.price,
            'type': self.signal_type,
            'reason': self.reason
        }
