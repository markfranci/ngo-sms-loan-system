from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from app.decorators import admin_required
from app.models.member import Member, RegistrationSession
from app.models.sms_log import SMSLog
from app.models.group import Group
from app.models.loan import Loan
from app.models.survey import SurveyResponse
from app import db
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
        member.group_id = int(group_id)
        db.session.commit()
        flash(f'Member assigned to group successfully.', 'success')
    else:
        flash('Please select a valid group.', 'danger')
    return redirect(url_for('members.profile', member_id=member_id))


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
