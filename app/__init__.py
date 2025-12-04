from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from config import Config
import redis

db = SQLAlchemy()
r = None

class MockRedis:
    """Simple in-memory cache fallback when Redis is unavailable"""
    def __init__(self):
        self.store = {}
        print("Warning: Redis unavailable. Using in-memory MockRedis.")

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value
        return True

    def setex(self, key, time, value):
        self.store[key] = value
        return True

def create_app(config_class=Config):
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config.from_object(config_class)

    db.init_app(app)
    CORS(app)
    
    # Redis connection with Fallback
    global r
    try:
        r = redis.from_url(app.config['REDIS_URL'])
        r.ping() # Test connection
    except (redis.ConnectionError, Exception):
        r = MockRedis()

    # Register Blueprints
    from app.routes.api import api_bp
    from app.routes.main import main_bp
    
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(main_bp)

    return app
