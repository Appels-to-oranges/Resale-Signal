import requests
from bs4 import BeautifulSoup
from dataclasses import dataclass
from urllib.parse import urljoin
import time
import random


USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]


@dataclass
class CraigslistPost:
    post_id: str
    title: str
    price: str
    url: str
    neighborhood: str
    date: str


def build_search_url(region: str, category: str, query: str,
                     min_price: int | None = None, max_price: int | None = None,
                     sort: str = "date") -> str:
    """Build a Craigslist search URL from parameters."""
    base = f"https://{region}.craigslist.org/search/{category}"
    params = {"query": query, "sort": sort}
    if min_price is not None:
        params["min_price"] = str(min_price)
    if max_price is not None:
        params["max_price"] = str(max_price)

    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    return f"{base}?{query_string}"


def scrape_listings(url: str) -> list[CraigslistPost]:
    """Scrape a Craigslist search results page and return parsed posts."""
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")
    posts: list[CraigslistPost] = []

    results = soup.select("li.cl-static-search-result")
    for item in results:
        link = item.select_one("a")
        if not link:
            continue

        href = link.get("href", "")
        post_id = href.rstrip("/").split("/")[-1].split(".")[0] if href else ""
        title_el = item.select_one("div.title")
        price_el = item.select_one("div.price")
        location_el = item.select_one("div.location")
        date_el = item.select_one("div.meta")

        title = title_el.get_text(strip=True) if title_el else "No title"
        price = price_el.get_text(strip=True) if price_el else "No price"
        neighborhood = location_el.get_text(strip=True) if location_el else ""
        date = date_el.get_text(strip=True) if date_el else ""

        if not post_id:
            post_id = str(hash(title + price + href))

        full_url = urljoin(f"https://craigslist.org", href) if href else ""

        posts.append(CraigslistPost(
            post_id=post_id,
            title=title,
            price=price,
            url=full_url,
            neighborhood=neighborhood,
            date=date,
        ))

    return posts


def polite_delay():
    """Random delay between requests to be respectful."""
    time.sleep(random.uniform(3, 7))
