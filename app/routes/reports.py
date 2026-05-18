import csv
import html
import io
from datetime import datetime

from flask import Blueprint, jsonify, make_response, render_template, request
from flask_login import login_required
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from app.decorators import admin_required
from app import db
from app.models.member import Member
from app.models.group import Group
from app.models.loan import Loan
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
            m.location or '', 
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
    cw.writerow(['Loan ID', 'Applicant Name', 'Phone Number', 'Group', 'Requested Amount', 'Automated Score', 'Decision Status', 'Staff Notes', 'Assessed By', 'Date'])
    
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
            loan.score or 0,
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
        if location:
            query = query.filter(Member.location.ilike(f"%{location}%"))
        if search:
            query = query.filter(db.or_(
                Member.full_name.ilike(f"%{search}%"),
                Member.phone_number.ilike(f"%{search}%"),
                Member.id_number.ilike(f"%{search}%")
            ))
            
        data = []
        for m in query.all():
            data.append({
                'id': m.id,
                'full_name': m.full_name,
                'phone_number': m.phone_number,
                'gender': m.gender or 'Unknown',
                'location': m.location or 'Unknown',
                'group_name': m.group.name if m.group else 'Unassigned',
                'registered_at': m.registered_at.strftime('%Y-%m-%d') if m.registered_at else ''
            })
        return jsonify(data)
        
    elif entity == 'loans':
        query = Loan.query
        if group_id and group_id != 'all':
            query = query.join(Member).filter(Member.group_id == group_id)
        if status and status != 'all':
            query = query.filter(Loan.status.ilike(status))
        if search:
            query = query.join(Member).filter(db.or_(
                Member.full_name.ilike(f"%{search}%"),
                Member.phone_number.ilike(f"%{search}%")
            ))
            
        data = []
        for l in query.all():
            data.append({
                'id': l.id,
                'applicant_name': l.member.full_name,
                'phone_number': l.member.phone_number,
                'group_name': l.member.group.name if l.member.group else 'Unassigned',
                'amount_requested': l.amount_requested or 0,
                'score': l.score or 0,
                'status': l.status,
                'created_at': l.created_at.strftime('%Y-%m-%d') if l.created_at else ''
            })
        return jsonify(data)
        
    elif entity == 'groups':
        query = Group.query
        if search:
            query = query.filter(Group.name.ilike(f"%{search}%"))
        
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
        return jsonify(data)
        
    elif entity == 'surveys':
        from app.models.survey import SurveyTemplate
        query = SurveyTemplate.query
        if search:
            query = query.filter(SurveyTemplate.title.ilike(f"%{search}%"))
            
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
        return jsonify(data)
        
    return jsonify({'error': 'Invalid entity'}), 400


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_column_label(column_name):
    return column_name.replace('_', ' ').title()


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
        ('Min Score', 'min_score'),
    ]:
        value = request.args.get(key)
        if value and value != 'all':
            filters.append((label, value))

    return filters


