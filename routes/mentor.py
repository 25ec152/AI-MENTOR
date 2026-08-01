"""
Mentor blueprint — chat interface and AI interaction.
"""

from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required, current_user
from extensions import db
from models import MentorSession, Message
from services.ai_service import AIService

mentor_bp = Blueprint("mentor", __name__)
ai_service = AIService()


@mentor_bp.route("/chat/<int:session_id>")
@login_required
def chat(session_id):
    session = MentorSession.query.get_or_404(session_id)
    if session.user_id != current_user.id:
        abort(403)
    messages = session.messages.order_by(Message.created_at.asc()).all()
    return render_template("mentor/chat.html", session=session, messages=messages)


@mentor_bp.route("/chat/<int:session_id>/send", methods=["POST"])
@login_required
def send_message(session_id):
    session = MentorSession.query.get_or_404(session_id)
    if session.user_id != current_user.id:
        abort(403)

    data = request.get_json(force=True)
    user_content = (data.get("message") or "").strip()
    if not user_content:
        return jsonify({"error": "Empty message"}), 400

    # Persist user message
    user_msg = Message(role="user", content=user_content, session=session)
    db.session.add(user_msg)
    db.session.flush()  # get id before commit

    # Build conversation history for the AI
    history = [
        {"role": m.role, "content": m.content}
        for m in session.messages.order_by(Message.created_at.asc()).all()
    ]

    # Get AI response
    reply = ai_service.get_response(history, stage=session.stage)

    # Persist assistant message
    assistant_msg = Message(role="assistant", content=reply, session=session)
    db.session.add(assistant_msg)
    db.session.commit()

    return jsonify({
        "user_message": user_msg.to_dict(),
        "assistant_message": assistant_msg.to_dict(),
    })


@mentor_bp.route("/chat/<int:session_id>/stage", methods=["POST"])
@login_required
def update_stage(session_id):
    session = MentorSession.query.get_or_404(session_id)
    if session.user_id != current_user.id:
        abort(403)

    data = request.get_json(force=True)
    new_stage = data.get("stage", "").lower()
    valid_stages = {"ideation", "prototype", "scale"}
    if new_stage not in valid_stages:
        return jsonify({"error": f"Invalid stage. Choose from {valid_stages}"}), 400

    session.stage = new_stage
    db.session.commit()
    return jsonify({"stage": session.stage})
