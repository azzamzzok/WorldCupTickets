#!/usr/bin/env python3
"""World Cup 2026 ticket-price notifier.

Automatically scrapes Ticombo for every men's FIFA World Cup 2026 match and
emails you the live ticket data (per match):

    * Watching STARTS 90 minutes BEFORE kickoff.
    * It checks prices every 10 seconds and emails you WHENEVER the cheapest
      price changes (a stable price stays quiet).
    * Watching STOPS  45 minutes AFTER kickoff.

Every match has its own independent window, so on days with several games the
alerts for the next game begin automatically once the previous game's window
has closed.

Usage:
    python3 notifier.py run        # run forever (default; used by launchd)
    python3 notifier.py once       # single check pass (good for cron)
    python3 notifier.py watch      # live: every 10s, print only when price changes
    python3 notifier.py schedule   # scrape + print upcoming matches & windows
    python3 notifier.py test-email # send a test email to confirm SMTP works
    python3 notifier.py preview    # print the email that WOULD be sent now
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import config
import emailer
import scraper


STATE_PATH = os.path.join(config.DATA_DIR, "state.json")


# --------------------------------------------------------------------------
# state (so restarts / cron runs don't double-send)
# --------------------------------------------------------------------------
def _load_state():
    if os.path.exists(STATE_PATH):
        try:
            with open(STATE_PATH, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (ValueError, OSError):
            return {}
    return {}


def _save_state(state):
    config.ensure_data_dir()
    with open(STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


def _parse(dt_iso):
    if not dt_iso:
        return None
    try:
        return datetime.fromisoformat(dt_iso)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# core scheduling logic
# --------------------------------------------------------------------------
def match_window(match):
    """Return (open, kickoff, close) as aware UTC datetimes, or None."""
    kickoff = _parse(match.get("kickoff_utc"))
    if kickoff is None:
        return None
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    open_at = kickoff - timedelta(minutes=config.LEAD_MINUTES)
    close_at = kickoff + timedelta(minutes=config.TRAIL_MINUTES)
    return open_at, kickoff, close_at


def _price_key(listings):
    """A comparable signature of the current cheapest prices."""
    return [round(l["price"], 2) for l in listings if l.get("price") is not None]


def _prev_price_key(state_entry):
    """Extract the last-emailed price signature from a state entry (handles old format)."""
    if isinstance(state_entry, dict):
        return state_entry.get("prices")
    return None  # old timestamp-only entries -> treat as "no baseline yet"


def run_once(matches, state, dry_run=False):
    """One pass: email in-window matches whenever their cheapest price changes.

    Returns the number of emails sent. We only email when the cheapest-ticket
    signature differs from what we last sent for that match (so a stable price
    stays quiet), and only while the match is inside its alert window.
    """
    now = datetime.now(timezone.utc)
    sent = 0
    for match in matches:
        window = match_window(match)
        if window is None:
            continue
        open_at, kickoff, close_at = window
        if not (open_at <= now <= close_at):
            continue

        try:
            listings = scraper.cheapest_listings(match["event_id"])
        except Exception as exc:  # noqa: BLE001
            _log("price fetch failed for {}: {}".format(match.get("name"), exc))
            continue

        price_key = _price_key(listings)
        prev_key = _prev_price_key(state.get(match["event_id"]))

        if price_key == prev_key:
            continue  # price unchanged -> no email
        if prev_key is None and not price_key:
            # Nothing listed yet and no prior baseline: record, don't email.
            state[match["event_id"]] = {"prices": price_key, "sent_at": now.isoformat()}
            continue

        minutes = (kickoff - now).total_seconds() / 60.0
        try:
            if dry_run:
                text, _ = emailer.build_bodies(match, minutes, listings)
                print("--- WOULD SEND ---")
                print(text)
                print("------------------")
            else:
                emailer.send_match_alert(match, minutes, listings)
                _log("sent alert (price change): {} ({:.0f} min to kickoff, cheapest {})".format(
                    match["name"], minutes,
                    (emailer._price_label(listings[0]) if listings else "n/a")))
            state[match["event_id"]] = {"prices": price_key, "sent_at": now.isoformat()}
            sent += 1
        except Exception as exc:  # noqa: BLE001
            _log("ERROR sending for {}: {}".format(match.get("name"), exc))
    if not dry_run:
        _save_state(state)
    return sent


# --------------------------------------------------------------------------
# helpers / logging
# --------------------------------------------------------------------------
def _log(msg):
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print("[{}] {}".format(stamp, msg), flush=True)


def _load_cached_matches():
    path = os.path.join(config.DATA_DIR, "matches.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return json.load(fh).get("matches", [])
        except (ValueError, OSError):
            return []
    return []


# --------------------------------------------------------------------------
# CLI commands
# --------------------------------------------------------------------------
def cmd_schedule():
    _log("Scraping Ticombo for World Cup 2026 men's matches ...")
    matches = scraper.refresh_and_save()
    _log("Found {} matches. Saved to data/matches.json".format(len(matches)))
    now = datetime.now(timezone.utc)
    print()
    print("{:<3} {:<48} {:<26} {:<18} {:<14} {}".format("#", "Match", "Kickoff (local)", "Emails open (UTC)", "Status", "Time src"))
    print("-" * 130)
    for m in matches:
        win = match_window(m)
        if win is None:
            continue
        open_at, kickoff, close_at = win
        if now < open_at:
            status = "opens {}".format(_fmt_eta(open_at - now))
        elif now <= close_at:
            status = "ACTIVE NOW"
        else:
            status = "finished"
        local = (m.get("local_time") or "").replace("T", " ").replace(".000Z", "")
        src = "official" if m.get("time_source") == "official" else "ticombo"
        print(
            "{:<3} {:<48} {:<26} {:<18} {:<14} {}".format(
                m.get("match_no") or "?",
                (m.get("name") or "")[:47],
                "{} {}".format(local, m.get("timezone") or "")[:25],
                open_at.strftime("%m-%d %H:%M"),
                status,
                src,
            )
        )


def _fmt_eta(delta):
    total = int(delta.total_seconds())
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if days:
        return "in {}d {}h".format(days, hours)
    if hours:
        return "in {}h {}m".format(hours, mins)
    return "in {}m".format(mins)


def cmd_test_email():
    _log("Sending test email to {} ...".format(config.RECIPIENT))
    emailer.send_test()
    _log("Test email sent. Check the inbox (and spam).")


def cmd_preview():
    matches = _load_cached_matches() or scraper.refresh_and_save()
    state = {}
    run_once(matches, state, dry_run=True)


def cmd_once():
    matches = _load_cached_matches()
    if not matches:
        matches = scraper.refresh_and_save()
    state = _load_state()
    sent = run_once(matches, state)
    _log("Pass complete. Emails sent this pass: {}".format(sent))


def _fmt_kickoff_delta(mins):
    """'1h 8m to kickoff' before, '12m after kickoff' once it has started."""
    after = mins < 0
    m = int(round(abs(mins)))
    h, mm = divmod(m, 60)
    t = "{}h {}m".format(h, mm) if h else "{}m".format(mm)
    return t + (" after kickoff" if after else " to kickoff")


def cmd_watch():
    """Poll every 10s and print ONLY when the cheapest price changes.

    Each time it prints, it shows how long until kickoff (or how long after
    kickoff, once the match has started). Watches the match currently in its
    alert window, or the next upcoming match if none is active. This is
    read-only: it never sends email. Stop with Ctrl+C.
    """
    interval = 10          # seconds between price checks
    schedule_refresh = 300  # seconds between full schedule re-scrapes
    _log("Watching cheapest prices every {}s - prints only on change. Ctrl+C to stop.".format(interval))

    last = {}
    matches = []
    last_scan = 0.0
    try:
        while True:
            now = datetime.now(timezone.utc)
            if (time.time() - last_scan) > schedule_refresh or not matches:
                try:
                    matches = scraper.get_matches()
                    last_scan = time.time()
                except Exception as exc:  # noqa: BLE001
                    if not matches:
                        matches = _load_cached_matches()
                    _log("schedule refresh failed: {}".format(exc))

            active = []
            for m in matches:
                win = match_window(m)
                if win and win[0] <= now <= win[2]:
                    active.append(m)
            if not active:
                upcoming = [m for m in matches if match_window(m) and match_window(m)[1] > now]
                upcoming.sort(key=lambda mm: match_window(mm)[1])
                active = upcoming[:1]

            for m in active:
                try:
                    listings = scraper.cheapest_listings(m["event_id"])
                except Exception as exc:  # noqa: BLE001
                    _log("price fetch failed for {}: {}".format(m.get("name"), exc))
                    continue
                key = tuple(
                    round(l["price"], 2) for l in listings if l.get("price") is not None
                )
                if last.get(m["event_id"]) == key:
                    continue  # price unchanged -> stay silent
                last[m["event_id"]] = key

                kickoff = match_window(m)[1]
                mins = (kickoff - now).total_seconds() / 60.0
                lines = ["\n[{}] {}  ({})".format(
                    now.strftime("%H:%M:%S UTC"), m.get("name"), _fmt_kickoff_delta(mins))]
                if not listings:
                    lines.append("  (no tickets currently listed)")
                for i, l in enumerate(listings, 1):
                    lines.append("  {}. {} | {} | Sec {} Row {} x{}".format(
                        i,
                        emailer._price_label(l),
                        l.get("category") or "-",
                        l.get("section") or "-",
                        l.get("row") or "-",
                        l.get("quantity") if l.get("quantity") is not None else "-",
                    ))
                print("\n".join(lines), flush=True)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.")


def cmd_run():
    _log("Starting World Cup 2026 notifier daemon.")
    _log("Recipient: {} | checks every {}s, emails on price change | window: {}m before -> {}m after".format(
        config.RECIPIENT, config.TICK_SECONDS, config.LEAD_MINUTES, config.TRAIL_MINUTES))
    if not config.credentials_ok():
        _log("WARNING: Gmail credentials not set. Emails will fail until you edit config.json.")

    state = _load_state()
    matches = []
    last_refresh = None

    while True:
        now = datetime.now(timezone.utc)
        need_refresh = (
            last_refresh is None
            or (now - last_refresh) >= timedelta(minutes=config.REFRESH_MINUTES)
            or not matches
        )
        if need_refresh:
            try:
                matches = scraper.refresh_and_save()
                last_refresh = now
                _log("Refreshed schedule: {} matches.".format(len(matches)))
            except Exception as exc:  # noqa: BLE001
                _log("Scrape failed ({}); using cached data.".format(exc))
                if not matches:
                    matches = _load_cached_matches()

        try:
            run_once(matches, state)
        except Exception as exc:  # noqa: BLE001
            _log("run_once error: {}".format(exc))

        time.sleep(config.TICK_SECONDS)


COMMANDS = {
    "run": cmd_run,
    "once": cmd_once,
    "watch": cmd_watch,
    "schedule": cmd_schedule,
    "test-email": cmd_test_email,
    "preview": cmd_preview,
}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    fn = COMMANDS.get(cmd)
    if fn is None:
        print(__doc__)
        print("Unknown command: {}".format(cmd))
        sys.exit(1)
    fn()


if __name__ == "__main__":
    main()
