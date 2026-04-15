from flask import Blueprint, render_template
from flask_login import login_required

# Create the main blueprint
# This will handle the dashboard and other core pages
main = Blueprint('main', __name__)


@main.route('/')
@main.route('/dashboard')
@login_required  # Only logged-in users can see the dashboard
def dashboard():
    """Temporary placeholder dashboard."""
    return render_template('main/dashboard.html')
