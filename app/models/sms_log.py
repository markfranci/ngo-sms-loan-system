from app import db
from datetime import datetime


class SMSLog(db.Model):
    """
    Records every SMS message that passes through the system.
    - 'incoming' = SMS sent BY a member TO the system
    - 'outgoing' = SMS sent BY the system TO a member
    This gives us a full history of all communication.
    """
    __tablename__ = 'sms_logs'

    id = db.Column(db.Integer, primary_key=True)

    # The phone number that sent the message
    sender = db.Column(db.String(20), nullable=False)

    # The phone number that received the message
    recipient = db.Column(db.String(20), nullable=False)

    # The actual text content of the SMS
    # We use db.Text instead of db.String because messages
    # can be longer than a fixed character limit
    message = db.Column(db.Text, nullable=False)

    # Direction tells us who sent it:
    # 'incoming' = member sent it to us
    # 'outgoing' = we sent it to the member
    direction = db.Column(db.String(10), nullable=False)

    # Status of the message:
    # 'received' = we got the message successfully
    # 'sent'     = we sent it successfully
    # 'failed'   = something went wrong
    status = db.Column(db.String(10), nullable=False, default='received')

    # Link to the member this SMS belongs to.
    # nullable=True because the SMS might come from an unknown number
    # (someone who is not yet registered in our system)
    member_id = db.Column(db.Integer, db.ForeignKey('members.id'), nullable=True)

    # Exact date and time the message was logged
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------

    # The member this SMS is linked to
    # This is the matching side of 'sms_logs' in member.py
    member = db.relationship('Member', back_populates='sms_logs')

    def __repr__(self):
        return f'<SMSLog [{self.direction}] from {self.sender}: "{self.message[:30]}...">'
