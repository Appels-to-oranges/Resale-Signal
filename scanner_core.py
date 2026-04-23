import logging
from collections import defaultdict
from datetime import datetime

from scraper import build_search_url, scrape_listings, polite_delay
from db import (
    get_all_active_alerts, is_new_post, save_post, update_alert, add_notification,
)
from notifier import notify_new_posts

log = logging.getLogger(__name__)


def _search_fingerprint(alert: dict) -> str:
    """Unique key for a Craigslist search URL (region+category+query+prices)."""
    return "|".join([
        alert["region"].lower(),
        alert["category"].lower(),
        alert["query"].lower(),
        str(alert.get("min_price") or ""),
        str(alert.get("max_price") or ""),
    ])


def check_single_alert(alert: dict, prefetched_listings=None) -> list[dict]:
    """Scrape one alert, save new posts, log a notification. Returns list of new posts."""
    if prefetched_listings is None:
        url = build_search_url(
            region=alert["region"],
            category=alert["category"],
            query=alert["query"],
            min_price=alert.get("min_price"),
            max_price=alert.get("max_price"),
        )
        log.info("Checking [%s] → %s", alert["name"], url)

        try:
            prefetched_listings = scrape_listings(url)
        except Exception as e:
            log.error("Failed to scrape [%s]: %s", alert["name"], e)
            return []

    query_words = alert["query"].lower().split()

    new_posts = []
    for post in prefetched_listings:
        title_lower = post.title.lower()
        if not all(word in title_lower for word in query_words):
            continue
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
    log.info("  [%s] Found %d listings, %d new", alert["name"],
             len(prefetched_listings), len(new_posts))

    if new_posts:
        msg = f"{len(new_posts)} new listing(s) found"
        add_notification(alert["id"], msg, len(new_posts))
        notify_new_posts(alert["name"], new_posts)

    return new_posts


def scan_all_alerts() -> dict[str, list[dict]]:
    """Scan every active alert, deduplicating identical Craigslist searches."""
    alerts = get_all_active_alerts()
    if not alerts:
        return {}

    groups: dict[str, list[dict]] = defaultdict(list)
    for alert in alerts:
        fp = _search_fingerprint(alert)
        groups[fp].append(alert)

    log.info("scan_all_alerts: %d alert(s) → %d unique search(es)",
             len(alerts), len(groups))

    results: dict[str, list[dict]] = {}
    first_group = True

    for fp, group in groups.items():
        if not first_group:
            polite_delay()
        first_group = False

        representative = group[0]
        url = build_search_url(
            region=representative["region"],
            category=representative["category"],
            query=representative["query"],
            min_price=representative.get("min_price"),
            max_price=representative.get("max_price"),
        )
        log.info("Scraping fingerprint [%s] → %s (%d alert(s))",
                 fp, url, len(group))

        try:
            listings = scrape_listings(url)
        except Exception as e:
            log.error("Failed to scrape fingerprint [%s]: %s", fp, e)
            for a in group:
                update_alert(a["id"],
                             last_checked=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            continue

        for alert in group:
            new_posts = check_single_alert(alert, prefetched_listings=listings)
            if new_posts:
                results[alert["name"]] = new_posts

    return results
