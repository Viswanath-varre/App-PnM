# app.py
from flask import Flask, redirect
from dotenv import load_dotenv
from datetime import timedelta
import os

load_dotenv()

def create_app():
    app = Flask(__name__, template_folder='templates')
    app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))
    app.permanent_session_lifetime = timedelta(days=7)

    # --- Supabase clients created once and stored in app.config ---
    from supabase import create_client
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    app.config['supabase'] = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    app.config['supabase_admin'] = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)

    # Modules list (same as before)
    app.config['MODULES'] = [
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

    # Register blueprints
    from auth_routes import auth_bp
    from admin_routes import admin_bp
    from user_routes import user_bp

    app.register_blueprint(auth_bp)                     # login/logout at /login, /logout, etc.
    app.register_blueprint(admin_bp, url_prefix='')     # admin routes (paths keep previous names)
    app.register_blueprint(user_bp, url_prefix='')      # user routes

    # home route preserves old behavior
    @app.route('/')
    def home():
        return redirect('/login')

    return app


if __name__ == "__main__":
    app = create_app()

    # Ensure first admin exists (keeps same logic)
    from services import ensure_first_admin
    ensure_first_admin(app.config['supabase_admin'], app.config['MODULES'])

    app.run(host="0.0.0.0", port=5000, debug=True)
