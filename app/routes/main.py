from flask import Blueprint, render_template
from flask_login import login_required

from app.models.member import Member
from app.models.group import Group
from app.models.survey import SurveyTemplate, SurveyResponse
from app.models.sms_log import SMSLog

# Create the main blueprint
# This will handle the dashboard and other core pages
main = Blueprint('main', __name__)


@main.route('/')
@main.route('/dashboard')
@login_required  # Only logged-in users can see the dashboard
def dashboard():
    # Calculate System Metrics
    total_members = Member.query.count()
    total_groups = Group.query.count()
    total_surveys = SurveyTemplate.query.count()
    total_responses = SurveyResponse.query.count()
    total_sms = SMSLog.query.count()

    # Get recent SMS traffic
    recent_sms = SMSLog.query.order_by(SMSLog.created_at.desc()).limit(10).all()

    return render_template('main/dashboard.html', 
                           metrics={
                               'members': total_members,
                               'groups': total_groups,
                               'surveys': total_surveys,
                               'responses': total_responses,
                               'sms': total_sms
                           },
                           recent_sms=recent_sms)
