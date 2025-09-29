# admin_routes.py
from flask import Blueprint, render_template, request, redirect, session, flash, Response, current_app
from services import require_role, _create_single_user, generate_users_csv
import io, csv

admin_bp = Blueprint("admin", __name__)

# ---------------- ADMIN DASHBOARD ----------------
@admin_bp.route('/admin_dashboard')
@require_role('admin')
def admin_dashboard():
    return render_template('admin_dashboard.html')


# ---------------- USER MANAGEMENT ----------------
@admin_bp.route('/admin_user_management')
@require_role('admin')
def admin_user_management():
    supabase_admin = current_app.config['supabase_admin']
    modules = current_app.config['MODULES']

    # Fetch users from Supabase
    users = supabase_admin.table("users_meta").select("*").execute()
    users = users.data if users.data else []

    counts = {
        "users": len(users),
        "admins": sum(1 for u in users if u.get("role") == "admin"),
        "active": len(users)  # adjust later if you track active separately
    }

    return render_template(
        'admin_user_management.html',
        users=users,
        counts=counts,
        default_columns=[
            'user_id', 'full_name', 'designation', 'phone', 'email',
            'accesses', 'role', 'auth_id', 'created_at'
        ],
        modules=modules
    )


@admin_bp.route('/create_users', methods=['POST'])
@require_role('admin')
def create_users():
    supabase_admin = current_app.config['supabase_admin']

    # If CSV upload
    if 'csv_file' in request.files:
        file = request.files['csv_file']
        if file.filename.endswith('.csv'):
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            reader = csv.DictReader(stream)
            for row in reader:
                try:
                    _create_single_user(row, supabase_admin)
                except Exception as e:
                    print("!!! CSV user create failed:", e)
                    flash(f"CSV user create failed: {e}")
        return redirect('/admin_user_management')

    # Otherwise normal form
    data = {
        "user_id": request.form.get("user_id"),
        "full_name": request.form.get("full_name"),
        "designation": request.form.get("designation"),
        "role": request.form.get("role"),
        "phone": request.form.get("phone"),
        "email": request.form.get("email"),
        "password": request.form.get("password"),
        "accesses": request.form.getlist("accesses"),
    }
    try:
        _create_single_user(data, supabase_admin)
    except Exception as e:
        print("!!! Failed to create user:", e)
        flash(f"Failed to create user: {e}")
    return redirect('/admin_user_management')


@admin_bp.route('/edit_user/<user_id>', methods=['POST'])
@require_role('admin')
def edit_user(user_id):
    supabase_admin = current_app.config['supabase_admin']

    full_name = request.form.get("full_name")
    designation = request.form.get("designation")
    phone = request.form.get("phone")
    email = request.form.get("email")
    password = request.form.get("password")
    accesses = request.form.getlist("accesses")

    try:
        supabase_admin.table("users_meta").update({
            "full_name": full_name,
            "designation": designation,
            "phone": phone,
            "email": email,
            "accesses": accesses
        }).eq("user_id", user_id).execute()

        if password:
            user_record = supabase_admin.table("users_meta").select("auth_id").eq("user_id", user_id).execute()
            if user_record.data and user_record.data[0].get("auth_id"):
                auth_id = user_record.data[0]["auth_id"]
                supabase_admin.auth.admin.update_user(auth_id, {"password": password})

        flash("User updated successfully")
    except Exception as e:
        flash(f"Failed to edit user: {e}")

    return redirect('/admin_user_management')


@admin_bp.route('/delete_user/<user_id>', methods=['POST'])
@require_role('admin')
def delete_user(user_id):
    supabase_admin = current_app.config['supabase_admin']
    try:
        supabase_admin.table("users_meta").delete().eq("user_id", user_id).execute()
    except Exception as e:
        flash(f"Failed to delete user: {e}")
    return redirect('/admin_user_management')


@admin_bp.route('/download_users_csv')
@require_role('admin')
def download_users_csv():
    supabase_admin = current_app.config['supabase_admin']
    try:
        users = supabase_admin.table("users_meta").select("*").execute()
        users = users.data if users.data else []
        output = generate_users_csv(users)
        return Response(
            output,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=users.csv"}
        )
    except Exception as e:
        return f"Failed to generate CSV: {e}", 500


# ---------------- ADMIN PROFILE ----------------
@admin_bp.route('/admin_profile')
@require_role('admin')
def admin_profile():
    user_email = session.get('user')
    user_role = session.get('role')
    return render_template('admin_profile.html', user_email=user_email, user_role=user_role)


# ---------------- DYNAMIC SIMPLE ADMIN PAGES ----------------
# Catch-all for /admin_<module_name> routes (like your old make_routes)
@admin_bp.route('/admin_<module_name>')
@require_role('admin')
def admin_module_page(module_name):
    modules = current_app.config['MODULES']
    if module_name not in modules:
        return redirect('/admin_dashboard')
    try:
        return render_template(f"admin_{module_name}.html")
    except Exception:
        # fallback if template missing
        return render_template('admin_asset_master.html')
