import threading
import time
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
    verify_magic_token,
)
from scraper import polite_delay
from scanner_core import check_single_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "resale-signal-secret-key-change-me")

# Trust Railway/Render/etc reverse proxy headers so request.url_root uses https
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

init_db()

scanner_thread = None
scanner_running = False
scanner_status = {"state": "stopped", "last_run": None, "current_alert": None}


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


# --------------- Background Scanner ---------------

def run_scanner():
    global scanner_running, scanner_status
    scanner_status["state"] = "running"
    log.info("Scanner thread started")

    while scanner_running:
        alerts = get_all_active_alerts()
        for alert in alerts:
            if not scanner_running:
                break
            scanner_status["current_alert"] = alert["name"]
            check_single_alert(alert)
            polite_delay()

        scanner_status["current_alert"] = None
        scanner_status["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        interval = int(get_setting("poll_interval_minutes", "10"))
        log.info("Scan complete. Sleeping %d minutes...", interval)

        for _ in range(interval * 60):
            if not scanner_running:
                break
            time.sleep(1)

    scanner_status["state"] = "stopped"
    log.info("Scanner thread stopped")


def start_scanner():
    global scanner_thread, scanner_running
    if scanner_running:
        return
    scanner_running = True
    scanner_thread = threading.Thread(target=run_scanner, daemon=True)
    scanner_thread.start()


def stop_scanner():
    global scanner_running
    scanner_running = False


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
    interval = get_setting("poll_interval_minutes", "10")

    return render_template("dashboard.html",
                           alerts=alerts,
                           notifications=notifications,
                           scanner=scanner_status,
                           scanner_running=scanner_running,
                           poll_interval=interval)


# --------------- Alert CRUD ---------------

@app.route("/alerts/new")
@login_required
def new_alert():
    return render_template("alert_form.html", alert=None)


@app.route("/alerts", methods=["POST"])
@login_required
def create_alert():
    uid = session["user_id"]
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


# --------------- Scanner controls ---------------

@app.route("/scan", methods=["POST"])
@login_required
def trigger_scan():
    uid = session["user_id"]
    if not scanner_running:
        flash("Start the scanner first.", "error")
        return redirect(url_for("dashboard"))

    def one_off():
        for alert in get_alerts_for_user(uid, active_only=True):
            check_single_alert(alert)
            polite_delay()

    threading.Thread(target=one_off, daemon=True).start()
    flash("Manual scan triggered for your alerts.", "success")
    return redirect(url_for("dashboard"))


@app.route("/scanner/start", methods=["POST"])
@login_required
def start_scanner_route():
    start_scanner()
    flash("Scanner started.", "success")
    return redirect(url_for("dashboard"))


@app.route("/scanner/stop", methods=["POST"])
@login_required
def stop_scanner_route():
    stop_scanner()
    flash("Scanner stopping...", "success")
    return redirect(url_for("dashboard"))


@app.route("/settings", methods=["POST"])
@login_required
def update_settings():
    interval = request.form.get("poll_interval", "10").strip()
    try:
        val = max(1, int(interval))
        set_setting("poll_interval_minutes", str(val))
        flash(f"Poll interval set to {val} minutes.", "success")
    except ValueError:
        flash("Invalid interval value.", "error")
    return redirect(url_for("dashboard"))


@app.route("/api/status")
def api_status():
    return jsonify({
        "scanner_running": scanner_running,
        "status": scanner_status,
    })


# --------------- Startup ---------------

if __name__ == "__main__":
    log.info("Starting Resale Signal web app...")
    port = int(os.getenv("PORT", "5000"))
    app.run(debug=True, host="0.0.0.0", port=port, use_reloader=False)
