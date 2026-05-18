from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.models.loan import (
    Loan, LoanAssessmentDetails, LoanFinancialSnapshot, 
    LoanInventoryItem, LoanCashFlowMonth, LoanApprovalSignoff
)
from app.models.member import Member
from app.loan_assessment_surveys import (
    CASH_FLOW_MONTH_COUNT,
    CHECKBOX_LOAN_ASSESSMENT_FIELDS,
    INVENTORY_ITEM_COUNT,
    LOAN_ASSESSMENT_FIELD_MAP,
    NUMERIC_LOAN_ASSESSMENT_FIELDS,
)
from app.decorators import admin_required
from app import db
from flask_login import current_user, login_required

loans_bp = Blueprint('loans', __name__, url_prefix='/loans')


def _to_float(value, default=0.0):
    try:
        return float(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return default


def _to_yes_no(value):
    cleaned = str(value).strip().lower()
    if cleaned.startswith(('1.', 'yes')):
        return True
    if cleaned in {'1', 'y', 'true', 'completed', 'complete'}:
        return True
    return False


def _blank_inventory_data():
    return [
        {'item_name': '', 'quantity': '', 'unit_price': ''}
        for _ in range(INVENTORY_ITEM_COUNT)
    ]


def _blank_cash_flow_data():
    return [
        {
            'month_index': month_index,
            'month_name': f'Month {month_index}',
            'cash_inflow': 0,
            'cash_outflow': 0,
        }
        for month_index in range(1, CASH_FLOW_MONTH_COUNT + 1)
    ]


def _collect_assessment_survey_data(member):
    survey_data = {
        'county': '',
        'sub_county': '',
        'ward': '',
        'male_participants': 0,
        'female_participants': 0,
        'business_location': '',
        'nature_of_business': '',
        'registration_number': '',
        'training_completion': False,
        'fixed_assets': 0,
        'current_assets': 0,
        'liabilities': 0,
        'revenue': 0,
        'business_expenses': 0,
        'family_expenses': 0,
        'disposable_income': 0,
        'amount_requested': '',
        'loan_term_months': 6,
        'monthly_instalment': 0,
        'loan_purpose': '',
        'notes': '',
    }
    survey_inventory = _blank_inventory_data()
    survey_cash_flow = _blank_cash_flow_data()

    total_income = 0
    total_expenses = 0
    exact_revenue_found = False
    exact_expenses_found = False

    responses = sorted(
        member.survey_responses,
        key=lambda response: response.submitted_at,
    )

    for response in responses:
        question_text = response.question.question_text.strip()
        question_key = question_text.casefold()
        answer = response.answer.strip()
        mapped_field = LOAN_ASSESSMENT_FIELD_MAP.get(question_key)

        if mapped_field:
            if mapped_field.startswith('inventory_'):
                _, item_index_raw, field_name = mapped_field.split('_', 2)
                item_index = int(item_index_raw) - 1
                if 0 <= item_index < len(survey_inventory):
                    survey_inventory[item_index][field_name] = (
                        _to_float(answer) if mapped_field in NUMERIC_LOAN_ASSESSMENT_FIELDS else answer
                    )
                continue

            if mapped_field.startswith('cash_flow_'):
                _, _, month_index_raw, field_name = mapped_field.split('_', 3)
                month_index = int(month_index_raw) - 1
                if 0 <= month_index < len(survey_cash_flow):
                    survey_cash_flow[month_index][field_name] = (
                        _to_float(answer) if mapped_field in NUMERIC_LOAN_ASSESSMENT_FIELDS else answer
                    )
                continue

            if mapped_field in CHECKBOX_LOAN_ASSESSMENT_FIELDS:
                survey_data[mapped_field] = _to_yes_no(answer)
            elif mapped_field in NUMERIC_LOAN_ASSESSMENT_FIELDS:
                survey_data[mapped_field] = _to_float(answer)
            else:
                survey_data[mapped_field] = answer

            exact_revenue_found = exact_revenue_found or mapped_field == 'revenue'
            exact_expenses_found = exact_expenses_found or mapped_field == 'business_expenses'
            continue

        # Backward compatibility for older surveys created before default templates.
        q_text = question_key
        if response.question.question_type == 'number':
            value = _to_float(answer)
            if any(keyword in q_text for keyword in ['income', 'sales', 'profit', 'earn', 'revenue']):
                total_income += value
            elif any(keyword in q_text for keyword in ['expense', 'debt', 'cost', 'spend', 'liability']):
                total_expenses += value

        if 'county' in q_text and 'sub' not in q_text and not survey_data['county']:
            survey_data['county'] = answer
        elif 'sub' in q_text and 'county' in q_text and not survey_data['sub_county']:
            survey_data['sub_county'] = answer
        elif 'ward' in q_text and not survey_data['ward']:
            survey_data['ward'] = answer
        elif ('location' in q_text or 'where' in q_text) and not survey_data['business_location']:
            survey_data['business_location'] = answer
        elif (
            'nature' in q_text
            or 'type of business' in q_text
            or 'what business' in q_text
        ) and not survey_data['nature_of_business']:
            survey_data['nature_of_business'] = answer
        elif ('purpose' in q_text or 'why' in q_text) and not survey_data['loan_purpose']:
            survey_data['loan_purpose'] = answer

    if not exact_revenue_found:
        survey_data['revenue'] = total_income
    if not exact_expenses_found:
        survey_data['business_expenses'] = total_expenses
    if not survey_data['disposable_income']:
        survey_data['disposable_income'] = (
            survey_data['revenue']
            - survey_data['business_expenses']
            - survey_data['family_expenses']
        )

    return survey_data, survey_inventory, survey_cash_flow

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
    survey_data, survey_inventory, survey_cash_flow = _collect_assessment_survey_data(member)

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
        survey_data=survey_data,
        survey_inventory=survey_inventory,
        survey_cash_flow=survey_cash_flow,
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
