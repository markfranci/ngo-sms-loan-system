import os
import uuid
from datetime import datetime
from html import escape

from flask import Blueprint, current_app, render_template, request, redirect, send_from_directory, url_for, flash
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename

from app.models.loan import (
    Loan, LoanAssessmentDetails, LoanFinancialSnapshot, 
    LoanInventoryItem, LoanCashFlowMonth, LoanApprovalSignoff, LoanDisbursement, LoanDocument, LoanRepayment
)
from app.models.member import Member
from app.loan_assessment_surveys import (
    CASH_FLOW_MONTH_COUNT,
    INVENTORY_ITEM_COUNT,
)
from app.kenya_locations import KENYA_COUNTIES_SUBCOUNTIES
from app.decorators import admin_required
from app import db
from app.pdf_utils import (
    BRAND_DARK,
    BRAND_LINE,
    BRAND_MUTED,
    BRAND_SOFT,
    BRAND_TEXT,
    build_pdf_response,
    key_value_table,
    modern_table,
    pdf_styles,
)
from flask_login import current_user, login_required
from app.whatsapp_service import WhatsAppNotConfiguredError, send_whatsapp_message

loans_bp = Blueprint('loans', __name__, url_prefix='/loans')

ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}
REQUIRED_DOCUMENTS = {
    'national_id': 'National ID Copy',
    'business_verification': 'Business Verification Document',
    'group_confirmation': 'Group or Guarantor Confirmation',
    'balance_sheet': 'Balance Sheet',
    'profit_and_loss': 'Profit and Loss Statement',
    'cash_flow_statement': 'Cash Flow Statement',
}

DISBURSEMENT_METHODS = [
    'Bank transfer',
    'M-Pesa',
    'Cheque',
    'Cash',
    'Mobile money',
]


