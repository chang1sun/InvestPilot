"""
Scheduler stub — APScheduler has been removed.

Cron jobs are now managed by a single systemd timer (see project root):
  - investpilot-decision.timer → scripts/run_daily_decision.py
    (handles price refresh + snapshot + AI decision in one pipeline)

This module is kept only for backward compatibility; calling
start_tracking_scheduler() is a safe no-op.
"""


def start_tracking_scheduler(app):  # noqa: ARG001
    """No-op — scheduling is handled externally by systemd timers."""
    print(
        "ℹ️  In-process APScheduler has been removed. "
        "Cron jobs are now managed by systemd timers."
    )
