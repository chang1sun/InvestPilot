import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'hard-to-guess-string'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///investpilot.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    REDIS_URL = os.environ.get('REDIS_URL') or 'redis://localhost:6379/0'
    
    # AI Model API Keys
    GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
    OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
    ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY')
    QWEN_API_KEY = os.environ.get('QWEN_API_KEY')

    # Stock Tracking Cron
    ENABLE_STOCK_TRACKING_CRON = os.environ.get('ENABLE_STOCK_TRACKING_CRON', 'false').lower() == 'true'
    TRACKING_MODEL = os.environ.get('TRACKING_MODEL', 'gemini-3-flash-preview')
    TRACKING_CRON_HOUR_UTC = int(os.environ.get('TRACKING_CRON_HOUR_UTC', '22'))  # Default: 22:00 UTC (17:00 ET)

