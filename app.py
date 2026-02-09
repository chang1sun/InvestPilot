"""
Local development entry point
Use this file for local development: python app.py
For production/Docker, use wsgi.py instead
"""
from app import create_app, db

app = create_app()

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
            with app.app_context():
                from app.services.tracking_service import tracking_service
                print(f"\n🕐 [Cron] Running daily stock tracking decision...")
                try:
                    result = tracking_service.run_daily_decision(model_name=model)
                    print(f"✅ [Cron] Tracking decision complete. Changes: {result.get('has_changes', False)}")
                except Exception as e:
                    print(f"❌ [Cron] Tracking decision failed: {e}")

        scheduler = BackgroundScheduler()
        # Run at specified hour UTC, Monday-Friday only
        scheduler.add_job(
            run_tracking_job,
            CronTrigger(hour=cron_hour, minute=0, day_of_week='mon-fri', timezone='UTC'),
            id='stock_tracking_daily',
            replace_existing=True
        )
        scheduler.start()
        print(f"✅ Stock tracking cron ENABLED — runs at {cron_hour}:00 UTC (Mon-Fri) with model: {model}")

    except ImportError:
        print("⚠️  APScheduler not installed. Run: pip install apscheduler")
    except Exception as e:
        print(f"⚠️  Failed to start tracking scheduler: {e}")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    start_tracking_scheduler(app)
    app.run(debug=True, host='0.0.0.0', port=5000)

