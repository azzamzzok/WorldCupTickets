"""Scrapes FIFA World Cup 2026 (men's) matches from Ticombo.

Ticombo's public website is an Angular app that loads its data from a JSON API
at /prod/discovery/search/events. We hit that API directly (no browser needed),
which is far more reliable than parsing rendered HTML.

Each returned match is normalised into a small dict with the kickoff time (in
real UTC), local wall-clock time, venue, live ticket availability and price.
"""

import json
import math
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import config
import schedule_source

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Safari/537.36"
_MATCH_RE = re.compile(r"match-(\d+)-")


def _parse_iso(value):
    """Parse Ticombo ISO timestamps (which end in 'Z') into datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _get(url):
    req = urllib.request.Request(
        url, headers={"User-Agent": _UA, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _fetch_page(keyword, page):
    query = urllib.parse.urlencode(
        {"keyword": keyword, "page": page, "limit": config.PAGE_SIZE}
    )
    return _get("{}?{}".format(config.API_URL, query))


def fetch_all_events(keyword=None):
    """Return every raw event the search returns for the keyword."""
    keyword = keyword or config.SEARCH_KEYWORD
    first = _fetch_page(keyword, 1)
    payload = first.get("payload", {})
    total = payload.get("total", 0)
    results = list(payload.get("results", []))
    pages = math.ceil(total / config.PAGE_SIZE) if total else 1
    for page in range(2, pages + 1):
        try:
            results += _fetch_page(keyword, page).get("payload", {}).get("results", [])
        except Exception:  # noqa: BLE001 - one bad page shouldn't kill the run
            break
    return results


def _is_mens_wc_match(event):
    """A real single men's WC 2026 game: football + a match number + a real date."""
    slug = (event.get("safeUrlName") or "").lower()
    if event.get("subcategory") != "football":
        return False
    if "world-cup-2026" not in slug:
        return False
    if not _MATCH_RE.search(slug):
        return False  # excludes stadium bundles like "Atlanta Stadium 8 Matches"
    date = event.get("date") or {}
    if date.get("tbdDate") or date.get("tbdTime"):
        return False
    return bool(date.get("from"))


def _top_categories(event, limit=6):
    stats = (event.get("stats") or {}).get("ticketTypes") or []
    rows = []
    for t in stats:
        rows.append(
            {
                "category": t.get("category"),
                "avg_price": t.get("averagePrice"),
                "available": t.get("availableTickets"),
            }
        )
    rows.sort(key=lambda r: (r["available"] or 0), reverse=True)
    return rows[:limit]


def normalise(event):
    date = event.get("date") or {}
    listing = event.get("listing") or {}
    inventory = event.get("inventory") or {}
    location = event.get("location") or {}
    slug = event.get("safeUrlName") or ""
    match_no = None
    m = _MATCH_RE.search(slug.lower())
    if m:
        match_no = int(m.group(1))

    kickoff_utc = _parse_iso(date.get("from"))
    local_dt = _parse_iso(date.get("start"))  # naive wall-clock, mislabelled Z

    return {
        "event_id": event.get("eventId"),
        "match_no": match_no,
        "name": event.get("name"),
        "description": event.get("description"),
        "url": config.EVENT_URL_TEMPLATE.format(slug=slug),
        "kickoff_utc": kickoff_utc.isoformat() if kickoff_utc else None,
        "local_time": date.get("start"),
        "timezone": date.get("timezone"),
        "venue": (event.get("venue") or {}).get("name") or location.get("venue"),
        "city": location.get("city"),
        "country": location.get("country"),
        "available_tickets": listing.get("availableTickets")
        or inventory.get("forSale"),
        "start_price": listing.get("startPrice") or inventory.get("startPrice"),
        "avg_price": listing.get("avgPrice"),
        "max_price": listing.get("maxPrice") or inventory.get("maxPrice"),
        "categories": _top_categories(event),
    }


_RATES_CACHE = {"rates": None, "base": None, "fetched": 0.0}


def _exchange_rates():
    """Ticombo's EUR-based exchange rates, cached for an hour."""
    import time

    now = time.time()
    if _RATES_CACHE["rates"] and (now - _RATES_CACHE["fetched"]) < 3600:
        return _RATES_CACHE["rates"], _RATES_CACHE["base"]
    try:
        data = _get(config.EXCHANGE_RATES_URL).get("payload", {})
        rates = data.get("rates") or {}
        base = data.get("base") or "EUR"
        if rates:
            _RATES_CACHE.update(rates=rates, base=base, fetched=now)
        return rates, base
    except Exception:  # noqa: BLE001
        return _RATES_CACHE["rates"] or {}, _RATES_CACHE["base"] or "EUR"


