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
    'asset_master', 'asset_running_status', 'hsd_issued', 'breakdown',
    'daywise_works', 'spares_requirements', 'asset_documents', 'maintenance_schedule',
    'digital_status', 'asset_fit_unfit', 'uauc_status', 'hire_billing',
    'concrete_production', 'workmen_status'
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


# ---------------- MAIN ----------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)
