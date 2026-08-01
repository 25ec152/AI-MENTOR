"""
Voice Assistant package — Blueprint factory.

Usage (in app.py):
    from voice_assistant import create_voice_blueprint
    app.register_blueprint(create_voice_blueprint(), url_prefix="/voice")
"""

from flask import Blueprint

# Blueprint is declared here so routes.py can import it without a circular dep.
voice_bp = Blueprint(
    "voice",
    __name__,
    template_folder="templates",   # resolves to voice_assistant/templates/
)


def create_voice_blueprint() -> Blueprint:
    """
    Import routes to register them on voice_bp, then return the blueprint.
    The import is deferred inside the factory to avoid circular imports at
    module load time (routes imports voice_bp from this module).
    """
    from voice_assistant import routes  # noqa: F401  – side-effect import
    return voice_bp
