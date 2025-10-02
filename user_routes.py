# user_routes.py
from flask import Blueprint, render_template, session, redirect, current_app
from services import require_role

user_bp = Blueprint("user", __name__)

@user_bp.route('/user_dashboard')
@require_role('user')
def user_dashboard():
    return render_template('user_dashboard.html')


@user_bp.route('/user_profile')
@require_role('user')
def user_profile():
    user_email = session.get('user')
    user_role = session.get('role')
    return render_template('user_profile.html', user_email=user_email, user_role=user_role)


# Dynamic simple user pages: /user_<module> (only if module in session['accesses'])
@user_bp.route('/user_<module_name>')
@require_role('user')
def user_module_page(module_name):
    # Ensure the user has access
    accesses = session.get('accesses', [])
    if module_name not in accesses:
        return redirect('/user_dashboard')

    try:
        return render_template(f"user_{module_name}.html")
    except Exception:
        # fallback placeholder if missing
        return render_template('user_asset_master.html')

# ---------------- USER ASSET MASTER ----------------
from flask import Response, request, session, current_app
import io, csv
from datetime import datetime

@user_bp.route('/user_get_assets')
@require_role('user')
def user_get_assets():
    supabase = current_app.config['supabase']
    try:
        # ✅ return everything (same as admin)
        result = supabase.table("asset_master").select("*").execute()
        return result.data, 200
    except Exception as e:
        return {"success": False, "error": str(e)}, 500


@user_bp.route('/user_update_asset/<int:asset_id>', methods=['POST'])
@require_role('user')
def user_update_asset(asset_id):
    supabase = current_app.config['supabase']
    data = request.json
    try:
        # ✅ whitelist only editable fields
        allowed_fields = [
            "package","activity","location",
            "operator_available","helper_available",
            "supervisor_owner_name","supervisor_owner_phone",
            "operator1","operator1_phone","operator1_shift",
            "operator2","operator2_phone","operator2_shift"
        ]
        update_data = {k: v for k, v in data.items() if k in allowed_fields}
        update_data["last_updated_by"] = session.get("name")
        update_data["last_updated_at"] = datetime.utcnow().isoformat()

        supabase.table("asset_master").update(update_data).eq("id", asset_id).execute()
        return {"success": True}, 200
    except Exception as e:
        # ✅ Always return JSON with success flag
        return {"success": False, "error": str(e)}, 500


@user_bp.route('/user_download_assets_csv')
@require_role('user')
def user_download_assets_csv():
    supabase = current_app.config['supabase']
    try:
        assets = supabase.table("asset_master").select(
            "package, activity, location, operator_available, helper_available, "
            "supervisor_owner_name, supervisor_owner_phone, "
            "operator1, operator1_phone, operator1_shift, "
            "operator2, operator2_phone, operator2_shift, "
            "last_updated_by, last_updated_at"
        ).execute()
        assets = assets.data if assets.data else []

        si = io.StringIO()
        writer = csv.writer(si)
        writer.writerow([
            "Package","Activity","Location",
            "Operators Available","Helpers Available",
            "Supervisor/Owner Name","Supervisor/Owner Phone",
            "Operator 1","Operator 1 Phone","Operator 1 Shift",
            "Operator 2","Operator 2 Phone","Operator 2 Shift",
            "Last Updated By","Last Updated At"
        ])
        for a in assets:
            writer.writerow([
                a.get("package"), a.get("activity"), a.get("location"),
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
            headers={"Content-Disposition": "attachment;filename=user_asset_master.csv"}
        )
    except Exception as e:
        return {"success": False, "error": str(e)}, 500

@user_bp.route('/user_edit_asset/<int:asset_id>')
@require_role('user')
def user_edit_asset_page(asset_id):
    supabase = current_app.config['supabase']
    asset = supabase.table("asset_master").select("*").eq("id", asset_id).execute()
    if asset.data:
        return render_template("user_edit_asset.html", asset=asset.data[0])
    else:
        return "Asset not found", 404