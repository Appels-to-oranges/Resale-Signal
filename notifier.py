import platform
import logging

log = logging.getLogger(__name__)


def send_notification(title: str, message: str):
    """Send a desktop notification. Falls back to console output if toast fails."""
    try:
        from plyer import notification
        notification.notify(
            title=title,
            message=message[:256],
            app_name="Resale Signal",
            timeout=10,
        )
    except Exception as e:
        log.warning("Desktop notification failed (%s), printing to console", e)

    print(f"\n{'='*60}")
    print(f"  ALERT: {title}")
    print(f"  {message}")
    print(f"{'='*60}\n")


def notify_new_posts(alert_name: str, posts: list[dict]):
    """Send a notification summarizing new posts found for an alert."""
    count = len(posts)
    if count == 0:
        return

    title = f"{count} new listing{'s' if count > 1 else ''} — {alert_name}"

    lines = []
    for p in posts[:5]:
        price_str = f" ({p['price']})" if p.get("price") else ""
        lines.append(f"• {p['title']}{price_str}")
    if count > 5:
        lines.append(f"  ...and {count - 5} more")

    send_notification(title, "\n".join(lines))
