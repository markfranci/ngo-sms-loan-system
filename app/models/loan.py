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

class LoanAssessmentDetails(db.Model):
    __tablename__ = 'loan_assessment_details'
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loans.id'), nullable=False)

    county = db.Column(db.String(100))
    sub_county = db.Column(db.String(100))
    ward = db.Column(db.String(100))
    group_name = db.Column(db.String(100))

    business_location = db.Column(db.String(255))
    nature_of_business = db.Column(db.String(255))
    registration_number = db.Column(db.String(100))

    male_participants = db.Column(db.Integer, default=0)
    female_participants = db.Column(db.Integer, default=0)

    loan_term_months = db.Column(db.Integer)
    monthly_instalment = db.Column(db.Float)
    loan_purpose = db.Column(db.Text)

    loan = db.relationship('Loan', backref=db.backref('details', uselist=False))


class LoanFinancialSnapshot(db.Model):
    __tablename__ = 'loan_financial_snapshots'
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loans.id'), nullable=False)

    # Balance Sheet
    fixed_assets = db.Column(db.Float, default=0.0)
    current_assets = db.Column(db.Float, default=0.0)
    liabilities = db.Column(db.Float, default=0.0)

    # Income Statement
    revenue = db.Column(db.Float, default=0.0)
    business_expenses = db.Column(db.Float, default=0.0)
    family_expenses = db.Column(db.Float, default=0.0)
    disposable_income = db.Column(db.Float, default=0.0)

    loan = db.relationship('Loan', backref=db.backref('financials', uselist=False))


class LoanInventoryItem(db.Model):
    __tablename__ = 'loan_inventory_items'
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loans.id'), nullable=False)

    item_name = db.Column(db.String(255))
    quantity = db.Column(db.Integer, default=0)
    unit_price = db.Column(db.Float, default=0.0)
    total_value = db.Column(db.Float, default=0.0)

    loan = db.relationship('Loan', backref=db.backref('inventory', lazy=True, cascade="all, delete-orphan"))


class LoanCashFlowMonth(db.Model):
    __tablename__ = 'loan_cash_flow_months'
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loans.id'), nullable=False)

    month_index = db.Column(db.Integer) # 1 to 6
    month_name = db.Column(db.String(50))
    cash_inflow = db.Column(db.Float, default=0.0)
    cash_outflow = db.Column(db.Float, default=0.0)
    net_cash = db.Column(db.Float, default=0.0)

    loan = db.relationship('Loan', backref=db.backref('cash_flow', lazy=True, cascade="all, delete-orphan"))


class LoanApprovalSignoff(db.Model):
    __tablename__ = 'loan_approval_signoffs'
    id = db.Column(db.Integer, primary_key=True)
    loan_id = db.Column(db.Integer, db.ForeignKey('loans.id'), nullable=False)

    recommending_officer_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    recommendation_date = db.Column(db.DateTime)
    recommendation_notes = db.Column(db.Text)

    approving_officer_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    approval_date = db.Column(db.DateTime)
    approval_notes = db.Column(db.Text)

    loan = db.relationship('Loan', backref=db.backref('signoff', uselist=False))
    
    recommending_officer = db.relationship('User', foreign_keys=[recommending_officer_id])
    approving_officer = db.relationship('User', foreign_keys=[approving_officer_id])
