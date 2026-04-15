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
    """Scan all active alerts, then email a digest of new finds and exit."""
    from db import init_db, get_setting, set_setting, get_digest_results_since
    from scanner_core import scan_all_alerts
    from emailer import send_digest, build_digest_html, get_smtp_config

    init_db()

    last_sent = get_setting("last_digest_sent", "2000-01-01 00:00:00")
    log.info("Running digest (posts since %s)", last_sent)

    scan_results = scan_all_alerts()

    all_results = get_digest_results_since(last_sent)

    total = sum(len(posts) for posts in all_results.values())
    if total == 0:
        log.info("No new posts to report. Skipping email.")
    else:
        log.info("Digest: %d new post(s) across %d alert(s)", total, len(all_results))
        try:
            send_digest(all_results)
            log.info("Digest email sent successfully.")
        except Exception as e:
            log.error("Failed to send digest email: %s", e)
            sys.exit(1)

    set_setting("last_digest_sent", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("Done.")


def run_web():
    """Start the Flask web app."""
    from db import init_db
    from app import app

    init_db()
    print("\n  Resale Signal running at http://127.0.0.1:5000\n")
    app.run(debug=True, host="127.0.0.1", port=5000, use_reloader=False)


if __name__ == "__main__":
    if "--digest" in sys.argv:
        run_digest()
    else:
        run_web()
