# app.py
from flask import Flask, redirect
from dotenv import load_dotenv
from datetime import timedelta
import os

load_dotenv()

def create_app():
    app = Flask(__name__, template_folder='templates')
    app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))
    # Keep user sessions permanent for 30 days (approx. 1 month)
    app.permanent_session_lifetime = timedelta(days=30)

    # --- Supabase clients created once and stored in app.config ---
    from supabase import create_client
    from supabase.lib.client_options import SyncClientOptions
    from httpx import Client as HttpxClient, Timeout
    import certifi

    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

    # Configurable HTTP timeout (seconds) and debug
    try:
        http_timeout = float(os.getenv("SUPABASE_HTTP_TIMEOUT", "20"))
    except Exception:
        http_timeout = 20.0
    try:
        http_retries = int(os.getenv("SUPABASE_HTTP_RETRIES", "3"))
    except Exception:
        http_retries = 3
    http_debug = os.getenv("SUPABASE_HTTP_DEBUG", "0").lower() in ("1", "true", "yes")

    # Create a reusable httpx client with timeout, proxy support, and cert verification
    httpx_client = HttpxClient(timeout=Timeout(http_timeout), trust_env=True, verify=certifi.where())
    if http_debug:
        print(f"Supabase HTTP debug enabled; timeout={http_timeout}s, retries={http_retries}, trust_env=True, verify=certifi")

    options = SyncClientOptions(httpx_client=httpx_client, postgrest_client_timeout=http_timeout)

    # expose retry config to app for use in routes that need to retry on transient network errors
    app.config['SUPABASE_HTTP_RETRIES'] = http_retries

    app.config['supabase'] = create_client(SUPABASE_URL, SUPABASE_ANON_KEY, options=options)
    app.config['supabase_admin'] = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, options=options)

    # Modules list (cleaned and properly indented)
    app.config['MODULES'] = [
        'asset_documents_status',
        'asset_green_card_status',
        'asset_master',
        'breakdown_report',
        'concrete_production',
        'daywise_fuel_consumption',
        'daywise_works',
        'digital_status',
        'documents_status',
        'emfc_report',
        'hire_billing_status',
        'maintenance_schedule',
        'solar_report',
        'spares_requirements',
        'uauc_status',
        'workmen_status'
    ]
    
    # ------------------------------------------------------------
    # ✅  Auto-detect all user-page features from /templates
    # ------------------------------------------------------------
    from feature_registry import scan_user_templates
    app.config['FEATURE_MATRIX'] = scan_user_templates("templates")
    print("🔍 Loaded feature matrix with", len(app.config['FEATURE_MATRIX']), "user pages.")

    # Register blueprints
    from auth_routes import auth_bp
    from admin_routes import admin_bp
    from user_routes import user_bp

    app.register_blueprint(auth_bp)                     # login/logout at /login, /logout, etc.
    app.register_blueprint(admin_bp, url_prefix='/admin')     # admin routes (paths keep previous names)
    app.register_blueprint(user_bp, url_prefix='/user')      # user routes

    # home route preserves old behavior
    @app.route('/')
    def home():
        return redirect('/login')

    return app

if __name__ == "__main__":
    app = create_app()

    # Ensure first admin exists
    try:
        from services import ensure_first_admin
        import threading

        # Run admin creation in background to avoid blocking startup if Supabase is unreachable
        t = threading.Thread(target=lambda: ensure_first_admin(app.config['supabase_admin'], app.config['MODULES']))
        t.daemon = True
        t.start()
    except Exception as e:
        print("Warning: ensure_first_admin startup skipped:", e)

    app.run(host="0.0.0.0", port=5000, debug=True)
        