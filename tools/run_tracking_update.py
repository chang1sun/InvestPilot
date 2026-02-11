#!/usr/bin/env python3
"""
Admin script: Manually run stock tracking daily decision.

Usage:
    python tools/run_tracking_update.py                   # Run AI decision + snapshot
    python tools/run_tracking_update.py --snapshot-only   # Only take daily snapshot
    python tools/run_tracking_update.py --backfill        # Backfill missing snapshots
    python tools/run_tracking_update.py --model gemini-3-flash-preview  # Specify model
"""

import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

from app import create_app, db
from app.services.tracking_service import tracking_service


def _auto_upgrade_decision_log_columns(db):
    """Add missing columns to tracking_decision_logs if they don't exist (SQLite compat)."""
    from sqlalchemy import inspect, text
    inspector = inspect(db.engine)
    if 'tracking_decision_logs' not in inspector.get_table_names():
        return
    existing = {col['name'] for col in inspector.get_columns('tracking_decision_logs')}
    for col_name, col_type in [('report_json', 'TEXT'), ('market_regime', 'VARCHAR(20)'), ('confidence_level', 'VARCHAR(20)')]:
        if col_name not in existing:
            db.session.execute(text(f'ALTER TABLE tracking_decision_logs ADD COLUMN {col_name} {col_type}'))
    db.session.commit()


def main():
    parser = argparse.ArgumentParser(description='Run stock tracking update')
    parser.add_argument('--snapshot-only', action='store_true',
                        help='Only take daily snapshot without AI decision')
    parser.add_argument('--backfill', action='store_true',
                        help='Backfill missing daily snapshots')
    parser.add_argument('--model', type=str, default='gemini-3-pro-preview',
                        help='AI model to use for decision (default: gemini-3-pro-preview)')
    parser.add_argument('--refresh-prices', action='store_true',
                        help='Only refresh current prices')
    args = parser.parse_args()

    app = create_app()

    with app.app_context():
        # Ensure tables exist
        db.create_all()

        # Auto-upgrade: add missing columns for deep report support
        _auto_upgrade_decision_log_columns(db)

        if args.refresh_prices:
            print("🔄 Refreshing stock prices...")
            result = tracking_service.refresh_prices()
            print(f"✅ Updated {result['updated']}/{result['total']} prices")
            return

        if args.backfill:
            print("📊 Backfilling missing daily snapshots...")
            count = tracking_service.backfill_snapshots()
            print(f"✅ Created {count} snapshots")
            return

        if args.snapshot_only:
            print("📸 Taking daily snapshot...")
            snapshot = tracking_service.take_daily_snapshot()
            if snapshot:
                print(f"✅ Snapshot taken: value=${snapshot['portfolio_value']:,.2f}, "
                      f"return={snapshot['total_return_pct']:+.2f}%")
            else:
                print("⚠️ Snapshot already exists for today or failed")
            return

        # Full AI decision run
        print(f"🤖 Running AI stock tracking decision with model: {args.model}")
        print("=" * 60)

        result = tracking_service.run_daily_decision(model_name=args.model)

        print("=" * 60)
        print(f"📋 Decision Summary:")
        print(f"   Date: {result['date']}")
        print(f"   Model: {result['model_name']}")
        print(f"   Market Regime: {result.get('market_regime', 'N/A')}")
        print(f"   Confidence: {result.get('confidence_level', 'N/A')}")
        print(f"   Changes: {'Yes' if result['has_changes'] else 'No'}")
        if result.get('actions'):
            for action in result['actions']:
                emoji = '🟢' if action.get('action') == 'BUY' else '🔴'
                print(f"   {emoji} {action.get('action')} {action.get('symbol')}: {action.get('reason', '')[:80]}...")
        
        # Show holdings review scores if available
        report = result.get('report')
        if report and report.get('holdings_review'):
            print(f"\n📊 Holdings Score Card:")
            for h in report['holdings_review']:
                score = h.get('composite_score', 'N/A')
                rec = h.get('recommendation', 'N/A')
                print(f"   {h.get('symbol', '?')}: Score={score}, Rec={rec}")

        print(f"\n💬 Summary: {result.get('summary', 'N/A')[:300]}...")


if __name__ == '__main__':
    main()
