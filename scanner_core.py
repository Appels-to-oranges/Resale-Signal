import logging
from datetime import datetime

from scraper import build_search_url, scrape_listings, polite_delay
from db import (
    get_all_active_alerts, is_new_post, save_post, update_alert, add_notification,
)
from notifier import notify_new_posts

log = logging.getLogger(__name__)


def check_single_alert(alert: dict) -> list[dict]:
    """Scrape one alert, save new posts, log a notification. Returns list of new posts."""
    url = build_search_url(
        region=alert["region"],
        category=alert["category"],
        query=alert["query"],
        min_price=alert.get("min_price"),
        max_price=alert.get("max_price"),
    )
    log.info("Checking [%s] → %s", alert["name"], url)

    try:
        listings = scrape_listings(url)
    except Exception as e:
        log.error("Failed to scrape [%s]: %s", alert["name"], e)
        return []

    new_posts = []
    for post in listings:
        if is_new_post(post.post_id):
            save_post(post.post_id, post.title, post.price, post.url,
                      alert["id"], post.neighborhood)
            new_posts.append({
                "title": post.title,
                "price": post.price,
                "url": post.url,
                "neighborhood": post.neighborhood,
            })

    update_alert(alert["id"], last_checked=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    log.info("  [%s] Found %d listings, %d new", alert["name"], len(listings), len(new_posts))

    if new_posts:
        msg = f"{len(new_posts)} new listing(s) found"
        add_notification(alert["id"], msg, len(new_posts))
        notify_new_posts(alert["name"], new_posts)

    return new_posts


def scan_all_alerts() -> dict[str, list[dict]]:
    """Scan every active alert. Returns {alert_name: [new_posts]}."""
    alerts = get_all_active_alerts()
    results: dict[str, list[dict]] = {}
    for alert in alerts:
        new_posts = check_single_alert(alert)
        if new_posts:
            results[alert["name"]] = new_posts
        polite_delay()
    return results
