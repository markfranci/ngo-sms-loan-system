from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
import secrets

from app import db
from app.decorators import admin_required
from app.models.user import User
from app.validators import clean_spaces, is_valid_email, is_valid_username


settings = Blueprint('settings', __name__, url_prefix='/settings')


@settings.route('/users', methods=['GET', 'POST'])
@login_required
@admin_required
def users():
    invitation_url = None
    invited_user = None

    if request.method == 'POST':
        username = clean_spaces(request.form.get('username', ''))
        email = request.form.get('email', '').strip().lower()
        role = request.form.get('role', 'staff')

        if not username or not email:
            flash('Username and email address are required.', 'danger')
            return redirect(url_for('settings.users'))

        if not is_valid_username(username):
            flash('Username must start with a letter and use only letters, numbers, dots, underscores, or hyphens.', 'danger')
            return redirect(url_for('settings.users'))

        if not is_valid_email(email):
            flash('Please enter a valid email address.', 'danger')
            return redirect(url_for('settings.users'))

        if role not in ['admin', 'staff']:
            flash('Invalid user role selected.', 'danger')
            return redirect(url_for('settings.users'))

        if User.query.filter_by(username=username).first():
            flash('A user with that username already exists.', 'danger')
            return redirect(url_for('settings.users'))

        if User.query.filter_by(email=email).first():
            flash('A user with that email address already exists.', 'danger')
            return redirect(url_for('settings.users'))

        invited_user = User(username=username, email=email, role=role)
        invited_user.set_password(secrets.token_urlsafe(32))
        invited_user.create_invitation()
        db.session.add(invited_user)
        db.session.commit()

        invitation_url = url_for(
            'auth.accept_invitation',
            token=invited_user.invitation_token,
            _external=True,
        )
        flash(f'Invitation link created for {invited_user.email}. Copy and share it manually.', 'success')

    users_list = User.query.order_by(User.created_at.desc()).all()
    return render_template(
        'settings/users.html',
        users=users_list,
        invitation_url=invitation_url,
        invited_user=invited_user,
    )


@settings.route('/users/<int:user_id>/resend-invite', methods=['POST'])
@login_required
@admin_required
def resend_invite(user_id):
    user = User.query.get_or_404(user_id)
    user.create_invitation()
    db.session.commit()

    invitation_url = url_for(
        'auth.accept_invitation',
        token=user.invitation_token,
        _external=True,
    )
    users_list = User.query.order_by(User.created_at.desc()).all()
    flash(f'Invitation link refreshed for {user.email}. Copy and share it manually.', 'success')
    return render_template(
        'settings/users.html',
        users=users_list,
        invitation_url=invitation_url,
        invited_user=user,
    )
