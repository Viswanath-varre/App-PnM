# ==============================================================================
# 1. IMPORTS & INITIALIZATION
# Used for: Setting up Flask, importing necessary libraries, handling timezones, 
# and defining the Blueprint for the admin module.
# ==============================================================================
import io
import csv
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flask import (Blueprint, render_template, request, redirect, session, 
                   flash, Response, current_app, jsonify, url_for, stream_with_context)
from services import require_role, _create_single_user, generate_users_csv

# Define India Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

admin_bp = Blueprint("admin", __name__)


# ==============================================================================
# 2. DASHBOARD & PROFILE ROUTES
# Used for: Rendering the main admin dashboard and the admin's personal profile.
# ==============================================================================

@admin_bp.route('/admin_dashboard')
@require_role('admin')
def admin_dashboard():
    """Renders the main landing page for the admin panel."""
    return render_template('admin_dashboard.html')

@admin_bp.route('/admin_profile')
@require_role('admin')
def admin_profile():
    """Renders the profile view for the currently logged-in admin."""
    user_email = session.get('user')
    user_role = session.get('role')
    return render_template('admin_profile.html', user_email=user_email, user_role=user_role)


# ==============================================================================
# 3. USER MANAGEMENT (FRONTEND & API)
# Used for: Viewing users, refreshing permissions/features, adding/editing/deleting 
# users, and downloading user lists.
# ==============================================================================

@admin_bp.route('/admin_user_management')
@require_role('admin')
def admin_user_management():
    """Renders the main user management dashboard and calculates user counts."""
    supabase_admin = current_app.config['supabase_admin']
    modules = current_app.config['MODULES']

    users = supabase_admin.table("users_meta").select("*").execute()
    users = users.data if users.data else []

    counts = {
        "users": len(users),
        "admins": sum(1 for u in users if u.get("role") == "admin"),
        "active": len(users) 
    }

    return render_template(
        'admin_user_management.html',
        users=users,
        counts=counts,
        default_columns=[
            'user_id', 'full_name', 'designation', 'phone', 'email',
            'accesses', 'role', 'auth_id', 'created_at'
        ],
        modules=modules,
        feature_matrix=current_app.config['FEATURE_MATRIX']
    )

@admin_bp.route('/refresh_feature_matrix', methods=['POST'])
@require_role('admin')
def refresh_feature_matrix():
    """Scans templates to refresh the available features/modules matrix."""
    try:
        from feature_registry import scan_user_templates
        fm = scan_user_templates("templates")
        current_app.config['FEATURE_MATRIX'] = fm
        return jsonify({"success": True, "pages": len(fm)})
    except Exception as e:
        current_app.logger.error(f"Failed to refresh feature matrix: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/add_user', methods=['POST'])
@require_role('admin')
def add_user():
    """Creates a new user in Supabase Auth and saves metadata to DB."""
    supabase_admin = current_app.config['supabase_admin']
    full_name = request.form.get('full_name')
    email = request.form.get('email')
    phone = request.form.get('phone', '')
    designation = request.form.get('designation', '')
    role = request.form.get('role')
    password = request.form.get('password')

    try:
        # 1. Create user in Supabase Auth System
        auth_res = supabase_admin.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True
        })
        auth_id = auth_res.user.id

        # 2. Save user profile to database
        supabase_admin.table('users_meta').insert({
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "designation": designation,
            "role": role,
            "auth_id": auth_id
        }).execute()

        flash(f"User {full_name} created successfully!", "success")
    except Exception as e:
        current_app.logger.error(f"Error adding user: {e}")
        flash(f"Error creating user: {str(e)}", "error")

    # Redirect back to wherever they came from
    return redirect(request.referrer or '/admin/user_management')

@admin_bp.route('/edit_user/<user_id>', methods=['POST'])
@require_role('admin')
def edit_user(user_id):
    """Updates an existing user's metadata/profile details."""
    supabase_admin = current_app.config['supabase_admin']
    full_name = request.form.get('full_name')
    designation = request.form.get('designation', '')
    role = request.form.get('role')

    try:
        supabase_admin.table('users_meta').update({
            "full_name": full_name,
            "designation": designation,
            "role": role
        }).eq("user_id", user_id).execute()

        flash(f"User {full_name} updated successfully!", "success")
    except Exception as e:
        current_app.logger.error(f"Error updating user: {e}")
        flash(f"Error updating user: {str(e)}", "error")

    return redirect(request.referrer or '/admin/user_management')

@admin_bp.route('/delete_user/<user_id>', methods=['POST'])
@require_role('admin')
def delete_user(user_id):
    """Deletes a user record based on user_id."""
    supabase_admin = current_app.config['supabase_admin']
    try:
        supabase_admin.table("users_meta").delete().eq("user_id", user_id).execute()
    except Exception as e:
        flash(f"Failed to delete user: {e}")
    return redirect(url_for('admin.admin_user_management'))

