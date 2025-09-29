# auth_routes.py
from flask import Blueprint, render_template, request, redirect, session, current_app, flash
from services import require_role
import re

auth_bp = Blueprint("auth", __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    supabase = current_app.config['supabase']
    supabase_admin = current_app.config['supabase_admin']
    modules = current_app.config['MODULES']

    if request.method == 'POST':
        identifier = request.form.get('email')  # can be phone or email
        password = request.form.get('password')

        try:
            # If input looks like phone number → lookup email from users_meta
            if re.match(r'^\d{10,15}$', identifier):
                print(">>> Login attempt with phone:", identifier)
                result = supabase_admin.table("users_meta").select("email").eq("phone", identifier).execute()
                print(">>> Phone lookup result:", result.data)

                if not result.data:
                    return render_template('login.html', error="Phone not registered")
                email = result.data[0]["email"]
            else:
                email = identifier  # treat as email

            # Authenticate with Supabase Auth
            auth = supabase.auth.sign_in_with_password({
                'email': email,
                'password': password
            })
            user = getattr(auth, 'user', None)

            if not user:
                return render_template('login.html', error="Invalid credentials")

            # Save session
            session['user'] = email
            session['role'] = user.user_metadata.get('role', 'user')

            # Always fetch full_name from users_meta
            meta = supabase_admin.table("users_meta").select("full_name").eq("email", email).single().execute()
            if meta.data and meta.data.get("full_name"):
                session['name'] = meta.data["full_name"]
            else:
                session['name'] = user.user_metadata.get('full_name', email)

            # Fetch accesses for sidebar
            if session['role'] == 'user':
                result = supabase_admin.table("users_meta").select("accesses").eq("email", email).execute()
                if result.data:
                    session['accesses'] = result.data[0].get("accesses", [])
                else:
                    session['accesses'] = []
            else:
                # Admins see everything
                session['accesses'] = [m for m in modules]

            # Handle "Remember me"
            if request.form.get('remember'):
                session.permanent = True
            else:
                session.permanent = False

            if session['role'] == 'admin':
                return redirect('/admin_dashboard')
            else:
                return redirect('/user_dashboard')

        except Exception as e:
            print("!!! Login failed:", str(e))
            return render_template('login.html', error=f"Login failed: {str(e)}")

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


@auth_bp.route('/change_password', methods=['GET', 'POST'])
@require_role('user')
def change_password():
    supabase = current_app.config['supabase']

    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        user_email = session.get('user')

        try:
            auth = supabase.auth.sign_in_with_password({
                'email': user_email,
                'password': old_password
            })

            if not auth.user:
                return render_template('change_password.html', error="Incorrect current password")

            supabase.auth.update_user({"password": new_password})
            return redirect('/user_dashboard')

        except Exception as e:
            return render_template('change_password.html', error=str(e))

    return render_template('change_password.html')


@auth_bp.route('/admin_change_password', methods=['GET', 'POST'])
@require_role('admin')
def admin_change_password():
    supabase = current_app.config['supabase']

    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        user_email = session.get('user')

        try:
            auth = supabase.auth.sign_in_with_password({
                'email': user_email,
                'password': old_password
            })

            if not auth.user:
                return render_template('change_password.html', error="Incorrect current password")

            supabase.auth.update_user({"password": new_password})
            return redirect('/admin_dashboard')

        except Exception as e:
            return render_template('change_password.html', error=str(e))

    return render_template('change_password.html')
