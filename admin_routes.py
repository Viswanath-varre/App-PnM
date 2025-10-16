from flask import Blueprint, render_template, request, redirect, session, flash, Response, current_app, jsonify, url_for
from services import require_role, _create_single_user, generate_users_csv
import io, csv
from flask import jsonify
from datetime import datetime, timedelta, timezone
# ✅ Define India Standard Time (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

admin_bp = Blueprint("admin", __name__)

# ---------------- ADMIN DASHBOARD ----------------
@admin_bp.route('/admin_dashboard')
@require_role('admin')
def admin_dashboard():
    return render_template('admin_dashboard.html')


# ---------------- ADMIN ASSET MASTER PAGE ----------------
@admin_bp.route('/admin_asset_master')
@require_role('admin')
def admin_asset_master_page():
    return render_template("admin_asset_master.html")


# ---------------- ADMIN ADD ASSET PAGE ----------------
@admin_bp.route('/admin_add_asset')
@require_role('admin')
def admin_add_asset_page():
    return render_template("admin_add_asset.html")


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
        modules=modules,
        feature_matrix=current_app.config['FEATURE_MATRIX']   # ✅ Added line
    )


@admin_bp.route('/create_users', methods=['POST'])
@require_role('admin')
def create_users():
    supabase_admin = current_app.config['supabase_admin']

    # ---------- 1️⃣ CSV Upload ----------
    if 'csv_file' in request.files:
        file = request.files['csv_file']
        if not file.filename.lower().endswith('.csv'):
            flash("Only CSV files allowed", "danger")
            return redirect(url_for('admin.admin_user_management'))

        stream = io.StringIO(file.stream.read().decode("utf8"), newline=None)
        reader = csv.DictReader(stream)
        created_rows, errors = [], []

        for i, row in enumerate(reader, start=1):
            try:
                row['accesses'] = [x.strip() for x in row.get('accesses', '').split(',') if x.strip()]
                result = _create_single_user(row, supabase_admin)
                gen_pass = result.get("generated_password") if isinstance(result, dict) else None
                created_rows.append({
                    "user_id": row.get("user_id", ""),
                    "email": row.get("email", ""),
                    "generated_password": gen_pass or (row.get("password") or "")
                })
            except Exception as e:
                errors.append(f"Row {i}: {str(e)}")

        if errors:
            flash(f"CSV upload finished with {len(errors)} error(s).", "warning")
            for err in errors[:10]:
                flash(err, "danger")

        if created_rows:
            si = io.StringIO()
            writer = csv.writer(si)
            writer.writerow(["user_id", "email", "generated_password"])
            for r in created_rows:
                writer.writerow([r["user_id"], r["email"], r["generated_password"]])
            output = si.getvalue().encode("utf-8")
            return Response(
                output,
                mimetype="text/csv",
                headers={"Content-Disposition": "attachment;filename=created_users_with_passwords.csv"}
            )

        return redirect(url_for('admin.admin_user_management'))

    # ---------- 2️⃣ Manual Form Creation ----------
    raw_feature_accesses = request.form.getlist("feature_accesses")
    feature_accesses = {}
    flat_accesses = set()

    for item in raw_feature_accesses:
        parts = item.split(":")
        if len(parts) == 1:
            page = parts[0]
            feature_accesses.setdefault(page, {})
            flat_accesses.add(page)
        elif len(parts) == 2:
            page, feature = parts
            feature_accesses.setdefault(page, {}).setdefault(feature, [])
            flat_accesses.add(page)
        elif len(parts) == 3:
            page, feature, sub = parts
            feature_accesses.setdefault(page, {}).setdefault(feature, []).append(sub)
            flat_accesses.add(page)

    accesses = sorted(set(flat_accesses.union(request.form.getlist("accesses"))))

    data = {
        "user_id": request.form.get("user_id"),
        "full_name": request.form.get("full_name"),
        "designation": request.form.get("designation"),
        "role": request.form.get("role"),
        "phone": request.form.get("phone"),
        "email": request.form.get("email"),
        "password": request.form.get("password"),
        "accesses": accesses,
        "feature_accesses": feature_accesses
    }

    try:
        _create_single_user(data, supabase_admin)
        flash("✅ User created successfully!", "success")
    except Exception as e:
        print("❌ Failed to create user:", e)
        flash(f"Failed to create user: {e}", "danger")

    return redirect(url_for('admin.admin_user_management'))


    # ---------- 2️⃣ Manual Form User Creation ----------
    raw_feature_accesses = request.form.getlist("feature_accesses")
    feature_accesses = {}
    flat_accesses = set()

    for item in raw_feature_accesses:
        # Handles:
        #  - page:feature
        #  - page:feature:subfeature
        #  - simple page (edge cases)
        parts = item.split(":")
        if len(parts) == 1:
            page = parts[0]
            feature_accesses.setdefault(page, {})
            flat_accesses.add(page)
        elif len(parts) == 2:
            page, feature = parts
            feature_accesses.setdefault(page, {}).setdefault(feature, [])
            flat_accesses.add(page)
        elif len(parts) == 3:
            page, feature, sub = parts
            feature_accesses.setdefault(page, {}).setdefault(feature, []).append(sub)
            flat_accesses.add(page)

    # Also include old-style "accesses" checkboxes if used
    accesses = sorted(set(flat_accesses.union(request.form.getlist("accesses"))))

    data = {
        "user_id": request.form.get("user_id"),
        "full_name": request.form.get("full_name"),
        "designation": request.form.get("designation"),
        "role": request.form.get("role"),
        "phone": request.form.get("phone"),
        "email": request.form.get("email"),
        "password": request.form.get("password"),
        "accesses": accesses,  # flat page names
        "feature_accesses": feature_accesses  # full structure
    }

    try:
        _create_single_user(data, supabase_admin)
        flash("✅ User created successfully!", "success")
    except Exception as e:
        print("❌ Failed to create user:", e)
        flash(f"Failed to create user: {e}", "danger")

    return redirect(url_for('admin.admin_user_management'))


