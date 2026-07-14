"""Configuration loading for the World Cup 2026 ticket notifier.

Settings are read from (in priority order):
  1. Environment variables
  2. config.json living next to this file
  3. Built-in defaults

Only the Gmail credentials are secret; everything else has a sensible default.
"""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_JSON = os.path.join(_HERE, "config.json")
DATA_DIR = os.path.join(_HERE, "data")

# --- Notification timing rules (from the requirement) ---------------------
LEAD_MINUTES = 90      # start emailing 1h30 BEFORE kickoff
TRAIL_MINUTES = 45     # stop emailing 45 min AFTER kickoff
INTERVAL_MINUTES = 15  # send an email every 15 minutes inside that window

# --- Scraper settings -----------------------------------------------------
SEARCH_KEYWORD = "World Cup 2026"
API_URL = "https://www.ticombo.com/prod/discovery/search/events"
# Per-event individual ticket listings (section / row / category / price).
LISTINGS_URL_TEMPLATE = (
    "https://www.ticombo.com/prod/discovery/events/{event_id}/listings"
)
EVENT_URL_TEMPLATE = "https://www.ticombo.com/en/e/{slug}"
PAGE_SIZE = 100
# Max listings the endpoint returns in one call (server caps it at 100).
LISTINGS_LIMIT = 100
# How many cheapest tickets to include in each email.
CHEAPEST_COUNT = 3
# All prices are reported in this currency (converted when a listing is not
# already in it, using Ticombo's own exchange rates).
DISPLAY_CURRENCY = "USD"
EXCHANGE_RATES_URL = "https://www.ticombo.com/prod/payment/exchange-rates"
# How often (minutes) to re-scrape the site for fresh dates/prices.
REFRESH_MINUTES = 10

# --- Loop settings --------------------------------------------------------
TICK_SECONDS = 10  # how often the daemon checks prices (emails only on change)


def _load_file():
    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (ValueError, OSError):
            return {}
    return {}


def _get(file_cfg, env_key, json_key, default=None):
    if os.environ.get(env_key):
        return os.environ[env_key]
    if json_key in file_cfg and file_cfg[json_key] not in (None, ""):
        return file_cfg[json_key]
    return default


_FILE = _load_file()

# Gmail account used to SEND the email (needs an App Password, not the normal
# login password). See README for how to generate one.
GMAIL_ADDRESS = _get(_FILE, "GMAIL_ADDRESS", "gmail_address", "")
GMAIL_APP_PASSWORD = _get(_FILE, "GMAIL_APP_PASSWORD", "gmail_app_password", "")

# Where the notifications are delivered.
RECIPIENT = _get(_FILE, "RECIPIENT", "recipient", "azzamsidhu2@gmail.com")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def credentials_ok():
    return bool(GMAIL_ADDRESS) and bool(GMAIL_APP_PASSWORD)


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)
    return DATA_DIR
