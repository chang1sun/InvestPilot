"""
WSGI entry point for Gunicorn/Docker
This file is used by Docker Compose and Gunicorn in production
For local development, use app.py instead: python app.py
"""
from app import create_app

app = create_app()

if __name__ == '__main__':
    app.run()

