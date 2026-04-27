import threading
import logging
import os
from functools import wraps
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from werkzeug.middleware.proxy_fix import ProxyFix

from db import (
    init_db, get_alerts_for_user, get_all_active_alerts, get_alert, add_alert,
    update_alert, delete_alert, toggle_alert, get_posts_for_alert, get_post_count,
    add_notification, get_notifications_for_user, get_setting, set_setting,
    create_user, get_user_by_email, get_user_by_id, generate_magic_token,
    verify_magic_token, get_users_with_alerts, get_digest_results_for_user,
    update_user_digest_sent, get_user_by_unsubscribe_token, deactivate_user_alerts,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)
log.info("Starting Resale Signal app module...")

MAX_ALERTS_PER_USER = 5

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "resale-signal-secret-key-change-me")

# Trust Railway/Render/etc reverse proxy headers so request.url_root uses https
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

log.info("Initializing database at %s", os.getenv("DATABASE_PATH", "(default ./scraper.db)"))
init_db()
log.info("Database ready. App module loaded.")


# --------------- Auth helpers ---------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("landing"))
        return f(*args, **kwargs)
    return decorated


def current_user():
    uid = session.get("user_id")
    if uid:
        return get_user_by_id(uid)
    return None


@app.context_processor
def inject_user():
    return {"current_user": current_user()}


# --------------- Auth routes ---------------

@app.route("/")
def landing():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/auth/login", methods=["POST"])
def auth_login():
    email = request.form.get("email", "").strip().lower()
    if not email or "@" not in email:
        flash("Please enter a valid email address.", "error")
        return redirect(url_for("landing"))

    user = get_user_by_email(email)
    if not user:
        uid = create_user(email)
    else:
        uid = user["id"]

    token = generate_magic_token(uid)

    base_url = os.getenv("SITE_URL", "").rstrip("/") or request.url_root.rstrip("/")
    magic_url = f"{base_url}/auth/verify?token={token}"

    try:
        from emailer import send_magic_link_email
        send_magic_link_email(email, magic_url)
    except Exception as e:
        log.error("Failed to send magic link to %s: %s", email, e)
        flash("Failed to send login email. Please try again.", "error")
        return redirect(url_for("landing"))

    return render_template("login_sent.html", email=email)


@app.route("/auth/verify")
def auth_verify():
    token = request.args.get("token", "")
    user = verify_magic_token(token)
    if not user:
        flash("Invalid or expired link. Please request a new one.", "error")
        return redirect(url_for("landing"))

    session["user_id"] = user["id"]
    flash(f"Welcome back, {user['email']}!", "success")
    return redirect(url_for("dashboard"))


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    session.clear()
    flash("You've been logged out.", "success")
    return redirect(url_for("landing"))


# --------------- Dashboard ---------------

@app.route("/dashboard")
@login_required
def dashboard():
    user = current_user()
    uid = user["id"]

    alerts = get_alerts_for_user(uid)
    for a in alerts:
        a["post_count"] = get_post_count(a["id"])
        a["recent_posts"] = get_posts_for_alert(a["id"], limit=5)

    notifications = get_notifications_for_user(uid, limit=10)

    return render_template("dashboard.html",
                           alerts=alerts,
                           notifications=notifications,
                           max_alerts=MAX_ALERTS_PER_USER)


# --------------- Alert CRUD ---------------

@app.route("/alerts/new")
@login_required
def new_alert():
    uid = session["user_id"]
    if len(get_alerts_for_user(uid)) >= MAX_ALERTS_PER_USER:
        flash(f"You've reached the maximum of {MAX_ALERTS_PER_USER} alerts. Edit or delete an existing alert first.", "error")
        return redirect(url_for("dashboard"))
    return render_template("alert_form.html", alert=None)


@app.route("/alerts", methods=["POST"])
@login_required
def create_alert():
    uid = session["user_id"]

    if len(get_alerts_for_user(uid)) >= MAX_ALERTS_PER_USER:
        flash(f"You've reached the maximum of {MAX_ALERTS_PER_USER} alerts. Edit or delete an existing alert first.", "error")
        return redirect(url_for("dashboard"))

    name = request.form.get("name", "").strip()
    region = request.form.get("region", "").strip().lower()
    category = request.form.get("category", "sss").strip().lower()
    query = request.form.get("query", "").strip()
    min_price = request.form.get("min_price", "").strip()
    max_price = request.form.get("max_price", "").strip()

    if not name or not region or not query:
        flash("Name, region, and search query are required.", "error")
        return redirect(url_for("new_alert"))

    add_alert(
        user_id=uid,
        name=name,
        region=region,
        category=category,
        query=query,
        min_price=int(min_price) if min_price else None,
        max_price=int(max_price) if max_price else None,
    )
    flash(f"Alert \"{name}\" created.", "success")
    return redirect(url_for("dashboard"))


