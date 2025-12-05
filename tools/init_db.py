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
from app.models.analysis import AnalysisLog, StockTradeSignal, RecommendationCache

def init_database():
    """初始化数据库表"""
    app = create_app()
    
    with app.app_context():
        print("Creating database tables...")
        db.create_all()
        print("✓ Database tables created successfully!")
        
        # 显示已创建的表
        print("\nExisting tables:")
        print("- analysis_logs")
        print("- stock_trade_signals")
        print("- recommendation_cache (NEW)")
        
        # 显示统计信息
        analysis_count = AnalysisLog.query.count()
        signal_count = StockTradeSignal.query.count()
        cache_count = RecommendationCache.query.count()
        
        print(f"\nCurrent data:")
        print(f"- Analysis logs: {analysis_count}")
        print(f"- Trade signals: {signal_count}")
        print(f"- Recommendation cache: {cache_count}")

if __name__ == '__main__':
    init_database()

