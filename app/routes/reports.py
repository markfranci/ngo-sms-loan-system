import csv
import html
import io
from datetime import datetime

from flask import Blueprint, jsonify, make_response, render_template, request
from flask_login import login_required
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import Paragraph, Spacer
from app.pdf_utils import build_pdf_response, modern_table, pdf_styles
from app.decorators import admin_required
from app import db
from app.models.member import Member
from app.models.group import Group
from app.models.loan import Loan
from app.models.sms_log import SMSLog
from app.models.survey import SurveyTemplate
from sqlalchemy import func

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')

@reports_bp.route('/')
@login_required
@admin_required
def index():
    """
    Renders the central reports hub where staff can download CSV files and view dynamic charts.
    """
    # 1. Loan Status Distribution
    loan_status_query = db.session.query(Loan.status, func.count(Loan.id)).group_by(Loan.status).all()
    loan_status_data = {
        'labels': [status.capitalize() for status, count in loan_status_query],
        'counts': [count for status, count in loan_status_query]
    }

    # 2. Gender Distribution
    gender_query = db.session.query(Member.gender, func.count(Member.id)).group_by(Member.gender).all()
    gender_data = {
        'labels': [gender.capitalize() if gender else 'Unknown' for gender, count in gender_query],
        'counts': [count for gender, count in gender_query]
    }

    # 3. Monthly Registrations (Last 6 Months approx, or just simple grouped by month-year)
    # Using strftime for SQLite/MySQL depending on DB, but for general compatibility we can just fetch all and process in python for a small dataset, or use a simple extract.
    # Since sqlite and postgres have different date functions, processing in python is safer for a small app.
    members = Member.query.all()
    monthly_counts = {}
    for m in members:
        if m.registered_at:
            month_year = m.registered_at.strftime('%b %Y')
            monthly_counts[month_year] = monthly_counts.get(month_year, 0) + 1
    
    registration_data = {
        'labels': list(monthly_counts.keys()),
        'counts': list(monthly_counts.values())
    }

    groups = Group.query.all()

    return render_template('reports/index.html', 
                           loan_status_data=loan_status_data, 
                           gender_data=gender_data,
                           registration_data=registration_data,
                           groups=groups)

