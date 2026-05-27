import os
import secrets
from urllib.parse import quote_plus
from dotenv import load_dotenv

# Load all the values from the .env file
load_dotenv()

class Config:
    # SECRET_KEY must be set in .env for production.
    # A random fallback is generated for local development only.
    SECRET_KEY = os.getenv('SECRET_KEY') or secrets.token_hex(32)

    DB_USERNAME = os.getenv('DB_USERNAME')
    DB_PASSWORD = os.getenv('DB_PASSWORD')
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_NAME = os.getenv('DB_NAME')

    # quote_plus() safely encodes special characters in the password
    # e.g. 'Project@2026' becomes 'Project%402026' so the URL is not broken
    SQLALCHEMY_DATABASE_URI = (
        f"mysql+pymysql://{DB_USERNAME}:{quote_plus(DB_PASSWORD or '')}@{DB_HOST}/{DB_NAME}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Secure session cookies in production
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'

    # Twilio credentials for outgoing WhatsApp messages
    TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
    TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
    TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER', 'whatsapp:+14155238886')

    UPLOAD_FOLDER = os.getenv(
        'UPLOAD_FOLDER',
        os.path.join(os.path.dirname(__file__), 'uploads')
    )
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
