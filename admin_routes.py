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

# ---------------- ASSET MASTER ----------------
from datetime import datetime

@admin_bp.route('/get_assets')
@require_role('admin')
def get_assets():
    supabase_admin = current_app.config['supabase_admin']
    try:
        result = supabase_admin.table("asset_master").select("*").execute()
        return result.data, 200
    except Exception as e:
        return {"error": str(e)}, 500


@admin_bp.route('/add_asset', methods=['POST'])
@require_role('admin')
def add_asset():
    supabase_admin = current_app.config['supabase_admin']
    data = request.json
    try:
        data["last_updated_by"] = session.get("name")
        data["last_updated_at"] = datetime.utcnow().isoformat()
        supabase_admin.table("asset_master").insert(data).execute()
        return {"success": True}, 201
    except Exception as e:
        return {"error": str(e)}, 500


@admin_bp.route('/update_asset/<int:asset_id>', methods=['POST'])
@require_role('admin')
def update_asset(asset_id):
    supabase_admin = current_app.config['supabase_admin']
    data = request.json
    try:
        data["last_updated_by"] = session.get("name")
        data["last_updated_at"] = datetime.utcnow().isoformat()
        supabase_admin.table("asset_master").update(data).eq("id", asset_id).execute()
        return {"success": True}, 200
    except Exception as e:
        return {"error": str(e)}, 500


@admin_bp.route('/delete_asset/<int:asset_id>', methods=['DELETE'])
@require_role('admin')
def delete_asset(asset_id):
    supabase_admin = current_app.config['supabase_admin']
    try:
        supabase_admin.table("asset_master").delete().eq("id", asset_id).execute()
        return {"success": True}, 200
    except Exception as e:
        return {"error": str(e)}, 500


@admin_bp.route('/delete_assets_bulk', methods=['POST'])
@require_role('admin')
def delete_assets_bulk():
    supabase_admin = current_app.config['supabase_admin']
    ids = request.json.get("ids", [])
    try:
        if not ids:
            return {"success": False, "error": "No IDs provided"}, 400

        batch_size = 200
        for i in range(0, len(ids), batch_size):
            supabase_admin.table("asset_master").delete().in_("id", ids[i:i+batch_size]).execute()

        return {"success": True}, 200
    except Exception as e:
        return {"success": False, "error": str(e)}, 500
    
# ---- Helper to normalize dates ----
def normalize_date(val):
    """Convert DD-MM-YYYY or YYYY-MM-DD to YYYY-MM-DD (DB format)."""
    if not val:
        return None
    try:
        return datetime.strptime(val, "%Y-%m-%d").strftime("%Y-%m-%d")
    except:
        pass
    try:
        return datetime.strptime(val, "%d-%m-%Y").strftime("%Y-%m-%d")
    except:
        return None


@admin_bp.route('/upload_assets_csv', methods=['POST'])
@require_role('admin')
def upload_assets_csv():
    supabase_admin = current_app.config['supabase_admin']
    if 'csv_file' not in request.files:
        return {"success": False, "error": "No file uploaded"}, 400

    file = request.files['csv_file']
    if not file.filename.endswith('.csv'):
        return {"success": False, "error": "Only CSV files are allowed"}, 400

    try:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        reader = csv.DictReader(stream)

        inserted = 0
        errors = []

        for i, row in enumerate(reader, start=1):
            try:
                # Normalize date fields
                if "date_of_commission" in row:
                    row["date_of_commission"] = normalize_date(row["date_of_commission"])

                # Convert numeric fields safely
                for field in ["starting_reading", "tank_capacity", "hsd_available",
                              "ehc", "additional_operator_charge", "shift_hours",
                              "operator_available", "helper_available"]:
                    if field in row and row[field]:
                        try:
                            row[field] = float(row[field])
                        except:
                            row[field] = None

                asset_data = {
                    "asset_code": row.get("asset_code"),
                    "asset_description": row.get("asset_description"),
                    "reg_no": row.get("reg_no"),
                    "package": row.get("package"),
                    "activity": row.get("activity"),
                    "location": row.get("location"),
                    "meter_type": row.get("meter_type"),
                    "uom": row.get("uom"),
                    "fuel_norms": row.get("fuel_norms"),
                    "owner": row.get("owner"),
                    "vendor_code": row.get("vendor_code"),
                    "agency": row.get("agency"),
                    "wod_number": row.get("wod_number"),
                    "vendor_mail_id": row.get("vendor_mail_id"),
                    "date_of_commission": row.get("date_of_commission"),
                    "starting_reading": row.get("starting_reading"),
                    "tank_capacity": row.get("tank_capacity"),
                    "hsd_available": row.get("hsd_available"),
                    "make": row.get("make"),
                    "model": row.get("model"),
                    "pm_make": row.get("pm_make"),
                    "pm_model": row.get("pm_model"),
                    "ehc": row.get("ehc"),
                    "additional_operator_charge": row.get("additional_operator_charge"),
                    "shift_hours": row.get("shift_hours"),
                    "operator_available": row.get("operator_available"),
                    "helper_available": row.get("helper_available"),
                    "supervisor_owner_name": row.get("supervisor_owner_name"),
                    "supervisor_owner_phone": row.get("supervisor_owner_phone"),
                    "operator1": row.get("operator1"),
                    "operator1_phone": row.get("operator1_phone"),
                    "operator1_shift": row.get("operator1_shift"),
                    "operator2": row.get("operator2"),
                    "operator2_phone": row.get("operator2_phone"),
                    "operator2_shift": row.get("operator2_shift"),
                    "last_updated_by": session.get("name"),
                    "last_updated_at": datetime.utcnow().isoformat()
                }

                supabase_admin.table("asset_master").insert(asset_data).execute()
                inserted += 1

            except Exception as row_err:
                errors.append(f"Row {i}: {row_err}")

        if errors:
            return {
                "success": False,
                "error": f"Upload completed with {len(errors)} error(s).",
                "details": errors
            }, 400

        return {"success": True, "message": f"Successfully uploaded {inserted} records."}, 200

    except Exception as e:
        err_msg = str(e)
        if "date/time field value out of range" in err_msg:
            return {"success": False, "error": "Invalid date format. Please use DD-MM-YYYY (e.g., 25-08-2025)."}, 400
        return {"success": False, "error": "Upload failed. Please check your CSV data."}, 400


