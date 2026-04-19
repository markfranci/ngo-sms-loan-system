from flask import Blueprint, render_template
from flask_login import login_required
from app.models.sms_log import SMSLog

sms = Blueprint('sms', __name__, url_prefix='/sms')

@sms.route('/logs')
@login_required
def logs():
    # Fetch top 100 recent SMS logs to avoid massive page load initially
    recent_logs = SMSLog.query.order_by(SMSLog.created_at.desc()).limit(100).all()
    return render_template('sms/logs.html', logs=recent_logs)
