from app import db
from datetime import datetime

class AnalysisLog(db.Model):
    __tablename__ = 'analysis_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    symbol = db.Column(db.String(20), nullable=False)
    analysis_result = db.Column(db.Text, nullable=True) # JSON string
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'symbol': self.symbol,
            'analysis_result': self.analysis_result,
            'created_at': self.created_at.isoformat()
        }