@app.route("/alerts/<int:alert_id>")
@login_required
def alert_detail(alert_id):
    uid = session["user_id"]
    alert = get_alert(alert_id, user_id=uid)
    if not alert:
        flash("Alert not found.", "error")
        return redirect(url_for("dashboard"))

    posts = get_posts_for_alert(alert_id, limit=200)
    return render_template("alert_detail.html", alert=alert, posts=posts)


@app.route("/alerts/<int:alert_id>/edit")
@login_required
def edit_alert(alert_id):
    uid = session["user_id"]
    alert = get_alert(alert_id, user_id=uid)
    if not alert:
        flash("Alert not found.", "error")
        return redirect(url_for("dashboard"))
    return render_template("alert_form.html", alert=alert)


@app.route("/alerts/<int:alert_id>/edit", methods=["POST"])
@login_required
def update_alert_route(alert_id):
    uid = session["user_id"]
    alert = get_alert(alert_id, user_id=uid)
    if not alert:
        flash("Alert not found.", "error")
        return redirect(url_for("dashboard"))

    name = request.form.get("name", "").strip()
    region = request.form.get("region", "").strip().lower()
    category = request.form.get("category", "sss").strip().lower()
    query = request.form.get("query", "").strip()
    min_price = request.form.get("min_price", "").strip()
    max_price = request.form.get("max_price", "").strip()

    if not name or not region or not query:
        flash("Name, region, and search query are required.", "error")
        return redirect(url_for("edit_alert", alert_id=alert_id))

    update_alert(
        alert_id,
        name=name,
        region=region,
        category=category,
        query=query,
        min_price=int(min_price) if min_price else None,
        max_price=int(max_price) if max_price else None,
    )
    flash(f"Alert \"{name}\" updated.", "success")
    return redirect(url_for("dashboard"))


@app.route("/alerts/<int:alert_id>/delete", methods=["POST"])
@login_required
def remove_alert(alert_id):
    uid = session["user_id"]
    alert = get_alert(alert_id, user_id=uid)
    if alert:
        delete_alert(alert_id, uid)
        flash(f"Alert \"{alert['name']}\" deleted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/alerts/<int:alert_id>/toggle", methods=["POST"])
@login_required
def toggle_alert_route(alert_id):
    uid = session["user_id"]
    toggle_alert(alert_id, uid)
    return redirect(url_for("dashboard"))


# --------------- Unsubscribe ---------------

@app.route("/unsubscribe")
def unsubscribe():
    token = request.args.get("token", "")
    user = get_user_by_unsubscribe_token(token)
    if not user:
        flash("Invalid unsubscribe link.", "error")
        return redirect(url_for("landing"))
    deactivate_user_alerts(user["id"])
    return render_template("unsubscribed.html", email=user["email"])


# --------------- Digest endpoint (cron trigger) ---------------

def _run_digest_job():
    """Run the full digest pipeline in-process."""
    from scanner_core import scan_all_alerts
    from emailer import send_digest

    log.info("Digest job: scanning all active alerts...")
    scan_all_alerts()

    users = get_users_with_alerts()
    log.info("Digest job: building digests for %d user(s)...", len(users))

    for user in users:
        since = user.get("last_digest_sent") or "2000-01-01 00:00:00"
        results = get_digest_results_for_user(user["id"], since)
        total = sum(len(posts) for posts in results.values())

        if total == 0:
            log.info("  [%s] No new posts. Skipping.", user["email"])
            update_user_digest_sent(user["id"])
            continue

        log.info("  [%s] %d new post(s) across %d alert(s)", user["email"], total, len(results))
        try:
            send_digest(user["email"], results,
                        unsubscribe_token=user.get("unsubscribe_token"))
            update_user_digest_sent(user["id"])
            log.info("  [%s] Digest sent.", user["email"])
        except Exception as e:
            log.error("  [%s] Failed to send digest: %s", user["email"], e)

    log.info("Digest job: done.")


@app.route("/digest/run", methods=["POST"])
def digest_run():
    secret = os.getenv("DIGEST_SECRET", "")
    provided = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()

    if not secret or provided != secret:
        return jsonify({"error": "unauthorized"}), 401

    threading.Thread(target=_run_digest_job, daemon=True).start()
    return jsonify({"status": "digest started"}), 202


@app.route("/api/status")
def api_status():
    return jsonify({"status": "ok"})


# --------------- Startup ---------------

if __name__ == "__main__":
    log.info("Starting Resale Signal web app...")
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=True, host="0.0.0.0", port=port, use_reloader=False)
