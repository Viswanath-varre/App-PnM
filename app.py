from flask import Flask, render_template, request, redirect, session
from supabase import create_client
from dotenv import load_dotenv
import os

# Load environment variables from .env
load_dotenv()

app = Flask(__name__, template_folder='templates')
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))

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


# ---------------- ROUTES ----------------
@app.route('/')
def home():
    return redirect('/login')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        try:
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

            if session['role'] == 'admin':
                return redirect('/admin_dashboard')
            else:
                return redirect('/user_dashboard')

        except Exception as e:
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
    return render_template(
        'admin_user_management.html',
        users=[],
        counts={'users': 0, 'admins': 0, 'active': 0},
        default_columns=['user_id', 'full_name', 'designation', 'email', 'phone', 'role']
    )


# ---------------- MODULE ROUTES ----------------
modules = [
    'asset_master',
    'asset_running_status',
    'fuel_consumption_analysis',              # matches /admin_HSD_Issued
    'break_down_report',       # matches /admin_break_down_report
    'day_wise_works',          # matches /admin_day_wise_works
    'spares_requirements',       # matches /admin.spares.requirment
    'docments_status',         # matches /admin_docments_status
    'maintenance_schedule',
    'breakdown_report',            # matches /admin_maintances_shedule
    'digital_status',
    'asset_green_card_status', 
    'asset_documents_status', 
    'daywise_works',   # matches /admin_asset_fit_unfit_status
    'uauc_status',
    'hire_billing_status',     # matches /admin_hire_billing_status
    'concrete_production',
    'solar_report',
    'workmen_status'
]



def make_routes():
    for m in modules:
        # Admin route
        def admin_page(m=m):
            return render_template(f"admin_{m}.html")
        app.add_url_rule(f"/admin_{m}", f"admin_{m}", require_role('admin')(admin_page))

        # User route
        def user_page(m=m):
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
            # Step 1: Re-authenticate user with old password 
            auth = supabase.auth.sign_in_with_password({ 
                'email': user_email,
                'password': old_password
            })

            if not auth.user:
                return render_template('change_password.html', error="Incorrect current password")

            # Step 2: Update password for logged-in user
            supabase.auth.update_user({"password": new_password})

            return redirect('/user_dashboard')

        except Exception as e:
            return render_template('change_password.html', error=str(e))

    return render_template('change_password.html')

# ---------------- MAIN ----------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)