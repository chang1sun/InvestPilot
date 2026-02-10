"""
Local development entry point
Use this file for local development: python app.py
For production/Docker, use wsgi.py instead
"""
from app import create_app, db
from app.scheduler import start_tracking_scheduler

app = create_app()

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    start_tracking_scheduler(app)
    app.run(debug=True, host='0.0.0.0', port=5000)