@admin_bp.route('/edit_user/<user_id>', methods=['POST'])
@require_role('admin')
def edit_user(user_id):
    supabase_admin = current_app.config['supabase_admin']

    full_name = request.form.get("full_name")
    designation = request.form.get("designation")
    phone = request.form.get("phone")
    email = request.form.get("email")
    password = request.form.get("password")
    role = request.form.get("role", "user")

    # 🟡 Collect all permission data coming from checkboxes
    raw_feature_accesses = request.form.getlist("feature_accesses")
    feature_accesses = {}
    flat_accesses = set()

    for item in raw_feature_accesses:
        parts = item.split(":")
        if len(parts) == 1:
            page = parts[0]
            feature_accesses.setdefault(page, {})
            flat_accesses.add(page)
        elif len(parts) == 2:
            page, feature = parts
            feature_accesses.setdefault(page, {}).setdefault(feature, [])
            flat_accesses.add(page)
        elif len(parts) == 3:
            page, feature, sub = parts
            feature_accesses.setdefault(page, {}).setdefault(feature, []).append(sub)
            flat_accesses.add(page)

    # Merge page-only checkboxes too
    page_accesses = set(request.form.getlist("accesses"))
    accesses = list(flat_accesses.union(page_accesses))

    try:
        # --- Update user_meta record in Supabase ---
        supabase_admin.table("users_meta").update({
            "full_name": full_name,
            "designation": designation,
            "phone": phone,
            "email": email,
            "role": role,
            "accesses": accesses,               # flat page list
            "feature_accesses": feature_accesses  # nested dict
        }).eq("user_id", user_id).execute()

        # --- Update password in Supabase Auth (if provided) ---
        if password:
            user_record = supabase_admin.table("users_meta").select("auth_id").eq("user_id", user_id).execute()
            if user_record.data and user_record.data[0].get("auth_id"):
                auth_id = user_record.data[0]["auth_id"]
                supabase_admin.auth.admin.update_user(auth_id, {"password": password})

        flash("✅ User updated successfully", "success")

    except Exception as e:
        print("❌ edit_user error:", e)
        flash(f"Failed to edit user: {e}", "danger")

    return redirect(url_for('admin.admin_user_management'))



