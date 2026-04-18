from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from config import Config

# Create the database object
db = SQLAlchemy()

# Create the login manager object
login_manager = LoginManager()
login_manager.login_view = 'auth.login'

def create_app():
    # Create the Flask application
    app = Flask(__name__)

    # Load settings from config.py
    app.config.from_object(Config)

    # Connect the database to the app
    db.init_app(app)

    # Connect the login manager to the app
    login_manager.init_app(app)

    # Import all models so SQLAlchemy knows about every table.
    # This must happen inside create_app() to avoid circular import errors.
    # A circular import is when file A imports file B, and file B imports file A
    # — Python gets confused. Importing inside the function avoids this.
    from app import models  # noqa: F401

    # ----------------------------------------------------------------
    # Register Blueprints
    # Each blueprint is a group of related routes.
    # We register them here so Flask knows they exist.
    # ----------------------------------------------------------------

    # Auth blueprint — handles /login and /logout
    from app.routes.auth import auth
    app.register_blueprint(auth)

    # Main blueprint — handles /dashboard and core pages
    from app.routes.main import main
    app.register_blueprint(main)

    # Groups blueprint — handles /groups routes
    from app.routes.groups import groups
    app.register_blueprint(groups)

    return app