@admin_bp.route('/download_assets_csv')
@require_role('admin')
def download_assets_csv():
    supabase_admin = current_app.config['supabase_admin']
    try:
        assets = supabase_admin.table("asset_master").select("*").execute()
        assets = assets.data if assets.data else []
        si = io.StringIO()
        writer = csv.writer(si)
        writer.writerow([
            "id","asset_code","asset_description","reg_no","package","activity","location",
            "meter_type","uom","fuel_norms","owner","vendor_code","agency","wod_number",
            "vendor_mail_id","date_of_commission","starting_reading","tank_capacity","hsd_available",
            "make","model","pm_make","pm_model","ehc","ihc",
            "additional_operator_charge","shift_hours",
            "operator_available","helper_available",
            "supervisor_owner_name","supervisor_owner_phone",
            "operator1","operator1_phone","operator1_shift",
            "operator2","operator2_phone","operator2_shift",
            "last_updated_by","last_updated_at"
        ])
        for a in assets:
            writer.writerow([
                a.get("id"), a.get("asset_code"), a.get("asset_description"), a.get("reg_no"),
                a.get("package"), a.get("activity"), a.get("location"), a.get("meter_type"),
                a.get("uom"), a.get("fuel_norms"), a.get("owner"), a.get("vendor_code"), a.get("agency"),
                a.get("wod_number"), a.get("vendor_mail_id"), a.get("date_of_commission"), a.get("starting_reading"),
                a.get("tank_capacity"), a.get("hsd_available"), a.get("make"), a.get("model"),
                a.get("pm_make"), a.get("pm_model"), a.get("ehc"), a.get("ihc"),
                a.get("additional_operator_charge"), a.get("shift_hours"),
                a.get("operator_available"), a.get("helper_available"),
                a.get("supervisor_owner_name"), a.get("supervisor_owner_phone"),
                a.get("operator1"), a.get("operator1_phone"), a.get("operator1_shift"),
                a.get("operator2"), a.get("operator2_phone"), a.get("operator2_shift"),
                a.get("last_updated_by"), a.get("last_updated_at")
            ])
        output = si.getvalue().encode("utf-8")
        return Response(
            output,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=asset_master.csv"}
        )
    except Exception as e:
        return {"error": str(e)}, 500


@admin_bp.route('/download_assets_template_csv')
@require_role('admin')
def download_assets_template_csv():
    headers = [
        "asset_code","asset_description","reg_no","package","activity","location",
        "meter_type","uom","fuel_norms","owner","vendor_code","agency","wod_number",
        "vendor_mail_id","date_of_commission","starting_reading","tank_capacity",
        "hsd_available","make","model","pm_make","pm_model","ehc",
        "additional_operator_charge","shift_hours","operator_available","helper_available",
        "supervisor_owner_name","supervisor_owner_phone","operator1","operator1_phone",
        "operator1_shift","operator2","operator2_phone","operator2_shift"
    ]
    si = io.StringIO()
    writer = csv.writer(si)
    writer.writerow(headers)
    output = si.getvalue().encode("utf-8")
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=asset_master_template.csv"}
    )

# ---------------- ADD ASSET PAGES ----------------
@admin_bp.route('/admin_add_asset')
@require_role('admin')
def admin_add_asset_page():
    return render_template("admin_add_asset.html")

@admin_bp.route('/admin_edit_asset/<int:asset_id>')
@require_role('admin')
def admin_edit_asset_page(asset_id):
    supabase_admin = current_app.config['supabase_admin']
    asset = supabase_admin.table("asset_master").select("*").eq("id", asset_id).execute()
    if asset.data:
        return render_template("admin_edit_asset.html", asset=asset.data[0])
    else:
        return "Asset not found", 404