import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

log = logging.getLogger(__name__)


def _site_url() -> str:
    return os.getenv("SITE_URL", "").rstrip("/") or "http://localhost:5000"


def get_smtp_config() -> dict:
    return {
        "host": os.getenv("SMTP_HOST", ""),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "user": os.getenv("SMTP_USER", ""),
        "password": os.getenv("SMTP_PASSWORD", ""),
        "use_tls": os.getenv("SMTP_USE_TLS", "true").lower() == "true",
    }


def send_email(recipient: str, subject: str, html_body: str,
               unsubscribe_url: str | None = None):
    cfg = get_smtp_config()
    host = cfg["host"]
    port = cfg["port"]
    user = cfg["user"]
    password = cfg["password"]

    if not all([host, user, password, recipient]):
        log.error("SMTP not configured. Set values in .env.")
        raise ValueError("SMTP not configured — fill in .env settings.")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = recipient

    if unsubscribe_url:
        msg["List-Unsubscribe"] = f"<{unsubscribe_url}>"
        msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    msg.attach(MIMEText(html_body, "html"))

    log.info("Sending email to %s via %s:%d", recipient, host, port)

    if cfg["use_tls"]:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(user, password)
            server.sendmail(user, [recipient], msg.as_string())
    else:
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.ehlo()
            server.login(user, password)
            server.sendmail(user, [recipient], msg.as_string())

    log.info("Email sent successfully")


# --------------- Magic Link Email ---------------

def send_magic_link_email(to_email: str, magic_url: str):
    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:40px 0;">
<tr><td align="center">
<table width="480" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
    <tr>
        <td style="background:linear-gradient(135deg,#3366ff,#1a4fdd);padding:28px 24px;text-align:center;">
            <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">Resale Signal</h1>
        </td>
    </tr>
    <tr>
        <td style="padding:32px 28px;">
            <p style="margin:0 0 16px;font-size:16px;color:#333;line-height:1.5;">
                Click the button below to sign in to your Resale Signal account.
            </p>
            <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                    <td align="center" style="padding:16px 0;">
                        <a href="{magic_url}"
                           style="display:inline-block;background:#3366ff;color:#fff;font-size:16px;font-weight:600;padding:14px 36px;border-radius:8px;text-decoration:none;">
                            Sign In
                        </a>
                    </td>
                </tr>
            </table>
            <p style="margin:16px 0 0;font-size:13px;color:#999;line-height:1.5;">
                This link expires in 1 hour. If you didn't request this, you can safely ignore this email.
            </p>
        </td>
    </tr>
    <tr>
        <td style="padding:16px 28px;text-align:center;font-size:12px;color:#aaa;border-top:1px solid #eee;">
            Sent by <a href="{_site_url()}/dashboard" style="color:#4a7dff;text-decoration:none;">Resale Signal</a>
        </td>
    </tr>
</table>
</td></tr>
</table>
</body>
</html>"""
    send_email(to_email, "Sign in to Resale Signal", html)


# --------------- Digest Email ---------------

def build_digest_html(results: dict[str, list[dict]],
                      dashboard_url: str | None = None,
                      unsubscribe_url: str | None = None) -> str:
    total = sum(len(posts) for posts in results.values())
    date_str = datetime.now().strftime("%B %d, %Y")

    rows_html = ""
    for alert_name, posts in results.items():
        if not posts:
            continue
        rows_html += f"""
        <tr>
            <td colspan="3" style="padding:16px 12px 6px;font-size:16px;font-weight:700;color:#1a4fdd;border-bottom:2px solid #e0eaff;">
                {alert_name} &mdash; {len(posts)} new
            </td>
        </tr>"""
        for p in posts:
            price = p.get("price", "")
            location = p.get("neighborhood", "")
            loc_html = f'<span style="color:#888;font-size:12px;"> &middot; {location}</span>' if location else ""
            rows_html += f"""
        <tr>
            <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;">
                <a href="{p['url']}" style="color:#222;text-decoration:none;">{p['title']}</a>{loc_html}
            </td>
            <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;color:#16a34a;font-weight:600;white-space:nowrap;">
                {price}
            </td>
            <td style="padding:8px 12px;border-bottom:1px solid #f0f0f0;text-align:right;">
                <a href="{p['url']}" style="color:#4a7dff;text-decoration:none;font-size:13px;">View &rarr;</a>
            </td>
        </tr>"""

    if not rows_html:
        rows_html = """
        <tr>
            <td colspan="3" style="padding:30px 12px;text-align:center;color:#999;">
                No new listings found since the last digest.
            </td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:20px 0;">
<tr><td align="center">
<table width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.06);">
    <tr>
        <td colspan="3" style="background:linear-gradient(135deg,#3366ff,#1a4fdd);padding:24px 20px;text-align:center;">
            <h1 style="margin:0;color:#fff;font-size:22px;font-weight:700;">Resale Signal</h1>
            <p style="margin:6px 0 0;color:rgba(255,255,255,0.8);font-size:14px;">{date_str} &middot; {total} new listing{'s' if total != 1 else ''}</p>
        </td>
    </tr>
    {rows_html}
    <tr>
        <td colspan="3" style="padding:16px 12px;text-align:center;font-size:12px;color:#aaa;border-top:1px solid #eee;">
            Sent by Resale Signal{f' &middot; <a href="{dashboard_url}" style="color:#4a7dff;text-decoration:none;">Manage alerts</a>' if dashboard_url else ''}{f' &middot; <a href="{unsubscribe_url}" style="color:#aaa;text-decoration:underline;">Unsubscribe</a>' if unsubscribe_url else ''}
        </td>
    </tr>
</table>
</td></tr>
</table>
</body>
</html>"""


def send_digest(recipient: str, results: dict[str, list[dict]],
                unsubscribe_token: str | None = None):
    """Build and send a digest email to a specific user."""
    total = sum(len(posts) for posts in results.values())
    subject = f"Resale Signal: {total} new listing{'s' if total != 1 else ''} — {datetime.now().strftime('%b %d')}"

    base = _site_url()
    dashboard_url = f"{base}/dashboard"
    unsub_url = f"{base}/unsubscribe?token={unsubscribe_token}" if unsubscribe_token else None

    html = build_digest_html(results, dashboard_url=dashboard_url, unsubscribe_url=unsub_url)
    send_email(recipient, subject, html, unsubscribe_url=unsub_url)


def send_test_email(recipient: str):
    """Send a test email to verify SMTP config is working."""
    base = _site_url()
    html = build_digest_html(
        {"Test Alert": [
            {"title": "This is a test listing", "price": "$100", "url": "#", "neighborhood": "Downtown"},
        ]},
        dashboard_url=f"{base}/dashboard",
    )
    send_email(recipient, "Resale Signal — Test Email", html)
