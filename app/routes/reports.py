import csv
import io
from flask import Blueprint, render_template, make_response
from flask_login import login_required
from app.decorators import admin_required
from app.models.member import Member
from app.models.group import Group
from app.models.loan import Loan
from sqlalchemy import func
from app import db

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

from flask import jsonify

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

from flask import request
from datetime import datetime

@reports_bp.route('/custom/export')
@login_required
@admin_required
def custom_export():
    """
    Generates and downloads a customizable CSV report based on filters and selected columns.
    """
    entity = request.args.get('entity', 'members')
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    group_id = request.args.get('group_id')
    selected_columns = request.args.getlist('columns')

    si = io.StringIO()
    cw = csv.writer(si)

    if not selected_columns:
        cw.writerow(['Error: No columns selected'])
        return make_response(si.getvalue(), 200, {'Content-Disposition': 'attachment; filename=error.csv', 'Content-Type': 'text/csv'})

    if entity == 'members':
        # Apply filters
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
                
        members = query.all()
        
        # Write Headers
        headers = [col.replace('_', ' ').title() for col in selected_columns]
        cw.writerow(headers)
        
        # Write Data
        for m in members:
            row = []
            for col in selected_columns:
                if col == 'id': row.append(m.id)
                elif col == 'full_name': row.append(m.full_name)
                elif col == 'phone_number': row.append(m.phone_number)
                elif col == 'id_number': row.append(m.id_number or '')
                elif col == 'gender': row.append(m.gender or '')
                elif col == 'location': row.append(m.location or '')
                elif col == 'group_name': row.append(m.group.name if m.group else 'Unassigned')
                elif col == 'registered_at': row.append(m.registered_at.strftime('%Y-%m-%d %H:%M') if m.registered_at else '')
                elif col == 'current_survey_id': row.append(m.current_survey_id or '')
                else: row.append('')
            cw.writerow(row)
            
        filename = 'custom_members_report.csv'

    elif entity == 'loans':
        # Apply filters
        status = request.args.get('status')
        min_amount = request.args.get('min_amount')
        max_amount = request.args.get('max_amount')
        min_score = request.args.get('min_score')
        
        query = Loan.query
        if group_id and group_id != 'all':
            query = query.join(Member).filter(Member.group_id == group_id)
        if status and status != 'all':
            query = query.filter(Loan.status.ilike(status))
        if min_amount:
            query = query.filter(Loan.amount_requested >= float(min_amount))
        if max_amount:
            query = query.filter(Loan.amount_requested <= float(max_amount))
        if min_score:
            query = query.filter(Loan.score >= float(min_score))
            
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
                
        loans = query.all()
        
        # Write Headers
        headers = [col.replace('_', ' ').title() for col in selected_columns]
        cw.writerow(headers)
        
        # Write Data
        for l in loans:
            row = []
            for col in selected_columns:
                if col == 'id': row.append(l.id)
                elif col == 'applicant_name': row.append(l.member.full_name)
                elif col == 'phone_number': row.append(l.member.phone_number)
                elif col == 'group_name': row.append(l.member.group.name if l.member.group else 'Unassigned')
                elif col == 'amount_requested': row.append(l.amount_requested or 0)
                elif col == 'score': row.append(l.score or 0)
                elif col == 'status': row.append(l.status.upper())
                elif col == 'notes': row.append(l.notes or '')
                elif col == 'assessed_by': row.append(l.assessor.username if l.assessor else 'System')
                elif col == 'created_at': row.append(l.created_at.strftime('%Y-%m-%d %H:%M') if l.created_at else '')
                elif col == 'updated_at': row.append(l.updated_at.strftime('%Y-%m-%d %H:%M') if l.updated_at else '')
                else: row.append('')
            cw.writerow(row)
            
        filename = 'custom_loans_report.csv'

    else:
        cw.writerow(['Error: Unknown entity'])
        filename = 'error_report.csv'

    response = make_response(si.getvalue())
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'text/csv'
    return response
