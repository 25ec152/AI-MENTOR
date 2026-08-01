"""
Database models.
"""

from datetime import datetime
from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sessions = db.relationship("MentorSession", back_populates="user", lazy="dynamic")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class MentorSession(db.Model):
    __tablename__ = "mentor_sessions"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False, default="Untitled Session")
    stage = db.Column(db.String(50), nullable=False, default="ideation")  # ideation | prototype | scale
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    user = db.relationship("User", back_populates="sessions")
    messages = db.relationship("Message", back_populates="session", lazy="dynamic", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<MentorSession {self.id} [{self.stage}]>"


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    role = db.Column(db.String(20), nullable=False)   # "user" | "assistant"
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    session_id = db.Column(db.Integer, db.ForeignKey("mentor_sessions.id"), nullable=False)
    session = db.relationship("MentorSession", back_populates="messages")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<Message {self.id} [{self.role}]>"
