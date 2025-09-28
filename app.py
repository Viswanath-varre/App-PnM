from flask import Flask, render_template, request, redirect, session, Response, flash
from supabase import create_client
from dotenv import load_dotenv
import os
import re
import io
import csv
from datetime import timedelta   # ✅ NEW

# Load environment variables from .env
load_dotenv()

app = Flask(__name__, template_folder='templates')
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))

# ✅ Session lifetime for "Remember Me"
app.permanent_session_lifetime = timedelta(days=7)

# Supabase setup
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

# Normal client (anon key)
supabase = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

# Admin client (service role key) – only use for admin tasks
supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


# ---------------- HELPERS ----------------
def require_role(role=None):
    def decorator(fn):
        def wrapper(*args, **kwargs):
            if 'user' not in session:
                return redirect('/login')
            if role and session.get('role') != role:
                return redirect('/login')
            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorator


def ensure_first_admin():
    """Ensure at least one admin exists in the system."""
    try:
        users = supabase_admin.table("users_meta").select("user_id").eq("role", "admin").execute()
        if not users.data:  # No admin found
            email = os.getenv("ADMIN_EMAIL", "admin@example.com")
            password = os.getenv("ADMIN_PASSWORD", "admin123")

            # Create admin in Supabase Auth
            auth_user = supabase_admin.auth.sign_up({
                "email": email,
                "password": password,
                "options": {"data": {"role": "admin"}}
            })
            auth_id = getattr(auth_user.user, "id", None)

            # Insert admin into users_meta
            supabase_admin.table("users_meta").insert({
                "user_id": "admin001",
                "full_name": "Default Admin",
                "designation": "P&M Incharge",
                "phone": "9999999999",
                "email": email,
                "accesses": modules,
                "role": "admin",
                "auth_id": auth_id
            }).execute()

            print(f"⚡ Default admin created: {email} / {password}")
    except Exception as e:
        print("!!! Failed to ensure first admin:", e)


# ---------------- ROUTES ----------------
@app.route('/')
def home():
    return redirect('/login')


@app.route('/login', methods=['GET', 'POST'])
def login():
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

            # ✅ Always fetch full_name from users_meta
            meta = supabase_admin.table("users_meta").select("full_name").eq("email", email).single().execute()
            if meta.data and meta.data.get("full_name"):
                session['name'] = meta.data["full_name"]
            else:
                session['name'] = user.user_metadata.get('full_name', email)

            # ✅ Fetch accesses for sidebar
            if session['role'] == 'user':
                result = supabase_admin.table("users_meta").select("accesses").eq("email", email).execute()
                if result.data:
                    session['accesses'] = result.data[0].get("accesses", [])
                else:
                    session['accesses'] = []
            else:
                # Admins see everything
                session['accesses'] = [m for m in modules]

            # ✅ Handle "Remember me"
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


@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')


# ---------------- DASHBOARDS ----------------
@app.route('/admin_dashboard')
@require_role('admin')
def admin_dashboard():
    return render_template('admin_dashboard.html')


@app.route('/user_dashboard')
@require_role('user')
def user_dashboard():
    return render_template('user_dashboard.html')


# ---------------- USER MANAGEMENT ----------------
@app.route('/admin_user_management')
@require_role('admin')
def admin_user_management():
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
        default_columns=['user_id', 'full_name', 'designation', 'phone', 'email', 'accesses', 'role', 'auth_id', 'created_at'],
        modules=modules
    )


@app.route('/create_users', methods=['POST'])
@require_role('admin')
def create_users():
    # If CSV upload
    if 'csv_file' in request.files:
        file = request.files['csv_file']
        if file.filename.endswith('.csv'):
            stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
            reader = csv.DictReader(stream)
            for row in reader:
                try:
                    _create_single_user(row)
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
        _create_single_user(data)
    except Exception as e:
        print("!!! Failed to create user:", e)   # log in terminal
        flash(f"Failed to create user: {e}")     # show in UI
    return redirect('/admin_user_management')


