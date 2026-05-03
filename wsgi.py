"""
WSGI Entry Point
-----------------
This file is used by Gunicorn (the production server) to start the app.
It is separate from run.py, which is only for local development.

Usage:
    gunicorn --bind 0.0.0.0:5000 wsgi:app
"""

from app import create_app

app = create_app()
