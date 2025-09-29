# services.py
import re
import io
import csv
from flask import redirect, session, current_app, Response

def require_role(role=None):
    """
    Decorator to enforce session and role.
    Usage: @require_role('admin') or @require_role('user') or @require_role()
    """
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


def _create_single_user(data, supabase_admin):
    """
    Creates a single user (auth + users_meta). Raises Exception if invalid.
    Mirrors the logic you used previously.
    """
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
        "email_confirm": True,
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


def generate_users_csv(users):
    """
    Given a list of users (dicts), return CSV bytes (utf-8)
    """
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(["user_id", "full_name", "designation", "phone", "email", "accesses", "role", "auth_id", "created_at"])
    for u in users:
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
    return si.getvalue().encode("utf-8")
