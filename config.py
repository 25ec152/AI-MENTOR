"""
Configuration classes for different environments.
"""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///ai_mentor.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # IBM watsonx.ai settings
    WATSONX_API_KEY    = os.environ.get("WATSONX_API_KEY", "")
    WATSONX_PROJECT_ID = os.environ.get("WATSONX_PROJECT_ID", "")
    WATSONX_URL        = os.environ.get("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
    WATSONX_MODEL_ID   = os.environ.get("WATSONX_MODEL_ID", "ibm/granite-13b-instruct-v2")
    AI_MAX_TOKENS      = int(os.environ.get("AI_MAX_TOKENS", 1024))

    # Mentor persona
    MENTOR_NAME = os.environ.get("MENTOR_NAME", "Aria")


class DevelopmentConfig(Config):
    DEBUG = True


class ProductionConfig(Config):
    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "postgresql://user:pass@localhost/ai_mentor")


class TestingConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
