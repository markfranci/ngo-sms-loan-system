from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required
from app import db
from app.decorators import admin_required
from app.models.sms_log import SMSLog

sms = Blueprint('sms', __name__, url_prefix='/sms')

@sms.route('/logs')
@login_required
def logs():
    # Fetch top 100 recent SMS logs to avoid massive page load initially
    recent_logs = SMSLog.query.order_by(SMSLog.created_at.desc()).limit(100).all()
    return render_template('sms/logs.html', logs=recent_logs)


@sms.route('/logs/<int:log_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_log(log_id):
    log = SMSLog.query.get_or_404(log_id)
    db.session.delete(log)
    db.session.commit()
    flash('SMS log deleted successfully.', 'success')
    return redirect(url_for('sms.logs'))
