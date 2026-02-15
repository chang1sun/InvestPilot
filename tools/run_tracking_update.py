#!/usr/bin/env python3
"""
Admin script: Manually run stock tracking daily decision.

Usage:
    python tools/run_tracking_update.py                          # Run AI decision (only)
    python tools/run_tracking_update.py --full-pipeline          # Full cron pipeline: refresh + snapshot + decision
    python tools/run_tracking_update.py --snapshot-only          # Only take daily snapshot
    python tools/run_tracking_update.py --backfill               # Backfill missing snapshots
    python tools/run_tracking_update.py --refresh-prices         # Only refresh prices
    python tools/run_tracking_update.py --model gemini-3-pro     # Specify AI model
"""

import sys
import os
import argparse

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

from app.services.tracking_service import tracking_service


def run_full_pipeline(model: str = 'gemini-3-pro-preview'):
    """
    Full daily pipeline (used by cron / systemd / Docker scheduler):
      1. Refresh prices
      2. Take daily snapshot
      3. Run AI decision
      4. Evaluate past decisions (T+5 accuracy scoring)
      5. Backfill sector data (for stocks missing it)
      6. Send notification (email / webhook)

    Exits with code 1 on failure so schedulers can detect errors.
    """
    from flask import current_app
    from app.services.notification_service import get_notification_service

    pipeline_summary = {}

    # ── Step 1: Refresh prices ──────────────────────────────
    print("🕐 [Pipeline] Step 1/6 — Refreshing stock prices...")
    try:
        refresh_result = tracking_service.refresh_prices()
        pipeline_summary['price_refresh'] = refresh_result
        print(f"✅ [Pipeline] Price refresh done. "
              f"Updated {refresh_result['updated']}/{refresh_result['total']} stocks.")
    except Exception as e:
        print(f"❌ [Pipeline] Price refresh failed: {e}", file=sys.stderr)
        sys.exit(1)

    # ── Step 2: Daily snapshot ──────────────────────────────
    print("🕐 [Pipeline] Step 2/6 — Taking daily portfolio snapshot...")
    try:
        snapshot = tracking_service.take_daily_snapshot()
        if snapshot:
            pipeline_summary['snapshot'] = snapshot
            print(f"✅ [Pipeline] Daily snapshot taken. "
                  f"Portfolio value: ${snapshot.get('portfolio_value', 'N/A')}")
        else:
            print("ℹ️  [Pipeline] Snapshot already exists for today, skipped.")
    except Exception as e:
        print(f"❌ [Pipeline] Snapshot failed: {e}", file=sys.stderr)
        sys.exit(1)

    # ── Step 3: AI decision ─────────────────────────────────
    print(f"🕐 [Pipeline] Step 3/6 — Running AI decision (model={model})...")
    decision_result = None
    try:
        decision_result = tracking_service.run_daily_decision(model_name=model)
        has_changes = decision_result.get('has_changes', False)
        print(f"✅ [Pipeline] AI decision complete. Changes: {has_changes}")
    except Exception as e:
        print(f"❌ [Pipeline] AI decision failed: {e}", file=sys.stderr)
        sys.exit(1)

    # ── Step 4: Evaluate past decisions (T+5 accuracy) ──────
    print("🕐 [Pipeline] Step 4/6 — Evaluating past decision accuracy...")
    try:
        eval_count = tracking_service.evaluate_past_decisions(lookback_days=5)
        pipeline_summary['decisions_evaluated'] = eval_count
        print(f"✅ [Pipeline] Evaluated {eval_count} past decisions.")
    except Exception as e:
        print(f"⚠️ [Pipeline] Decision evaluation failed (non-fatal): {e}")

    # ── Step 5: Backfill sector data ────────────────────────
    print("🕐 [Pipeline] Step 5/6 — Backfilling sector data...")
    try:
        sector_count = tracking_service.backfill_sectors()
        print(f"✅ [Pipeline] Backfilled sector data for {sector_count} stocks.")
    except Exception as e:
        print(f"⚠️ [Pipeline] Sector backfill failed (non-fatal): {e}")

    # ── Step 6: Send notification ───────────────────────────
    print("🕐 [Pipeline] Step 6/6 — Sending notifications...")
    try:
        notify_svc = get_notification_service({
            k: current_app.config.get(k, '')
            for k in ['RESEND_API_KEY', 'RESEND_FROM', 'NOTIFY_WEBHOOK_URL']
        })
        notify_result = notify_svc.notify_daily_result(decision_result or {}, pipeline_summary)
        print(f"✅ [Pipeline] Notification: email={notify_result['email_sent']}, "
              f"webhook={notify_result['webhook_sent']}")
        if notify_result['errors']:
            for err in notify_result['errors']:
                print(f"  ⚠️ {err}")
    except Exception as e:
        print(f"⚠️ [Pipeline] Notification failed (non-fatal): {e}")

    print("🎉 [Pipeline] Daily pipeline finished successfully.")


def main():
    parser = argparse.ArgumentParser(description='Run stock tracking update')
    parser.add_argument('--full-pipeline', action='store_true',
                        help='Run full daily pipeline: refresh prices + snapshot + AI decision')
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

        if args.full_pipeline:
            run_full_pipeline(model=args.model)
            return

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

        # Full AI decision run (without refresh / snapshot)
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
