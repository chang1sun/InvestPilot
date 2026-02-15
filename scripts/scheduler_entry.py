#!/usr/bin/env python3
"""
Lightweight Docker scheduler — replaces cron / systemd timer.

Schedule: Mon-Fri 22:00 UTC  (matches investment-decision.timer)

This runs as a long-lived process inside the scheduler container,
sleeping until the next scheduled time, then executing the daily pipeline.
No external crontab file or cron daemon required.
"""

import time
import signal
import sys
from datetime import datetime, timedelta, timezone

# ── Configuration ────────────────────────────────────────────
SCHEDULE_HOUR = 22      # UTC hour
SCHEDULE_MINUTE = 0     # UTC minute
WEEKDAYS = {0, 1, 2, 3, 4}  # Mon=0 .. Fri=4


def _seconds_until_next_run() -> float:
    """Calculate seconds until the next scheduled run."""
    now = datetime.now(timezone.utc)
    candidate = now.replace(hour=SCHEDULE_HOUR, minute=SCHEDULE_MINUTE,
                            second=0, microsecond=0)

    # If today's slot already passed, start from tomorrow
    if candidate <= now:
        candidate += timedelta(days=1)

    # Skip weekends
    while candidate.weekday() not in WEEKDAYS:
        candidate += timedelta(days=1)

    return (candidate - now).total_seconds()


def _run_pipeline():
    """Execute the daily decision pipeline (in-process)."""
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from app import create_app, db
    from tools.run_tracking_update import run_full_pipeline

    app = create_app()
    with app.app_context():
        db.create_all()
        model = app.config.get('TRACKING_MODEL', 'gemini-3-pro-preview')
        run_full_pipeline(model=model)


def main():
    # Graceful shutdown
    def _handle_signal(signum, _frame):
        print(f"\n🛑 [Scheduler] Received signal {signum}, shutting down.")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    print("🚀 [Scheduler] Started. Schedule: Mon-Fri 22:00 UTC")

    while True:
        wait = _seconds_until_next_run()
        next_run = datetime.now(timezone.utc) + timedelta(seconds=wait)
        print(f"⏳ [Scheduler] Next run at {next_run.strftime('%Y-%m-%d %H:%M UTC')} "
              f"(in {wait / 3600:.1f}h)")

        time.sleep(wait)

        now = datetime.now(timezone.utc)
        print(f"\n{'='*60}")
        print(f"🔔 [Scheduler] Triggered at {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"{'='*60}")

        try:
            _run_pipeline()
        except SystemExit as e:
            # run_full_pipeline calls sys.exit(1) on failure — catch it
            # so the scheduler keeps running for the next day.
            print(f"⚠️ [Scheduler] Pipeline exited with code {e.code}", file=sys.stderr)
        except Exception as e:
            print(f"❌ [Scheduler] Pipeline error: {e}", file=sys.stderr)

        # Sleep a bit to avoid double-triggering in the same minute
        time.sleep(90)


if __name__ == '__main__':
    main()
