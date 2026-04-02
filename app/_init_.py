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

    return app
