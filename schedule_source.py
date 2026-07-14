"""Reliable FIFA World Cup 2026 kickoff times (independent of Ticombo).

Ticombo's kickoff times are entered by sellers and drift/are unreliable, so we
take the authoritative schedule from the openfootball dataset:

    https://github.com/openfootball/world-cup.json

It lists all 104 matches with the official FIFA match number, date, local
kickoff time + UTC offset, teams and venue. We key on the **match number**
(M1-M104), which is exactly what Ticombo embeds in every event URL
(``match-80-...``), so the mapping is exact.

The dataset is cached locally for a day and we fall back to the cached copy (or,
failing that, to Ticombo's own time) if the source is unreachable.
"""

import json
import os
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import config

OPENFOOTBALL_URL = (
    "https://raw.githubusercontent.com/openfootball/world-cup.json/master/2026/worldcup.json"
)
CACHE_TTL_SECONDS = 24 * 3600
_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_TIME_RE = re.compile(r"(\d{1,2}):(\d{2})\s*UTC\s*([+-]\d{1,2})?")

# In-process cache to avoid re-parsing every call.
_MEM = {"map": None, "loaded": 0.0}


def _cache_path():
    config.ensure_data_dir()
    return os.path.join(config.DATA_DIR, "official_schedule.json")


def _fetch_raw():
    req = urllib.request.Request(OPENFOOTBALL_URL, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _parse_kickoff(date_str, time_str):
    """('2026-07-01', '12:00 UTC-4') -> (utc_datetime, 'YYYY-MM-DD HH:MM', 'UTC-4')."""
    m = _TIME_RE.search(time_str or "")
    if not m or not date_str:
        return None, None, None
    hh, mm = int(m.group(1)), int(m.group(2))
    offset = int(m.group(3)) if m.group(3) else 0
    try:
        naive = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=hh, minute=mm)
    except ValueError:
        return None, None, None
    utc = (naive - timedelta(hours=offset)).replace(tzinfo=timezone.utc)
    local_str = "{} {:02d}:{:02d}".format(date_str, hh, mm)
    offset_str = "UTC{:+d}".format(offset) if m.group(3) else "UTC"
    return utc, local_str, offset_str


def _build_map(raw):
    """Return {match_no(int): {kickoff_utc, local_time, utc_offset, teams, ground, round}}."""
    out = {}
    for match in raw.get("matches", []):
        num = match.get("num")
        if not num:
            continue  # group-stage rows in this dataset carry no FIFA match number
        utc, local_str, offset_str = _parse_kickoff(match.get("date"), match.get("time"))
        if utc is None:
            continue
        out[int(num)] = {
            "kickoff_utc": utc.isoformat(),
            "local_time": local_str,
            "utc_offset": offset_str,
            "teams": "{} vs {}".format(match.get("team1"), match.get("team2")),
            "ground": match.get("ground"),
            "round": match.get("round"),
        }
    return out


def _load_cache():
    path = _cache_path()
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (ValueError, OSError):
            return None
    return None


def _save_cache(raw):
    try:
        with open(_cache_path(), "w", encoding="utf-8") as fh:
            json.dump({"fetched_at": time.time(), "raw": raw}, fh)
    except OSError:
        pass


def by_match_no(force=False):
    """Return {match_no: info} for the official schedule (cached).

    Never raises: on any failure it returns whatever it last had (possibly {}).
    """
    now = time.time()
    if not force and _MEM["map"] is not None and (now - _MEM["loaded"]) < CACHE_TTL_SECONDS:
        return _MEM["map"]

    cache = _load_cache()
    cache_fresh = cache and (now - cache.get("fetched_at", 0)) < CACHE_TTL_SECONDS

    raw = None
    if cache_fresh and not force:
        raw = cache.get("raw")
    else:
        try:
            raw = _fetch_raw()
            _save_cache(raw)
        except Exception:  # noqa: BLE001 - network/parse issues -> fall back
            raw = (cache or {}).get("raw")

    mapping = _build_map(raw) if raw else {}
    if mapping:
        _MEM["map"] = mapping
        _MEM["loaded"] = now
    return mapping or (_MEM["map"] or {})