@reports_bp.route('/export/members')
@login_required
@admin_required
def export_members():
    """
    Generates and downloads a CSV of all members.
    """
    # Use io.StringIO as an in-memory buffer for the CSV data
    si = io.StringIO()
    cw = csv.writer(si)
    
    # Write the column headers
    cw.writerow(['ID', 'Full Name', 'Phone Number', 'ID Number', 'Gender', 'Location', 'Group Name', 'Registered At'])
    
    # Fetch data and write rows
    members = Member.query.all()
    for m in members:
        group_name = m.group.name if m.group else 'Unassigned'
        cw.writerow([
            m.id, 
            m.full_name, 
            m.phone_number, 
            m.id_number or '', 
            m.gender or '', 
            m.display_location or '',
            group_name, 
            m.registered_at.strftime('%Y-%m-%d %H:%M')
        ])

    # Convert the buffer to an HTTP response
    response = make_response(si.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=sme_members_report.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response
    
@reports_bp.route('/export/loans')
@login_required
@admin_required
def export_loans():
    """
    Generates and downloads a CSV of all loan assessments.
    """
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Loan ID', 'Applicant Name', 'Phone Number', 'Group', 'Requested Amount', 'Decision Status', 'Staff Notes', 'Assessed By', 'Date'])
    
    loans = Loan.query.all()
    for loan in loans:
        group_name = loan.member.group.name if loan.member.group else 'Unassigned'
        assessor = loan.assessor.username if loan.assessor else 'System'
        cw.writerow([
            loan.id,
            loan.member.full_name,
            loan.member.phone_number,
            group_name,
            loan.amount_requested or 0,
            loan.status.upper(),
            loan.notes or '',
            assessor,
            loan.created_at.strftime('%Y-%m-%d %H:%M')
        ])
        
    response = make_response(si.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=loan_assessments_report.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response

@reports_bp.route('/export/groups')
@login_required
@admin_required
def export_groups():
    """
    Generates and downloads a CSV of all SME groups and their aggregates.
    """
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Group ID', 'Group Name', 'Description', 'Total Members', 'Assigned Manager', 'Created At'])
    
    groups = Group.query.all()
    for g in groups:
        manager = g.manager.username if g.manager else 'Unassigned'
        cw.writerow([
            g.id,
            g.name,
            g.description or '',
            len(g.members),
            manager,
            g.created_at.strftime('%Y-%m-%d %H:%M')
        ])
        
    response = make_response(si.getvalue())
    response.headers['Content-Disposition'] = 'attachment; filename=sme_groups_report.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response

@reports_bp.route('/api/data')
@login_required
@admin_required
def get_report_data():
    """
    Returns JSON data for the dynamic frontend views (Graph, List, Pivot, Kanban).
    """
    entity = request.args.get('entity', 'members')
    # We will accept similar filters to the CSV export
    group_id = request.args.get('group_id')
    gender = request.args.get('gender')
    location = request.args.get('location')
    status = request.args.get('status')
    search = request.args.get('search') # Generic search field

    if entity == 'members':
        query = Member.query
        if group_id and group_id != 'all':
            query = query.filter(Member.group_id == group_id)
        if gender and gender != 'all':
            query = query.filter(Member.gender.ilike(gender))
        query = _apply_date_range(query, Member.registered_at)
            
        data = []
        for m in query.all():
            display_location = m.display_location or 'Unknown'
            if location and location.casefold() not in display_location.casefold():
                continue
            if search:
                searchable_text = ' '.join([
                    m.full_name or '',
                    m.phone_number or '',
                    m.id_number or '',
                    display_location,
                ]).casefold()
                if search.casefold() not in searchable_text:
                    continue
            data.append({
                'id': m.id,
                'full_name': m.full_name,
                'phone_number': m.phone_number,
                'id_number': m.id_number or '',
                'gender': m.gender or 'Unknown',
                'location': display_location,
                'group_name': m.group.name if m.group else 'Unassigned',
                'registered_at': m.registered_at.strftime('%Y-%m-%d') if m.registered_at else ''
            })
        data = _filter_records(data)
        return jsonify(data)
        
    elif entity == 'loans':
        query = Loan.query
        needs_member_join = (group_id and group_id != 'all') or bool(search)
        if needs_member_join:
            query = query.join(Member)
        if group_id and group_id != 'all':
            query = query.filter(Member.group_id == group_id)
        if status and status != 'all':
            query = query.filter(Loan.status.ilike(status))
        if search:
            query = query.filter(db.or_(
                Member.full_name.ilike(f"%{search}%"),
                Member.phone_number.ilike(f"%{search}%")
            ))
        query = _apply_date_range(query, Loan.created_at)
            
        data = []
        for l in query.all():
            data.append({
                'id': l.id,
                'applicant_name': l.member.full_name,
                'phone_number': l.member.phone_number,
                'group_name': l.member.group.name if l.member.group else 'Unassigned',
                'amount_requested': l.amount_requested or 0,
                'status': l.status,
                'created_at': l.created_at.strftime('%Y-%m-%d') if l.created_at else ''
            })
        data = _filter_records(data)
        return jsonify(data)
        
    elif entity == 'groups':
        query = Group.query
        if search:
            query = query.filter(Group.name.ilike(f"%{search}%"))
        query = _apply_date_range(query, Group.created_at)
        
        data = []
        for g in query.all():
            data.append({
                'id': g.id,
                'name': g.name,
                'description': g.description or 'No description',
                'member_count': len(g.members),
                'manager': g.manager.username if g.manager else 'Unassigned',
                'created_at': g.created_at.strftime('%Y-%m-%d') if g.created_at else ''
            })
        data = _filter_records(data)
        return jsonify(data)
        
    elif entity == 'sms_logs':
        query = SMSLog.query
        direction = request.args.get('direction')
        sms_status = request.args.get('sms_status')
        member_id = request.args.get('member_id')

        if direction and direction != 'all':
            query = query.filter(SMSLog.direction == direction)
        if sms_status and sms_status != 'all':
            query = query.filter(SMSLog.status == sms_status)
        if member_id and member_id != 'all':
            query = query.filter(SMSLog.member_id == int(member_id))
        query = _apply_date_range(query, SMSLog.created_at)
        if search:
            query = query.outerjoin(Member, SMSLog.member_id == Member.id).filter(db.or_(
                SMSLog.sender.ilike(f"%{search}%"),
                SMSLog.recipient.ilike(f"%{search}%"),
                SMSLog.message.ilike(f"%{search}%"),
                Member.full_name.ilike(f"%{search}%")
            ))

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
        data = _filter_records(data)
        return jsonify(data)

    elif entity == 'surveys':
        from app.models.survey import SurveyTemplate
        query = SurveyTemplate.query
        if search:
            query = query.filter(SurveyTemplate.title.ilike(f"%{search}%"))
        query = _apply_date_range(query, SurveyTemplate.created_at)
            
        data = []
        for s in query.all():
            data.append({
                'id': s.id,
                'title': s.title,
                'description': s.description or 'No description',
                'question_count': len(s.questions),
                'creator': s.creator.username if s.creator else 'System',
                'created_at': s.created_at.strftime('%Y-%m-%d') if s.created_at else ''
            })
        data = _filter_records(data)
        return jsonify(data)
        
    return jsonify({'error': 'Invalid entity'}), 400


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_column_label(column_name):
    return column_name.replace('_', ' ').title()


def _get_column_filters():
    return {
        key.removeprefix('filter_'): value.strip()
        for key, value in request.args.items()
        if key.startswith('filter_') and value.strip()
    }


def _record_matches_column_filters(record):
    exact_match_columns = {
        'gender',
        'status',
        'direction',
        'member_count',
        'question_count',
        'amount_requested',
    }

    for column, filter_value in _get_column_filters().items():
        record_value = str(record.get(column, '')).strip().casefold()
        if column.endswith('_at') and len(filter_value.strip()) == 10:
            record_value = record_value[:10]
        filter_value = filter_value.casefold()
        if column in exact_match_columns or column.endswith('_at'):
            if record_value != filter_value:
                return False
            continue
        if filter_value not in record_value:
            return False
    return True


def _filter_records(records):
    return [record for record in records if _record_matches_column_filters(record)]


def _parse_date_filter(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d')
    except ValueError:
        return None


def _apply_date_range(query, column):
    start_dt = _parse_date_filter(request.args.get('start_date'))
    end_dt = _parse_date_filter(request.args.get('end_date'))

    if start_dt:
        query = query.filter(column >= start_dt)
    if end_dt:
        query = query.filter(column <= end_dt.replace(hour=23, minute=59, second=59))

    return query


def _rows_from_records(records, selected_columns):
    return [
        [record.get(column, '') for column in selected_columns]
        for record in records
    ]


def _unique_filter_options(records):
    options = {}
    for record in records:
        for column, value in record.items():
            if value in (None, ''):
                continue
            options.setdefault(column, set()).add(str(value))

    return {
        column: sorted(values, key=lambda item: item.casefold())
        for column, values in options.items()
    }


@reports_bp.route('/api/filter-options')
@login_required
@admin_required
def get_filter_options():
    entity = request.args.get('entity', 'members')

    if entity == 'members':
        records = [
            {
                'full_name': member.full_name,
                'phone_number': member.phone_number,
                'id_number': member.id_number or '',
                'gender': member.gender or 'Unknown',
                'location': member.display_location or 'Unknown',
                'group_name': member.group.name if member.group else 'Unassigned',
                'registered_at': member.registered_at.strftime('%Y-%m-%d') if member.registered_at else '',
            }
            for member in Member.query.all()
        ]
        return jsonify(_unique_filter_options(records))

    if entity == 'loans':
        records = [
            {
                'applicant_name': loan.member.full_name,
                'phone_number': loan.member.phone_number,
                'amount_requested': loan.amount_requested or 0,
                'status': loan.status,
                'group_name': loan.member.group.name if loan.member.group else 'Unassigned',
                'created_at': loan.created_at.strftime('%Y-%m-%d') if loan.created_at else '',
            }
            for loan in Loan.query.all()
        ]
        return jsonify(_unique_filter_options(records))

    if entity == 'groups':
        records = [
            {
                'name': group.name,
                'description': group.description or 'No description',
                'member_count': len(group.members),
                'manager': group.manager.username if group.manager else 'Unassigned',
                'created_at': group.created_at.strftime('%Y-%m-%d') if group.created_at else '',
            }
            for group in Group.query.all()
        ]
        return jsonify(_unique_filter_options(records))

    if entity == 'sms_logs':
        members = Member.query.all()
        member_options = sorted(
            [{'id': m.id, 'label': f"{m.full_name} ({m.phone_number})"} for m in members],
            key=lambda x: x['label'].casefold()
        )
        # Also return distinct dates for the datalist
        logs = SMSLog.query.order_by(SMSLog.created_at.desc()).limit(500).all()
        records = [
            {
                'sender': log.sender,
                'recipient': log.recipient,
                'member_name': log.member.full_name if log.member else '',
                'status': log.status,
                'direction': log.direction,
                'created_at': log.created_at.strftime('%Y-%m-%d') if log.created_at else '',
            }
            for log in logs
        ]
        result = _unique_filter_options(records)
        result['members'] = member_options
        return jsonify(result)

    if entity == 'surveys':
        records = [
            {
                'title': survey.title,
                'description': survey.description or 'No description',
                'question_count': len(survey.questions),
                'creator': survey.creator.username if survey.creator else 'System',
                'created_at': survey.created_at.strftime('%Y-%m-%d') if survey.created_at else '',
            }
            for survey in SurveyTemplate.query.all()
        ]
        return jsonify(_unique_filter_options(records))

    return jsonify({})


def _build_report_filters():
    filters = []

    entity = request.args.get('entity', 'members').title()
    filters.append(('Entity', entity))

    group_id = request.args.get('group_id')
    if group_id and group_id != 'all':
        try:
            group = db.session.get(Group, int(group_id))
            group_label = group.name if group else f'ID {group_id}'
        except ValueError:
            group_label = f'ID {group_id}'
        filters.append(('Group', group_label))

    for label, key in [
        ('Gender', 'gender'),
        ('Location', 'location'),
        ('Status', 'status'),
        ('Phone', 'phone_number'),
        ('National ID', 'id_number'),
        ('Search', 'search'),
        ('Start Date', 'start_date'),
        ('End Date', 'end_date'),
        ('Min Amount', 'min_amount'),
        ('Max Amount', 'max_amount'),
    ]:
        value = request.args.get(key)
        if value and value != 'all':
            filters.append((label, value))

    for column, value in _get_column_filters().items():
        filters.append((_format_column_label(column), value))

    return filters


def _build_pdf_response(title, headers, rows, filename, filters):
    styles = pdf_styles()
    story = []

    if filters:
        filter_text = ' | '.join(
            f'{html.escape(str(label))}: {html.escape(str(value))}'
            for label, value in filters
        )
        story.append(Paragraph(filter_text, styles['BodyText']))
        story.append(Spacer(1, 6))

    if not rows:
        story.append(Paragraph('No records matched the selected filters.', styles['BodyText']))
    else:
        table_data = [
            [str(header) for header in headers],
            *[[str(value) for value in row] for row in rows],
        ]
        story.append(modern_table(table_data))

    return build_pdf_response(filename, title, story, pagesize=landscape(A4))


def _build_custom_report_payload():
    entity = request.args.get('entity', 'members')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    group_id = request.args.get('group_id')
    selected_columns = request.args.getlist('columns')
    search = request.args.get('search')

    default_columns = {
        'members': ['full_name', 'phone_number', 'gender', 'location', 'group_name', 'registered_at'],
        'loans': ['applicant_name', 'phone_number', 'amount_requested', 'status', 'group_name', 'created_at'],
        'groups': ['name', 'description', 'member_count', 'manager', 'created_at'],
        'sms_logs': ['direction', 'sender', 'recipient', 'member_name', 'message', 'status', 'created_at'],
        'surveys': ['title', 'description', 'question_count', 'creator', 'created_at'],
    }

    if not selected_columns:
        selected_columns = default_columns.get(entity, [])

    if not selected_columns:
        return None, None, None, 'error_report.csv', ('No columns selected', 400)

    if entity == 'members':
        gender = request.args.get('gender')
        location = request.args.get('location')
        phone_number = request.args.get('phone_number')
        id_number = request.args.get('id_number')

        query = Member.query
        if group_id and group_id != 'all':
            query = query.filter(Member.group_id == group_id)
        if gender and gender != 'all':
            query = query.filter(Member.gender.ilike(gender))
        if phone_number:
            query = query.filter(Member.phone_number.ilike(f"%{phone_number}%"))
        if id_number:
            query = query.filter(Member.id_number.ilike(f"%{id_number}%"))
        query = _apply_date_range(query, Member.registered_at)

        records = []
        for member in query.all():
            display_location = member.display_location or ''
            if location and location.casefold() not in display_location.casefold():
                continue
            if search:
                searchable_text = ' '.join([
                    member.full_name or '',
                    member.phone_number or '',
                    member.id_number or '',
                    display_location,
                ]).casefold()
                if search.casefold() not in searchable_text:
                    continue
            records.append({
                'id': member.id,
                'full_name': member.full_name,
                'phone_number': member.phone_number,
                'id_number': member.id_number or '',
                'gender': member.gender or '',
                'location': display_location,
                'group_name': member.group.name if member.group else 'Unassigned',
                'registered_at': member.registered_at.strftime('%Y-%m-%d %H:%M') if member.registered_at else '',
                'current_survey_id': member.current_survey_id or '',
            })
        records = _filter_records(records)

        return (
            'Members Report',
            [_format_column_label(col) for col in selected_columns],
            _rows_from_records(records, selected_columns),
            'custom_members_report',
            None,
        )

    if entity == 'loans':
        status = request.args.get('status')
        min_amount = _safe_float(request.args.get('min_amount'))
        max_amount = _safe_float(request.args.get('max_amount'))

        query = Loan.query
        needs_member_join = (group_id and group_id != 'all') or bool(search)
        if needs_member_join:
            query = query.join(Member)
        if group_id and group_id != 'all':
            query = query.filter(Member.group_id == group_id)
        if status and status != 'all':
            query = query.filter(Loan.status.ilike(status))
        if min_amount is not None:
            query = query.filter(Loan.amount_requested >= min_amount)
        if max_amount is not None:
            query = query.filter(Loan.amount_requested <= max_amount)
        if search:
            query = query.filter(db.or_(
                Member.full_name.ilike(f"%{search}%"),
                Member.phone_number.ilike(f"%{search}%")
            ))

        query = _apply_date_range(query, Loan.created_at)

        records = []
        for loan in query.all():
            records.append({
                'id': loan.id,
                'applicant_name': loan.member.full_name,
                'phone_number': loan.member.phone_number,
                'group_name': loan.member.group.name if loan.member.group else 'Unassigned',
                'amount_requested': loan.amount_requested or 0,
                'status': loan.status.upper(),
                'notes': loan.notes or '',
                'assessed_by': loan.assessor.username if loan.assessor else 'System',
                'created_at': loan.created_at.strftime('%Y-%m-%d %H:%M') if loan.created_at else '',
                'updated_at': loan.updated_at.strftime('%Y-%m-%d %H:%M') if loan.updated_at else '',
            })
        records = _filter_records(records)

        return (
            'Loans Report',
            [_format_column_label(col) for col in selected_columns],
            _rows_from_records(records, selected_columns),
            'custom_loans_report',
            None,
        )

    if entity == 'groups':
        query = Group.query
        if search:
            query = query.filter(Group.name.ilike(f"%{search}%"))
        query = _apply_date_range(query, Group.created_at)

        records = []
        for group in query.all():
            records.append({
                'id': group.id,
                'name': group.name,
                'description': group.description or 'No description',
                'member_count': len(group.members),
                'manager': group.manager.username if group.manager else 'Unassigned',
                'created_at': group.created_at.strftime('%Y-%m-%d %H:%M') if group.created_at else '',
            })
        records = _filter_records(records)

        return (
            'Groups Report',
            [_format_column_label(col) for col in selected_columns],
            _rows_from_records(records, selected_columns),
            'custom_groups_report',
            None,
        )

    if entity == 'sms_logs':
        direction = request.args.get('direction')
        sms_status = request.args.get('sms_status')
        member_id = request.args.get('member_id')

        query = SMSLog.query
        if direction and direction != 'all':
            query = query.filter(SMSLog.direction == direction)
        if sms_status and sms_status != 'all':
            query = query.filter(SMSLog.status == sms_status)
        if member_id and member_id != 'all':
            query = query.filter(SMSLog.member_id == int(member_id))
        if search:
            query = query.outerjoin(Member, SMSLog.member_id == Member.id).filter(db.or_(
                SMSLog.sender.ilike(f"%{search}%"),
                SMSLog.recipient.ilike(f"%{search}%"),
                SMSLog.message.ilike(f"%{search}%"),
                Member.full_name.ilike(f"%{search}%")
            ))
        query = _apply_date_range(query, SMSLog.created_at)

        query = query.order_by(SMSLog.created_at.desc()).limit(500)

        records = []
        for log in query.all():
            records.append({
                'id': log.id,
                'direction': log.direction,
                'sender': log.sender,
                'recipient': log.recipient,
                'member_name': log.member.full_name if log.member else '',
                'message': log.message,
                'status': log.status,
                'created_at': log.created_at.strftime('%Y-%m-%d %H:%M') if log.created_at else '',
            })
        records = _filter_records(records)

        return (
            'SMS Logs Report',
            [_format_column_label(col) for col in selected_columns],
            _rows_from_records(records, selected_columns),
            'custom_sms_logs_report',
            None,
        )

    if entity == 'surveys':
        query = SurveyTemplate.query
        if search:
            query = query.filter(SurveyTemplate.title.ilike(f"%{search}%"))
        query = _apply_date_range(query, SurveyTemplate.created_at)

        records = []
        for survey in query.all():
            records.append({
                'id': survey.id,
                'title': survey.title,
                'description': survey.description or 'No description',
                'question_count': len(survey.questions),
                'creator': survey.creator.username if survey.creator else 'System',
                'created_at': survey.created_at.strftime('%Y-%m-%d %H:%M') if survey.created_at else '',
            })
        records = _filter_records(records)

        return (
            'Surveys Report',
            [_format_column_label(col) for col in selected_columns],
            _rows_from_records(records, selected_columns),
            'custom_surveys_report',
            None,
        )

    return None, None, None, 'error_report.csv', ('Unknown entity', 400)

@reports_bp.route('/custom/export')
@login_required
@admin_required
def custom_export():
    """
    Generates and downloads a customizable CSV or PDF report based on filters and selected columns.
    """
    output_format = request.args.get('format', 'csv').lower()
    title, headers, rows, base_filename, error = _build_custom_report_payload()

    if error:
        message, status_code = error
        return make_response(message, status_code)

    if output_format == 'pdf':
        return _build_pdf_response(
            title=title,
            headers=headers,
            rows=rows,
            filename=f'{base_filename}.pdf',
            filters=_build_report_filters(),
        )

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(headers)
    for row in rows:
        cw.writerow(row)

    response = make_response(si.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename={base_filename}.csv'
    response.headers['Content-Type'] = 'text/csv'
    return response
