import os
import re
import io
import csv
import secrets
import string
from flask import redirect, session, current_app, Response, url_for, flash
from functools import wraps


# ==========================================================
# Role decorator
# ==========================================================
def require_role(role=None):
    """
    Decorator to enforce login session and correct role.
    Usage:
        @require_role('admin')  -> admin only
        @require_role('user')   -> user only (admins are also allowed)
        @require_role()         -> any logged-in user
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                flash("Session expired. Please log in again.", "warning")
                return redirect("/login")

            current_role = session.get("role")
            if role:
                role_allowed = current_role == role or (role == "user" and current_role == "admin")
                if not role_allowed:
                    flash("You are already logged in, but that page is not available for your role.", "warning")
                    if current_role == "admin":
                        return redirect("/admin/admin_dashboard")
                    return redirect("/user/dashboard")

            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ==========================================================
# Default admin creation
# ==========================================================
def ensure_first_admin(supabase_admin, modules):
    """Ensure at least one admin exists in the system."""
    try:
        users = supabase_admin.table("users_meta").select("user_id").eq("role", "admin").execute()
        if not users.data:
            email = os.getenv("ADMIN_EMAIL", "admin@example.com")
            password = os.getenv("ADMIN_PASSWORD", "admin123")

            auth_user = supabase_admin.auth.sign_up({
                "email": email,
                "password": password,
                "options": {"data": {"role": "admin"}}
            })
            auth_id = getattr(auth_user.user, "id", None)

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

            print(f"Default admin created: {email} / {password}")
    except Exception as e:
        print("Failed to ensure first admin:", e)


# ==========================================================
# Password generator helper
# ==========================================================
def _generate_password(length=10):
    """Generate a reasonably strong random password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ==========================================================
# Create single user (auth + meta)
# ==========================================================
def _create_single_user(data, supabase_admin, auto_password_fallback=True):
    """
    Create user in Supabase Auth and insert into users_meta.
    - Auto-generates password if missing.
    - Sanitizes names.
    - Returns dict with auth_id and generated_password (if created).
    """
    print(">>> Creating user with data:", data)

    full_name = (data.get("full_name") or "").strip()
    full_name_clean = re.sub(r"[^A-Za-z\s\.\-']", "", full_name).strip()
    if not full_name_clean:
        full_name_clean = "Unknown User"

    phone_raw = (data.get("phone") or "").strip()
    phone_digits = re.sub(r"\D", "", phone_raw)
    if phone_digits and len(phone_digits) != 10:
        raise ValueError(f"Invalid phone number: {phone_raw}")

    email = (data.get("email") or "").strip()
    if not email:
        raise ValueError("Missing email")

    role = data.get("role", "user")

    provided_password = (data.get("password") or "").strip()
    generated_password = None
    password_to_use = provided_password if provided_password else None
    if not password_to_use and auto_password_fallback:
        password_to_use = _generate_password(10)
        generated_password = password_to_use

    feature_accesses = data.get("feature_accesses", {})

    accesses = data.get("accesses", [])
    if isinstance(accesses, str):
        accesses = [x.strip() for x in accesses.split(",") if x.strip()]

    try:
        auth_user = supabase_admin.auth.admin.create_user({
            "email": email,
            "password": password_to_use,
            "email_confirm": True,
            "user_metadata": {"role": role, "full_name": full_name_clean}
        })
        auth_id = getattr(auth_user.user, "id", None)
        print("Created Supabase Auth user:", auth_id)
    except Exception as e:
        print("Supabase Auth user creation failed:", e)
        raise

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
        print("users_meta insert failed:", e)
        raise

    return {"success": True, "auth_id": auth_id, "generated_password": generated_password}


# ==========================================================
# Generate dynamic CSV (for user downloads)
# ==========================================================
def generate_users_csv(users):
    if not users:
        return b""

    columns = sorted(list(users[0].keys()))
    exclude = {"auth_id", "created_at"}
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
