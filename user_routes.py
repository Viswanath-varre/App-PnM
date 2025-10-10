from flask import Blueprint, render_template, session, redirect, current_app, Response, request, jsonify, url_for
from services import require_role
import io, csv, json
from datetime import datetime

# Blueprint
user_bp = Blueprint("user", __name__)

# ---------------- USER DASHBOARD ----------------
@user_bp.route('/dashboard')
@require_role('user')
def user_dashboard():
    return render_template('user_dashboard.html')


# ---------------- USER PROFILE ----------------
@user_bp.route('/profile')
@require_role('user')
def user_profile():
    user_email = session.get('user')
    user_role = session.get('role')
    return render_template('user_profile.html', user_email=user_email, user_role=user_role)


# ---------------- DYNAMIC SIMPLE USER PAGES ----------------
@user_bp.route('/<module_name>')
@require_role('user')
def user_module_page(module_name):
    accesses = session.get('accesses', [])
    if module_name not in accesses:
        return redirect(url_for('user.user_dashboard'))

    try:
        return render_template(f"user_{module_name}.html")
    except Exception:
        # fallback placeholder if missing
        return render_template('user_asset_master.html')


# ---------------- USER ASSET MASTER (API + PAGE) ----------------
@user_bp.route('/get_assets')
@require_role('user')
def user_get_assets():
    """
    Fetch all asset_master records for User Asset Master table + dashboard.
    Returns clean JSON array so Tabulator and dashboard JS can parse it directly.
    """
    supabase_admin = current_app.config['supabase_admin']  # ✅ Always use service key client

    try:
        result = supabase_admin.table("asset_master").select("*").execute()
        data = result.data or []

        if not data:
            print("⚠️ No data found in asset_master (user_get_assets).")
        else:
            print(f"✅ user_get_assets returned {len(data)} records")

        return Response(json.dumps(data), mimetype="application/json")

    except Exception as e:
        print("❌ user_get_assets error:", e)
        return jsonify({"success": False, "error": str(e)}), 500


@user_bp.route('/update_asset/<asset_id>', methods=['POST'])
@require_role('user')
def user_update_asset(asset_id):
    supabase_admin = current_app.config['supabase_admin']
    data = request.json or {}
    try:
        allowed_fields = [
            "package", "activity", "activity_works", "location",
            "operator_available", "helper_available",
            "supervisor_owner_name", "supervisor_owner_phone",
            "operator1", "operator1_phone", "operator1_shift",
            "operator2", "operator2_phone", "operator2_shift"
        ]
        update_data = {k: v for k, v in data.items() if k in allowed_fields}
        update_data["last_updated_by"] = session.get("name", "User")
        update_data["last_updated_at"] = datetime.utcnow().isoformat()

        supabase_admin.table("asset_master").update(update_data).eq("id", asset_id).execute()
        print(f"✅ Updated ID={asset_id}: {update_data}")
        return jsonify({"success": True}), 200
    except Exception as e:
        print("❌ user_update_asset error:", e)
        return jsonify({"success": False, "error": str(e)}), 500


@user_bp.route('/edit_asset/<int:asset_id>')
@require_role('user')
def user_edit_asset_page(asset_id):
    """
    Renders the edit page for a specific asset.
    """
    supabase_admin = current_app.config['supabase_admin']  # ✅ use admin client (full access)
    try:
        asset = supabase_admin.table("asset_master").select("*").eq("id", asset_id).execute()
        if asset.data and len(asset.data) > 0:
            return render_template("user_edit_asset.html", asset=asset.data[0])
        else:
            return "Asset not found", 404
    except Exception as e:
        print("❌ user_edit_asset_page error:", e)
        return f"Error loading asset: {e}", 500
