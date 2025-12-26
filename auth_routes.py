# auth_routes.py
from flask import Blueprint, render_template, request, redirect, session, current_app, flash, url_for
from services import require_role
import re
import os
import time
from httpx import ConnectTimeout

auth_bp = Blueprint("auth", __name__)


# --- Helpers to support different supabase-py return shapes (dict vs object) ---
def _extract_user_from_auth(resp):
    """Normalize supabase auth response to a user mapping or None."""
    if not resp:
        return None
    # If it's a dict-style response (newer clients)
    try:
        if isinstance(resp, dict):
            data = resp.get("data") or {}
            # data could be {'user': {...}, 'session': {...}}
            user = data.get("user") or data.get("user", None)
            if user:
                return user
            # fallback when sign_in_with_password returns {'user': {...}}
            return resp.get("user")
    except Exception:
        pass

    # If it's an object with attributes
    try:
        return getattr(resp, "user", None) or getattr(resp, "data", None)
    except Exception:
        return None


def _get_user_meta_field(user, field, default=None):
    if not user:
        return default
    if isinstance(user, dict):
        meta = user.get("user_metadata") or user.get("user_metadata", {})
        return meta.get(field, default) if isinstance(meta, dict) else default
    # object-style
    try:
        meta = getattr(user, "user_metadata", {})
        return meta.get(field, default) if isinstance(meta, dict) else getattr(meta, field, default)
    except Exception:
        return default

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    supabase = current_app.config['supabase']
    supabase_admin = current_app.config['supabase_admin']
    modules = current_app.config['MODULES']

    if request.method == 'POST':
        identifier = request.form.get('email')  # can be phone or email
        password = request.form.get('password')

        try:
            # ✅ Step 1: Resolve phone → email if needed
            if re.match(r'^\d{10,15}$', identifier):
                print(">>> Login attempt with phone:", identifier)
                result = supabase_admin.table("users_meta").select("email").eq("phone", identifier).execute()
                if not result.data:
                    return render_template('login.html', error="Phone not registered")
                email = result.data[0]["email"]
            else:
                email = identifier  # treat as email

            # ✅ Step 2: Authenticate with Supabase Auth (with retries for transient network/TLS errors)
            retries = int(current_app.config.get('SUPABASE_HTTP_RETRIES', int(os.getenv('SUPABASE_HTTP_RETRIES', '3'))))
            backoff = 1.0
            auth = None
            last_exc = None
            for attempt in range(1, retries + 1):
                try:
                    auth = supabase.auth.sign_in_with_password({
                        'email': email,
                        'password': password
                    })
                    if auth is not None:
                        break
                except ConnectTimeout as ct:
                    last_exc = ct
                    current_app.logger.warning("Supabase auth handshake timeout (attempt %s/%s): %s", attempt, retries, ct)
                except Exception as ex:
                    last_exc = ex
                    current_app.logger.warning("Supabase auth error (attempt %s/%s): %s", attempt, retries, ex)

                if attempt < retries:
                    time.sleep(backoff)
                    backoff *= 2

            print("--- raw auth response:", auth)
            user = _extract_user_from_auth(auth)
            # detect common error message
            auth_error = None
            if isinstance(auth, dict):
                auth_error = auth.get('error') or (auth.get('data') or {}).get('error')

            if not user:
                # Prefer last exception message if network error occurred
                if last_exc:
                    return render_template('login.html', error=f"Login failed: {str(last_exc)}")
                err_msg = auth_error or "Invalid credentials"
                return render_template('login.html', error=err_msg)

            # ✅ Step 3: Save base session info
            session['user'] = email
            session['role'] = _get_user_meta_field(user, 'role', 'user')
            print(f"+++ login ok: user={session.get('user')} role={session.get('role')}")

            # ✅ Step 4: Fetch name & permissions from users_meta
            meta = supabase_admin.table("users_meta") \
                .select("full_name, accesses, feature_accesses") \
                .eq("email", email) \
                .single() \
                .execute()
            print("+++ users_meta query result:", getattr(meta, 'data', None))

            if meta.data:
                session['name'] = meta.data.get("full_name") or _get_user_meta_field(user, 'full_name', email)

                # --- Original user accesses fetched from Supabase ---
                user_accesses = meta.data.get("accesses", [])
                session['feature_accesses'] = meta.data.get("feature_accesses", {})

                # --- ✅ Define your preferred sidebar order here ---
                ordered_pages = [
                    'user_dashboard',
                    'user_asset_master',
                    'user_daywise_fuel_consumption',
                    'user_breakdown_report',
                    'user_spares_requirements',
                    'user_maintenance_schedule',
                    'user_concrete_production',
                    'user_hire_billing_status',
                    'user_workmen_status',
                    'user_solar_report',
                    'user_digital_status',
                    'user_uauc_status',
                    'user_asset_documents_status',
                    'user_asset_green_card_status',
                    'user_daywise_works',
                    'user_profile'
                ]

                # --- ✅ Reorder the accesses based on preferred order ---
                session['accesses'] = [p for p in ordered_pages if p in user_accesses]

                print("🧭 Ordered session accesses:", session['accesses'])
            else:
                session['name'] = _get_user_meta_field(user, 'full_name', email)
                session['accesses'] = []
                session['feature_accesses'] = {}

            # ✅ Cache dropdown_config at login to avoid repeated Supabase calls on page load
            try:
                supabase_admin_cfg = supabase_admin
                if supabase_admin_cfg:
                    # reuse user_routes logic: fetch, group and store
                    dc_res = supabase_admin_cfg.table("dropdown_config").select("*").execute()
                    dc_data = sorted(dc_res.data or [], key=lambda x: (x.get("list_name", ""), x.get("value", "")))
                    dc_grouped = {}
                    for row in dc_data:
                        name = row.get("list_name") or "default"
                        dc_grouped.setdefault(name, []).append(row.get("value"))
                    session['dropdown_config'] = dc_grouped
            except Exception as e:
                current_app.logger.warning("Could not pre-cache dropdown_config at login: %s", e)

            # ✅ Step 5: Admin override (see everything)
            if session['role'] == 'admin':
                session['accesses'] = [m for m in modules]
                # Admins see all features too (optional)
                session['feature_accesses'] = {m: {} for m in modules}

            # ✅ Step 6: Keep session active for 7 days
            session.permanent = True

            # ✅ Step 7: Redirect based on role
            if session['role'] == 'admin':
                return redirect('/admin/admin_dashboard')
            else:
                return redirect('/user/dashboard')

        except Exception as e:
            print("!!! Login failed:", str(e))
            return render_template('login.html', error=f"Login failed: {str(e)}")

    # GET method (show login form)
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
            user = _extract_user_from_auth(auth)
            if not user:
                return render_template('change_password.html', error="Incorrect current password")

            # Update password
            # newer clients expect dict payload; admin update handled elsewhere
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
            user = _extract_user_from_auth(auth)
            if not user:
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