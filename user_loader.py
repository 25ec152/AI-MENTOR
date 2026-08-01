"""
Flask-Login user loader — kept in a separate file to avoid circular imports.
Import this module inside create_app after db.init_app().
"""

from extensions import db, login_manager
from models import User


@login_manager.user_loader
def load_user(user_id: str):
    return db.session.get(User, int(user_id))
