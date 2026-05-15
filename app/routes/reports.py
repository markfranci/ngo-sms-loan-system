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

    return render_template('reports/index.html', 
                           loan_status_data=loan_status_data, 
                           gender_data=gender_data,
                           registration_data=registration_data)

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
