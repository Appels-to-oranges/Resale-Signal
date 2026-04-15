import sys
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def run_digest():
    """Scan all active alerts, then email a per-user digest of new finds and exit."""
    from db import (
        init_db, get_users_with_alerts, get_alerts_for_user,
        get_digest_results_for_user, update_user_digest_sent,
    )
    from scanner_core import scan_all_alerts
    from emailer import send_digest

    init_db()

    log.info("Scanning all active alerts...")
    scan_all_alerts()

    users = get_users_with_alerts()
    log.info("Building digests for %d user(s)...", len(users))

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
            send_digest(user["email"], results)
            update_user_digest_sent(user["id"])
            log.info("  [%s] Digest sent.", user["email"])
        except Exception as e:
            log.error("  [%s] Failed to send digest: %s", user["email"], e)

    log.info("Done.")


def run_web():
    """Start the Flask dev server (use gunicorn in production)."""
    import os
    from app import app

    port = int(os.getenv("PORT", "5000"))
    host = os.getenv("HOST", "127.0.0.1")
    print(f"\n  Resale Signal running at http://{host}:{port}\n")
    app.run(debug=True, host=host, port=port, use_reloader=False)


if __name__ == "__main__":
    if "--digest" in sys.argv:
        run_digest()
    else:
        run_web()
