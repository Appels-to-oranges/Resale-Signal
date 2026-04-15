import threading
import time
import logging
from datetime import datetime

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

from db import (
    init_db, get_alerts, get_alert, add_alert, update_alert, delete_alert,
    toggle_alert, get_posts_for_alert, get_post_count,
    add_notification, get_notifications, get_setting, set_setting,
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
app.secret_key = "resale-signal-secret-key-change-me"

scanner_thread = None
scanner_running = False
scanner_status = {"state": "stopped", "last_run": None, "current_alert": None}


# --------------- Background Scanner ---------------

def run_scanner():
    global scanner_running, scanner_status
    scanner_status["state"] = "running"
    log.info("Scanner thread started")

    while scanner_running:
        alerts = get_alerts(active_only=True)
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


# --------------- Routes ---------------

@app.route("/")
def dashboard():
    alerts = get_alerts()
    alert_data = []
    for a in alerts:
        a["post_count"] = get_post_count(a["id"])
        recent = get_posts_for_alert(a["id"], limit=5)
        a["recent_posts"] = recent
        alert_data.append(a)

    notifications = get_notifications(limit=10)
    interval = get_setting("poll_interval_minutes", "10")

    email_settings = {
        "smtp_host": get_setting("smtp_host", ""),
        "smtp_port": get_setting("smtp_port", "587"),
        "smtp_user": get_setting("smtp_user", ""),
        "smtp_password": get_setting("smtp_password", ""),
        "smtp_to": get_setting("smtp_to", ""),
        "smtp_use_tls": get_setting("smtp_use_tls", "true"),
    }

    return render_template("dashboard.html",
                           alerts=alert_data,
                           notifications=notifications,
                           scanner=scanner_status,
                           scanner_running=scanner_running,
                           poll_interval=interval,
                           email=email_settings)


@app.route("/alerts/new")
def new_alert():
    return render_template("alert_form.html", alert=None)


@app.route("/alerts", methods=["POST"])
def create_alert():
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
def alert_detail(alert_id):
    alert = get_alert(alert_id)
    if not alert:
        flash("Alert not found.", "error")
        return redirect(url_for("dashboard"))

    posts = get_posts_for_alert(alert_id, limit=200)
    return render_template("alert_detail.html", alert=alert, posts=posts)


@app.route("/alerts/<int:alert_id>/delete", methods=["POST"])
def remove_alert(alert_id):
    alert = get_alert(alert_id)
    if alert:
        delete_alert(alert_id)
        flash(f"Alert \"{alert['name']}\" deleted.", "success")
    return redirect(url_for("dashboard"))


@app.route("/alerts/<int:alert_id>/toggle", methods=["POST"])
def toggle_alert_route(alert_id):
    toggle_alert(alert_id)
    return redirect(url_for("dashboard"))


@app.route("/scan", methods=["POST"])
def trigger_scan():
    if not scanner_running:
        flash("Start the scanner first.", "error")
        return redirect(url_for("dashboard"))

    def one_off():
        for alert in get_alerts(active_only=True):
            check_single_alert(alert)
            polite_delay()

    threading.Thread(target=one_off, daemon=True).start()
    flash("Manual scan triggered.", "success")
    return redirect(url_for("dashboard"))


@app.route("/scanner/start", methods=["POST"])
def start_scanner_route():
    start_scanner()
    flash("Scanner started.", "success")
    return redirect(url_for("dashboard"))


@app.route("/scanner/stop", methods=["POST"])
def stop_scanner_route():
    stop_scanner()
    flash("Scanner stopping...", "success")
    return redirect(url_for("dashboard"))


@app.route("/settings", methods=["POST"])
def update_settings():
    interval = request.form.get("poll_interval", "10").strip()
    try:
        val = max(1, int(interval))
        set_setting("poll_interval_minutes", str(val))
        flash(f"Poll interval set to {val} minutes.", "success")
    except ValueError:
        flash("Invalid interval value.", "error")
    return redirect(url_for("dashboard"))


@app.route("/settings/email", methods=["POST"])
def update_email_settings():
    for key in ["smtp_host", "smtp_port", "smtp_user", "smtp_password", "smtp_to"]:
        val = request.form.get(key, "").strip()
        if val:
            set_setting(key, val)

    tls = "true" if request.form.get("smtp_use_tls") else "false"
    set_setting("smtp_use_tls", tls)

    flash("Email settings saved.", "success")
    return redirect(url_for("dashboard"))


@app.route("/settings/email/test", methods=["POST"])
def test_email():
    try:
        from emailer import send_test_email
        send_test_email()
        flash("Test email sent! Check your inbox.", "success")
    except Exception as e:
        flash(f"Failed to send test email: {e}", "error")
    return redirect(url_for("dashboard"))


@app.route("/api/status")
def api_status():
    return jsonify({
        "scanner_running": scanner_running,
        "status": scanner_status,
        "alert_count": len(get_alerts()),
        "active_alerts": len(get_alerts(active_only=True)),
    })


# --------------- Startup ---------------

if __name__ == "__main__":
    init_db()
    log.info("Starting Resale Signal web app...")
    app.run(debug=True, host="127.0.0.1", port=5000, use_reloader=False)
