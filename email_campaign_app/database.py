from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def init_db(app):
    """Initialize the database, creating all tables."""
    with app.app_context():
        db.create_all()
