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


def main():
    parser = argparse.ArgumentParser(description='Run stock tracking update')
    parser.add_argument('--snapshot-only', action='store_true',
                        help='Only take daily snapshot without AI decision')
    parser.add_argument('--backfill', action='store_true',
                        help='Backfill missing daily snapshots')
    parser.add_argument('--model', type=str, default='gemini-3-flash-preview',
                        help='AI model to use for decision (default: gemini-3-flash-preview)')
    parser.add_argument('--refresh-prices', action='store_true',
                        help='Only refresh current prices')
    args = parser.parse_args()

    app = create_app()

    with app.app_context():
        # Ensure tables exist
        db.create_all()

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
        print(f"   Changes: {'Yes' if result['has_changes'] else 'No'}")
        if result.get('actions'):
            for action in result['actions']:
                emoji = '🟢' if action.get('action') == 'BUY' else '🔴'
                print(f"   {emoji} {action.get('action')} {action.get('symbol')}: {action.get('reason', '')[:80]}...")
        print(f"\n💬 Summary: {result.get('summary', 'N/A')[:200]}...")


if __name__ == '__main__':
    main()
