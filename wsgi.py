"""
WSGI entry point for Gunicorn/Docker
This file is used by Docker Compose and Gunicorn in production
For local development, use app.py instead: python app.py
"""
from app import create_app, db
from app.scheduler import start_tracking_scheduler

app = create_app()

# Initialize DB and start scheduler in production
with app.app_context():
    db.create_all()

start_tracking_scheduler(app)

if __name__ == '__main__':
    app.run()
