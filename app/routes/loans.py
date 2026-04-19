from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.models.loan import Loan
from app.models.member import Member
from app.models.survey import SurveyResponse
from app.decorators import login_required, role_required
from app import db
from flask_login import current_user

loans_bp = Blueprint('loans', __name__, url_prefix='/loans')

@loans_bp.route('/')
@login_required
def index():
    # Show all loans; order by newest first
    loans = Loan.query.order_by(Loan.created_at.desc()).all()
    return render_template('loans/index.html', loans=loans)

@loans_bp.route('/<int:loan_id>')
@login_required
def view(loan_id):
    # Detailed view of a loan assessment
    loan = Loan.query.get_or_404(loan_id)
    return render_template('loans/view.html', loan=loan)

@loans_bp.route('/new/<int:member_id>', methods=['GET', 'POST'])
@login_required
def new(member_id):
    # Page to start a new loan assessment for a specific member
    member = Member.query.get_or_404(member_id)
    
    # Financial data variables to show on assess page
    total_income = 0
    total_expenses = 0
    
    # Pre-calculate financial data for the GET view too
    for r in member.survey_responses:
        if r.question.question_type == 'number':
            q_text = r.question.question_text.lower()
            try:
                val = float(r.answer)
                if any(k in q_text for k in ['income', 'sales', 'profit', 'earn']):
                    total_income += val
                elif any(k in q_text for k in ['expense', 'debt', 'cost', 'spend', 'liability']):
                    total_expenses += val
            except ValueError:
                continue

    if request.method == 'POST':
        amount_requested = request.form.get('amount_requested', type=float)
        notes = request.form.get('notes')
        
        # Base Score logic
        score = 50
        
        # Group reliability bonus
        if member.group_id:
            score += 10
            
        # Financial logic check
        net_income = total_income - total_expenses
        
        if total_income > 0:
            # Positive weight: +1 point per 500 KSh net positive, up to max 40 points
            if net_income > 0:
                score += min(40, int(net_income / 500))
            else:
                score -= 20 # penalties for operating at loss
        
        # Normalize score between 0 and 100
        score = max(0, min(100, score))
        
        loan = Loan(
            member_id=member.id,
            assessed_by=current_user.id,
            amount_requested=amount_requested,
            score=score,
            status='pending',
            notes=notes
        )
        db.session.add(loan)
        db.session.commit()
        
        flash('Loan assessment created successfully!', 'success')
        return redirect(url_for('loans.view', loan_id=loan.id))
        
    return render_template(
        'loans/assess.html', 
        member=member,
        total_income=total_income, 
        total_expenses=total_expenses
    )

@loans_bp.route('/<int:loan_id>/status', methods=['POST'])
@login_required
@role_required('admin')
def update_status(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    status = request.form.get('status')
    
    if status in ['approved', 'rejected', 'pending']:
        loan.status = status
        db.session.commit()
        flash(f'Loan assessment marked as {status.capitalize()}.', 'success')
    else:
        flash('Invalid status provided.', 'danger')
        
    return redirect(url_for('loans.view', loan_id=loan.id))
