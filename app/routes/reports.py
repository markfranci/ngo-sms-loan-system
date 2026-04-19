import csv
import io
from flask import Blueprint, render_template, make_response
from flask_login import login_required
from app.decorators import role_required
from app.models.member import Member
from app.models.group import Group
from app.models.loan import Loan

reports_bp = Blueprint('reports', __name__, url_prefix='/reports')

@reports_bp.route('/')
@login_required
@role_required('admin')
def index():
    """
    Renders the central reports hub where staff can download CSV files.
    """
    return render_template('reports/index.html')

@reports_bp.route('/export/members')
@login_required
@role_required('admin')
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
@role_required('admin')
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
@role_required('admin')
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