@admin_bp.route('/download_users_csv')
@require_role('admin')
def download_users_csv():
    """Generates and downloads a CSV file of all registered users."""
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


# ==============================================================================
# 4. DYNAMIC ROLE & PERMISSIONS MANAGEMENT (API)
# Used for: Fetching, saving, and deleting custom roles and permissions.
# ==============================================================================

@admin_bp.route('/get_roles', methods=['GET'])
@require_role('admin')
def get_roles():
    """Fetches all roles and their associated permissions."""
    supabase_admin = current_app.config['supabase_admin']
    try:
        res = supabase_admin.table("roles_permissions").select("*").execute()
        return jsonify({"success": True, "roles": res.data}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/save_role', methods=['POST'])
@require_role('admin')
def save_role():
    """Creates a new role or updates an existing one."""
    supabase_admin = current_app.config['supabase_admin']
    data = request.json
    role_name = data.get("role_name")
    accesses = data.get("accesses", [])
    feature_accesses = data.get("feature_accesses", {})

    if not role_name:
        return jsonify({"success": False, "error": "Role name is required"}), 400

    try:
        # Check if role already exists
        existing = supabase_admin.table("roles_permissions").select("id").eq("role_name", role_name).execute()
        if existing.data and len(existing.data) > 0:
            # Update existing role
            supabase_admin.table("roles_permissions").update({
                "accesses": accesses,
                "feature_accesses": feature_accesses
            }).eq("role_name", role_name).execute()
        else:
            # Insert new role
            supabase_admin.table("roles_permissions").insert({
                "role_name": role_name,
                "accesses": accesses,
                "feature_accesses": feature_accesses
            }).execute()
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/delete_role/<int:role_id>', methods=['DELETE'])
@require_role('admin')
def delete_role(role_id):
    """Deletes a specific role by ID."""
    supabase_admin = current_app.config['supabase_admin']
    try:
        supabase_admin.table("roles_permissions").delete().eq("id", role_id).execute()
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500  


# ==============================================================================
# 5. ASSET MASTER (FRONTEND PAGES)
# Used for: Rendering the UI pages related to viewing, adding, and editing assets.
# ==============================================================================

@admin_bp.route('/admin_asset_master')
@require_role('admin')
def admin_asset_master_page():
    """Renders the main Asset Master tracking page."""
    return render_template("admin_asset_master.html")

@admin_bp.route('/admin_add_asset')
@require_role('admin')
def admin_add_asset_page():
    """Renders the form to manually add a new asset."""
    return render_template("admin_add_asset.html")

@admin_bp.route('/admin_edit_asset/<int:asset_id>')
@require_role('admin')
def admin_edit_asset_page(asset_id):
    """Renders the edit form for a specific asset."""
    supabase_admin = current_app.config['supabase_admin']
    asset = supabase_admin.table("asset_master").select("*").eq("id", asset_id).execute()
    if asset.data:
        return render_template("admin_edit_asset.html", asset=asset.data[0])
    else:
        return "Asset not found", 404


# ==============================================================================
# 6. ASSET MASTER (API ENDPOINTS)
# Used for: CRUD operations for assets, bulk deletions, and CSV Uploads/Downloads.
# ==============================================================================

@admin_bp.route('/get_assets')
@require_role('admin')
def get_assets():
    """Fetches all assets from the database."""
    supabase_admin = current_app.config['supabase_admin']
    try:
        result = supabase_admin.table("asset_master").select("*").execute()
        return jsonify(result.data), 200
    except Exception as e:
        return {"error": str(e)}, 500

@admin_bp.route('/add_asset', methods=['POST'])
@require_role('admin')
def add_asset():
    """Inserts a new asset record."""
    supabase_admin = current_app.config['supabase_admin']
    data = request.json
    try:
        data["last_updated_by"] = session.get("name")
        data["last_updated_at"] = datetime.now(IST).isoformat()
        supabase_admin.table("asset_master").insert(data).execute()
        return {"success": True}, 201
    except Exception as e:
        return {"error": str(e)}, 500

@admin_bp.route('/update_asset/<asset_id>', methods=['POST'])
@require_role('admin')
def update_asset(asset_id):
    """Updates an existing asset record."""
    supabase_admin = current_app.config['supabase_admin']
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        result = supabase_admin.table("asset_master").update(data).eq("id", asset_id).execute()
        if not result.data:
            return jsonify({"success": False, "error": "Asset not found"}), 404

        return jsonify({"success": True}), 200
    except Exception as e:
        current_app.logger.error(f"Error updating asset {asset_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/delete_asset/<int:asset_id>', methods=['DELETE'])
@require_role('admin')
def delete_asset(asset_id):
    """Deletes a single asset."""
    supabase_admin = current_app.config['supabase_admin']
    try:
        supabase_admin.table("asset_master").delete().eq("id", asset_id).execute()
        return {"success": True}, 200
    except Exception as e:
        return {"error": str(e)}, 500

@admin_bp.route('/delete_assets_bulk', methods=['POST'])
@require_role('admin')
def delete_assets_bulk():
    """Deletes multiple assets in batched requests to avoid timeout/limits."""
    supabase_admin = current_app.config['supabase_admin']
    ids = request.json.get("ids", [])
    try:
        if not ids:
            return {"success": False, "error": "No IDs provided"}, 400

        batch_size = 200
        for i in range(0, len(ids), batch_size):
            supabase_admin.table("asset_master").delete().in_("id", ids[i:i + batch_size]).execute()

        return {"success": True}, 200
    except Exception as e:
        return {"success": False, "error": str(e)}, 500


def normalize_date(val):
    """Helper utility function to clean up date formatting before DB insert."""
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
    """Parses an uploaded CSV file and inserts assets in bulk."""
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
                if "date_of_commission" in row:
                    row["date_of_commission"] = normalize_date(row["date_of_commission"])

                for field in ["starting_reading", "tank_capacity", "hsd_available",
                              "ehc", "ihc","additional_operator_charge", "shift_hours",
                              "operator_available", "helper_available"]:
                    if field in row and str(row[field]).strip():
                        try:
                            row[field] = float(row[field])
                        except:
                            row[field] = None

                asset_data = {
                    "asset_code": row.get("asset_code"),
                    "asset_description": row.get("asset_description"),
                    "asset_category": row.get("asset_category"),
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
                    "ihc": row.get("ihc"),
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
                    "last_updated_at": datetime.now(IST).isoformat()
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
    """Generates and downloads a CSV export of the asset master table."""
    supabase_admin = current_app.config['supabase_admin']
    try:
        assets = supabase_admin.table("asset_master").select("*").execute()
        assets = assets.data if assets.data else []

        if not assets:
            return {"error": "No assets found"}, 404

        headers = list(assets[0].keys())
        headers.sort()

        si = io.StringIO()
        writer = csv.writer(si)
        writer.writerow(headers)
        for a in assets:
            writer.writerow([a.get(h, "") for h in headers])

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
    """Provides an empty CSV template with headers for bulk uploading assets."""
    supabase_admin = current_app.config['supabase_admin']
    try:
        result = supabase_admin.table("asset_master").select("*").limit(1).execute()
        if not result.data:
            result = supabase_admin.table("asset_master").select("*").execute()
        sample = result.data[0] if result.data else {}

        headers = list(sample.keys()) if sample else ["asset_code", "activity", "location"]
        headers.sort()

        si = io.StringIO()
        writer = csv.writer(si)
        writer.writerow(headers)
        output = si.getvalue().encode("utf-8")

        return Response(
            output,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment;filename=asset_master_template.csv"}
        )
    except Exception as e:
        return {"error": f"Failed to generate template: {e}"}, 500


# ==============================================================================
# 7. DE-HIRED ASSETS (API ENDPOINTS)
# Used for: Archiving/removing active assets and saving them in the de_hired table.
# ==============================================================================

# Note: Local import retained from original source.
from datetime import datetime 

@admin_bp.route('/dehire_asset/<int:asset_id>', methods=['POST'])
@require_role('admin')
def dehire_asset(asset_id):
    """Moves an asset from the active asset_master into the de_hired_assets table."""
    try:
        supabase_admin = current_app.config['supabase_admin']
        data = request.json
        
        # 1. Fetch the original asset from the 'asset_master' table (FIXED TABLE NAME)
        asset_response = supabase_admin.table('asset_master').select('*').eq('id', asset_id).execute()
        if not asset_response.data:
            return jsonify({'success': False, 'error': 'Asset not found'})
            
        original_asset = asset_response.data[0]
        
        # 2. Build the payload for the de_hired_assets table
        dehired_payload = {
            'asset_code': original_asset.get('asset_code'),
            'asset_description': original_asset.get('asset_description'),
            'asset_category': original_asset.get('asset_category'),
            'reg_no': original_asset.get('reg_no'),
            'meter_type': original_asset.get('meter_type'),
            'uom': original_asset.get('uom'),
            'fuel_norms': original_asset.get('fuel_norms'),
            'owner': original_asset.get('owner'),
            'vendor_code': original_asset.get('vendor_code'),
            'agency': original_asset.get('agency'),
            'wod_number': original_asset.get('wod_number'),
            'vendor_mail_id': original_asset.get('vendor_mail_id'),
            'date_of_commission': original_asset.get('date_of_commission'),
            'starting_reading': original_asset.get('starting_reading'),
            'tank_capacity': original_asset.get('tank_capacity'),
            'hsd_available': original_asset.get('hsd_available'),
            
            # New De-Hire specific fields
            'date_of_dehire': data.get('date_of_dehire'),
            'end_reading': data.get('end_reading'),
            'hsd_at_dehire': data.get('hsd_at_dehire'),
            'reason': data.get('reason'),
            
            'make': original_asset.get('make'),
            'model': original_asset.get('model'),
            'pm_make': original_asset.get('pm_make'),
            'pm_model': original_asset.get('pm_model'),
            'ehc': original_asset.get('ehc'),
            'ihc': original_asset.get('ihc'),
            'shift_hours': original_asset.get('shift_hours'),
            'last_updated_by': session.get('name', 'Admin'),
            'last_updated_at': datetime.utcnow().isoformat()
        }

        # 3. Insert into de_hired_assets
        supabase_admin.table('de_hired_assets').insert(dehired_payload).execute()
        
        # 4. Delete from active assets table (FIXED TABLE NAME)
        supabase_admin.table('asset_master').delete().eq('id', asset_id).execute()
        
        return jsonify({'success': True, 'message': 'Asset successfully de-hired'})

    except Exception as e:
        current_app.logger.error(f"Error de-hiring asset: {e}")
        return jsonify({'success': False, 'error': str(e)})    

@admin_bp.route('/get_dehired_assets', methods=['GET'])
@require_role('admin')
def get_dehired_assets():
    """Fetches all assets from the de_hired_assets table."""
    supabase_admin = current_app.config['supabase_admin']
    try:
        # Fetch all records from the de_hired_assets table
        result = supabase_admin.table("de_hired_assets").select("*").execute()
        return jsonify(result.data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/update_dehired_asset/<int:asset_id>', methods=['POST'])
@require_role('admin')
def update_dehired_asset(asset_id):
    """Updates specifics of an already de-hired asset via Edit Modal."""
    supabase_admin = current_app.config['supabase_admin']
    data = request.json
    try:
        # Update payload mapping based on frontend submission
        update_payload = {
            'date_of_dehire': data.get('date_of_dehire'),
            'end_reading': data.get('end_reading'),
            'hsd_at_dehire': data.get('hsd_at_dehire'),
            'reason': data.get('reason'),
            'last_updated_by': session.get('name', 'Admin'),
            'last_updated_at': datetime.now(IST).isoformat()
        }
        
        supabase_admin.table('de_hired_assets').update(update_payload).eq('id', asset_id).execute()
        return jsonify({'success': True, 'message': 'De-hired details updated successfully'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500    


# ==============================================================================
# 8. SPARES REQUIREMENTS (FRONTEND & API)
# Used for: Managing mechanical/inventory spare parts requests and status.
# ==============================================================================

@admin_bp.route('/admin_spares_requirements')
@require_role('admin')
def admin_spares_requirements_page():
    """Renders the UI page for tracking Spare Parts Requirements."""
    user_obj = {
        'get_full_name': session.get('name') or '',
        'username': session.get('user') or ''
    }
    modules = current_app.config.get('MODULES', [])
    return render_template('admin_spares_requirements.html', user=user_obj, modules=modules)

@admin_bp.route('/get_spares')
@require_role('admin')
def admin_get_spares():
  """Fetches and formats all spare part requests."""
  supabase_admin = current_app.config['supabase_admin']
  try:
    res = supabase_admin.table("spares_requirements").select("*").order("created_at", desc=True).execute()
    rows = res.data if res.data else []
    out = []
    for r in rows:
      created = r.get("created_at")
      status_up = r.get("status_updated_at")
      created_fmt = created
      status_fmt = status_up
      try:
        if created:
          dt = datetime.fromisoformat(created)
          dt = dt.astimezone(IST)
          created_fmt = dt.strftime("%d-%m-%Y %I:%M %p")
        if status_up:
          dt2 = datetime.fromisoformat(status_up)
          dt2 = dt2.astimezone(IST)
          status_fmt = dt2.strftime("%d-%m-%Y %I:%M %p")
      except:
        pass

      out.append({
        "id": r.get("id"),
        "ref_no": r.get("ref_no") or r.get("ref_number"),
        "priority": r.get("priority"),
        "for_type": r.get("for_type"),
        "asset_code": r.get("asset_code"),
        "asset_description": r.get("asset_description"),
        "required_by": r.get("required_by"),
        "required_by_raw": r.get("required_by"),
        "title": r.get("title") or r.get("requisition") or "",
        "requisition": r.get("requisition"),
        "spares_req": r.get("spares_req") or r.get("spare_requirement"),
        "current_status": r.get("current_status"),
        "actioner": r.get("actioner"),
        "dc_required": r.get("dc_required") if "dc_required" in r else r.get("is_dc"),
        "dc_number": r.get("dc_number"),
        "created_at": created_fmt,
        "status_updated_at": status_fmt,
        "status": r.get("status"),
        "closed": r.get("closed") if "closed" in r else (r.get("status") == "Closed"),
        "created_by": r.get("created_by"),
        "metadata": r.get("metadata")
      })
    return jsonify(out), 200
  except Exception as e:
    current_app.logger.error(f"admin_get_spares error: {e}")
    return jsonify({"error": str(e)}), 500

@admin_bp.route('/get_spares_counts')
@require_role('admin')
def admin_get_spares_counts():
    """Generates a summary of active vs total spare requirements."""
    supabase_admin = current_app.config['supabase_admin']
    try:
        res = supabase_admin.table("spares_requirements").select("id, status, closed, created_at, last_updated_at").execute()
        rows = res.data if res.data else []
        total = len(rows)
        active = 0
        latest = None

        def parse_bool(val):
            if isinstance(val, bool):
                return val
            if val is None:
                return False
            s = str(val).strip().lower()
            return s in ("1", "true", "t", "yes", "y")

        def parse_dt(cand):
            if not cand:
                return None
            s = str(cand)
            if s.endswith('Z'):
                s = s[:-1] + '+00:00'
            try:
                return datetime.fromisoformat(s)
            except Exception:
                formats = ["%Y-%m-%d %H:%M:%S", "%d-%m-%Y %I:%M %p", "%Y-%m-%d"]
                for fmt in formats:
                    try:
                        return datetime.strptime(s, fmt)
                    except Exception:
                        continue
            return None

        for r in rows:
            closed_raw = r.get('closed') if 'closed' in r else None
            status_raw = r.get('status') or ''
            closed = parse_bool(closed_raw) or (str(status_raw).strip().lower() == 'closed')
            if not closed:
                active += 1
            cand = r.get('status_updated_at') or r.get('last_updated_at') or r.get('created_at')
            dt = parse_dt(cand)
            if dt:
                if latest is None or dt > latest:
                    latest = dt

        if latest:
            try:
                latest_iso = latest.astimezone(IST).isoformat()
            except Exception:
                latest_iso = latest.isoformat()
        else:
            latest_iso = datetime.now(IST).isoformat()

        return jsonify({"counts": {"active": active, "total": total}, "updated_at": latest_iso}), 200
    except Exception as e:
        current_app.logger.error(f"admin_get_spares_counts error: {e}")
        return jsonify({"counts": {"active": 0, "total": 0}, "updated_at": datetime.now(IST).isoformat(), "error": str(e)}), 500

@admin_bp.route('/get_spares_next_ref')
@require_role('admin')
def admin_get_spares_next_ref():
  """Generates the next sequential reference number for spares requests."""
  supabase_admin = current_app.config['supabase_admin']
  try:
    res = supabase_admin.table("spares_requirements").select("ref_no").order("id", desc=True).limit(1).execute()
    last = None
    if res.data and len(res.data) > 0:
      last = res.data[0].get("ref_no") or res.data[0].get("ref_number")
    if last:
      try:
        num = int(last)
      except:
        try:
          num = int(str(last).lstrip("0") or "0")
        except:
          num = 0
    else:
      num = 0
    next_ref = str(num + 1).zfill(4)
    return jsonify({"next_ref": next_ref}), 200
  except Exception as e:
    current_app.logger.error(f"admin_get_spares_next_ref error: {e}")
    return jsonify({"next_ref": "0001"}), 200

@admin_bp.route('/create_spare', methods=['POST'])
@require_role('admin')
def admin_create_spare():
  """Inserts a new spare parts request into the database."""
  supabase_admin = current_app.config['supabase_admin']
  data = request.get_json() or {}
  try:
    ref_no = data.get("ref_no")
    if not ref_no:
      r = supabase_admin.table("spares_requirements").select("ref_no").order("id", desc=True).limit(1).execute()
      last = None
      if r.data and len(r.data) > 0:
        last = r.data[0].get("ref_no") or r.data[0].get("ref_number")
      if last:
        try:
          num = int(last)
        except:
          try:
            num = int(str(last).lstrip("0") or "0")
          except:
            num = 0
      else:
        num = 0
      ref_no = str(num + 1).zfill(4)

    payload = {
      "ref_no": ref_no,
      "priority": data.get("priority"),
      "for_type": data.get("for_type"),
      "asset_code": data.get("asset_code"),
      "asset_description": data.get("asset_description"),
      "required_by": data.get("required_by"),
      "requisition": data.get("requisition"),
      "spares_req": data.get("spares_req"),
      "current_status": data.get("current_status") or "Active",
      "actioner": data.get("actioner") or session.get("name") or session.get("user"),
      "dc_required": bool(data.get("dc_required")),
      "dc_number": data.get("dc_number"),
      "status": data.get("status") or "Active",
      "closed": bool(data.get("closed", False)),
      "created_by": session.get("user") or session.get("name"),
      "metadata": data.get("metadata") or {},
      "created_at": datetime.now(IST).isoformat(),
      "status_updated_at": datetime.now(IST).isoformat()
    }

    supabase_admin.table("spares_requirements").insert(payload).execute()
    return jsonify({"success": True, "ref_no": ref_no}), 201
  except Exception as e:
    current_app.logger.error(f"admin_create_spare error: {e}")
    return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/update_spare/<int:spare_id>', methods=['POST'])
@require_role('admin')
def admin_update_spare(spare_id):
  """Updates details for a specific active spares requirement."""
  supabase_admin = current_app.config['supabase_admin']
  data = request.get_json() or {}
  try:
    update = {}
    for field in ["priority", "for_type", "asset_code", "asset_description", "required_by",
                  "requisition", "spares_req", "current_status", "actioner", "dc_required",
                  "dc_number", "status", "created_by", "metadata"]:
      if field in data:
        update[field] = data.get(field)
    if "dc_required" in update:
      update["dc_required"] = bool(update["dc_required"])
    if "closed" in data:
      update["closed"] = bool(data.get("closed"))
    update["status_updated_at"] = datetime.now(IST).isoformat()

    supabase_admin.table("spares_requirements").update(update).eq("id", spare_id).execute()
    return jsonify({"success": True}), 200
  except Exception as e:
    current_app.logger.error(f"admin_update_spare error: {e}")
    return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/close_spare/<int:spare_id>', methods=['POST'])
@require_role('admin')
def admin_close_spare(spare_id):
  """Marks a spare parts request as closed."""
  supabase_admin = current_app.config['supabase_admin']
  try:
    update = {
      "closed": True,
      "status": "Closed",
      "current_status": "Closed",
      "status_updated_at": datetime.now(IST).isoformat(),
      "actioner": session.get("name") or session.get("user")
    }
    supabase_admin.table("spares_requirements").update(update).eq("id", spare_id).execute()
    return jsonify({"success": True}), 200
  except Exception as e:
    current_app.logger.error(f"admin_close_spare error: {e}")
    return jsonify({"success": False, "error": str(e)}), 500

@admin_bp.route('/delete_spare/<int:spare_id>', methods=['DELETE'])
@require_role('admin')
def admin_delete_spare(spare_id):
    """Deletes a spare parts request entirely."""
    supabase_admin = current_app.config['supabase_admin']
    try:
        current_app.logger.debug(f"admin_delete_spare called for id={spare_id}, session_user={session.get('user')}")
        res = supabase_admin.table("spares_requirements").delete().eq("id", spare_id).execute()

        err = getattr(res, 'error', None)
        if err:
            current_app.logger.error(f"admin_delete_spare supabase error for id={spare_id}: {err}")
            return jsonify({"success": False, "error": str(err)}), 500

        deleted = getattr(res, 'data', None)

        if not deleted or (isinstance(deleted, list) and len(deleted) == 0):
            current_app.logger.warning(f"admin_delete_spare: no rows deleted for id={spare_id} (res.data={deleted})")
            return jsonify({"success": False, "error": "No record found to delete"}), 404

        current_app.logger.info(f"admin_delete_spare: deleted id={spare_id}, deleted_rows={deleted}")
        return jsonify({"success": True, "deleted": deleted}), 200
    except Exception as 2e:
        current_app.logger.error(f"admin_delete_spare error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500

# ==============================================================================
# 9. GENERAL / DYNAMIC MODULE ROUTING
# Used for: Fallback rendering for dynamic admin modules in configuration.
# ==============================================================================

@admin_bp.route('/admin_<module_name>')
@require_role('admin')
def admin_module_page(module_name):
    """Dynamically serves HTML templates based on registered modules."""
    modules = current_app.config.get('MODULES', [])
    if module_name not in modules:
        return redirect(url_for('admin.admin_dashboard'))
    try:
        return render_template(f"admin_{module_name}.html")
    except Exception:
        return render_template('admin_asset_master.html')


# ==============================================================================
# 10. SYSTEM CONFIGURATION / DROPDOWNS (API)
# Used for: Managing lookup data (e.g., categories, uom, locations) for dropdowns.
# ==============================================================================

@admin_bp.route('/dropdown_config', methods=['GET'])
@require_role('admin')
def admin_get_dropdown_config():
    """Retrieves all grouped dictionary values for system dropdown configurations."""
    supabase_admin = current_app.config['supabase_admin']
    try:
        result = supabase_admin.table("dropdown_config").select("*").execute()
        data = sorted(result.data or [], key=lambda x: (x["list_name"], x["value"]))
        grouped = {}
        for row in data:
            grouped.setdefault(row["list_name"], []).append({"value": row["value"], "id": row["id"]})
        return jsonify(grouped), 200
    except Exception as e:
        current_app.logger.error(f"dropdown_config GET error: {e}")
        return jsonify({"error": str(e)}), 500

@admin_bp.route('/update_dropdown', methods=['POST'])
@require_role('admin')
def admin_update_dropdown():
    """Adds or removes single values from the dropdown_config lookup table."""
    supabase_admin = current_app.config['supabase_admin']
    data = request.get_json() or {}
    action = data.get("action")
    list_name = data.get("list_name")
    value = data.get("value")

    if not action or not list_name or not value:
        return jsonify({"success": False, "error": "Missing action/list_name/value"}), 400

    try:
        if action == "add":
            supabase_admin.table("dropdown_config").insert({"list_name": list_name, "value": value}).execute()
        elif action == "remove":
            supabase_admin.table("dropdown_config").delete().eq("list_name", list_name).eq("value", value).execute()
        else:
            return jsonify({"success": False, "error": "Invalid action"}), 400

        return jsonify({"success": True}), 200
    except Exception as e:
        current_app.logger.error(f"update_dropdown error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
    from flask import Blueprint, request, jsonify, render_template, session
from datetime import datetime
import pytz

# Assuming you have a Supabase client initialized in your app
from database import supabase  # Adjust this import to match your project structure

admin_breakdowns_bp = Blueprint('admin_breakdowns', __name__, url_prefix='/admin/breakdowns')

# -----------------------------------------------------------------------------
# UTILITY FUNCTION: Calculate Hours Difference
# -----------------------------------------------------------------------------
def calc_hours_diff(start_str, end_str):
    """Calculates the difference in hours between two ISO 8601 datetime strings."""
    if not start_str or not end_str:
        return 0.0
    try:
        # Parse ISO strings to datetime objects
        start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
        diff = end - start
        return round(diff.total_seconds() / 3600, 2)
    except Exception:
        return 0.0



# ==============================================================================
# 11. ADMIN BREAKDOWN REPORTS 
# ==============================================================================
import pytz

def calc_hours_diff(start_str, end_str):
    """Calculates the difference in hours between two ISO 8601 datetime strings."""
    if not start_str or not end_str:
        return 0.0
    try:
        start = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
        end = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
        diff = end - start
        return round(diff.total_seconds() / 3600, 2)
    except Exception:
        return 0.0

@admin_bp.route('/admin_breakdown_report', methods=['GET'])
@require_role('admin')
def breakdown_dashboard():
    """Renders the main HTML dashboard."""
    user_info = {
        "name": session.get('name', 'Admin'),
        "department_category": session.get('department_category', 'P&M'),
        "can_update_repair": True, 
        "can_approve_closure": True
    }
    return render_template('admin_breakdown_report.html', user=user_info)

@admin_bp.route('/api/breakdowns/list', methods=['GET'])
@require_role('admin')
def get_breakdowns():
    month_filter = request.args.get('month')
    supabase_admin = current_app.config['supabase_admin']
    query = supabase_admin.table('breakdowns').select('*')
    if month_filter:
        query = query.gte('breakdown_start', f"{month_filter}-01T00:00:00Z")
    response = query.order('created_at', desc=True).execute()
    return jsonify({"success": True, "data": response.data})

@admin_bp.route('/api/breakdowns/report', methods=['POST'])
@require_role('admin')
def report_breakdown():
    data = request.json
    supabase_admin = current_app.config['supabase_admin']
    new_record = {
        "status": "Active",
        "asset_code": data.get("asset_code"),
        "asset_package": data.get("asset_package"),
        "agency": data.get("agency"),
        "breakdown_start": data.get("breakdown_start"),
        "breakdown_description": data.get("breakdown_description"),
        "reported_by": session.get('name', 'Unknown')
    }
    response = supabase_admin.table('breakdowns').insert(new_record).execute()
    return jsonify({"success": True, "data": response.data})

@admin_bp.route('/api/breakdowns/update/<int:bd_id>', methods=['PUT'])
@require_role('admin')
def update_breakdown(bd_id):
    data = request.json
    supabase_admin = current_app.config['supabase_admin']
    update_data = {
        "expected_eta": data.get("expected_eta"),
        "breakdown_type": data.get("breakdown_type"),
        "root_cause": data.get("root_cause"),
        "remarks": data.get("remarks"),
        "updated_by": session.get('name', 'Unknown'),
        "updated_at": datetime.now(pytz.utc).isoformat()
    }
    response = supabase_admin.table('breakdowns').update(update_data).eq('id', bd_id).execute()
    return jsonify({"success": True, "data": response.data})

@admin_bp.route('/api/breakdowns/mark_repaired/<int:bd_id>', methods=['PUT'])
@require_role('admin')
def mark_repaired(bd_id):
    data = request.json
    supabase_admin = current_app.config['supabase_admin']
    repaired_at = data.get("repaired_at") or datetime.now(pytz.utc).isoformat()
    existing = supabase_admin.table('breakdowns').select('breakdown_start').eq('id', bd_id).execute().data[0]
    repair_hrs = calc_hours_diff(existing['breakdown_start'], repaired_at)
    update_data = {
        "status": "Pending Approval",
        "repaired_at": repaired_at,
        "repair_downtime_hrs": repair_hrs,
        "repaired_by": session.get('name', 'Unknown')
    }
    response = supabase_admin.table('breakdowns').update(update_data).eq('id', bd_id).execute()
    return jsonify({"success": True, "data": response.data})

@admin_bp.route('/api/breakdowns/approve_close/<int:bd_id>', methods=['PUT'])
@require_role('admin')
def approve_closure(bd_id):
    data = request.json
    supabase_admin = current_app.config['supabase_admin']
    closed_at = data.get("closed_at") or datetime.now(pytz.utc).isoformat()
    existing = supabase_admin.table('breakdowns').select('breakdown_start, repaired_at').eq('id', bd_id).execute().data[0]
    approval_delay = calc_hours_diff(existing['repaired_at'], closed_at)
    total_downtime = calc_hours_diff(existing['breakdown_start'], closed_at)
    update_data = {
        "status": "Closed",
        "closed_at": closed_at,
        "approval_delay_hrs": approval_delay,
        "total_downtime_hrs": total_downtime,
        "approved_by": session.get('name', 'Unknown')
    }
    response = supabase_admin.table('breakdowns').update(update_data).eq('id', bd_id).execute()
    return jsonify({"success": True, "data": response.data})

@admin_bp.route('/api/breakdowns/analysis', methods=['GET'])
@require_role('admin')
def get_analysis_data():
    month_filter = request.args.get('month')
    supabase_admin = current_app.config['supabase_admin']
    query = supabase_admin.table('breakdowns').select('*')
    if month_filter:
        query = query.gte('breakdown_start', f"{month_filter}-01T00:00:00Z")
    records = query.execute().data
    
    agency_matrix = {}
    asset_counts = {}
    root_causes = {}
    total_repair_hrs = 0
    total_approval_hrs = 0
    closed_count = 0

    for r in records:
        agency = r.get('agency') or 'Unknown'
        eq_type = r.get('asset_description', 'Unknown').split()[0] if r.get('asset_description') else 'Unknown'
        
        if agency not in agency_matrix: agency_matrix[agency] = {}
        if eq_type not in agency_matrix[agency]: agency_matrix[agency][eq_type] = {"active": 0, "total": 0}
            
        agency_matrix[agency][eq_type]["total"] += 1
        if r.get('status') != 'Closed': agency_matrix[agency][eq_type]["active"] += 1
            
        code = r.get('asset_code')
        if code: asset_counts[code] = asset_counts.get(code, 0) + 1
            
        rtype = r.get('breakdown_type')
        if rtype: root_causes[rtype] = root_causes.get(rtype, 0) + 1
            
        if r.get('repair_downtime_hrs'): total_repair_hrs += r.get('repair_downtime_hrs')
        if r.get('status') == 'Closed' and r.get('approval_delay_hrs') is not None:
            total_approval_hrs += r.get('approval_delay_hrs')
            closed_count += 1

    chronic_assets = sorted([{"asset_code": k, "count": v} for k, v in asset_counts.items()], key=lambda x: x['count'], reverse=True)[:10]

    return jsonify({
        "success": True,
        "agency_matrix": agency_matrix,
        "chronic_assets": chronic_assets,
        "root_causes": root_causes,
        "bottlenecks": {
            "avg_repair_hrs": round(total_repair_hrs / len(records) if records else 0, 2),
            "avg_approval_delay_hrs": round(total_approval_hrs / closed_count if closed_count > 0 else 0, 2)
        }
    })