def _draw_report_brand(canvas, doc, title):
    canvas.saveState()

    page_width, page_height = doc.pagesize
    left = doc.leftMargin
    right = page_width - doc.rightMargin

    # Draw a simple vector logo to avoid external file dependencies.
    logo_x = left
    logo_y = page_height - 21 * mm
    canvas.setFillColor(colors.HexColor('#0f766e'))
    canvas.roundRect(logo_x, logo_y, 12 * mm, 12 * mm, 2 * mm, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont('Helvetica-Bold', 10)
    canvas.drawCentredString(logo_x + 6 * mm, logo_y + 4.1 * mm, 'NGO')

    canvas.setFillColor(colors.HexColor('#111827'))
    canvas.setFont('Helvetica-Bold', 14)
    canvas.drawString(left + 16 * mm, page_height - 13 * mm, 'NGO SMS Loan System')
    canvas.setFont('Helvetica', 10)
    canvas.setFillColor(colors.HexColor('#4b5563'))
    canvas.drawString(left + 16 * mm, page_height - 18 * mm, title)
    canvas.drawRightString(
        right,
        page_height - 13 * mm,
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    )

    canvas.setStrokeColor(colors.HexColor('#d1d5db'))
    canvas.setLineWidth(0.6)
    canvas.line(left, page_height - 24 * mm, right, page_height - 24 * mm)

    footer_y = 11 * mm
    canvas.line(left, footer_y + 4 * mm, right, footer_y + 4 * mm)
    canvas.setFont('Helvetica', 9)
    canvas.setFillColor(colors.HexColor('#6b7280'))
    canvas.drawString(left, footer_y, 'Confidential report')
    canvas.drawRightString(right, footer_y, f'Page {canvas.getPageNumber()}')

    canvas.restoreState()


def _build_pdf_response(title, headers, rows, filename, filters):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=30 * mm,
        bottomMargin=18 * mm,
    )

    styles = getSampleStyleSheet()
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
        table = Table(table_data, repeatRows=1)
        table.setStyle(
            TableStyle(
                [
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f766e')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 9),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                    ('TOPPADDING', (0, 0), (-1, 0), 8),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.white),
                    ('TEXTCOLOR', (0, 1), (-1, -1), colors.HexColor('#111827')),
                    ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
                    ('FONTSIZE', (0, 1), (-1, -1), 8),
                    ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#d1d5db')),
                    ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f9fafb')]),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 6),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 6),
                ]
            )
        )
        story.append(table)

    doc.build(
        story,
        onFirstPage=lambda canvas, document: _draw_report_brand(canvas, document, title),
        onLaterPages=lambda canvas, document: _draw_report_brand(canvas, document, title),
    )

    pdf = buffer.getvalue()
    buffer.close()

    response = make_response(pdf)
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'application/pdf'
    return response


