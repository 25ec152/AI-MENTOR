"""
Dashboard blueprint — session list and management.
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from extensions import db
from models import MentorSession

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
@login_required
def index():
    sessions = (
        current_user.sessions
        .order_by(MentorSession.updated_at.desc())
        .all()
    )
    return render_template("dashboard/index.html", sessions=sessions)


@dashboard_bp.route("/new", methods=["POST"])
@login_required
def new_session():
    title = request.form.get("title", "Untitled Session").strip() or "Untitled Session"
    stage = request.form.get("stage", "ideation")
    session = MentorSession(title=title, stage=stage, user=current_user)
    db.session.add(session)
    db.session.commit()
    return redirect(url_for("mentor.chat", session_id=session.id))


@dashboard_bp.route("/delete/<int:session_id>", methods=["POST"])
@login_required
def delete_session(session_id):
    session = MentorSession.query.get_or_404(session_id)
    if session.user_id != current_user.id:
        flash("Unauthorized.", "danger")
        return redirect(url_for("dashboard.index"))
    db.session.delete(session)
    db.session.commit()
    flash("Session deleted.", "info")
    return redirect(url_for("dashboard.index"))
