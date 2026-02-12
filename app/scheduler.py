"""
Background scheduler for stock tracking cron jobs.
Shared by both app.py (development) and wsgi.py (production).
"""


def start_tracking_scheduler(app):
    """Start the background scheduler for stock tracking (if enabled)."""
    if not app.config.get('ENABLE_STOCK_TRACKING_CRON', False):
        print("ℹ️  Stock tracking cron is DISABLED. Set ENABLE_STOCK_TRACKING_CRON=true to enable.")
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        cron_hour = app.config.get('TRACKING_CRON_HOUR_UTC', 22)
        model = app.config.get('TRACKING_MODEL', 'gemini-3-flash-preview')

        def run_tracking_job():
            """Run AI daily decision for the tracking portfolio."""
            with app.app_context():
                from app.services.tracking_service import tracking_service
                print(f"\n🕐 [Cron] Running daily stock tracking decision...")
                try:
                    result = tracking_service.run_daily_decision(model_name=model)
                    print(f"✅ [Cron] Tracking decision complete. Changes: {result.get('has_changes', False)}")
                except Exception as e:
                    print(f"❌ [Cron] Tracking decision failed: {e}")

        def run_price_refresh_job():
            """Refresh prices and take daily snapshot after market close."""
            with app.app_context():
                from app.services.tracking_service import tracking_service
                print(f"\n🕐 [Cron] Running post-market price refresh & daily snapshot...")
                try:
                    refresh_result = tracking_service.refresh_prices()
                    print(f"✅ [Cron] Price refresh done. Updated {refresh_result['updated']}/{refresh_result['total']} stocks.")
                    snapshot = tracking_service.take_daily_snapshot()
                    if snapshot:
                        print(f"✅ [Cron] Daily snapshot taken. Portfolio value: ${snapshot.get('portfolio_value', 'N/A')}")
                    else:
                        print(f"ℹ️  [Cron] Snapshot already exists for today, skipped.")
                except Exception as e:
                    print(f"❌ [Cron] Price refresh / snapshot failed: {e}")

        scheduler = BackgroundScheduler()
        # Run AI decision at specified hour UTC, Monday-Friday only
        scheduler.add_job(
            run_tracking_job,
            CronTrigger(hour=cron_hour, minute=0, day_of_week='mon-fri', timezone='UTC'),
            id='stock_tracking_daily',
            replace_existing=True
        )
        # Run price refresh 30 minutes after AI decision (to ensure market data is settled)
        scheduler.add_job(
            run_price_refresh_job,
            CronTrigger(hour=cron_hour, minute=30, day_of_week='mon-fri', timezone='UTC'),
            id='stock_price_refresh_daily',
            replace_existing=True
        )
        scheduler.start()
        print(f"✅ Stock tracking cron ENABLED -- runs at {cron_hour}:00 UTC (Mon-Fri) with model: {model}")
        print(f"✅ Price refresh cron ENABLED -- runs at {cron_hour}:30 UTC (Mon-Fri)")

    except ImportError:
        print("⚠️  APScheduler not installed. Run: pip install apscheduler")
    except Exception as e:
        print(f"⚠️  Failed to start tracking scheduler: {e}")
