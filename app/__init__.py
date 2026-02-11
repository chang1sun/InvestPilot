from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from config import Config
import redis
import os
import time as _time

db = SQLAlchemy()
r = None

class MockRedis:
    """Simple in-memory cache fallback when Redis is unavailable, with TTL support."""
    MAX_SIZE = 100  # Maximum number of entries to prevent unbounded growth

    def __init__(self):
        self.store = {}       # key -> value
        self.expiry = {}      # key -> expiry timestamp (None = no expiry)
        print("Warning: Redis unavailable. Using in-memory MockRedis.")

    def _is_expired(self, key):
        """Check if a key has expired."""
        exp = self.expiry.get(key)
        if exp is not None and _time.time() > exp:
            # Clean up expired entry
            self.store.pop(key, None)
            self.expiry.pop(key, None)
            return True
        return False

    def _evict_expired(self):
        """Remove all expired entries to free memory."""
        now = _time.time()
        expired_keys = [k for k, exp in self.expiry.items() if exp is not None and now > exp]
        for k in expired_keys:
            self.store.pop(k, None)
            self.expiry.pop(k, None)

    def _enforce_max_size(self):
        """Evict oldest entries if store exceeds MAX_SIZE."""
        if len(self.store) > self.MAX_SIZE:
            # First evict expired
            self._evict_expired()
            # If still over limit, remove entries with earliest expiry
            if len(self.store) > self.MAX_SIZE:
                # Sort by expiry time (None = no expiry, treat as infinity)
                sorted_keys = sorted(
                    self.expiry.keys(),
                    key=lambda k: self.expiry.get(k) or float('inf')
                )
                # Remove oldest entries until within limit
                to_remove = len(self.store) - self.MAX_SIZE
                for k in sorted_keys[:to_remove]:
                    self.store.pop(k, None)
                    self.expiry.pop(k, None)

    def get(self, key):
        if self._is_expired(key):
            return None
        return self.store.get(key)

    def set(self, key, value):
        self.store[key] = value
        self.expiry[key] = None  # No expiry
        self._enforce_max_size()
        return True

    def setex(self, key, ttl_seconds, value):
        """Set a key with TTL (time-to-live) in seconds."""
        self.store[key] = value
        self.expiry[key] = _time.time() + ttl_seconds
        self._enforce_max_size()
        return True

def create_app(config_class=Config):
    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config.from_object(config_class)

    db.init_app(app)
    
    # Enable SQLite WAL mode for better concurrency and crash resilience
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if db_uri.startswith('sqlite'):
        # Ensure the directory for SQLite DB file exists
        if 'sqlite:///' in db_uri:
            db_path = db_uri.replace('sqlite:///', '')
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)
        
        from sqlalchemy import event
        
        with app.app_context():
            @event.listens_for(db.engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()

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
    
    # Import models to ensure they are registered
    from app.models.analysis import User, Task, TrackingStock, TrackingTransaction, TrackingDailySnapshot, TrackingDecisionLog
    
    # Register error handlers for API routes to return JSON
    @app.errorhandler(500)
    @app.errorhandler(404)
    @app.errorhandler(403)
    @app.errorhandler(401)
    def handle_error(e):
        """Ensure API errors return JSON instead of HTML"""
        from flask import request, jsonify
        # Only return JSON for API routes
        if request.path.startswith('/api/'):
            code = getattr(e, 'code', 500)
            message = getattr(e, 'description', str(e))
            return jsonify({
                'error': message,
                'code': code
            }), code
        # For non-API routes, use default Flask error handling
        return e
    
    @app.errorhandler(Exception)
    def handle_exception(e):
        """Handle all unhandled exceptions for API routes"""
        from flask import request, jsonify
        import traceback
        
        # Only return JSON for API routes
        if request.path.startswith('/api/'):
            # Log the full traceback for debugging
            app.logger.error(f"Unhandled exception: {str(e)}\n{traceback.format_exc()}")
            
            # Return user-friendly error message
            error_msg = str(e)
            if 'cryptography' in error_msg.lower():
                error_msg = '数据库连接失败：缺少必要的加密库。请确保已安装 cryptography 包。'
            elif 'connection' in error_msg.lower() or 'database' in error_msg.lower():
                error_msg = '数据库连接失败，请检查数据库配置。'
            
            return jsonify({
                'error': error_msg,
                'code': 500
            }), 500
        
        # For non-API routes, re-raise the exception
        raise e

    return app
