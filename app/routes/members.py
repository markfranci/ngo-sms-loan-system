from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from app.models.member import Member
from app.models.sms_log import SMSLog
from app.models.group import Group
from app import db
from flask import request, flash, redirect, url_for

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
