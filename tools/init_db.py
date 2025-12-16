#!/usr/bin/env python3
"""
数据库初始化脚本
用于创建或更新数据库表结构
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models.analysis import AnalysisLog, StockTradeSignal, RecommendationCache, User, Task

def init_database():
    """初始化数据库表（幂等性：如果表已存在则跳过）"""
    app = create_app()
    
    with app.app_context():
        # 检查表是否已存在（幂等性检查）
        from sqlalchemy import inspect
        inspector = inspect(db.engine)
        existing_tables = inspector.get_table_names()
        
        required_tables = ['users', 'tasks', 'analysis_logs', 'stock_trade_signals', 'recommendation_cache']
        missing_tables = [t for t in required_tables if t not in existing_tables]
        
        if missing_tables:
            print(f"Creating database tables... (missing: {', '.join(missing_tables)})")
            db.create_all()
            print("✓ Database tables created successfully!")
        else:
            print("✓ All database tables already exist. Skipping table creation.")
        
        # 显示已创建的表
        print("\nExisting tables:")
        print("- analysis_logs")
        print("- stock_trade_signals")
        print("- recommendation_cache")
        print("- users")
        print("- tasks")
        
        # 显示统计信息
        try:
            analysis_count = AnalysisLog.query.count()
            signal_count = StockTradeSignal.query.count()
            cache_count = RecommendationCache.query.count()
            user_count = User.query.count()
            task_count = Task.query.count()
            
            print(f"\nCurrent data:")
            print(f"- Analysis logs: {analysis_count}")
            print(f"- Trade signals: {signal_count}")
            print(f"- Recommendation cache: {cache_count}")
            print(f"- Users: {user_count}")
            print(f"- Tasks: {task_count}")
        except Exception as e:
            print(f"\nWarning: Could not query statistics: {e}")

if __name__ == '__main__':
    init_database()

