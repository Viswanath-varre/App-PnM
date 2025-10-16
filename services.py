import os
import re
import io
import csv
import secrets
import string
from flask import redirect, session, current_app, Response, url_for, flash
from functools import wraps


# ==========================================================
# ✅ 1. ROLE DECORATOR
# ==========================================================
def require_role(role=None):
    """
    Decorator to enforce login session and correct role.
    Usage:
        @require_role('admin')  -> admin only
        @require_role('user')   -> user only
        @require_role()         -> any logged-in user
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # ✅ 1. Check if session exists
            if "user" not in session:
                flash("Session expired. Please log in again.", "warning")
                return redirect('/login')

            # ✅ 2. If specific role is required, check it
            if role and session.get("role") != role:
                flash("Unauthorized access — logging out for security.", "danger")
                session.clear()
                return redirect('/login')

            # ✅ 3. Otherwise continue
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ==========================================================
# ✅ 2. DEFAULT ADMIN CREATION
# ==========================================================
def ensure_first_admin(supabase_admin, modules):
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


# ==========================================================
# ✅ 3. PASSWORD GENERATOR HELPER
# ==========================================================
def _generate_password(length=10):
    """Generate a reasonably strong random password."""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


# ==========================================================
# ✅ 4. CREATE SINGLE USER (AUTH + META)
# ==========================================================
def _create_single_user(data, supabase_admin, auto_password_fallback=True):
    """
    Create user in Supabase Auth and insert into users_meta.
    - Auto-generates password if missing.
    - Sanitizes names.
    - Returns dict with auth_id and generated_password (if created).
    """
    print(">>> Creating user with data:", data)

    # --- Clean full_name ---
    full_name = (data.get("full_name") or "").strip()
    # Allow letters, spaces, dot, hyphen, apostrophe
    full_name_clean = re.sub(r"[^A-Za-z\s\.\-']", "", full_name).strip()
    if not full_name_clean:
        full_name_clean = "Unknown User"

    # --- Validate phone ---
    phone_raw = (data.get("phone") or "").strip()
    phone_digits = re.sub(r"\D", "", phone_raw)
    if phone_digits and len(phone_digits) != 10:
        raise ValueError(f"Invalid phone number: {phone_raw}")

    # --- Required fields ---
    email = (data.get("email") or "").strip()
    if not email:
        raise ValueError("Missing email")

    role = data.get("role", "user")

    # --- Password (use provided or auto-generate) ---
    provided_password = (data.get("password") or "").strip()
    generated_password = None
    password_to_use = provided_password if provided_password else None
    if not password_to_use and auto_password_fallback:
        password_to_use = _generate_password(10)
        generated_password = password_to_use

    # --- Feature access structure ---
    feature_accesses = data.get("feature_accesses", {})

    # --- Access list normalization ---
    accesses = data.get("accesses", [])
    if isinstance(accesses, str):
        accesses = [x.strip() for x in accesses.split(",") if x.strip()]

    # --- Create Supabase Auth user ---
    try:
        auth_user = supabase_admin.auth.admin.create_user({
            "email": email,
            "password": password_to_use,
            "email_confirm": True,
            "user_metadata": {"role": role, "full_name": full_name_clean}
        })
        auth_id = getattr(auth_user.user, "id", None)
        print("✅ Created Supabase Auth user:", auth_id)
    except Exception as e:
        print("❌ Supabase Auth user creation failed:", e)
        raise

    # --- Insert into users_meta (no password stored) ---
    try:
        supabase_admin.table("users_meta").insert({
            "user_id": data.get("user_id"),
            "full_name": full_name_clean,
            "designation": data.get("designation"),
            "phone": phone_digits or None,
            "email": email,
            "accesses": accesses,
            "feature_accesses": feature_accesses,
            "role": role,
            "auth_id": auth_id
        }).execute()
    except Exception as e:
        print("❌ users_meta insert failed:", e)
        raise

    return {"success": True, "auth_id": auth_id, "generated_password": generated_password}


# ==========================================================
# ✅ 5. GENERATE DYNAMIC CSV (for user downloads)
# ==========================================================
def generate_users_csv(users):
    if not users:
        return b""

    # Detect columns dynamically but remove unwanted ones
    columns = sorted(list(users[0].keys()))
    exclude = {"auth_id", "created_at"}  # 👈 exclude these fields
    columns = [c for c in columns if c not in exclude]

    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(columns)

    for u in users:
        row = []
        for c in columns:
            val = u.get(c, "")
            if isinstance(val, list):
                val = ", ".join(str(x) for x in val)
            row.append(val)
        writer.writerow(row)

    return si.getvalue().encode("utf-8")
