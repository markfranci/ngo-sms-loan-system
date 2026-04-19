from flask import Blueprint, render_template, abort
from flask_login import login_required, current_user
from app.models.member import Member
from app.models.sms_log import SMSLog

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
    # Let's get survey responses directly from member.survey_responses
    return render_template('members/profile.html', member=member, sms_logs=sms_logs)
