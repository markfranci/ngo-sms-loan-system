from functools import wraps
from flask import flash, redirect, url_for
from flask_login import current_user

def admin_required(f):
    """
    Decorator to restrict access to admin users only.
    If a normal staff member tries to access a route protected by this decorator,
    they will be sent back to the dashboard with an error message.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Step 1: Ensure the user is actually signed in
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        
        # Step 2: Check if their role is Admin (using our helper from the User model)
        if not current_user.is_admin():
            # Send a notification message and send them away
            flash('Access Denied: You do not have permission to view that page.', 'danger')
            return redirect(url_for('main.dashboard'))
            
        # Step 3: If they are an admin, allow the view to load normally
        return f(*args, **kwargs)
        
    return decorated_function