@admin_bp.route('/delete_user/<user_id>', methods=['POST'])
@require_role('admin')
def delete_user(user_id):
    supabase_admin = current_app.config['supabase_admin']
    try:
        supabase_admin.table("users_meta").delete().eq("user_id", user_id).execute()
    except Exception as e:
        flash(f"Failed to delete user: {e}")
    return redirect(url_for('admin.admin_user_management'))


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


# ---------------- ASSET MASTER (API endpoints) ----------------
@admin_bp.route('/get_assets')
@require_role('admin')
def get_assets():
    supabase_admin = current_app.config['supabase_admin']
    try:
        result = supabase_admin.table("asset_master").select("*").execute()
        return jsonify(result.data), 200
    except Exception as e:
        return {"error": str(e)}, 500


@admin_bp.route('/add_asset', methods=['POST'])
@require_role('admin')
def add_asset():
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
    supabase_admin = current_app.config['supabase_admin']
    try:
        data = request.get_json()
        if not data:
            return jsonify({"success": False, "error": "No data provided"}), 400

        # Update in Supabase
        result = supabase_admin.table("asset_master").update(data).eq("id", asset_id).execute()

        # Optionally check if rows updated
        if not result.data:
            return jsonify({"success": False, "error": "Asset not found"}), 404

        return jsonify({"success": True}), 200

    except Exception as e:
        current_app.logger.error(f"Error updating asset {asset_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


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
            supabase_admin.table("asset_master").delete().in_("id", ids[i:i + batch_size]).execute()

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
    supabase_admin = current_app.config['supabase_admin']
    try:
        assets = supabase_admin.table("asset_master").select("*").execute()
        assets = assets.data if assets.data else []

        if not assets:
            return {"error": "No assets found"}, 404

        # ✅ Dynamically detect columns
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
    supabase_admin = current_app.config['supabase_admin']

    try:
        # ✅ Dynamically get one row to detect columns
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


# ---------------- ADMIN EDIT ASSET PAGE ----------------
@admin_bp.route('/admin_edit_asset/<int:asset_id>')
@require_role('admin')
def admin_edit_asset_page(asset_id):
    supabase_admin = current_app.config['supabase_admin']
    asset = supabase_admin.table("asset_master").select("*").eq("id", asset_id).execute()
    if asset.data:
        return render_template("admin_edit_asset.html", asset=asset.data[0])
    else:
        return "Asset not found", 404


# ---------------- DYNAMIC SIMPLE ADMIN PAGES (catch-all) ----------------
@admin_bp.route('/admin_<module_name>')
@require_role('admin')
def admin_module_page(module_name):
    modules = current_app.config.get('MODULES', [])
    if module_name not in modules:
        return redirect(url_for('admin.admin_dashboard'))
    try:
        return render_template(f"admin_{module_name}.html")
    except Exception:
        return render_template('admin_asset_master.html')

# ---------------- DROPDOWN CONFIG API (Admin) ----------------
@admin_bp.route('/dropdown_config', methods=['GET'])
@require_role('admin')
def admin_get_dropdown_config():
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
    """
    Body (JSON):
      { "action": "add"|"remove", "list_name": "<name>", "value": "<value>" }
    For remove you may pass value (exact match). Remove will delete rows where list_name & value match.
    """
    supabase_admin = current_app.config['supabase_admin']
    data = request.get_json() or {}
    action = data.get("action")
    list_name = data.get("list_name")
    value = data.get("value")

    if not action or not list_name or not value:
        return jsonify({"success": False, "error": "Missing action/list_name/value"}), 400

    try:
        if action == "add":
            # Insert (allow duplicates prevention via DB constraint if set)
            supabase_admin.table("dropdown_config").insert({"list_name": list_name, "value": value}).execute()
        elif action == "remove":
            supabase_admin.table("dropdown_config").delete().eq("list_name", list_name).eq("value", value).execute()
        else:
            return jsonify({"success": False, "error": "Invalid action"}), 400

        return jsonify({"success": True}), 200
    except Exception as e:
        current_app.logger.error(f"update_dropdown error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