def _allowed_document(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_DOCUMENT_EXTENSIONS


def _loan_document_dir():
    path = os.path.join(current_app.config['UPLOAD_FOLDER'], 'loan_documents')
    os.makedirs(path, exist_ok=True)
    return path


def _save_loan_documents(loan, files_by_type):
    for document_type, file in files_by_type.items():
        extension = secure_filename(file.filename).rsplit('.', 1)[1].lower()
        stored_filename = f'loan-{loan.id}-{document_type}-{uuid.uuid4().hex}.{extension}'
        file.save(os.path.join(_loan_document_dir(), stored_filename))
        db.session.add(LoanDocument(
            loan_id=loan.id,
            uploaded_by=current_user.id,
            document_type=document_type,
            original_filename=secure_filename(file.filename),
            stored_filename=stored_filename,
        ))


def _validate_required_documents(files):
    valid_files = {}
    for document_type, label in REQUIRED_DOCUMENTS.items():
        file = files.get(document_type)
        if not file or not file.filename:
            return None, f'{label} is required.'
        if not _allowed_document(file.filename):
            return None, f'{label} must be a PDF, PNG, JPG, or JPEG file.'
        valid_files[document_type] = file
    return valid_files, None


def _notify_loan_decision(loan):
    if loan.status == 'approved':
        message = (
            f"Hello {loan.member.full_name}, your loan application for "
            f"KSh {loan.amount_requested:,.2f} has been approved."
        )
    elif loan.status == 'rejected':
        message = (
            f"Hello {loan.member.full_name}, your loan application for "
            f"KSh {loan.amount_requested:,.2f} was not approved at this time."
        )
    else:
        return

    send_whatsapp_message(loan.member, message)


def _notify_loan_disbursement(loan, disbursement):
    message = (
        f"Hello {loan.member.full_name}, your approved loan has been disbursed. "
        f"Amount: KSh {disbursement.amount:,.2f}. Reference: {disbursement.reference}."
    )
    send_whatsapp_message(loan.member, message)


def _build_pdf_response(filename, title, story):
    return build_pdf_response(filename, title, story, pagesize=A4)


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


def _blank_assessment_data():
    return {
        'county': '',
        'sub_county': '',
        'ward': '',
        'is_in_sme_group': False,
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


def _group_participant_counts(group):
    male_count = 0
    female_count = 0
    for group_member in group.members:
        gender = (group_member.gender or '').strip().lower()
        if gender == 'male':
            male_count += 1
        elif gender == 'female':
            female_count += 1
    return male_count, female_count


REQUIRED_ASSESSMENT_FIELDS = {
    'county': 'County',
    'sub_county': 'Sub-County',
    'ward': 'Ward',
    'business_location': 'Business Location',
    'nature_of_business': 'Nature of Business',
    'fixed_assets': 'Fixed Assets',
    'current_assets': 'Current Assets / Business Assets',
    'liabilities': 'Existing Debts / Liabilities',
    'revenue': 'Estimated Monthly Revenue / Sales',
    'business_expenses': 'Monthly Business Expenses',
    'family_expenses': 'Monthly Family / Household Expenses',
    'disposable_income': 'Net Profit / Disposable Income',
    'amount_requested': 'Loan Amount Requested',
    'loan_term_months': 'Loan Term',
    'monthly_instalment': 'Proposed Monthly Instalment',
    'loan_purpose': 'Loan Purpose',
    'notes': 'Assessment Notes',
}


def _missing_required_assessment_fields(form):
    return [
        label
        for field_name, label in REQUIRED_ASSESSMENT_FIELDS.items()
        if not str(form.get(field_name, '')).strip()
    ]


def _validate_county_sub_county(form):
    county = str(form.get('county', '')).strip()
    sub_county = str(form.get('sub_county', '')).strip()
    if county not in KENYA_COUNTIES_SUBCOUNTIES:
        return None, None, 'Please select a valid Kenyan county.'
    if sub_county not in KENYA_COUNTIES_SUBCOUNTIES[county]:
        return None, None, 'Please select a valid sub-county for the selected county.'
    return county, sub_county, None


def _parse_required_float(form, field_name, label, minimum=0):
    raw_value = str(form.get(field_name, '')).strip().replace(',', '')
    try:
        value = float(raw_value)
    except ValueError:
        return None, f'{label} must be a valid number.'
    if value < minimum:
        return None, f'{label} must be at least {minimum}.'
    return value, None


def _parse_required_int(form, field_name, label, minimum=0):
    raw_value = str(form.get(field_name, '')).strip()
    try:
        value = int(raw_value)
    except ValueError:
        return None, f'{label} must be a valid whole number.'
    if value < minimum:
        return None, f'{label} must be at least {minimum}.'
    return value, None


def _parse_optional_float(form, field_name, label, minimum=0):
    raw_value = str(form.get(field_name, '')).strip().replace(',', '')
    if raw_value == '':
        return 0.0, None
    try:
        value = float(raw_value)
    except ValueError:
        return None, f'{label} must be a valid number.'
    if value < minimum:
        return None, f'{label} must be at least {minimum}.'
    return value, None

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
    signoff = LoanApprovalSignoff.query.filter_by(loan_id=loan.id).first()
    disbursement_min_date = signoff.approval_date if signoff and signoff.approval_date else loan.created_at
    confirmed_disbursement_dates = [
        disbursement.disbursement_date
        for disbursement in loan.confirmed_disbursements
        if disbursement.disbursement_date
    ]
    repayment_min_date = max(confirmed_disbursement_dates) if confirmed_disbursement_dates else None
    return render_template(
        'loans/view.html',
        loan=loan,
        now=datetime.utcnow(),
        disbursement_methods=DISBURSEMENT_METHODS,
        disbursement_min_date=disbursement_min_date,
        repayment_min_date=repayment_min_date,
    )

@loans_bp.route('/new/<int:member_id>', methods=['GET', 'POST'])
@login_required
def new(member_id):
    # Page to start a new loan assessment for a specific member
    member = Member.query.get_or_404(member_id)
    if not member.group_id or not member.group:
        flash('Member must be assigned to an SME group before a loan assessment can be created.', 'danger')
        return redirect(url_for('members.profile', member_id=member.id))

    assessment_data = _blank_assessment_data()
    assessment_inventory = _blank_inventory_data()
    assessment_cash_flow = _blank_cash_flow_data()
    male_participants, female_participants = _group_participant_counts(member.group)
    assessment_data.update({
        'is_in_sme_group': True,
        'male_participants': male_participants,
        'female_participants': female_participants,
    })

    if request.method == 'POST':
        valid_documents, document_error = _validate_required_documents(request.files)
        if document_error:
            flash(document_error, 'danger')
            return redirect(url_for('loans.new', member_id=member.id))

        missing_fields = _missing_required_assessment_fields(request.form)
        if missing_fields:
            flash(f'Please complete required assessment fields: {", ".join(missing_fields)}.', 'danger')
            return redirect(url_for('loans.new', member_id=member.id))

        county, sub_county, location_error = _validate_county_sub_county(request.form)
        if location_error:
            flash(location_error, 'danger')
            return redirect(url_for('loans.new', member_id=member.id))

        amount_requested, number_error = _parse_required_float(request.form, 'amount_requested', 'Amount requested', 1)
        if number_error:
            flash(number_error, 'danger')
            return redirect(url_for('loans.new', member_id=member.id))

        loan_term_months, number_error = _parse_required_int(request.form, 'loan_term_months', 'Loan term', 1)
        if number_error:
            flash(number_error, 'danger')
            return redirect(url_for('loans.new', member_id=member.id))

        monthly_instalment, number_error = _parse_required_float(request.form, 'monthly_instalment', 'Proposed monthly instalment', 1)
        if number_error:
            flash(number_error, 'danger')
            return redirect(url_for('loans.new', member_id=member.id))
            
        notes = request.form.get('notes', '')
        
        disposable_income, number_error = _parse_required_float(request.form, 'disposable_income', 'Disposable income', 0)
        if number_error:
            flash(number_error, 'danger')
            return redirect(url_for('loans.new', member_id=member.id))

        existing_debts, number_error = _parse_required_float(request.form, 'liabilities', 'Existing debts', 0)
        if number_error:
            flash(number_error, 'danger')
            return redirect(url_for('loans.new', member_id=member.id))

        business_assets, number_error = _parse_required_float(request.form, 'current_assets', 'Current assets', 0)
        if number_error:
            flash(number_error, 'danger')
            return redirect(url_for('loans.new', member_id=member.id))

        fixed_assets, number_error = _parse_required_float(request.form, 'fixed_assets', 'Fixed assets', 0)
        if number_error:
            flash(number_error, 'danger')
            return redirect(url_for('loans.new', member_id=member.id))

        revenue, number_error = _parse_required_float(request.form, 'revenue', 'Revenue', 0)
        if number_error:
            flash(number_error, 'danger')
            return redirect(url_for('loans.new', member_id=member.id))

        business_expenses, number_error = _parse_required_float(request.form, 'business_expenses', 'Business expenses', 0)
        if number_error:
            flash(number_error, 'danger')
            return redirect(url_for('loans.new', member_id=member.id))

        family_expenses, number_error = _parse_required_float(request.form, 'family_expenses', 'Family expenses', 0)
        if number_error:
            flash(number_error, 'danger')
            return redirect(url_for('loans.new', member_id=member.id))
        
        loan = Loan(
            member_id=member.id,
            assessed_by=current_user.id,
            amount_requested=amount_requested,
            status='submitted',
            notes=notes
        )
        db.session.add(loan)
        db.session.flush() # Get loan ID

        # Save Assessment Details
        details = LoanAssessmentDetails(
            loan_id=loan.id,
            county=county,
            sub_county=sub_county,
            ward=request.form.get('ward', ''),
            group_name=member.group.name,
            business_location=request.form.get('business_location', ''),
            nature_of_business=request.form.get('nature_of_business', ''),
            registration_number=request.form.get('registration_number', ''),
            male_participants=male_participants,
            female_participants=female_participants,
            loan_term_months=loan_term_months,
            monthly_instalment=monthly_instalment,
            loan_purpose=request.form.get('loan_purpose', '')
        )
        db.session.add(details)

        # Save Financial Snapshot
        financials = LoanFinancialSnapshot(
            loan_id=loan.id,
            fixed_assets=fixed_assets,
            current_assets=business_assets,
            liabilities=existing_debts,
            revenue=revenue,
            business_expenses=business_expenses,
            family_expenses=family_expenses,
            disposable_income=disposable_income
        )
        db.session.add(financials)

        # Process Inventory Items
        item_names = request.form.getlist('item_name[]')
        quantities = request.form.getlist('quantity[]')
        unit_prices = request.form.getlist('unit_price[]')
        
        for i in range(len(item_names)):
            if item_names[i].strip():
                try:
                    qty = int(quantities[i]) if i < len(quantities) and quantities[i] else 0
                    price = float(unit_prices[i]) if i < len(unit_prices) and unit_prices[i] else 0.0
                except ValueError:
                    flash('Inventory quantities and unit prices must be valid numbers.', 'danger')
                    return redirect(url_for('loans.new', member_id=member.id))
                if qty < 0 or price < 0:
                    flash('Inventory quantities and unit prices cannot be negative.', 'danger')
                    return redirect(url_for('loans.new', member_id=member.id))
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
            inflow, number_error = _parse_optional_float(request.form, f'cash_inflow_{m}', f'Month {m} cash inflow', 0)
            if number_error:
                flash(number_error, 'danger')
                return redirect(url_for('loans.new', member_id=member.id))
            outflow, number_error = _parse_optional_float(request.form, f'cash_outflow_{m}', f'Month {m} cash outflow', 0)
            if number_error:
                flash(number_error, 'danger')
                return redirect(url_for('loans.new', member_id=member.id))
            cf = LoanCashFlowMonth(
                loan_id=loan.id,
                month_index=m,
                month_name=request.form.get(f'month_name_{m}', f'Month {m}'),
                cash_inflow=inflow,
                cash_outflow=outflow,
                net_cash=inflow - outflow
            )
            db.session.add(cf)

        _save_loan_documents(loan, valid_documents)
        db.session.commit()
        
        flash('Loan assessment submitted successfully for admin approval.', 'success')
        return redirect(url_for('loans.view', loan_id=loan.id))
        
    return render_template(
        'loans/assess.html', 
        member=member,
        assessment_data=assessment_data,
        assessment_inventory=assessment_inventory,
        assessment_cash_flow=assessment_cash_flow,
        kenya_locations=KENYA_COUNTIES_SUBCOUNTIES,
    )


def delete_loan_record(loan):
    LoanApprovalSignoff.query.filter_by(loan_id=loan.id).delete()
    LoanRepayment.query.filter_by(loan_id=loan.id).delete()
    LoanDisbursement.query.filter_by(loan_id=loan.id).delete()
    for document in LoanDocument.query.filter_by(loan_id=loan.id).all():
        try:
            os.remove(os.path.join(_loan_document_dir(), document.stored_filename))
        except OSError:
            pass
        db.session.delete(document)
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
    
    if loan.status not in ['submitted', 'pending'] and status in ['approved', 'rejected']:
        flash('Only submitted assessments can be approved or rejected.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    if status in ['approved', 'rejected']:
        if not loan.documents:
            flash('Verification documents are required before making a decision.', 'danger')
            return redirect(url_for('loans.view', loan_id=loan.id))

        decision_notes = request.form.get('approval_notes', '').strip()
        if not decision_notes:
            flash('Decision notes are required before confirming approval or rejection.', 'danger')
            return redirect(url_for('loans.view', loan_id=loan.id))

        loan.status = status
        
        signoff = LoanApprovalSignoff.query.filter_by(loan_id=loan.id).first()
        if not signoff:
            signoff = LoanApprovalSignoff(loan_id=loan.id)
            db.session.add(signoff)
        if status == 'approved':
            signoff.approving_officer_id = current_user.id
            signoff.approval_date = datetime.utcnow()
            signoff.approval_notes = decision_notes
        else:
            signoff.approving_officer_id = current_user.id
            signoff.approval_date = datetime.utcnow()
            signoff.approval_notes = decision_notes

        notification_sent = False
        notification_error = None
        try:
            _notify_loan_decision(loan)
            notification_sent = True
        except WhatsAppNotConfiguredError as error:
            notification_error = str(error)
        except Exception as error:
            notification_error = str(error)

        db.session.commit()
        if notification_sent:
            flash(f'Loan assessment marked as {status.capitalize()} and member notified on WhatsApp.', 'success')
        else:
            flash(
                f'Loan assessment marked as {status.capitalize()}, but WhatsApp notification failed: {notification_error}',
                'warning',
            )
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


@loans_bp.route('/documents/<int:document_id>/download')
@login_required
def download_document(document_id):
    document = LoanDocument.query.get_or_404(document_id)
    return send_from_directory(
        _loan_document_dir(),
        document.stored_filename,
        as_attachment=True,
        download_name=document.original_filename,
    )


@loans_bp.route('/documents/<int:document_id>/view')
@login_required
def view_document(document_id):
    document = LoanDocument.query.get_or_404(document_id)
    return send_from_directory(
        _loan_document_dir(),
        document.stored_filename,
        as_attachment=False,
        download_name=document.original_filename,
    )


@loans_bp.route('/<int:loan_id>/repayments', methods=['POST'])
@login_required
def post_repayment(loan_id):
    loan = Loan.query.get_or_404(loan_id)

    if loan.status != 'disbursed':
        flash('Repayments can only be posted after the loan has been disbursed.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    amount, amount_error = _parse_required_float(request.form, 'amount', 'Repayment amount', 1)
    if amount_error:
        flash(amount_error, 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    payment_date_text = request.form.get('payment_date', '').strip()
    reference = request.form.get('reference', '').strip()
    notes = request.form.get('notes', '').strip()

    if not reference:
        flash('Payment reference is required.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    if amount > loan.outstanding_balance:
        flash('Repayment amount cannot exceed the outstanding balance.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    if len(reference) > 120:
        flash('Payment reference is too long.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    if len(notes) > 1000:
        flash('Repayment notes are too long.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    try:
        payment_date = datetime.strptime(payment_date_text, '%Y-%m-%d') if payment_date_text else datetime.utcnow()
    except ValueError:
        flash('Payment date must use YYYY-MM-DD format.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    latest_disbursement_date = max(
        (
            disbursement.disbursement_date
            for disbursement in loan.confirmed_disbursements
            if disbursement.disbursement_date
        ),
        default=None,
    )
    if latest_disbursement_date and payment_date.date() < latest_disbursement_date.date():
        flash('Payment date cannot be before the confirmed disbursement date.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    if payment_date.date() > datetime.utcnow().date():
        flash('Payment date cannot be in the future.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    db.session.add(LoanRepayment(
        loan_id=loan.id,
        posted_by=current_user.id,
        amount=amount,
        payment_date=payment_date,
        reference=reference,
        notes=notes,
    ))
    db.session.commit()

    flash('Repayment posted successfully.', 'success')
    return redirect(url_for('loans.view', loan_id=loan.id))


@loans_bp.route('/<int:loan_id>/disbursement/initiate', methods=['POST'])
@login_required
def initiate_disbursement(loan_id):
    loan = Loan.query.get_or_404(loan_id)

    if loan.status != 'approved':
        flash('Only approved loans can be prepared for disbursement.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    pending_disbursement = LoanDisbursement.query.filter_by(
        loan_id=loan.id,
        status='pending',
    ).first()
    if pending_disbursement:
        flash('This loan already has a pending disbursement waiting for admin confirmation.', 'warning')
        return redirect(url_for('loans.view', loan_id=loan.id))

    amount, amount_error = _parse_required_float(request.form, 'amount', 'Disbursement amount', 1)
    if amount_error:
        flash(amount_error, 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    disbursement_date_text = request.form.get('disbursement_date', '').strip()
    reference = request.form.get('reference', '').strip()
    method = request.form.get('method', '').strip()
    notes = request.form.get('notes', '').strip()

    if amount > (loan.amount_requested or 0):
        flash('Disbursement amount cannot exceed the approved loan amount.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    if not reference:
        flash('Disbursement reference is required.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    if len(reference) > 120:
        flash('Disbursement reference is too long.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    if len(method) > 80:
        flash('Disbursement method is too long.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    if method and method not in DISBURSEMENT_METHODS:
        flash('Please select a valid disbursement method.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    if len(notes) > 1000:
        flash('Disbursement notes are too long.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    try:
        disbursement_date = datetime.strptime(disbursement_date_text, '%Y-%m-%d')
    except ValueError:
        flash('Disbursement date is required and must use YYYY-MM-DD format.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    signoff = LoanApprovalSignoff.query.filter_by(loan_id=loan.id).first()
    earliest_disbursement_date = signoff.approval_date if signoff and signoff.approval_date else loan.created_at
    if earliest_disbursement_date and disbursement_date.date() < earliest_disbursement_date.date():
        flash('Disbursement date cannot be before the loan approval date.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    if disbursement_date.date() > datetime.utcnow().date():
        flash('Disbursement date cannot be in the future.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    try:
        db.session.add(LoanDisbursement(
            loan_id=loan.id,
            initiated_by=current_user.id,
            amount=amount,
            disbursement_date=disbursement_date,
            reference=reference,
            method=method,
            notes=notes,
            status='pending',
        ))
        loan.status = 'disbursement_pending'
        db.session.commit()
    except SQLAlchemyError as error:
        db.session.rollback()
        current_app.logger.exception('Failed to submit loan disbursement %s', loan.id)
        flash(f'Could not submit disbursement for admin confirmation: {error.__class__.__name__}.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    flash('Disbursement prepared and submitted for admin confirmation.', 'success')
    return redirect(url_for('loans.view', loan_id=loan.id))


@loans_bp.route('/<int:loan_id>/disbursement/confirm', methods=['POST'])
@login_required
@admin_required
def confirm_disbursement(loan_id):
    loan = Loan.query.get_or_404(loan_id)

    if loan.status != 'disbursement_pending':
        flash('Only loans with disbursement in progress can be confirmed.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    disbursement = LoanDisbursement.query.filter_by(
        loan_id=loan.id,
        status='pending',
    ).order_by(LoanDisbursement.created_at.desc()).first()

    if not disbursement:
        flash('No pending disbursement record was found.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    disbursement.status = 'confirmed'
    disbursement.confirmed_by = current_user.id
    disbursement.confirmed_at = datetime.utcnow()
    loan.status = 'disbursed'

    notification_sent = False
    notification_error = None
    try:
        _notify_loan_disbursement(loan, disbursement)
        notification_sent = True
    except WhatsAppNotConfiguredError as error:
        notification_error = str(error)
    except Exception as error:
        notification_error = str(error)

    db.session.commit()
    if notification_sent:
        flash('Disbursement confirmed and member notified on WhatsApp.', 'success')
    else:
        flash(f'Disbursement confirmed, but WhatsApp notification failed: {notification_error}', 'warning')
    return redirect(url_for('loans.view', loan_id=loan.id))


@loans_bp.route('/<int:loan_id>/statement.pdf')
@login_required
def loan_statement(loan_id):
    loan = Loan.query.get_or_404(loan_id)
    styles = pdf_styles()
    rows = [['Date', 'Transaction', 'Reference', 'Method', 'Debit', 'Credit', 'Balance', 'Processed By', 'Notes']]
    transactions = []
    for disbursement in loan.confirmed_disbursements:
        transactions.append({
            'date': disbursement.disbursement_date,
            'type': 'Disbursement',
            'reference': disbursement.reference,
            'method': disbursement.method or '',
            'debit': disbursement.amount or 0,
            'credit': 0,
            'processed_by': (
                disbursement.confirmer.username
                if disbursement.confirmer
                else disbursement.initiator.username if disbursement.initiator else 'System'
            ),
            'notes': disbursement.notes or disbursement.method or '',
        })
    for repayment in loan.repayments:
        transactions.append({
            'date': repayment.payment_date,
            'type': 'Repayment',
            'reference': repayment.reference or '',
            'method': '',
            'debit': 0,
            'credit': repayment.amount or 0,
            'processed_by': repayment.poster.username if repayment.poster else 'System',
            'notes': repayment.notes or '',
        })
    balance = 0
    for transaction in sorted(transactions, key=lambda item: item['date'] or datetime.utcnow()):
        balance += transaction['debit']
        balance -= transaction['credit']
        rows.append([
            transaction['date'].strftime('%Y-%m-%d') if transaction['date'] else '',
            transaction['type'],
            transaction['reference'],
            transaction['method'],
            f"KSh {transaction['debit']:,.2f}" if transaction['debit'] else '',
            f"KSh {transaction['credit']:,.2f}" if transaction['credit'] else '',
            f"KSh {balance:,.2f}",
            transaction['processed_by'],
            transaction['notes'],
        ])
    rows.extend([
        ['', '', '', '', '', '', '', '', ''],
        ['Approved Amount', '', '', '', f"KSh {loan.amount_requested:,.2f}", '', '', '', ''],
        ['Total Disbursed', '', '', '', f"KSh {loan.total_disbursed:,.2f}", '', '', '', ''],
        ['Total Repaid', '', '', '', '', f"KSh {loan.total_repaid:,.2f}", '', '', ''],
        ['Outstanding', '', '', '', '', '', f"KSh {loan.outstanding_balance:,.2f}", '', ''],
    ])

    table = modern_table(rows, font_size=7, header_font_size=7)
    table.setStyle(TableStyle([
        ('ALIGN', (4, 1), (6, -1), 'RIGHT'),
        ('FONTNAME', (0, -4), (-1, -1), 'Helvetica-Bold'),
        ('BACKGROUND', (0, -4), (-1, -1), colors.HexColor('#FAFAFA')),
    ]))
    story = [
        key_value_table([
            ('Member', loan.member.full_name),
            ('Phone', loan.member.phone_number),
            ('Loan ID', f'#{loan.id}'),
            ('Approved Amount', f'KSh {loan.amount_requested:,.2f}'),
            ('Total Disbursed', f'KSh {loan.total_disbursed:,.2f}'),
            ('Outstanding Balance', f'KSh {loan.outstanding_balance:,.2f}'),
        ]),
        Spacer(1, 12),
        Paragraph('Transaction History', styles['SectionTitle']),
        table,
    ]
    return _build_pdf_response(f'loan_{loan.id}_statement.pdf', 'Loan Repayment Statement', story)


@loans_bp.route('/<int:loan_id>/clearance-certificate.pdf')
@login_required
def clearance_certificate(loan_id):
    loan = Loan.query.get_or_404(loan_id)

    if not loan.is_cleared:
        flash('Clearance certificate is only available after the loan is fully repaid.', 'danger')
        return redirect(url_for('loans.view', loan_id=loan.id))

    styles = pdf_styles()
    summary = key_value_table([
        ('Member', loan.member.full_name),
        ('Phone', loan.member.phone_number),
        ('Loan Assessment', f'#{loan.id}'),
        ('Issued On', datetime.utcnow().strftime('%Y-%m-%d')),
    ], columns=2)

    financials = modern_table([
        ['Loan Amount', 'Total Repaid', 'Outstanding Balance'],
        [
            f'KSh {loan.amount_requested:,.2f}',
            f'KSh {loan.total_repaid:,.2f}',
            f'KSh {loan.outstanding_balance:,.2f}',
        ],
    ], font_size=10, header_font_size=9)
    financials.setStyle(TableStyle([
        ('ALIGN', (0, 1), (-1, 1), 'CENTER'),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 1), (-1, 1), BRAND_DARK),
    ]))

    certificate_box = Table(
        [[Paragraph(
            f'This certifies that <b>{escape(loan.member.full_name)}</b> has fully repaid loan assessment '
            f'<b>#{loan.id}</b>. The account has no outstanding balance as at the date of issue.',
            styles['CertificateBody'],
        )]],
        colWidths=[165 *  mm],
    )
    certificate_box.setStyle(TableStyle([
        ('BOX', (0, 0), (-1, -1), 1.2, BRAND_DARK),
        ('INNERGRID', (0, 0), (-1, -1), 0.3, BRAND_LINE),
        ('BACKGROUND', (0, 0), (-1, -1), colors.white),
        ('TOPPADDING', (0, 0), (-1, -1), 24),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 24),
        ('LEFTPADDING', (0, 0), (-1, -1), 20),
        ('RIGHTPADDING', (0, 0), (-1, -1), 20),
    ]))

    story = [
        Paragraph('Loan Clearance Certificate', styles['CertificateTitle']),
        summary,
        Spacer(1, 18),
        certificate_box,
        Spacer(1, 18),
        financials,
        Spacer(1, 30),
        Table([
            ['Authorized Officer', 'Date'],
            ['____________________________', datetime.utcnow().strftime('%Y-%m-%d')],
        ], colWidths=[110 * mm, 55 * mm], style=TableStyle([
            ('TEXTCOLOR', (0, 0), (-1, 0), BRAND_MUTED),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ])),
    ]
    return _build_pdf_response(f'loan_{loan.id}_clearance_certificate.pdf', 'Loan Clearance Certificate', story)
