"""
WSGI entry point for Gunicorn/Docker
This file is used by Docker Compose and Gunicorn in production
For local development, use app.py instead: python app.py
"""
from app import create_app, db

app = create_app()

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run()
