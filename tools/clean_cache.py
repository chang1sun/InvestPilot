from app import create_app, db
from app.models.analysis import AnalysisLog

app = create_app()
with app.app_context():
    try:
        num_deleted = db.session.query(AnalysisLog).delete()
        db.session.commit()
        print(f"Deleted {num_deleted} records from AnalysisLog.")
    except Exception as e:
        print(f"Error deleting records: {e}")

