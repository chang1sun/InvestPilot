from app import db
from datetime import datetime
import uuid
import json
import bcrypt

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
    symbol = db.Column(db.String(32), nullable=False, index=True)
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
    symbol = db.Column(db.String(32), nullable=False, index=True)
    date = db.Column(db.Date, nullable=False, index=True)
    price = db.Column(db.Float, nullable=False)
    signal_type = db.Column(db.String(10), nullable=False) # 'BUY', 'SELL', 'HOLD'
    reason = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(20), default='ai') # 'ai', 'local'
    model_name = db.Column(db.String(50), nullable=False, index=True)  # 模型名称，用于区分不同模型的结果
    asset_type = db.Column(db.String(20), default='STOCK', index=True)  # 'STOCK', 'CRYPTO', 'COMMODITY', 'BOND'
    
    # 采纳状态
    adopted = db.Column(db.Boolean, default=False, index=True)  # 是否被用户采纳
    related_transaction_id = db.Column(db.Integer, db.ForeignKey('transactions.id'), nullable=True, index=True)  # 关联的交易ID
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)  # 关联的用户ID（用于区分不同用户的采纳）
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (
        db.UniqueConstraint('symbol', 'date', 'model_name', 'asset_type', name='unique_symbol_date_model_asset'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.strftime('%Y-%m-%d'),
            'price': self.price,
            'type': self.signal_type,
            'reason': self.reason,
            'adopted': self.adopted,
            'related_transaction_id': self.related_transaction_id
        }

class User(db.Model):
    """用户模型"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(200), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(128), nullable=False)  # 密码哈希
    session_id = db.Column(db.String(64), nullable=True, unique=True, index=True)  # 用于会话管理
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime, default=datetime.utcnow)
    
    def set_password(self, password):
        """设置密码（加密存储）"""
        password_bytes = password.encode('utf-8')
        salt = bcrypt.gensalt()
        self.password_hash = bcrypt.hashpw(password_bytes, salt).decode('utf-8')
    
    def check_password(self, password):
        """验证密码"""
        password_bytes = password.encode('utf-8')
        password_hash_bytes = self.password_hash.encode('utf-8')
        return bcrypt.checkpw(password_bytes, password_hash_bytes)
    
    def generate_session_id(self):
        """生成新的会话ID"""
        self.session_id = str(uuid.uuid4())
        return self.session_id
    
    def to_dict(self):
        return {
            'id': self.id,
            'nickname': self.nickname,
            'email': self.email,
            'session_id': self.session_id,
            'created_at': self.created_at.isoformat(),
            'last_login': self.last_login.isoformat()
        }

class Account(db.Model):
    """用户账户模型 - 记录资金流水和收益统计"""
    __tablename__ = 'accounts'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    currency = db.Column(db.String(10), nullable=False, default='USD')  # 账户币种
    
    # 资金流水统计
    total_deposit = db.Column(db.Float, nullable=False, default=0)  # 累计入金
    total_withdrawal = db.Column(db.Float, nullable=False, default=0)  # 累计出金
    
    # 收益统计（按币种）
    realized_profit_loss = db.Column(db.Float, nullable=False, default=0)  # 已实现盈亏
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联
    user = db.relationship('User', backref='accounts')
    cash_flows = db.relationship('CashFlow', backref='account', cascade='all, delete-orphan', order_by='CashFlow.flow_date.desc()')
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'currency', name='unique_user_currency'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'currency': self.currency,
            'total_deposit': self.total_deposit,
            'total_withdrawal': self.total_withdrawal,
            'net_deposit': self.total_deposit - self.total_withdrawal,
            'realized_profit_loss': self.realized_profit_loss,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class CashFlow(db.Model):
    """资金流水模型 - 记录每笔入金/出金"""
    __tablename__ = 'cash_flows'
    
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey('accounts.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    
    # 流水信息
    flow_type = db.Column(db.String(20), nullable=False, index=True)  # DEPOSIT(入金), WITHDRAWAL(出金)
    flow_date = db.Column(db.Date, nullable=False, index=True)  # 流水日期
    amount = db.Column(db.Float, nullable=False)  # 金额（正数）
    currency = db.Column(db.String(10), nullable=False, default='USD')
    
    # 备注
    notes = db.Column(db.Text, nullable=True)
    
    # 来源
    source = db.Column(db.String(20), default='manual')  # manual, auto
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联
    user = db.relationship('User', backref='cash_flows')
    
    def to_dict(self):
        return {
            'id': self.id,
            'account_id': self.account_id,
            'user_id': self.user_id,
            'flow_type': self.flow_type,
            'flow_date': self.flow_date.strftime('%Y-%m-%d'),
            'amount': self.amount,
            'currency': self.currency,
            'notes': self.notes,
            'source': self.source,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
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
    
    # 任务结果
    task_result = db.Column(db.Text, nullable=True)  # JSON string
    
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

class Portfolio(db.Model):
    """用户虚拟持仓模型"""
    __tablename__ = 'portfolios'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    symbol = db.Column(db.String(32), nullable=False, index=True)  # 标的代码
    asset_type = db.Column(db.String(20), nullable=False, default='STOCK')  # STOCK, CRYPTO, GOLD, CASH
    currency = db.Column(db.String(10), nullable=False, default='USD')  # USD, HKD, CNY
    
    # 持仓信息
    total_quantity = db.Column(db.Float, nullable=False, default=0)  # 总持仓数量
    avg_cost = db.Column(db.Float, nullable=False, default=0)  # 平均成本
    total_cost = db.Column(db.Float, nullable=False, default=0)  # 总成本
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联
    user = db.relationship('User', backref='portfolios')
    transactions = db.relationship('Transaction', backref='portfolio', cascade='all, delete-orphan', order_by='Transaction.trade_date.desc()')
    
    __table_args__ = (
        db.UniqueConstraint('user_id', 'symbol', 'asset_type', 'currency', name='unique_user_symbol_asset_currency'),
    )
    
    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'symbol': self.symbol,
            'asset_type': self.asset_type,
            'currency': self.currency,
            'total_quantity': self.total_quantity,
            'avg_cost': self.avg_cost,
            'total_cost': self.total_cost,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

class Transaction(db.Model):
    """交易记录模型"""
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    portfolio_id = db.Column(db.Integer, db.ForeignKey('portfolios.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    
    # 交易信息
    transaction_type = db.Column(db.String(10), nullable=False)  # BUY, SELL
    trade_date = db.Column(db.Date, nullable=False, index=True)  # 交易日期
    price = db.Column(db.Float, nullable=False)  # 交易价格
    quantity = db.Column(db.Float, nullable=False)  # 交易数量
    amount = db.Column(db.Float, nullable=False)  # 交易金额（price * quantity）
    
    # 成本和收益（仅卖出时有值）
    cost_basis = db.Column(db.Float, nullable=True, default=0)  # 卖出时的成本基础（平均成本 * 数量）
    realized_profit_loss = db.Column(db.Float, nullable=True, default=0)  # 已实现盈亏（卖出金额 - 成本基础）
    
    # 备注
    notes = db.Column(db.Text, nullable=True)
    
    # 来源（手动添加或AI建议）
    source = db.Column(db.String(20), default='manual')  # manual, ai_suggestion
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联
    user = db.relationship('User', backref='transactions')
    
    def to_dict(self):
        return {
            'id': self.id,
            'portfolio_id': self.portfolio_id,
            'user_id': self.user_id,
            'transaction_type': self.transaction_type,
            'trade_date': self.trade_date.strftime('%Y-%m-%d'),
            'price': self.price,
            'quantity': self.quantity,
            'amount': self.amount,
            'cost_basis': self.cost_basis,
            'realized_profit_loss': self.realized_profit_loss,
            'notes': self.notes,
            'source': self.source,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


# ============================================================
# Stock Tracking Models (Curated Stock Tracking Feature)
# ============================================================

class TrackingStock(db.Model):
    """Currently tracked (held) stocks in the curated list"""
    __tablename__ = 'tracking_stocks'

    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(32), nullable=False, unique=True, index=True)
    name = db.Column(db.String(128), nullable=True)  # Stock display name
    buy_price = db.Column(db.Float, nullable=False)  # Price when added to the list
    buy_date = db.Column(db.Date, nullable=False, index=True)
    current_price = db.Column(db.Float, nullable=True)  # Latest cached price
    cost_amount = db.Column(db.Float, nullable=True)  # Actual capital invested (may differ from PER_STOCK_ALLOCATION for replacements)
    reason = db.Column(db.Text, nullable=True)  # AI reasoning for buying

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def get_cost_amount(self):
        """Return actual cost amount, defaulting to PER_STOCK_ALLOCATION for legacy records."""
        return self.cost_amount if self.cost_amount is not None else 10000.0

    def to_dict(self):
        cost = self.get_cost_amount()
        unrealized_pct = None
        if self.buy_price and self.current_price and self.buy_price > 0:
            unrealized_pct = round(((self.current_price - self.buy_price) / self.buy_price) * 100, 2)
        return {
            'id': self.id,
            'symbol': self.symbol,
            'name': self.name,
            'buy_price': self.buy_price,
            'buy_date': self.buy_date.strftime('%Y-%m-%d'),
            'current_price': self.current_price,
            'cost_amount': round(cost, 2),
            'reason': self.reason,
            'unrealized_pct': unrealized_pct,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }


class TrackingTransaction(db.Model):
    """Historical buy/sell transactions for tracking portfolio"""
    __tablename__ = 'tracking_transactions'

    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(32), nullable=False, index=True)
    name = db.Column(db.String(128), nullable=True)
    action = db.Column(db.String(10), nullable=False, index=True)  # BUY or SELL
    price = db.Column(db.Float, nullable=False)
    date = db.Column(db.Date, nullable=False, index=True)
    reason = db.Column(db.Text, nullable=True)  # AI reasoning

    # For SELL transactions: record realized P&L
    buy_price = db.Column(db.Float, nullable=True)  # Original buy price (for SELL)
    realized_pct = db.Column(db.Float, nullable=True)  # Realized return % (for SELL)
    # For BUY transactions: actual capital invested (may differ from PER_STOCK_ALLOCATION for replacements)
    cost_amount = db.Column(db.Float, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_cost_amount(self):
        """Return actual cost amount, defaulting to PER_STOCK_ALLOCATION for legacy records."""
        return self.cost_amount if self.cost_amount is not None else 10000.0

    def to_dict(self):
        return {
            'id': self.id,
            'symbol': self.symbol,
            'name': self.name,
            'action': self.action,
            'price': self.price,
            'date': self.date.strftime('%Y-%m-%d'),
            'reason': self.reason,
            'buy_price': self.buy_price,
            'realized_pct': self.realized_pct,
            'cost_amount': round(self.get_cost_amount(), 2),
            'created_at': self.created_at.isoformat()
        }


class TrackingDailySnapshot(db.Model):
    """Daily portfolio value snapshot for performance charting"""
    __tablename__ = 'tracking_daily_snapshots'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True, index=True)
    portfolio_value = db.Column(db.Float, nullable=False)  # Total portfolio value (initial_capital basis)
    cash = db.Column(db.Float, nullable=False)  # Remaining cash
    holdings_value = db.Column(db.Float, nullable=False)  # Sum of current holding values
    total_return_pct = db.Column(db.Float, nullable=False, default=0)  # Total return % since inception
    realized_pnl = db.Column(db.Float, nullable=False, default=0)  # Cumulative realized P&L
    holdings_json = db.Column(db.Text, nullable=True)  # JSON snapshot of holdings at this date

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'date': self.date.strftime('%Y-%m-%d'),
            'portfolio_value': self.portfolio_value,
            'cash': self.cash,
            'holdings_value': self.holdings_value,
            'total_return_pct': self.total_return_pct,
            'realized_pnl': self.realized_pnl,
            'holdings_json': self.holdings_json,
            'created_at': self.created_at.isoformat()
        }


class TrackingDecisionLog(db.Model):
    """Log of each AI decision run (even when no changes are made)"""
    __tablename__ = 'tracking_decision_logs'

    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, index=True)
    model_name = db.Column(db.String(50), nullable=False)
    has_changes = db.Column(db.Boolean, default=False)  # Whether portfolio was updated
    summary = db.Column(db.Text, nullable=True)  # AI's market summary / reasoning
    actions_json = db.Column(db.Text, nullable=True)  # JSON list of actions taken
    raw_response = db.Column(db.Text, nullable=True)  # Full AI response for debugging
    elapsed_seconds = db.Column(db.Float, nullable=True)

    # Deep report fields
    report_json = db.Column(db.Text, nullable=True)  # Full structured daily report (JSON)
    market_regime = db.Column(db.String(20), nullable=True)  # RISK-ON / NEUTRAL / RISK-OFF
    confidence_level = db.Column(db.String(20), nullable=True)  # HIGH / MEDIUM / LOW

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        actions = []
        if self.actions_json:
            try:
                actions = json.loads(self.actions_json)
            except Exception:
                pass
        report = None
        if self.report_json:
            try:
                report = json.loads(self.report_json)
            except Exception:
                pass
        return {
            'id': self.id,
            'date': self.date.strftime('%Y-%m-%d'),
            'model_name': self.model_name,
            'has_changes': self.has_changes,
            'summary': self.summary,
            'actions': actions,
            'elapsed_seconds': self.elapsed_seconds,
            'market_regime': self.market_regime,
            'confidence_level': self.confidence_level,
            'report': report,
            'created_at': self.created_at.isoformat()
        }
