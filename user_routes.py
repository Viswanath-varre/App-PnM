# user_routes.py
from flask import Blueprint, render_template, session, redirect, current_app
from services import require_role

user_bp = Blueprint("user", __name__)

@user_bp.route('/user_dashboard')
@require_role('user')
def user_dashboard():
    return render_template('user_dashboard.html')


@user_bp.route('/user_profile')
@require_role('user')
def user_profile():
    user_email = session.get('user')
    user_role = session.get('role')
    return render_template('user_profile.html', user_email=user_email, user_role=user_role)


# Dynamic simple user pages: /user_<module> (only if module in session['accesses'])
@user_bp.route('/user_<module_name>')
@require_role('user')
def user_module_page(module_name):
    # Ensure the user has access
    accesses = session.get('accesses', [])
    if module_name not in accesses:
        return redirect('/user_dashboard')

    try:
        return render_template(f"user_{module_name}.html")
    except Exception:
        # fallback placeholder if missing
        return render_template('user_asset_master.html')
