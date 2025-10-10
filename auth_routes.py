# auth_routes.py
from flask import Blueprint, render_template, request, redirect, session, current_app, flash, url_for
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

            # ✅ Keep session active for 7 days
            session.permanent = True

            # ✅ Redirect based on role (adjusted for blueprint prefixes)
            if session['role'] == 'admin':
                return redirect('/admin/admin_dashboard')
            else:
                return redirect('/user/dashboard')

        except Exception as e:
            print("!!! Login failed:", str(e))
            return render_template('login.html', error=f"Login failed: {str(e)}")

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# ---------------- CHANGE PASSWORD (USER) ----------------
@auth_bp.route('/change_password', methods=['GET', 'POST'])
@require_role()  # Works for both admin and user
def change_password():
    supabase = current_app.config['supabase']

    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        user_email = session.get('user')
        role = session.get('role')

        try:
            # Verify old password first
            auth = supabase.auth.sign_in_with_password({
                'email': user_email,
                'password': old_password
            })

            if not auth.user:
                return render_template('change_password.html', error="Incorrect current password")

            # Update password
            supabase.auth.update_user({"password": new_password})

            # Redirect based on role
            if role == 'admin':
                return redirect('/admin/admin_dashboard')
            else:
                return redirect('/user/user_dashboard')

        except Exception as e:
            print("❌ Password change error:", e)
            return render_template('change_password.html', error=str(e))

    return render_template('change_password.html')

# ---------------- CHANGE PASSWORD (ADMIN) ----------------
@auth_bp.route('/admin_change_password', methods=['GET', 'POST'])
@require_role('admin')
def admin_change_password():
    supabase = current_app.config['supabase']
    supabase_admin = current_app.config['supabase_admin']

    if request.method == 'POST':
        old_password = request.form.get('old_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')
        user_email = session.get('user')

        if not user_email:
            return render_template('admin_change_password.html', error="Session expired. Please log in again.")

        if new_password != confirm_password:
            return render_template('admin_change_password.html', error="New password and confirmation do not match.")

        try:
            # Step 1: Verify old password
            auth = supabase.auth.sign_in_with_password({
                'email': user_email,
                'password': old_password
            })
            if not getattr(auth, "user", None):
                return render_template('admin_change_password.html', error="Incorrect current password.")

            # Step 2: Retrieve admin's auth_id from users_meta
            meta = supabase_admin.table("users_meta").select("auth_id").eq("email", user_email).single().execute()
            auth_id = meta.data.get("auth_id") if meta.data else None
            if not auth_id:
                return render_template('admin_change_password.html', error="Admin record not found.")

            # Step 3: Update password using admin client
            supabase_admin.auth.admin.update_user(auth_id, {"password": new_password})

            flash("Password changed successfully!", "success")
            return redirect('/admin/admin_dashboard')

        except Exception as e:
            print("Error changing admin password:", e)
            return render_template('admin_change_password.html', error=str(e))

    return render_template('admin_change_password.html')
