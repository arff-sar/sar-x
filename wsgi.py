import os

from app import create_app


app = create_app(os.getenv("APP_ENV") or os.getenv("FLASK_ENV") or "production")
