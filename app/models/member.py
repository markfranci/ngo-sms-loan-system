from app import db
from datetime import datetime


class Member(db.Model):
    """
    Represents an SME member registered in the system.
    Members do NOT have login accounts — they interact only via SMS.
    Their data is saved here when they send a registration SMS.
    """
    __tablename__ = 'members'

    id = db.Column(db.Integer, primary_key=True)

    # Basic personal information
    full_name = db.Column(db.String(100), nullable=False)

    # Phone number is very important — it is how we identify a member
    # when they send us an SMS. Must be unique (one account per number).
    phone_number = db.Column(db.String(20), unique=True, nullable=False)

    # National ID number — must also be unique
    id_number = db.Column(db.String(20), unique=True, nullable=True)

    # Gender: 'male' or 'female'
    gender = db.Column(db.String(10), nullable=True)

    # Date of birth — we use db.Date (not DateTime) since we only need the date
    date_of_birth = db.Column(db.Date, nullable=True)

    # The town, village or area the member lives in
    location = db.Column(db.String(100), nullable=True)

    # Which group this member belongs to
    # This links to the 'id' column in the 'groups' table
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=True)

    # Automatically records the exact date and time the member was registered
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------

    # The group this member belongs to
    # This is the matching side of 'members' relationship in group.py
    group = db.relationship('Group', back_populates='members')

    # One member can have many SMS messages (sent and received)
    sms_logs = db.relationship('SMSLog', back_populates='member')

    # One member can answer many survey questions
    survey_responses = db.relationship('SurveyResponse', back_populates='member')

    # One member can have many loan assessments over time
    loans = db.relationship('Loan', back_populates='member')

    def __repr__(self):
        return f'<Member {self.full_name} ({self.phone_number})>'
