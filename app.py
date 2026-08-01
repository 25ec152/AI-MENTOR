"""
AI Innovation Mentor - Flask Application Entry Point
"""

from flask import Flask, redirect, url_for
from config import Config
from extensions import db, login_manager, migrate
from routes.auth import auth_bp
from routes.mentor import mentor_bp
from routes.dashboard import dashboard_bp
from voice_assistant import create_voice_blueprint
import user_loader


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions
    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    # Register blueprints
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(mentor_bp, url_prefix="/mentor")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(create_voice_blueprint(), url_prefix="/voice")

    # Redirect "/" to login page
    @app.route("/")
    def home():
        return redirect(url_for("auth.login"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