def _build_custom_report_payload():
    entity = request.args.get('entity', 'members')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    group_id = request.args.get('group_id')
    selected_columns = request.args.getlist('columns')
    search = request.args.get('search')

    default_columns = {
        'members': ['full_name', 'phone_number', 'gender', 'location', 'group_name', 'registered_at'],
        'loans': ['applicant_name', 'phone_number', 'amount_requested', 'score', 'status', 'group_name', 'created_at'],
        'groups': ['name', 'description', 'member_count', 'manager', 'created_at'],
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
        if location:
            query = query.filter(Member.location.ilike(f"%{location}%"))
        if phone_number:
            query = query.filter(Member.phone_number.ilike(f"%{phone_number}%"))
        if id_number:
            query = query.filter(Member.id_number.ilike(f"%{id_number}%"))
        if search:
            query = query.filter(db.or_(
                Member.full_name.ilike(f"%{search}%"),
                Member.phone_number.ilike(f"%{search}%"),
                Member.id_number.ilike(f"%{search}%")
            ))

        if start_date:
            try:
                dt = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(Member.registered_at >= dt)
            except ValueError:
                pass
        if end_date:
            try:
                dt = datetime.strptime(end_date, '%Y-%m-%d')
                query = query.filter(Member.registered_at <= dt.replace(hour=23, minute=59, second=59))
            except ValueError:
                pass

        records = query.all()
        rows = []
        for member in records:
            row = []
            for col in selected_columns:
                if col == 'id':
                    row.append(member.id)
                elif col == 'full_name':
                    row.append(member.full_name)
                elif col == 'phone_number':
                    row.append(member.phone_number)
                elif col == 'id_number':
                    row.append(member.id_number or '')
                elif col == 'gender':
                    row.append(member.gender or '')
                elif col == 'location':
                    row.append(member.location or '')
                elif col == 'group_name':
                    row.append(member.group.name if member.group else 'Unassigned')
                elif col == 'registered_at':
                    row.append(member.registered_at.strftime('%Y-%m-%d %H:%M') if member.registered_at else '')
                elif col == 'current_survey_id':
                    row.append(member.current_survey_id or '')
                else:
                    row.append('')
            rows.append(row)

        return (
            'Members Report',
            [_format_column_label(col) for col in selected_columns],
            rows,
            'custom_members_report',
            None,
        )

    if entity == 'loans':
        status = request.args.get('status')
        min_amount = _safe_float(request.args.get('min_amount'))
        max_amount = _safe_float(request.args.get('max_amount'))
        min_score = _safe_float(request.args.get('min_score'))

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
        if min_score is not None:
            query = query.filter(Loan.score >= min_score)
        if search:
            query = query.filter(db.or_(
                Member.full_name.ilike(f"%{search}%"),
                Member.phone_number.ilike(f"%{search}%")
            ))

        if start_date:
            try:
                dt = datetime.strptime(start_date, '%Y-%m-%d')
                query = query.filter(Loan.created_at >= dt)
            except ValueError:
                pass
        if end_date:
            try:
                dt = datetime.strptime(end_date, '%Y-%m-%d')
                query = query.filter(Loan.created_at <= dt.replace(hour=23, minute=59, second=59))
            except ValueError:
                pass

        records = query.all()
        rows = []
        for loan in records:
            row = []
            for col in selected_columns:
                if col == 'id':
                    row.append(loan.id)
                elif col == 'applicant_name':
                    row.append(loan.member.full_name)
                elif col == 'phone_number':
                    row.append(loan.member.phone_number)
                elif col == 'group_name':
                    row.append(loan.member.group.name if loan.member.group else 'Unassigned')
                elif col == 'amount_requested':
                    row.append(loan.amount_requested or 0)
                elif col == 'score':
                    row.append(loan.score or 0)
                elif col == 'status':
                    row.append(loan.status.upper())
                elif col == 'notes':
                    row.append(loan.notes or '')
                elif col == 'assessed_by':
                    row.append(loan.assessor.username if loan.assessor else 'System')
                elif col == 'created_at':
                    row.append(loan.created_at.strftime('%Y-%m-%d %H:%M') if loan.created_at else '')
                elif col == 'updated_at':
                    row.append(loan.updated_at.strftime('%Y-%m-%d %H:%M') if loan.updated_at else '')
                else:
                    row.append('')
            rows.append(row)

        return (
            'Loans Report',
            [_format_column_label(col) for col in selected_columns],
            rows,
            'custom_loans_report',
            None,
        )

    if entity == 'groups':
        query = Group.query
        if search:
            query = query.filter(Group.name.ilike(f"%{search}%"))

        records = query.all()
        rows = []
        for group in records:
            row = []
            for col in selected_columns:
                if col == 'id':
                    row.append(group.id)
                elif col == 'name':
                    row.append(group.name)
                elif col == 'description':
                    row.append(group.description or 'No description')
                elif col == 'member_count':
                    row.append(len(group.members))
                elif col == 'manager':
                    row.append(group.manager.username if group.manager else 'Unassigned')
                elif col == 'created_at':
                    row.append(group.created_at.strftime('%Y-%m-%d %H:%M') if group.created_at else '')
                else:
                    row.append('')
            rows.append(row)

        return (
            'Groups Report',
            [_format_column_label(col) for col in selected_columns],
            rows,
            'custom_groups_report',
            None,
        )

    if entity == 'surveys':
        query = SurveyTemplate.query
        if search:
            query = query.filter(SurveyTemplate.title.ilike(f"%{search}%"))

        records = query.all()
        rows = []
        for survey in records:
            row = []
            for col in selected_columns:
                if col == 'id':
                    row.append(survey.id)
                elif col == 'title':
                    row.append(survey.title)
                elif col == 'description':
                    row.append(survey.description or 'No description')
                elif col == 'question_count':
                    row.append(len(survey.questions))
                elif col == 'creator':
                    row.append(survey.creator.username if survey.creator else 'System')
                elif col == 'created_at':
                    row.append(survey.created_at.strftime('%Y-%m-%d %H:%M') if survey.created_at else '')
                else:
                    row.append('')
            rows.append(row)

        return (
            'Surveys Report',
            [_format_column_label(col) for col in selected_columns],
            rows,
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
