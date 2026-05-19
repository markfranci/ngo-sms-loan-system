from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
import secrets


# This tells Flask-Login how to load a user from the database
# given their ID (stored in the session)
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class User(db.Model, UserMixin):
    """
    Represents an Admin or SME Staff member who can log in to the system.
    SME Members do NOT have accounts — they interact only via SMS.
    """
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

    # Role can be 'admin' or 'staff'
    role = db.Column(db.String(20), nullable=False, default='staff')

    invitation_token = db.Column(db.String(128), unique=True, nullable=True)
    invitation_sent_at = db.Column(db.DateTime, nullable=True)
    invitation_accepted_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ----------------------------------------------------------------
    # Password helpers — we never store plain text passwords
    # ----------------------------------------------------------------

    def set_password(self, password):
        """Hash and store the password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check if the provided password matches the stored hash."""
        return check_password_hash(self.password_hash, password)

    def create_invitation(self):
        """Create a secure one-time token for a new user to set their password."""
        self.invitation_token = secrets.token_urlsafe(32)
        self.invitation_sent_at = datetime.utcnow()
        self.invitation_accepted_at = None
        return self.invitation_token

    def accept_invitation(self, password):
        """Set the user's password and mark the invitation as accepted."""
        self.set_password(password)
        self.invitation_token = None
        self.invitation_accepted_at = datetime.utcnow()

    # ----------------------------------------------------------------
    # Role helpers — easy way to check what a user can do
    # ----------------------------------------------------------------

    def is_admin(self):
        return self.role == 'admin'

    def is_staff(self):
        return self.role == 'staff'

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'
