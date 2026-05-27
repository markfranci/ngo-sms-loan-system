from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from app.decorators import admin_required
from app.models.member import Member, RegistrationSession
from app.models.sms_log import SMSLog
from app.models.group import Group
from app.models.loan import Loan
from app.models.survey import SurveyResponse
from app import db
from app.validators import clean_spaces, is_valid_label, is_valid_national_id, is_valid_person_name, is_valid_phone_number, title_case_name
from flask import request, flash, redirect, url_for
from app.routes.loans import delete_loan_record

members = Blueprint('members', __name__, url_prefix='/members')


@members.route('/')
@login_required
def index():
    all_members = Member.query.all()
    return render_template('members/index.html', members=all_members)

@members.route('/<int:member_id>')
@login_required
def profile(member_id):
    member = Member.query.get_or_404(member_id)
    # Get SMS logs for this member
    sms_logs = SMSLog.query.filter_by(member_id=member.id).order_by(SMSLog.created_at.desc()).all()
    groups = Group.query.all()
    return render_template('members/profile.html', member=member, sms_logs=sms_logs, groups=groups)

@members.route('/<int:member_id>/assign_group', methods=['POST'])
@login_required
def assign_group(member_id):
    member = Member.query.get_or_404(member_id)
    group_id = request.form.get('group_id')
    if group_id:
        try:
            group_id_int = int(group_id)
        except ValueError:
            flash('Please select a valid group.', 'danger')
            return redirect(url_for('members.profile', member_id=member_id))
        if not Group.query.get(group_id_int):
            flash('Please select a valid group.', 'danger')
            return redirect(url_for('members.profile', member_id=member_id))
        member.group_id = group_id_int
        db.session.commit()
        flash(f'Member assigned to group successfully.', 'success')
    else:
        flash('Please select a valid group.', 'danger')
    return redirect(url_for('members.profile', member_id=member_id))


@members.route('/<int:member_id>/update', methods=['POST'])
@login_required
def update(member_id):
    member = Member.query.get_or_404(member_id)
    full_name = request.form.get('full_name', '').strip()
    phone_number = request.form.get('phone_number', '').strip()
    id_number = request.form.get('id_number', '').strip() or None
    gender = request.form.get('gender', '').strip() or None
    location = clean_spaces(request.form.get('location', '')) or None
    group_id = request.form.get('group_id')

    if not full_name or not phone_number:
        flash('Full name and phone number are required.', 'danger')
        return redirect(url_for('members.profile', member_id=member.id))

    if not is_valid_person_name(full_name):
        flash('Please enter a valid real full name with at least two letter-based names.', 'danger')
        return redirect(url_for('members.profile', member_id=member.id))

    if not is_valid_phone_number(phone_number):
        flash('Please enter a valid phone number using digits and optional leading +.', 'danger')
        return redirect(url_for('members.profile', member_id=member.id))

    if gender and gender not in ('male', 'female'):
        flash('Please select a valid gender.', 'danger')
        return redirect(url_for('members.profile', member_id=member.id))

    if id_number and not is_valid_national_id(id_number):
        flash('ID number must contain 5 to 20 digits only.', 'danger')
        return redirect(url_for('members.profile', member_id=member.id))

    if location and not is_valid_label(location, min_length=2, max_length=100):
        flash('Location must contain meaningful text using letters, numbers, and standard punctuation.', 'danger')
        return redirect(url_for('members.profile', member_id=member.id))

    group_id_int = None
    if group_id:
        try:
            group_id_int = int(group_id)
        except ValueError:
            flash('Please select a valid group.', 'danger')
            return redirect(url_for('members.profile', member_id=member.id))
        if not Group.query.get(group_id_int):
            flash('Please select a valid group.', 'danger')
            return redirect(url_for('members.profile', member_id=member.id))

    existing_phone = Member.query.filter(
        Member.phone_number == phone_number,
        Member.id != member.id,
    ).first()
    if existing_phone:
        flash('Another member already uses that phone number.', 'danger')
        return redirect(url_for('members.profile', member_id=member.id))

    if id_number:
        existing_id = Member.query.filter(
            Member.id_number == id_number,
            Member.id != member.id,
        ).first()
        if existing_id:
            flash('Another member already uses that ID number.', 'danger')
            return redirect(url_for('members.profile', member_id=member.id))

    member.full_name = title_case_name(full_name)
    member.phone_number = phone_number
    member.id_number = id_number
    member.gender = gender
    member.location = location
    member.group_id = group_id_int

    db.session.commit()
    flash('Member details updated successfully.', 'success')
    return redirect(url_for('members.profile', member_id=member.id))


@members.route('/<int:member_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete(member_id):
    member = Member.query.get_or_404(member_id)
    member_name = member.full_name

    for loan in Loan.query.filter_by(member_id=member.id).all():
        delete_loan_record(loan)

    SurveyResponse.query.filter_by(member_id=member.id).delete()
    SMSLog.query.filter_by(member_id=member.id).delete()
    RegistrationSession.query.filter_by(phone_number=member.phone_number).delete()
    db.session.delete(member)
    db.session.commit()

    flash(f'Member "{member_name}" deleted successfully.', 'success')
    return redirect(url_for('members.index'))
