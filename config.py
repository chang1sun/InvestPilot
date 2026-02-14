import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hard-to-guess-string'
    # Default: SQLite in local instance/ directory; Docker overrides via DATABASE_URL env
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'instance', 'investpilot.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    
    # AI Model API Keys
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
    QWEN_API_KEY = os.environ.get('QWEN_API_KEY')

    # Stock Tracking Cron
    TRACKING_MODEL = os.environ.get('TRACKING_MODEL', 'gemini-3-flash-preview')

