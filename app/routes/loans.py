from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.models.loan import (
    Loan, LoanAssessmentDetails, LoanFinancialSnapshot, 
    LoanInventoryItem, LoanCashFlowMonth, LoanApprovalSignoff
)
from app.models.member import Member
from app.models.survey import SurveyResponse
from app.decorators import admin_required
from app import db
from flask_login import current_user, login_required

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
    survey_data = {
        'county': '',
        'sub_county': '',
        'ward': '',
        'business_location': '',
        'nature_of_business': '',
        'loan_purpose': ''
    }
    
    # Pre-calculate financial data for the GET view too
    for r in member.survey_responses:
        q_text = r.question.question_text.lower()
        val_str = r.answer

        if r.question.question_type == 'number':
            try:
                val = float(val_str)
                if any(k in q_text for k in ['income', 'sales', 'profit', 'earn', 'revenue']):
                    total_income += val
                elif any(k in q_text for k in ['expense', 'debt', 'cost', 'spend', 'liability']):
                    total_expenses += val
            except ValueError:
                pass

        if 'county' in q_text and 'sub' not in q_text:
            survey_data['county'] = val_str
        elif 'sub' in q_text and 'county' in q_text:
            survey_data['sub_county'] = val_str
        elif 'ward' in q_text:
            survey_data['ward'] = val_str
        elif 'location' in q_text or 'where' in q_text:
            survey_data['business_location'] = val_str
        elif 'nature' in q_text or 'type of business' in q_text or 'what business' in q_text:
            survey_data['nature_of_business'] = val_str
        elif 'purpose' in q_text or 'why' in q_text:
            survey_data['loan_purpose'] = val_str

    if request.method == 'POST':
        amount_requested = request.form.get('amount_requested', type=float) or 0.0
        
        if amount_requested <= 0:
            flash('Amount requested must be greater than zero.', 'danger')
            return redirect(url_for('loans.new', member_id=member.id))
            
        notes = request.form.get('notes', '')
        
        # New Detailed Assessment Fields
        disposable_income = request.form.get('disposable_income', type=float) or 0.0
        existing_debts = request.form.get('liabilities', type=float) or 0.0
        monthly_instalment = request.form.get('monthly_instalment', type=float) or 0.0
        business_assets = request.form.get('current_assets', type=float) or 0.0
        training_completion = request.form.get('training_completion') == 'on'
        
        # Base Score logic based on actual assessment fields
        score = 30
        
        # Group reliability bonus
        if member.group_id:
            score += 15
            
        # Training completion bonus
        if training_completion:
            score += 10
            
        # Financial logic check
        if disposable_income > monthly_instalment * 1.5:
            score += 20 # Comfortable affordability
        elif disposable_income > monthly_instalment:
            score += 10 # Basic affordability
        else:
            score -= 10 # High risk

        if business_assets > amount_requested:
            score += 15 # Good collateral/assets
            
        if existing_debts < disposable_income:
            score += 10
        else:
            score -= 10
        
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
        db.session.flush() # Get loan ID

        # Save Assessment Details
        details = LoanAssessmentDetails(
            loan_id=loan.id,
            county=request.form.get('county', ''),
            sub_county=request.form.get('sub_county', ''),
            ward=request.form.get('ward', ''),
            group_name=request.form.get('group_name', ''),
            business_location=request.form.get('business_location', ''),
            nature_of_business=request.form.get('nature_of_business', ''),
            registration_number=request.form.get('registration_number', ''),
            male_participants=request.form.get('male_participants', type=int) or 0,
            female_participants=request.form.get('female_participants', type=int) or 0,
            loan_term_months=request.form.get('loan_term_months', type=int) or 0,
            monthly_instalment=monthly_instalment,
            loan_purpose=request.form.get('loan_purpose', '')
        )
        db.session.add(details)

        # Save Financial Snapshot
        financials = LoanFinancialSnapshot(
            loan_id=loan.id,
            fixed_assets=request.form.get('fixed_assets', type=float) or 0.0,
            current_assets=business_assets,
            liabilities=existing_debts,
            revenue=request.form.get('revenue', type=float) or 0.0,
            business_expenses=request.form.get('business_expenses', type=float) or 0.0,
            family_expenses=request.form.get('family_expenses', type=float) or 0.0,
            disposable_income=disposable_income
        )
        db.session.add(financials)

        # Process Inventory Items
        item_names = request.form.getlist('item_name[]')
        quantities = request.form.getlist('quantity[]')
        unit_prices = request.form.getlist('unit_price[]')
        
        for i in range(len(item_names)):
            if item_names[i].strip():
                qty = int(quantities[i]) if i < len(quantities) and quantities[i] else 0
                price = float(unit_prices[i]) if i < len(unit_prices) and unit_prices[i] else 0.0
                inv = LoanInventoryItem(
                    loan_id=loan.id,
                    item_name=item_names[i],
                    quantity=qty,
                    unit_price=price,
                    total_value=qty * price
                )
                db.session.add(inv)

        # Process Cash Flow
        for m in range(1, 7):
            inflow = request.form.get(f'cash_inflow_{m}', type=float) or 0.0
            outflow = request.form.get(f'cash_outflow_{m}', type=float) or 0.0
            cf = LoanCashFlowMonth(
                loan_id=loan.id,
                month_index=m,
                month_name=request.form.get(f'month_name_{m}', f'Month {m}'),
                cash_inflow=inflow,
                cash_outflow=outflow,
                net_cash=inflow - outflow
            )
            db.session.add(cf)

        db.session.commit()
        
        flash('Loan assessment created successfully!', 'success')
        return redirect(url_for('loans.view', loan_id=loan.id))
        
    return render_template(
        'loans/assess.html', 
        member=member,
        total_income=total_income, 
        total_expenses=total_expenses,
        survey_data=survey_data
    )


def delete_loan_record(loan):
    LoanApprovalSignoff.query.filter_by(loan_id=loan.id).delete()
    LoanCashFlowMonth.query.filter_by(loan_id=loan.id).delete()
    LoanInventoryItem.query.filter_by(loan_id=loan.id).delete()
    LoanFinancialSnapshot.query.filter_by(loan_id=loan.id).delete()
    LoanAssessmentDetails.query.filter_by(loan_id=loan.id).delete()
    db.session.delete(loan)


@loans_bp.route('/<int:loan_id>/status', methods=['POST'])
@login_required
@admin_required
def update_status(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    status = request.form.get('status')
    
    if status in ['approved', 'rejected', 'pending']:
        loan.status = status
        
        # Save Signoff Details
        if status == 'approved':
            signoff = LoanApprovalSignoff.query.filter_by(loan_id=loan.id).first()
            if not signoff:
                signoff = LoanApprovalSignoff(loan_id=loan.id)
                db.session.add(signoff)
            signoff.approving_officer_id = current_user.id
            from datetime import datetime
            signoff.approval_date = datetime.utcnow()
            signoff.approval_notes = request.form.get('approval_notes', '')

        db.session.commit()
        flash(f'Loan assessment marked as {status.capitalize()}.', 'success')
    else:
        flash('Invalid status provided.', 'danger')
        
    return redirect(url_for('loans.view', loan_id=loan.id))


@loans_bp.route('/<int:loan_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    delete_loan_record(loan)
    db.session.commit()
    flash('Loan assessment deleted successfully.', 'success')
    return redirect(url_for('loans.index'))
