from app import db
from datetime import datetime


class Loan(db.Model):
    """
    Represents a loan assessment for an SME member.
    After reviewing a member's data and survey responses,
    an Admin or Staff member fills in this assessment.
    The final decision (approved/rejected/pending) is stored here.
    """
    __tablename__ = 'loans'

    id = db.Column(db.Integer, primary_key=True)

    # Which member this loan assessment is for
    member_id = db.Column(
        db.Integer, db.ForeignKey('members.id'), nullable=False
    )

    # Which admin or staff member performed this assessment
    assessed_by = db.Column(
        db.Integer, db.ForeignKey('users.id'), nullable=True
    )

    # How much money (in KSh) the member is requesting
    amount_requested = db.Column(db.Float, nullable=True)

    # A score out of 100 based on the member's data and survey responses
    # Higher score = stronger loan application
    score = db.Column(db.Float, nullable=True)

    # The final loan decision:
    # 'pending'  = assessment is not yet complete
    # 'approved' = member qualifies for the loan
    # 'rejected' = member does not qualify
    status = db.Column(db.String(20), nullable=False, default='pending')

    # Any extra notes or remarks written by the staff member
    # For example: "Member has stable income but high existing debt"
    notes = db.Column(db.Text, nullable=True)

    # When this assessment was first created
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # When this assessment was last updated
    # onupdate=datetime.utcnow means this automatically updates
    # every time the row is changed (e.g. status changed from pending to approved)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # ----------------------------------------------------------------
    # Relationships
    # ----------------------------------------------------------------

    # The member being assessed
    # This is the matching side of 'loans' in member.py
    member = db.relationship('Member', back_populates='loans')

    # The staff or admin who did the assessment
    assessor = db.relationship('User', foreign_keys=[assessed_by])

    # ----------------------------------------------------------------
    # Helper methods
    # ----------------------------------------------------------------

    def is_approved(self):
        return self.status == 'approved'

    def is_rejected(self):
        return self.status == 'rejected'

    def is_pending(self):
        return self.status == 'pending'

    def __repr__(self):
        return f'<Loan member={self.member_id} status={self.status} score={self.score}>'
