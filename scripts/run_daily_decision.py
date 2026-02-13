#!/usr/bin/env python3
"""
Standalone cron script — runs the full daily stock tracking pipeline:
  1. Refresh prices (fetch latest post-market quotes)
  2. Take daily portfolio snapshot
  3. Run AI decision (buy / sell / hold)

Intended to be called by systemd timer — NOT from within Gunicorn.

Usage:
    python scripts/run_daily_decision.py
"""

import sys
import os

# Ensure the project root is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.services.tracking_service import TrackingService


def main():
    app = create_app()

    with app.app_context():
        db.create_all()

        svc = TrackingService()
        model = app.config.get('TRACKING_MODEL', 'gemini-3-flash-preview')

        # ── Step 1: Refresh prices ──────────────────────────────
        print("🕐 [Cron] Step 1/3 — Refreshing stock prices...")
        try:
            refresh_result = svc.refresh_prices()
            print(f"✅ [Cron] Price refresh done. "
                  f"Updated {refresh_result['updated']}/{refresh_result['total']} stocks.")
        except Exception as e:
            print(f"❌ [Cron] Price refresh failed: {e}", file=sys.stderr)
            sys.exit(1)

        # ── Step 2: Daily snapshot ──────────────────────────────
        print("🕐 [Cron] Step 2/3 — Taking daily portfolio snapshot...")
        try:
            snapshot = svc.take_daily_snapshot()
            if snapshot:
                print(f"✅ [Cron] Daily snapshot taken. "
                      f"Portfolio value: ${snapshot.get('portfolio_value', 'N/A')}")
            else:
                print("ℹ️  [Cron] Snapshot already exists for today, skipped.")
        except Exception as e:
            print(f"❌ [Cron] Snapshot failed: {e}", file=sys.stderr)
            sys.exit(1)

        # ── Step 3: AI decision ─────────────────────────────────
        print(f"🕐 [Cron] Step 3/3 — Running AI decision (model={model})...")
        try:
            result = svc.run_daily_decision(model_name=model)
            has_changes = result.get('has_changes', False)
            print(f"✅ [Cron] AI decision complete. Changes: {has_changes}")
        except Exception as e:
            print(f"❌ [Cron] AI decision failed: {e}", file=sys.stderr)
            sys.exit(1)

        print("🎉 [Cron] Daily pipeline finished successfully.")


if __name__ == '__main__':
    main()
