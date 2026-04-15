from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, login_required, current_user
from app.models.user import User

# ----------------------------------------------------------------
# Create the auth blueprint
# A Blueprint is like a mini-app within our main app.
# All routes defined here will be prefixed with the name 'auth'.
# For example: url_for('auth.login') → /login
# ----------------------------------------------------------------
auth = Blueprint('auth', __name__)


# ----------------------------------------------------------------
# LOGIN ROUTE
# ----------------------------------------------------------------
@auth.route('/login', methods=['GET', 'POST'])
def login():
    """
    GET  /login → Show the login form
    POST /login → Process the submitted form (check credentials)
    """

    # If the user is already logged in, send them straight to the dashboard
    # No need to log in twice!
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))

    # When the user submits the form, method will be POST
    if request.method == 'POST':

        # Get the values the user typed into the form
        # request.form is a dictionary of all form fields
        email = request.form.get('email')
        password = request.form.get('password')

        # Look up the user in the database by their email
        user = User.query.filter_by(email=email).first()

        # Check if we found a user AND the password matches
        if user and user.check_password(password):
            # Log them in — Flask-Login saves their info in the session
            # remember=True means they stay logged in even if they close the browser
            login_user(user, remember=True)

            # After login, redirect to the page they were trying to visit
            # (or the dashboard if they came directly to /login)
            next_page = request.args.get('next')
            return redirect(next_page or url_for('main.dashboard'))

        else:
            # Wrong email or password — show an error message
            # flash() sends a one-time message to be displayed on the page
            flash('Invalid email or password. Please try again.', 'danger')

    # Show the login page (GET request, or after a failed POST)
    return render_template('auth/login.html')


# ----------------------------------------------------------------
# LOGOUT ROUTE
# ----------------------------------------------------------------
@auth.route('/logout')
@login_required  # Only logged-in users can log out (makes sense!)
def logout():
    """
    /logout → End the session and redirect to login page
    """
    logout_user()  # Flask-Login clears the session
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('auth.login'))