def to_display_currency(value_eur, native_currency, native_value):
    """Convert a price into config.DISPLAY_CURRENCY.

    If the listing is already in the display currency we use its exact value;
    otherwise we convert the EUR-normalised value with Ticombo's rates.
    """
    target = config.DISPLAY_CURRENCY
    if native_currency == target and native_value is not None:
        return float(native_value)
    if value_eur is None:
        return None
    rates, base = _exchange_rates()
    # Rates are quoted per the base currency (EUR). USD = EUR_value * rate[USD].
    rate = rates.get(target)
    if base != "EUR" and rates.get("EUR"):
        # Normalise if the base ever changes away from EUR.
        rate = rates.get(target) and rates.get(target) / rates.get(base, 1)
    if not rate:
        return None
    return float(value_eur) * float(rate)


def fetch_listings(event_id, limit=None):
    """Return the raw individual ticket listings for one event."""
    limit = limit or config.LISTINGS_LIMIT
    base = config.LISTINGS_URL_TEMPLATE.format(event_id=event_id)
    query = urllib.parse.urlencode({"limit": limit})
    data = _get("{}?{}".format(base, query))
    return data.get("payload", []) or []


def cheapest_listings(event_id, count=None):
    """Return the N cheapest available tickets for an event.

    The price reported is the FULL amount a buyer actually pays: the seller's
    asking price plus Ticombo's buyer commission (``selling * (1 + commissionRate
    / 100)``), matching the site's own "final" price. Everything is converted to
    ``config.DISPLAY_CURRENCY`` and listings are ranked by that total.
    """
    count = count or config.CHEAPEST_COUNT
    rows = fetch_listings(event_id)

    def buyer_total(row):
        """Full buyer price for a listing, in the display currency (or None)."""
        price = row.get("price") or {}
        selling = price.get("selling") or {}
        mult = 1 + (price.get("commissionRate") or 0) / 100.0
        eur = price.get("sellingEur")
        buyer_eur = eur * mult if eur is not None else None
        native_val = selling.get("value")
        buyer_native = native_val * mult if native_val is not None else None
        return to_display_currency(buyer_eur, selling.get("currency"), buyer_native)

    priced = [r for r in rows if buyer_total(r) is not None]
    priced.sort(key=buyer_total)

    out = []
    for row in priced[:count]:
        ticket = row.get("ticket") or {}
        price = row.get("price") or {}
        selling = price.get("selling") or {}
        mult = 1 + (price.get("commissionRate") or 0) / 100.0
        native_val = selling.get("value")
        out.append(
            {
                "price": buyer_total(row),
                "currency": config.DISPLAY_CURRENCY,
                "native_value": native_val * mult if native_val is not None else None,
                "native_currency": selling.get("currency"),
                "seller_price": to_display_currency(
                    price.get("sellingEur"), selling.get("currency"), native_val
                ),
                "commission_rate": price.get("commissionRate") or 0,
                "category": ticket.get("category") or "",
                "section": ticket.get("section") or "",
                "row": ticket.get("row") or "",
                "quantity": ticket.get("amount"),
                "listing_id": row.get("listingId"),
            }
        )
    return out


def _apply_official_times(matches):
    """Override each match's kickoff with the reliable schedule (by match number).

    Ticombo's times are seller-entered and drift, so when we have an official
    kickoff for that FIFA match number we use it for scheduling and display, and
    tag the source. Ticombo's time is kept only as a fallback.
    """
    try:
        official = schedule_source.by_match_no()
    except Exception:  # noqa: BLE001
        official = {}
    for m in matches:
        info = official.get(m.get("match_no"))
        if info and info.get("kickoff_utc"):
            m["kickoff_utc"] = info["kickoff_utc"]
            m["local_time"] = info.get("local_time") or m.get("local_time")
            m["timezone"] = info.get("utc_offset") or m.get("timezone")
            m["time_source"] = "official"
        else:
            m["time_source"] = "ticombo"
    return matches


def get_matches(keyword=None):
    """Fetch, filter and normalise all men's WC 2026 matches, sorted by kickoff."""
    events = fetch_all_events(keyword)
    matches = [normalise(e) for e in events if _is_mens_wc_match(e)]
    # De-duplicate by event id (search can repeat across relevance buckets).
    unique = {}
    for match in matches:
        unique[match["event_id"]] = match
    result = list(unique.values())
    result = _apply_official_times(result)
    result.sort(key=lambda r: r["kickoff_utc"] or "")
    return result


def save_matches(matches):
    config.ensure_data_dir()
    import os

    path = os.path.join(config.DATA_DIR, "matches.json")
    payload = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "count": len(matches),
        "matches": matches,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return path


def refresh_and_save(keyword=None):
    matches = get_matches(keyword)
    save_matches(matches)
    return matches
