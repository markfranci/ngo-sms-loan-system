from app import create_app, db
from app.models.member import Member
from app.models.sms_log import SMSLog
from app.models.survey import SurveyResponse
from app.models.loan import (
    Loan, LoanAssessmentDetails, LoanFinancialSnapshot, 
    LoanInventoryItem, LoanCashFlowMonth, LoanApprovalSignoff,
    LoanDisbursement, LoanRepayment
)

app = create_app()

with app.app_context():
    try:
        # Delete in order of dependencies to avoid foreign key constraints
        db.session.query(LoanApprovalSignoff).delete()
        db.session.query(LoanRepayment).delete()
        db.session.query(LoanDisbursement).delete()
        db.session.query(LoanCashFlowMonth).delete()
        db.session.query(LoanInventoryItem).delete()
        db.session.query(LoanFinancialSnapshot).delete()
        db.session.query(LoanAssessmentDetails).delete()
        db.session.query(Loan).delete()
        
        db.session.query(SurveyResponse).delete()
        db.session.query(SMSLog).delete()
        db.session.query(Member).delete()
        
        db.session.commit()
        print("✅ Clean Slate: Successfully deleted all Members, Loans, SMS Logs, and Survey Responses.")
        print("Note: Admin Users, Groups, and Survey Templates were kept intact.")
    except Exception as e:
        db.session.rollback()
        print(f"Error clearing data: {e}")
