"""User routes consolidated: spares + breakdown reports.

This file had duplicate imports and definitions; it's been cleaned to provide a
single `user` blueprint with all user-facing routes.

Keep `supabase_admin` in `current_app.config['supabase_admin']` and ensure
`require_role` is available from `services`.
"""

from datetime import datetime, timedelta, timezone
import traceback

from flask import Blueprint, render_template, current_app, jsonify, request, session
import csv
import io

from services import require_role
import openpyxl
from openpyxl.styles import Border, Side, Alignment, Font

# Blueprint (no prefix here; app.py registers under `/user`)
user_bp = Blueprint("user", __name__)

# IST timezone helper
IST = timezone(timedelta(hours=5, minutes=30))

UTC = timezone.utc

def ist_to_utc(val):
    if not val:
        return None

    try:
        # Case 1: already a datetime
        if isinstance(val, datetime):
            dt = val

        # Case 2: ISO string (YYYY-MM-DDTHH:MM[:SS])
        elif isinstance(val, str) and "T" in val:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))

        # Case 3: UI string "DD/MM/YYYY h:mm AM/PM"
        elif isinstance(val, str):
            dt = datetime.strptime(val, "%d/%m/%Y %I:%M %p")

        else:
            return None

        # Attach IST if naive
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)

        # Convert to UTC for DB
        return dt.astimezone(UTC).isoformat()

    except Exception as e:
        raise ValueError(f"Invalid datetime value: {val}") from e

# ⬇⬇⬇ PASTE THIS EXACTLY HERE ⬇⬇⬇
def json_safe(val):
    if isinstance(val, datetime):
        return val.isoformat()
    return val

def utc_to_ist(dt):
    if not dt:
        return None

    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)

    return dt.astimezone(IST)

def _to_iso(val):
    if not val:
        return None
    try:
        if isinstance(val, str):
            return val
        return val.isoformat()
    except Exception:
        try:
            return str(val)
        except Exception:
            return None


def _format_dt_to_ist_string(val):
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        return dt.astimezone(IST).strftime("%d/%m/%Y %I:%M %p")
    except Exception:
        return None


# ✅ ADD THIS EXACTLY HERE (GLOBAL HELPER)
def _safe_fromiso(val):
    if not val:
        return None
    try:
        # Parse strings and normalize to IST-aware datetimes.
        if isinstance(val, str):
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        elif isinstance(val, datetime):
            dt = val
        else:
            return None

        # If naive, assume IST and attach tzinfo; otherwise convert to IST
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        else:
            dt = dt.astimezone(IST)

        return dt
    except Exception:
        raise ValueError("Invalid ISO datetime")


# ---------------- Basic user pages ----------------
@user_bp.route("/dashboard")
@require_role("user")
def user_dashboard():
    return render_template("user_dashboard.html")


@user_bp.route("/profile")
@require_role("user")
def user_profile():
    user_email = session.get("user")
    user_role = session.get("role")
    return render_template("user_profile.html", user_email=user_email, user_role=user_role)


@user_bp.route("/<module_name>")
@require_role("user")
def user_module_page(module_name):
    accesses = session.get("accesses", [])
    prefixed = f"user_{module_name}"
    if prefixed not in accesses:
        current_app.logger.info("Access denied to %s; redirecting to dashboard", prefixed)
        return render_template("user_dashboard.html")
    try:
        return render_template(f"user_{module_name}.html")
    except Exception as e:
        current_app.logger.warning("Missing template user_%s: %s", module_name, e)
        return render_template("user_asset_master.html")


