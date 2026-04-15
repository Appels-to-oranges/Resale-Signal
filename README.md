# Resale Signal

A web app that monitors Craigslist and alerts you when new listings match your searches. Set up alerts, run the scanner, and get notified via desktop toasts or a daily email digest.

## Setup

```bash
pip install -r requirements.txt
```

## Usage

**Web dashboard** (manage alerts, view results, control scanner):
```bash
python main.py
```
Then open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser.

**Email digest** (scan once, email results, exit):
```bash
python main.py --digest
```
Schedule this with cron or Windows Task Scheduler to receive a daily summary without keeping the web app running.

## How it works

1. Create alerts in the web UI — specify a search query, Craigslist region, category, and optional price range
2. Start the scanner from the dashboard (or schedule `--digest` for hands-off use)
3. The scanner checks all active alerts on a configurable interval
4. New listings are saved to a local SQLite database and trigger a desktop notification
5. Browse all found posts in the dashboard, grouped by alert

## Email digest setup

1. Copy `.env.example` to `.env` and fill in your SMTP credentials, or configure them from the dashboard under Email Digest settings
2. Schedule `python main.py --digest` to run daily (e.g. `0 8 * * *` in cron)

## Finding your region

Visit [craigslist.org/about/sites](https://www.craigslist.org/about/sites) and use the subdomain (e.g. `newyork`, `sfbay`, `losangeles`, `chicago`).

## Common category codes

| Code | Category |
|------|----------|
| `sss` | All for sale |
| `cta` | Cars & trucks |
| `mca` | Motorcycles |
| `bik` | Bicycles |
| `ele` | Electronics |
| `fuo` | Furniture |
| `clo` | Clothing |
| `spo` | Sporting goods |
| `tls` | Tools |
| `vgm` | Video gaming |

## Files

| File | Purpose |
|------|---------|
| `main.py` | Entry point — web server or digest mode |
| `app.py` | Flask routes and background scanner thread |
| `scraper.py` | HTTP requests and HTML parsing |
| `scanner_core.py` | Shared scanning logic |
| `db.py` | SQLite storage for alerts, posts, and notifications |
| `emailer.py` | SMTP email digest builder and sender |
| `notifier.py` | Desktop notification delivery |
| `templates/` | HTML templates (Tailwind CSS) |
