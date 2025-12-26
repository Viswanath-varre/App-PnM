from flask import Blueprint, render_template, request, redirect, session, flash, Response, current_app, jsonify, url_for
from services import require_role, _create_single_user, generate_users_csv
import io, csv
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


# ---------------- ADMIN SPARES REQUIREMENTS PAGE ----------------
@admin_bp.route('/admin_spares_requirements')
@require_role('admin')
def admin_spares_requirements_page():
    """Serve the admin spares requirements page explicitly.

    The app previously relied on a catch-all admin_<module> route which
    would fall back to the asset master when the template couldn't be
    located. Providing an explicit route prevents accidental redirects.
    """
    # Provide a minimal `user` object into the template context so
    # templates that reference `user` (for example to show the name)
    # do not raise Jinja2 UndefinedError when session data is used
    # to populate the current user.
    user_obj = {
        # templates check `user.get_full_name` first, then `user.username`
        'get_full_name': session.get('name') or '',
        'username': session.get('user') or ''
    }

    # Pass modules too (some admin pages expect it); keep minimal to
    # avoid surprising undefined errors in templates.
    modules = current_app.config.get('MODULES', [])

    return render_template('admin_spares_requirements.html', user=user_obj, modules=modules)


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


@admin_bp.route('/refresh_feature_matrix', methods=['POST'])
@require_role('admin')
def refresh_feature_matrix():
    """Manually refresh the FEATURE_MATRIX from templates without restarting the app.

    This endpoint scans `templates/` with the scanner and updates
    `current_app.config['FEATURE_MATRIX']`. It requires admin auth and
    returns JSON with success and the number of pages detected.
    """
    try:
        from feature_registry import scan_user_templates
        fm = scan_user_templates("templates")
        current_app.config['FEATURE_MATRIX'] = fm
        return jsonify({"success": True, "pages": len(fm)})
    except Exception as e:
        current_app.logger.error(f"Failed to refresh feature matrix: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


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

# add these imports at top if not present
from uuid import uuid4
from flask import stream_with_context

# ---------------- ADMIN SPARES REQUIREMENTS (API) ----------------
# Reuses IST defined earlier in this file

@admin_bp.route('/get_spares')
@require_role('admin')
def admin_get_spares():
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
    """Return simple counts for the spares dashboard (active/total) and
    a last-updated timestamp (ISO). The front-end expects JSON like:
        { counts: { active: 12, total: 34 }, updated_at: "2025-11-05T12:00:00Z" }
    """
    supabase_admin = current_app.config['supabase_admin']
    try:
        # Note: some DBs don't have `status_updated_at`. Avoid selecting a column
        # that may not exist to prevent SQL errors; we'll read it from the row
        # if present. Select last_updated_at and created_at which are expected.
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
            # handle trailing Z
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
            # consider status_updated_at first, then last_updated_at, then created_at
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

        current_app.logger.debug(f"get_spares_counts: total={total} active={active} latest={latest_iso}")
        return jsonify({"counts": {"active": active, "total": total}, "updated_at": latest_iso}), 200
    except Exception as e:
        current_app.logger.error(f"admin_get_spares_counts error: {e}")
        return jsonify({"counts": {"active": 0, "total": 0}, "updated_at": datetime.now(IST).isoformat(), "error": str(e)}), 500


@admin_bp.route('/get_spares_next_ref')
@require_role('admin')
def admin_get_spares_next_ref():
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


@admin_bp.route('/debug_spares_sample')
@require_role('admin')
def admin_debug_spares_sample():
    """Temporary debug endpoint: returns a small sample of raw spares rows
    including the raw `closed` value and our parsed boolean so you can
    inspect why rows might be considered closed by the counts logic.
    Remove this endpoint after debugging.
    """
    supabase_admin = current_app.config['supabase_admin']
    try:
        res = supabase_admin.table('spares_requirements').select('*').limit(20).execute()
        rows = res.data if res.data else []
        def parse_bool(val):
            if isinstance(val, bool):
                return val
            if val is None:
                return False
            s = str(val).strip().lower()
            return s in ("1", "true", "t", "yes", "y")

        sample = []
        for r in rows:
            closed_raw = r.get('closed') if 'closed' in r else None
            status_raw = r.get('status') or ''
            closed_parsed = parse_bool(closed_raw) or (str(status_raw).strip().lower() == 'closed')
            sample.append({
                'id': r.get('id'),
                'ref_no': r.get('ref_no'),
                'status': status_raw,
                'closed_raw': closed_raw,
                'closed_parsed': closed_parsed,
                'created_at': r.get('created_at'),
                'status_updated_at': r.get('status_updated_at')
            })

        return jsonify({'sample_count': len(sample), 'sample': sample}), 200
    except Exception as e:
        current_app.logger.error(f"admin_debug_spares_sample error: {e}")
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/create_spare', methods=['POST'])
@require_role('admin')
def admin_create_spare():
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
  supabase_admin = current_app.config['supabase_admin']
  data = request.get_json() or {}
  try:
    update = {}
    # Allow admin to update many fields
    for field in ["priority", "for_type", "asset_code", "asset_description", "required_by",
                  "requisition", "spares_req", "current_status", "actioner", "dc_required",
                  "dc_number", "status", "created_by", "metadata"]:
      if field in data:
        update[field] = data.get(field)
    # ensure proper booleans
    if "dc_required" in update:
      update["dc_required"] = bool(update["dc_required"])
    if "closed" in data:
      update["closed"] = bool(data.get("closed"))
    # update status timestamp
    update["status_updated_at"] = datetime.now(IST).isoformat()

    supabase_admin.table("spares_requirements").update(update).eq("id", spare_id).execute()
    return jsonify({"success": True}), 200
  except Exception as e:
    current_app.logger.error(f"admin_update_spare error: {e}")
    return jsonify({"success": False, "error": str(e)}), 500


@admin_bp.route('/close_spare/<int:spare_id>', methods=['POST'])
@require_role('admin')
def admin_close_spare(spare_id):
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
    supabase_admin = current_app.config['supabase_admin']
    try:
        current_app.logger.debug(f"admin_delete_spare called for id={spare_id}, session_user={session.get('user')}")
        res = supabase_admin.table("spares_requirements").delete().eq("id", spare_id).execute()

        # Check for Supabase client-level error
        err = getattr(res, 'error', None)
        if err:
            current_app.logger.error(f"admin_delete_spare supabase error for id={spare_id}: {err}")
            return jsonify({"success": False, "error": str(err)}), 500

        deleted = getattr(res, 'data', None)

        # If deleted is None or empty list => nothing deleted
        if not deleted or (isinstance(deleted, list) and len(deleted) == 0):
            current_app.logger.warning(f"admin_delete_spare: no rows deleted for id={spare_id} (res.data={deleted})")
            return jsonify({"success": False, "error": "No record found to delete"}), 404

        current_app.logger.info(f"admin_delete_spare: deleted id={spare_id}, deleted_rows={deleted}")
        return jsonify({"success": True, "deleted": deleted}), 200

    except Exception as e:
        current_app.logger.error(f"admin_delete_spare error: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500