# ---------------- Asset endpoints ----------------
@user_bp.route("/get_assets")
@require_role("user")
def user_get_assets():
    """Return a lightweight list of assets for client dropdowns."""
    supabase_admin = current_app.config.get("supabase_admin")
    try:
        if not supabase_admin:
            raise RuntimeError("supabase_admin not configured")
        res = supabase_admin.table("asset_master").select("*").execute()
        rows = res.data or []
        out = []
        for r in rows:
            out.append({
                "id": r.get("id"),
                "asset_code": r.get("asset_code"),
                "asset_description": r.get("asset_description"),
                "reg_no": r.get("reg_no"),
                "package": r.get("package"),
                "activity": r.get("activity"),
            })
        return jsonify(out), 200
    except Exception as e:
        current_app.logger.error("user_get_assets error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


# ---------------- Dropdown config ----------------
@user_bp.route("/dropdown_config", methods=["GET"])
@require_role("user")
def user_get_dropdown_config():
    supabase_admin = current_app.config.get("supabase_admin")
    try:
        # Return cached dropdown config from session if present and not explicitly refreshed
        if request.args.get('refresh') != '1' and session.get('dropdown_config'):
            return jsonify(session.get('dropdown_config')), 200

        if not supabase_admin:
            raise RuntimeError("supabase_admin not configured")
        # retry transient network errors when fetching dropdown config
        retries = int(current_app.config.get('SUPABASE_HTTP_RETRIES', 3))
        backoff = 1.0
        result = None
        last_exc = None
        from httpx import ConnectTimeout
        for attempt in range(1, retries + 1):
            try:
                result = supabase_admin.table("dropdown_config").select("*").execute()
                break
            except ConnectTimeout as ct:
                last_exc = ct
                current_app.logger.warning("dropdown_config handshake timeout (attempt %s/%s): %s", attempt, retries, ct)
            except Exception as ex:
                last_exc = ex
                current_app.logger.warning("dropdown_config error (attempt %s/%s): %s", attempt, retries, ex)

            if attempt < retries:
                import time
                time.sleep(backoff)
                backoff *= 2

        if result is None:
            raise last_exc or RuntimeError("Failed to fetch dropdown_config")
        data = sorted(result.data or [], key=lambda x: (x.get("list_name", ""), x.get("value", "")))
        grouped = {}
        for row in data:
            name = row.get("list_name") or "default"
            grouped.setdefault(name, []).append(row.get("value"))

        # Cache the grouped config in session so subsequent page loads don't hit Supabase
        try:
            session['dropdown_config'] = grouped
        except Exception:
            # if session storage fails for any reason, continue without caching
            current_app.logger.warning("Could not cache dropdown_config in session")

        return jsonify(grouped), 200
    except Exception as e:
        current_app.logger.error("user_dropdown_config GET error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


# ---------------- Spares: page render ----------------
@user_bp.route("/spares_requirements")
@require_role("user")
def user_spares_page():
    user = {
        "username": session.get("user"),
        "get_full_name": session.get("name", session.get("user")),
    }
    return render_template("user_spares_requirements.html", user=user)


# ---------------- Spares: API endpoints ----------------
@user_bp.route("/get_spares")
@require_role("user")
def user_get_spares():
    supabase_admin = current_app.config.get("supabase_admin")
    try:
        if not supabase_admin:
            raise RuntimeError("supabase_admin not configured")

        # Prefer ordering by created_at; fallback to local sort by id
        try:
            res = supabase_admin.table("spares_requirements").select("*").order("created_at", desc=True).execute()
            rows = res.data or []
        except Exception as e:
            current_app.logger.info("get_spares fallback due to: %s", e)
            res = supabase_admin.table("spares_requirements").select("*").execute()
            rows = res.data or []
            try:
                rows = sorted(rows, key=lambda x: x.get("id", 0), reverse=True)
            except Exception:
                pass

        out = []
        for r in rows:
            created_raw = r.get("created_at")
            updated_raw = r.get("last_updated_at") or r.get("status_updated_at")
            expected_raw = r.get("expected_date")

            out.append({
                "id": r.get("id"),
                "ref_no": r.get("ref_no"),
                "status": r.get("status"),
                "priority": r.get("priority"),
                "for_type": r.get("for_type"),
                "asset_code": r.get("asset_code"),
                "asset_description": r.get("asset_description"),
                "asset_display": (r.get("asset_code") or "") + (" - " + r.get("asset_description") if r.get("asset_description") else ""),
                "spares_req": r.get("spares_req"),
                "qty_required": r.get("qty_required"),
                "qty_available": r.get("qty_available"),
                "required_by": r.get("required_by"),
                "requisition": r.get("requisition") or r.get("created_by") or r.get("requested_by"),
                "actioner": r.get("actioner"),
                "current_status": r.get("current_status"),
                "dc_required": r.get("dc_required", False),
                "dc_number": r.get("dc_number"),
                "expected_date": expected_raw,
                "closed": r.get("closed", False),
                # iso/time fields
                "created_at_iso": _to_iso(created_raw),
                "last_updated_at_iso": _to_iso(updated_raw),
                "expected_date_iso": _to_iso(expected_raw),
                # display strings (IST)
                "created_at": _format_dt_to_ist_string(created_raw) or (r.get("created_at") or ""),
                "last_updated_at": _format_dt_to_ist_string(updated_raw) or (r.get("last_updated_at") or ""),
            })
        return jsonify(out), 200
    except Exception as e:
        current_app.logger.error("user_get_spares error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@user_bp.route("/create_spare", methods=["POST"])
@require_role("user")
def user_create_spare():
    supabase_admin = current_app.config.get("supabase_admin")
    data = request.get_json() or {}
    try:
        if not data.get("ref_no") or not data.get("spares_req"):
            return jsonify({"success": False, "error": "ref_no and spares_req are required"}), 400

        if not supabase_admin:
            raise RuntimeError("supabase_admin not configured")

        base = {
            "ref_no": data.get("ref_no"),
            "status": data.get("status") or "Active",
            "priority": data.get("priority"),
            "for_type": data.get("for_type"),
            "asset_code": data.get("asset_code"),
            "asset_description": data.get("asset_description"),
            "spares_req": data.get("spares_req"),
            "qty_required": float(data.get("qty_required") or 0),
            "qty_available": float(data.get("qty_available") or 0),
            "required_by": data.get("required_by") or None,
            "requisition": data.get("requisition") or session.get("name", session.get("user")),
            "actioner": data.get("actioner") or session.get("name", session.get("user")),
            "current_status": data.get("current_status") or None,
            "dc_required": bool(data.get("dc_required")) if "dc_required" in data else False,
            "dc_number": data.get("dc_number"),
            "expected_date": data.get("expected_date") if data.get("expected_date") else None,
            "closed": bool(data.get("closed")) if "closed" in data else False,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "last_updated_by": session.get("name", session.get("user")),
        }

        # try insert, if DB schema lacks optional columns retry without them
        try:
            supabase_admin.table("spares_requirements").insert(base).execute()
            return jsonify({"success": True}), 201
        except Exception as ex_insert:
            current_app.logger.warning("create_spare initial insert failed: %s — retrying without optional fields", ex_insert)
            # remove commonly optional/absent fields and retry
            for optional in ("expected_date", "last_updated_at", "last_updated_by", "created_at"):
                base.pop(optional, None)
            try:
                supabase_admin.table("spares_requirements").insert(base).execute()
                return jsonify({"success": True, "warning": "insert retried without some optional fields"}), 201
            except Exception as ex_retry:
                current_app.logger.error("create_spare retry failed: %s\n%s", ex_retry, traceback.format_exc())
                return jsonify({"success": False, "error": str(ex_retry)}), 500

    except ValueError:
        return jsonify({"success": False, "error": "Invalid numeric value"}), 400
    except Exception as e:
        current_app.logger.error("user_create_spare error: %s\n%s", e, traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500


@user_bp.route("/get_spares_next_ref")
@require_role("user")
def user_get_spares_next_ref():
    supabase_admin = current_app.config.get("supabase_admin")
    try:
        if not supabase_admin:
            raise RuntimeError("supabase_admin not configured")
        res = supabase_admin.table("spares_requirements").select("ref_no").order("id", desc=True).limit(1).execute()
        if res.data and len(res.data) > 0:
            last_ref = res.data[0].get("ref_no") or ""
            try:
                next_num = str(int(last_ref) + 1).zfill(4)
            except Exception:
                next_num = "0001"
        else:
            next_num = "0001"
        return jsonify({"next_ref": next_num}), 200
    except Exception as e:
        current_app.logger.error("user_get_spares_next_ref error: %s\n%s", e, traceback.format_exc())
        return jsonify({"next_ref": "0001", "error": str(e)}), 200


@user_bp.route("/get_spares_counts")
@require_role("user")
def user_get_spares_counts():
    supabase_admin = current_app.config.get("supabase_admin")
    try:
        if not supabase_admin:
            raise RuntimeError("supabase_admin not configured")

        active_q = supabase_admin.table("spares_requirements").select("id", count="exact").eq("status", "Active").execute()
        pending_q = supabase_admin.table("spares_requirements").select("id", count="exact").eq("status", "Pending").execute()
        total_q = supabase_admin.table("spares_requirements").select("id", count="exact").execute()

        def _count(q):
            if hasattr(q, "count") and q.count is not None:
                return q.count
            return len(q.data or [])

        return jsonify({
            "counts": {
                "active": _count(active_q),
                "pending": _count(pending_q),
                "total": _count(total_q),
            },
            "updated_at": datetime.utcnow().isoformat(),
        }), 200
    except Exception as e:
        current_app.logger.error("user_get_spares_counts error: %s\n%s", e, traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500


@user_bp.route("/update_spare/<int:spare_id>", methods=["POST"])
@require_role("user")
def user_update_spare(spare_id):
    supabase_admin = current_app.config.get("supabase_admin")
    data = request.get_json() or {}
    try:
        if not supabase_admin:
            raise RuntimeError("supabase_admin not configured")

        allowed = {"current_status", "dc_required", "dc_number", "priority", "status", "remarks", "expected_date", "qty_required", "qty_available"}
        payload = {k: data.get(k) for k in data.keys() if k in allowed}

        payload["last_updated_at"] = datetime.utcnow().isoformat()
        payload["last_updated_by"] = session.get("name", session.get("user"))

        supabase_admin.table("spares_requirements").update(payload).eq("id", spare_id).execute()
        return jsonify({"success": True}), 200
    except Exception as e:
        current_app.logger.error("user_update_spare error: %s\n%s", e, traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500


@user_bp.route("/close_spare/<int:spare_id>", methods=["POST"])
@require_role("user")
def user_close_spare(spare_id):
    supabase_admin = current_app.config.get("supabase_admin")
    try:
        if not supabase_admin:
            raise RuntimeError("supabase_admin not configured")

        payload = {
            "status": "Closed",
            "closed": True,
            "last_updated_at": datetime.utcnow().isoformat(),
            "last_updated_by": session.get("name", session.get("user")),
        }
        supabase_admin.table("spares_requirements").update(payload).eq("id", spare_id).execute()
        return jsonify({"success": True}), 200
    except Exception as e:
        current_app.logger.error("user_close_spare error: %s\n%s", e, traceback.format_exc())
        return jsonify({"success": False, "error": str(e)}), 500


# =================================================
# Breakdown report pages + endpoints
# =================================================
@user_bp.route("/breakdown_report")
@require_role("user")
def user_breakdown_report_page():
    # Ensure template gets an `asset_master` list (can be empty) so `tojson` succeeds
    supabase_admin = current_app.config.get("supabase_admin")
    assets = []
    try:
        if supabase_admin:
            res = supabase_admin.table("asset_master").select("asset_code, asset_description, package, owner, location").execute()
            assets = res.data or []
    except Exception as e:
        current_app.logger.warning("Could not load asset_master for breakdown page: %s", e)

    return render_template("user_breakdown_report.html", asset_master=assets)


@user_bp.route("/breakdown_reports", methods=["GET"])
@require_role("user")
def get_breakdown_reports():
    supabase_admin = current_app.config.get("supabase_admin")

    try:
        res = supabase_admin.table("breakdown_reports").select("*").order("id", desc=True).execute()
        rows = res.data or []

        now = datetime.now(IST)
        output = []

        for r in rows:
          # preserve all DB fields and compute downtime per rule
          start_raw = r.get("breakdown_start")
          end_raw   = r.get("breakdown_end")

          downtime = None

          start_dt = _safe_fromiso(start_raw)
          end_dt   = _safe_fromiso(end_raw)

          if start_dt:
            if end_dt:
              delta = end_dt - start_dt
            else:
              delta = now - start_dt

            downtime = round(delta.total_seconds() / 3600, 2)
            
            # return the full DB row plus computed downtime in hours
            row_out = dict(r)
            row_out["breakdown_start"] = _format_dt_to_ist_string(start_raw)
            row_out["breakdown_end"]   = _format_dt_to_ist_string(end_raw)
            row_out["downtime_hrs"] = downtime
            # created_at display kept for backward compatibility
            row_out["created_at"] = _format_dt_to_ist_string(r.get("created_at"))

            output.append(row_out)

        return jsonify(output), 200

    except Exception as e:
        current_app.logger.error("get_breakdown_reports error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@user_bp.route("/breakdown_reports", methods=["POST"])
@require_role("user")
def create_breakdown_report():
    supabase_admin = current_app.config.get("supabase_admin")
    data = request.get_json() or {}

    # ---- Required fields (DB truth) ----
    required = ["asset_code", "breakdown_start"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({
            "success": False,
            "error": f"Missing required fields: {', '.join(missing)}"
        }), 400

    # ---- Normalize own_hire to satisfy DB CHECK constraint ----
    if data.get("own_hire"):
        data["own_hire"] = data["own_hire"].strip().upper()

    # ---- STRICT whitelist (matches DB exactly) ----
    allowed_fields = {
        "asset_code",
        "asset_description",
        "asset_package",
        "own_hire",
        "agency",
        "breakdown_start",
        "breakdown_end",
        "breakdown_type",
        "breakdown_description",
        "root_cause",
        "responsible_person",
        "expected_commissioned_at",
        "eip_commissioned_at",
        "downtime_hrs",
        "reported_by",
        "remarks",
        "location",
    }

    payload = {k: data.get(k) for k in allowed_fields if k in data}




    # ---- Backend owns timestamps (IST → UTC for DB) ----
    for f in (
        "breakdown_start",
        "breakdown_end",
        "expected_commissioned_at",
        "eip_commissioned_at",
    ):
        if payload.get(f):
            payload[f] = ist_to_utc(payload[f])

    now_utc = datetime.now(UTC).isoformat()

    payload["created_at"] = now_utc
    payload["updated_at"] = now_utc
    payload["status"] = "Active"
    payload["reported_by"] = payload.get("reported_by") or session.get("name", session.get("user"))
    payload["last_updated_by"] = session.get("name", session.get("user"))

    # force agency from asset master (create only)
    if not payload.get("agency") and payload.get("asset_code"):
        am = supabase_admin.table("asset_master") \
            .select("agency") \
            .eq("asset_code", payload["asset_code"]) \
            .single() \
            .execute()
        if am.data:
            payload["agency"] = am.data.get("agency")

    # ---- FORCE PAYLOAD TO BE JSON SAFE (MANDATORY) ----
    payload = {k: json_safe(v) for k, v in payload.items()}

    try:
        supabase_admin.table("breakdown_reports").insert(payload).execute()
        return jsonify({"success": True}), 201
    except Exception as e:
        current_app.logger.error("Breakdown insert failed", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500



@user_bp.route("/breakdown_reports/<int:report_id>", methods=["PUT"])
@require_role("user")
def update_breakdown_report(report_id):
  supabase_admin = current_app.config.get("supabase_admin")
  data = request.get_json() or {}

  try:
    # ---- Fetch existing row ----
    existing = supabase_admin.table("breakdown_reports") \
      .select("*") \
      .eq("id", report_id) \
      .single() \
      .execute()

    row = existing.data or {}

    # ---- HARD BLOCK: already closed (allow only CLOSE action) ----
    if row.get("status") == "Closed" and not (
        data.get("breakdown_end") and data.get("eip_commissioned_at")
    ):
      return jsonify({"error": "Closed breakdowns cannot be edited"}), 400

    # ---- Allowed update fields ----
    allowed_fields = {
      "location",
      "breakdown_end",
      "breakdown_type",
      "root_cause",
      "breakdown_description",
      "responsible_person",
      "expected_commissioned_at",
      "eip_commissioned_at",
      "remarks",
    }

    payload = {k: data.get(k) for k in allowed_fields if k in data}

    # ---- Convert IST input → UTC (BEFORE validation) ----
    for f in ("breakdown_end", "expected_commissioned_at", "eip_commissioned_at"):
      if payload.get(f):
        payload[f] = ist_to_utc(payload[f])

    # ---- VALIDATE & APPLY CLOSE LOGIC (STRICT) ----
    is_close_action = bool(
      payload.get("breakdown_end") and payload.get("eip_commissioned_at")
    )

    if is_close_action:

      # Mandatory dates
      if not payload.get("breakdown_end") or not payload.get("eip_commissioned_at"):
        return jsonify({
          "error": "Dates are mandatory to close the breakdown."
        }), 400

      try:
        # ---- Parse datetimes (ALL IN UTC) ----
        now = datetime.now(UTC)

        start_dt = _safe_fromiso(row.get("breakdown_start")).astimezone(UTC)
        end_dt   = payload.get("breakdown_end")
        eip_dt   = payload.get("eip_commissioned_at")

        # ---- Logical validations ----
        if end_dt <= start_dt:
          return jsonify({
            "error": "Breakdown End Date must be AFTER Breakdown Start."
          }), 400

        if eip_dt <= start_dt:
          return jsonify({
            "error": "EIP Commission Date must be AFTER Breakdown Start."
          }), 400

        if end_dt > now:
          return jsonify({
            "error": "Breakdown End Date cannot be in the future."
          }), 400

        if eip_dt > now:
          return jsonify({
            "error": "EIP Commission Date cannot be in the future."
          }), 400

      except Exception:
        return jsonify({"error": "Invalid date format"}), 400

      # ---- Apply CLOSE fields ----
      payload["status"] = "Closed"
      payload["current_status"] = "Breakdown Closed"
      payload["closed_by"] = session.get("name") or session.get("user")
      payload["closed_at"] = datetime.now(UTC).isoformat()

    # ---- Audit fields ----
    payload["updated_by"] = session.get("name", session.get("user"))
    payload["updated_at"] = datetime.now(UTC).isoformat()

    supabase_admin.table("breakdown_reports") \
      .update(payload) \
      .eq("id", report_id) \
      .execute()

    return jsonify({"success": True}), 200

  except Exception as e:
    current_app.logger.error(
      "update_breakdown_report error: %s\n%s",
      e,
      traceback.format_exc()
    )
    return jsonify({"error": str(e)}), 500


@user_bp.route("/breakdown_summary")
@require_role("user")
def get_breakdown_summary():
    """Return package-wise counts and active downtime totals plus grand totals."""
    supabase_admin = current_app.config.get("supabase_admin")
    try:
        if not supabase_admin:
            raise RuntimeError("supabase_admin not configured")

        res = supabase_admin.table("breakdown_reports").select("*").execute()
        rows = res.data or []

        now = datetime.now(IST)
        packages = {}
        totals = {"ACTIVE_COUNT": 0, "ACTIVE_DOWNTIME_HRS": 0.0, "TOTAL_COUNT": 0}

        for r in rows:
                pkg = r.get("asset_package") or "Unknown"
                totals["TOTAL_COUNT"] += 1

                # initialize
                if pkg not in packages:
                        packages[pkg] = {
                                "ACTIVE_COUNT": 0,
                                "ACTIVE_DOWNTIME_HRS": 0.0,
                                "TOTAL_COUNT": 0
                        }

                packages[pkg]["TOTAL_COUNT"] += 1

                status = (r.get("status") or "").strip().lower()
                current_status = (r.get("current_status") or "").strip().lower()

                is_closed = (
                        status == "closed"
                        or "closed" in current_status
                )

                is_active = not is_closed

                if is_active:
                        packages[pkg]["ACTIVE_COUNT"] += 1
                        totals["ACTIVE_COUNT"] += 1

                        # compute downtime for active rows (SAFE)
                        start_raw = r.get("breakdown_start")
                        end_raw   = r.get("breakdown_end")

                        start_dt = _safe_fromiso(start_raw)
                        end_dt   = _safe_fromiso(end_raw)

                        if start_dt:
                                if end_dt:
                                        delta = end_dt - start_dt
                                else:
                                        delta = now - start_dt

                                hrs = round(delta.total_seconds() / 3600, 2)

                                packages[pkg]["ACTIVE_DOWNTIME_HRS"] += hrs
                                totals["ACTIVE_DOWNTIME_HRS"] += hrs

        # -----------------------------------------
        # UI-compatible summary (OWN / HIRE)
        # -----------------------------------------
        ui_packages = {}
        ui_totals = {"OWN": 0, "HIRE": 0}

        for r in rows:
            pkg = r.get("asset_package") or "Unknown"
            oh = (r.get("own_hire") or "").upper()
            
            

            if pkg not in ui_packages:
                ui_packages[pkg] = {"OWN": 0, "HIRE": 0}

            if oh in ("OWN", "HIRE"):
                ui_packages[pkg][oh] += 1
                ui_totals[oh] += 1

        ui_totals["ALL"] = ui_totals["OWN"] + ui_totals["HIRE"]

        return jsonify({
                "packages": packages,
                "totals": totals,
                "own_hire": {
                        "packages": ui_packages,
                        "totals": ui_totals
                }
        }), 200

    except Exception as e:
        current_app.logger.error(
            "get_breakdown_summary error: %s\n%s",
            e,
            traceback.format_exc()
        )
        return jsonify({"error": str(e)}), 500

@user_bp.route("/breakdown_dashboard")
@require_role("user")
def get_breakdown_dashboard():
    """
    New unified dashboard API for Breakdown Speed & Recovery Dashboard.
    This is the ONLY source for dashboard KPIs, cards, and charts.
    """

    supabase_admin = current_app.config.get("supabase_admin")

    try:
        if not supabase_admin:
            raise RuntimeError("supabase_admin not configured")

        res = supabase_admin.table("breakdown_reports").select("*").execute()
        rows = res.data or []

        now = datetime.now(IST)

        # -----------------------------
        # Base counters
        # -----------------------------
        total_count = 0
        active_count = 0
        closed_count = 0

        # -----------------------------
        # Time accumulators
        # -----------------------------
        active_delay_sum = 0.0
        closed_repair_sum = 0.0
        closed_repair_count = 0

        # -----------------------------
        # Package buckets
        # -----------------------------
        packages = {}

        # -----------------------------
        # OWN / HIRE buckets
        # -----------------------------
        own_hire = {
            "OWN": {"count": 0, "repair_sum": 0.0},
            "HIRE": {"count": 0, "repair_sum": 0.0}
        }
        package_own_hire = {}
        # -----------------------------
        # Active ageing buckets (hrs)
        # -----------------------------
        ageing = {
            "0_24": 0,
            "24_48": 0,
            "48_plus": 0
        }

        for r in rows:
            total_count += 1

            status = (r.get("status") or "").strip().lower()
            current_status = (r.get("current_status") or "").strip().lower()

            is_closed = (
                status == "closed"
                or "closed" in current_status
            )

            pkg = r.get("asset_package") or "Unknown"
            oh  = (r.get("own_hire") or "").upper()

            # ---- Init package OWN/HIRE card metrics ----
            if pkg not in package_own_hire:
                package_own_hire[pkg] = {
                    "OWN": {
                        "active_count": 0,
                        "active_downtime": 0.0,
                        "total_count": 0,
                        "total_downtime": 0.0
                    },
                    "HIRE": {
                        "active_count": 0,
                        "active_downtime": 0.0,
                        "total_count": 0,
                        "total_downtime": 0.0
                    }
                }

            # ---- Existing package buckets (KEEP) ----
            if pkg not in packages:
                packages[pkg] = {
                    "ACTIVE": 0,
                    "ACTIVE_DELAY_SUM": 0.0,
                    "CLOSED": 0,
                    "CLOSED_REPAIR_SUM": 0.0
                }

            start_dt = _safe_fromiso(r.get("breakdown_start"))
            end_dt   = _safe_fromiso(r.get("breakdown_end"))

            if not start_dt:
                continue

            if is_closed:
                closed_count += 1
                packages[pkg]["CLOSED"] += 1

                if end_dt:
                    hrs = round((end_dt - start_dt).total_seconds() / 3600, 2)
                    closed_repair_sum += hrs
                    closed_repair_count += 1
                    packages[pkg]["CLOSED_REPAIR_SUM"] += hrs

                    # ---- EXISTING OWN / HIRE AVG REPAIR ----
                    if oh in own_hire:
                        own_hire[oh]["count"] += 1
                        own_hire[oh]["repair_sum"] += hrs

                    # ---- NEW: OWN / HIRE TOTAL (Closed) ----
                    if oh in ("OWN", "HIRE"):
                        package_own_hire[pkg][oh]["total_count"] += 1
                        package_own_hire[pkg][oh]["total_downtime"] += hrs

            else:
                active_count += 1
                packages[pkg]["ACTIVE"] += 1

                hrs = round((now - start_dt).total_seconds() / 3600, 2)
                active_delay_sum += hrs
                packages[pkg]["ACTIVE_DELAY_SUM"] += hrs

                # ---- NEW: OWN / HIRE ACTIVE ----
                if oh in ("OWN", "HIRE"):
                    package_own_hire[pkg][oh]["active_count"] += 1
                    package_own_hire[pkg][oh]["active_downtime"] += hrs
                    package_own_hire[pkg][oh]["total_count"] += 1
                    package_own_hire[pkg][oh]["total_downtime"] += hrs

                # ---- EXISTING AGEING ----
                if hrs <= 24:
                    ageing["0_24"] += 1
                elif hrs <= 48:
                    ageing["24_48"] += 1
                else:
                    ageing["48_plus"] += 1


        # -----------------------------
        # Final computed KPIs
        # -----------------------------
        avg_active_delay = (
            active_delay_sum / active_count
            if active_count else 0.0
        )

        avg_repair_time = (
            closed_repair_sum / closed_repair_count
            if closed_repair_count else 0.0
        )

        own_hire_result = {}
        for k, v in own_hire.items():
            own_hire_result[k] = (
                v["repair_sum"] / v["count"]
                if v["count"] else 0.0
            )

        # -----------------------------
        # Package averages
        # -----------------------------
        package_result = {}

        for pkg, p in packages.items():
            package_result[pkg] = {
                "active": p["ACTIVE"],
                "avg_active_delay": (
                    p["ACTIVE_DELAY_SUM"] / p["ACTIVE"]
                    if p["ACTIVE"] else 0.0
                ),
                "avg_repair_time": (
                    p["CLOSED_REPAIR_SUM"] / p["CLOSED"]
                    if p["CLOSED"] else 0.0
                )
            }

        return jsonify({
                "counts": {
                        "total": total_count,
                        "active": active_count,
                        "closed": closed_count
                },
                "kpi": {
                        "avg_active_delay": round(avg_active_delay, 2),
                        "avg_repair_time": round(avg_repair_time, 2)
                },
                "packages": package_result,
                "own_hire": own_hire_result,
                "ageing": ageing,
                "rows": rows   # ✅ ADD THIS LINE
        }), 200


    except Exception as e:
        current_app.logger.error(
            "get_breakdown_dashboard error: %s\n%s",
            e,
            traceback.format_exc()
        )
        return jsonify({"error": str(e)}), 500


@user_bp.route("/assets_autocomplete")
@require_role("user")
def assets_autocomplete():
    """Simple autocomplete for asset_code -> returns asset_code, asset_description, owner."""
    supabase_admin = current_app.config.get("supabase_admin")
    q = (request.args.get("q") or "").strip()
    try:
        if not supabase_admin:
            raise RuntimeError("supabase_admin not configured")
        if not q:
            return jsonify([]), 200
        # use ilike for case-insensitive partial match; limit to 50
        res = supabase_admin.table("asset_master").select("asset_code, asset_description, owner, package, location").ilike("asset_code", f"%{q}%").limit(50).execute()
        rows = res.data or []
        out = []
        for r in rows:
            out.append({
                "asset_code": r.get("asset_code"),
                "asset_description": r.get("asset_description"),
                "owner": r.get("owner"),
                "package": r.get("package"),
                "location": r.get("location"),
            })
        return jsonify(out), 200
    except Exception as e:
        current_app.logger.error("assets_autocomplete error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@user_bp.route("/breakdown_reports/export")
@require_role("user")
def export_breakdown_reports():
    """Export all breakdown reports as CSV (Excel-compatible)."""
    supabase_admin = current_app.config.get("supabase_admin")
    try:
        if not supabase_admin:
            raise RuntimeError("supabase_admin not configured")

        res = supabase_admin.table("breakdown_reports").select("*").order("id", desc=True).execute()
        rows = res.data or []

        now = datetime.now(IST)

        output = io.StringIO()
        writer = csv.writer(output)

        # header
        header = [
                "id", "asset_code", "asset_description", "asset_package", "own_hire","agency", "location",
                "breakdown_start", "breakdown_end", "downtime_hrs", "breakdown_type", "root_cause",
                "breakdown_description", "status", "current_status", "responsible_person",
                "expected_commissioned_at", "eip_commissioned_at", "reported_by", "created_by",
                "updated_by", "created_at", "remarks"
        ]
        writer.writerow(header)

        for r in rows:
                start_raw = r.get("breakdown_start")
                end_raw   = r.get("breakdown_end")

                downtime = ""

                start_dt = _safe_fromiso(start_raw)
                end_dt   = _safe_fromiso(end_raw)

                if start_dt:
                        if end_dt:
                                delta = end_dt - start_dt
                        else:
                                delta = now - start_dt

                        downtime = round(delta.total_seconds() / 3600, 2)

                row_vals = [
                        r.get("id"), r.get("asset_code"), r.get("asset_description"),
                        r.get("asset_package"), r.get("own_hire"), r.get("agency"), r.get("location"),
                        _to_iso(start_raw), _to_iso(end_raw), downtime,
                        r.get("breakdown_type"), r.get("root_cause"),
                        r.get("breakdown_description"), r.get("status"),
                        r.get("current_status"), r.get("responsible_person"),
                        _to_iso(r.get("expected_commissioned_at")),
                        _to_iso(r.get("eip_commissioned_at")),
                        r.get("reported_by"), r.get("created_by"),
                        r.get("updated_by"), _to_iso(r.get("created_at")),
                        r.get("remarks")
                ]

                writer.writerow(row_vals)

        output.seek(0)
        csv_bytes = output.getvalue().encode("utf-8")
        return current_app.response_class(csv_bytes, mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=breakdown_reports.csv"})

    except Exception as e:
        current_app.logger.error("export_breakdown_reports error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500


@user_bp.route("/breakdown_reports/export_xlsx")
@require_role("user")
def export_breakdown_reports_xlsx():
    """Export all breakdown reports as a formatted Excel file with borders and centered text."""
    supabase_admin = current_app.config.get("supabase_admin")
    try:
        if not supabase_admin:
            raise RuntimeError("supabase_admin not configured")

        res = supabase_admin.table("breakdown_reports").select("*").order("id", desc=True).execute()
        rows = res.data or []

        now = datetime.now(IST)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Breakdown Reports"

        header = [
                "id", "asset_code", "asset_description", "asset_package", "own_hire", "agency", "location",
                "breakdown_start", "breakdown_end", "downtime_hrs", "breakdown_type", "root_cause",
                "breakdown_description", "status", "current_status", "responsible_person",
                "expected_commissioned_at", "eip_commissioned_at", "reported_by", "created_by",
                "updated_by", "created_at", "remarks"
        ]

        # write header
        for c, h in enumerate(header, start=1):
                cell = ws.cell(row=1, column=c, value=h)
                cell.font = Font(bold=True)
                cell.alignment = Alignment(horizontal='center', vertical='center')

        thin = Side(border_style="thin", color="000000")
        border = Border(left=thin, right=thin, top=thin, bottom=thin)

        # write rows
        for r_idx, r in enumerate(rows, start=2):
                start_raw = r.get("breakdown_start")
                end_raw   = r.get("breakdown_end")

                downtime = ""

                start_dt = _safe_fromiso(start_raw)
                end_dt   = _safe_fromiso(end_raw)

                if start_dt:
                        if end_dt:
                                delta = end_dt - start_dt
                        else:
                                delta = now - start_dt

                        downtime = round(delta.total_seconds() / 3600, 2)

                vals = [
                        r.get("id"), r.get("asset_code"), r.get("asset_description"),
                        r.get("asset_package"), r.get("own_hire"), r.get("agency"), r.get("location"),
                        _to_iso(start_raw), _to_iso(end_raw), downtime,
                        r.get("breakdown_type"), r.get("root_cause"),
                        r.get("breakdown_description"), r.get("status"),
                        r.get("current_status"), r.get("responsible_person"),
                        _to_iso(r.get("expected_commissioned_at")),
                        _to_iso(r.get("eip_commissioned_at")),
                        r.get("reported_by"), r.get("created_by"),
                        r.get("updated_by"), _to_iso(r.get("created_at")),
                        r.get("remarks")
                ]

                for c_idx, v in enumerate(vals, start=1):
                        cell = ws.cell(row=r_idx, column=c_idx, value=v)
                        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=False)
                        cell.border = border


        # auto-size columns (simple heuristic)
        for i, col in enumerate(ws.columns, start=1):
            max_length = 0
            for cell in col:
                try:
                    if cell.value:
                        l = len(str(cell.value))
                        if l > max_length:
                            max_length = l
                except Exception:
                    pass
            adjusted_width = (max_length + 2) if max_length > 0 else 12
            ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = adjusted_width

        bio = io.BytesIO()
        wb.save(bio)
        bio.seek(0)
        return current_app.response_class(bio.getvalue(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={"Content-Disposition": "attachment;filename=breakdown_reports.xlsx"})

    except Exception as e:
        current_app.logger.error("export_breakdown_reports_xlsx error: %s\n%s", e, traceback.format_exc())
        return jsonify({"error": str(e)}), 500




