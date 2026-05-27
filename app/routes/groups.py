from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models.group import Group
from app.models.member import Member
from app.models.user import User
from app.decorators import admin_required
from app.validators import clean_spaces, is_valid_label

groups = Blueprint('groups', __name__, url_prefix='/groups')

@groups.route('/')
@login_required
def index():
    if current_user.role == 'admin':
        # Admin can view all groups
        all_groups = Group.query.all()
    else:
        # Staff can only view groups assigned to them
        all_groups = Group.query.filter_by(assigned_staff_id=current_user.id).all()
        
    return render_template('groups/index.html', groups=all_groups)

@groups.route('/new', methods=['GET', 'POST'])
@login_required
@admin_required
def create():
    if request.method == 'POST':
        name = clean_spaces(request.form.get('name', ''))
        description = clean_spaces(request.form.get('description', ''))
        assigned_staff_id = request.form.get('assigned_staff_id', '').strip()
        
        # Validation
        if not is_valid_label(name, min_length=3, max_length=100):
            flash('Group name must be meaningful, include letters, and be between 3 and 100 characters.', 'danger')
            return redirect(url_for('groups.create'))

        if len(description) > 500:
            flash('Description must not exceed 500 characters.', 'danger')
            return redirect(url_for('groups.create'))
        if description and not is_valid_label(description, min_length=5, max_length=500):
            flash('Description must contain meaningful text using letters, numbers, and standard punctuation.', 'danger')
            return redirect(url_for('groups.create'))

        existing_group = Group.query.filter_by(name=name).first()
        if existing_group:
            flash('Group name already exists.', 'danger')
            return redirect(url_for('groups.create'))

        # Validate assigned staff exists
        staff_user_id = None
        if assigned_staff_id:
            try:
                staff_user_id = int(assigned_staff_id)
            except ValueError:
                flash('Invalid staff selection.', 'danger')
                return redirect(url_for('groups.create'))
            staff_user = User.query.get(staff_user_id)
            if not staff_user:
                flash('Selected staff member does not exist.', 'danger')
                return redirect(url_for('groups.create'))
            if staff_user.role != 'staff':
                flash('Groups can only be assigned to staff users.', 'danger')
                return redirect(url_for('groups.create'))

        new_group = Group(
            name=name,
            description=description,
            created_by=current_user.id,
            assigned_staff_id=staff_user_id
        )
        db.session.add(new_group)
        db.session.commit()
        
        flash('Group created successfully!', 'success')
        return redirect(url_for('groups.index'))
        
    staff_members = User.query.filter_by(role='staff').all()
    return render_template('groups/create.html', staff_members=staff_members)

@groups.route('/<int:group_id>')
@login_required
def view_group(group_id):
    group = Group.query.get_or_404(group_id)
    
    # If the user is staff, ensure they can only view groups assigned to them
    if current_user.role == 'staff' and group.assigned_staff_id != current_user.id:
        flash('You do not have permission to view this group.', 'danger')
        return redirect(url_for('groups.index'))
        
    return render_template('groups/view.html', group=group)


@groups.route('/<int:group_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete(group_id):
    group = Group.query.get_or_404(group_id)
    group_name = group.name

    Member.query.filter_by(group_id=group.id).update({'group_id': None})
    db.session.delete(group)
    db.session.commit()

    flash(f'Group "{group_name}" deleted successfully. Members were left in the system as unassigned.', 'success')
    return redirect(url_for('groups.index'))