def _create_single_user(data):
    print(">>> Creating user with data:", data)  # DEBUG

    # Basic validation
    if not re.match(r'^[A-Za-z ]+$', data["full_name"]):
        raise ValueError("Full name must contain only letters and spaces")

    if not re.match(r'^\d{10}$', data["phone"]):
        raise ValueError("Phone must be 10 digits")

    role = data.get("role", "user")

    # 1. Create user in Supabase Auth
    auth_user = supabase_admin.auth.admin.create_user({
        "email": data["email"],
        "password": data["password"],
        "email_confirm": True,   # ✅ mark email confirmed
        "user_metadata": {"role": role, "full_name": data["full_name"]}
    })
    auth_id = getattr(auth_user.user, "id", None)
    print(">>> Supabase Auth create_user result:", auth_user)

    # 2. Insert into users_meta (include auth_id)
    supabase_admin.table("users_meta").insert({
        "user_id": data["user_id"],
        "full_name": data["full_name"],
        "designation": data["designation"],
        "phone": data["phone"],
        "email": data["email"],
        "accesses": data["accesses"],
        "role": role,
        "auth_id": auth_id
    }).execute()

    return True


@app.route('/edit_user/<user_id>', methods=['POST'])
@require_role('admin')
def edit_user(user_id):
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


@app.route('/delete_user/<user_id>', methods=['POST'])
@require_role('admin')
def delete_user(user_id):
    try:
        supabase_admin.table("users_meta").delete().eq("user_id", user_id).execute()
    except Exception as e:
        flash(f"Failed to delete user: {e}")
    return redirect('/admin_user_management')


@app.route('/download_users_csv')
@require_role('admin')
def download_users_csv():
    try:
        users = supabase_admin.table("users_meta").select("*").execute()
        si = io.StringIO()
        writer = csv.writer(si)
        writer.writerow(["user_id", "full_name", "designation", "phone", "email", "accesses", "role", "auth_id", "created_at"])
        for u in users.data:
            writer.writerow([
                u.get("user_id", ""),
                u.get("full_name", ""),
                u.get("designation", ""),
                u.get("phone", ""),
                u.get("email", ""),
                ",".join(u.get("accesses", [])),
                u.get("role", ""),
                u.get("auth_id", ""),
                u.get("created_at", "")
            ])
        output = si.getvalue().encode("utf-8")
        return Response(
            output,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=users.csv"}
        )
    except Exception as e:
        return f"Failed to generate CSV: {e}", 500


# ---------------- MODULE ROUTES ----------------
modules = [
    'asset_master',
    'asset_running_status',
    'fuel_consumption_analysis',
    'break_down_report',
    'day_wise_works',
    'spares_requirements',
    'docments_status',
    'maintenance_schedule',
    'breakdown_report',
    'digital_status',
    'asset_green_card_status',
    'asset_documents_status',
    'daywise_works',
    'uauc_status',
    'hire_billing_status',
    'concrete_production',
    'solar_report',
    'workmen_status'
]


def make_routes():
    for m in modules:
        def admin_page(m=m):
            return render_template(f"admin_{m}.html")
        app.add_url_rule(f"/admin_{m}", f"admin_{m}", require_role('admin')(admin_page))

        def user_page(m=m):
            if m not in session.get('accesses', []):
                return redirect('/user_dashboard')
            return render_template(f"user_{m}.html")
        app.add_url_rule(f"/user_{m}", f"user_{m}", require_role('user')(user_page))


make_routes()


# ---------------- view profile ----------------
@app.route('/user_profile')
@require_role('user')
def user_profile():
    user_email = session.get('user')
    user_role = session.get('role')
    return render_template('user_profile.html', user_email=user_email, user_role=user_role)


# ---------------- Change Password ----------------
@app.route('/change_password', methods=['GET', 'POST'])
@require_role('user')
def change_password():
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


# ---------------- MAIN ----------------
if __name__ == "__main__":
    ensure_first_admin()
    app.run(host="0.0.0.0", port=5000, debug=True)
