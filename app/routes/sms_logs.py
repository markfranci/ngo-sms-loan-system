from datetime import datetime

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import login_required
from app import db
from app.decorators import admin_required
from app.models.member import Member
from app.models.sms_log import SMSLog

sms = Blueprint('sms', __name__, url_prefix='/sms')

@sms.route('/logs')
@login_required
def logs():
    return render_template('sms/logs.html')


@sms.route('/logs/api/data')
@login_required
def get_sms_data():
    """Returns JSON data for the dynamic SMS logs frontend."""
    search = request.args.get('search')
    direction = request.args.get('direction')
    sms_status = request.args.get('sms_status')
    member_id = request.args.get('member_id')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = SMSLog.query

    if direction and direction != 'all':
        query = query.filter(SMSLog.direction == direction)
    if sms_status and sms_status != 'all':
        query = query.filter(SMSLog.status == sms_status)
    if member_id and member_id != 'all':
        try:
            query = query.filter(SMSLog.member_id == int(member_id))
        except (ValueError, TypeError):
            pass
    if start_date:
        try:
            dt = datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(SMSLog.created_at >= dt)
        except ValueError:
            pass
    if end_date:
        try:
            dt = datetime.strptime(end_date, '%Y-%m-%d')
            query = query.filter(SMSLog.created_at <= dt.replace(hour=23, minute=59, second=59))
        except ValueError:
            pass
    if search:
        query = query.outerjoin(Member, SMSLog.member_id == Member.id).filter(db.or_(
            SMSLog.sender.ilike(f"%{search}%"),
            SMSLog.recipient.ilike(f"%{search}%"),
            SMSLog.message.ilike(f"%{search}%"),
            Member.full_name.ilike(f"%{search}%")
        ))

    # Apply column-level filters passed as filter_<column>=value
    sender_filter = request.args.get('filter_sender', '').strip()
    recipient_filter = request.args.get('filter_recipient', '').strip()
    if sender_filter:
        query = query.filter(SMSLog.sender.ilike(f"%{sender_filter}%"))
    if recipient_filter:
        query = query.filter(SMSLog.recipient.ilike(f"%{recipient_filter}%"))

    query = query.order_by(SMSLog.created_at.desc()).limit(500)

    data = []
    for log in query.all():
        data.append({
            'id': log.id,
            'direction': log.direction,
            'sender': log.sender,
            'recipient': log.recipient,
            'member_name': log.member.full_name if log.member else '',
            'member_id': log.member_id or '',
            'message': log.message,
            'status': log.status,
            'created_at': log.created_at.strftime('%Y-%m-%d %H:%M') if log.created_at else ''
        })
    return jsonify(data)


@sms.route('/logs/api/filter-options')
@login_required
def get_sms_filter_options():
    """Returns available filter options for SMS logs."""
    members = Member.query.all()
    member_options = sorted(
        [{'id': m.id, 'label': f"{m.full_name} ({m.phone_number})"} for m in members],
        key=lambda x: x['label'].casefold()
    )

    logs = SMSLog.query.order_by(SMSLog.created_at.desc()).limit(500).all()

    senders = set()
    recipients = set()
    for log in logs:
        if log.sender:
            senders.add(log.sender)
        if log.recipient:
            recipients.add(log.recipient)

    return jsonify({
        'members': member_options,
        'sender': sorted(senders),
        'recipient': sorted(recipients),
    })


@sms.route('/logs/<int:log_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_log(log_id):
    log = SMSLog.query.get_or_404(log_id)
    db.session.delete(log)
    db.session.commit()
    flash('SMS log deleted successfully.', 'success')
    return redirect(url_for('sms.logs'))
