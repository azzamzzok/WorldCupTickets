# FIFA World Cup 2026 – Ticombo Ticket Notifier

Automatically scrapes [Ticombo](https://www.ticombo.com/en/discover/search?q=World%20Cup)
for every **men's FIFA World Cup 2026 match** and emails you the **3 cheapest
tickets** (with Category, Section, Row, quantity and price) on this schedule,
**per match**:

- Emails **start 90 minutes before** kickoff.
- Emails **repeat every 15 minutes**.
- Emails **stop 45 minutes after** kickoff.

Each match has its own independent window, so on days with up to 4 games the
alerts for the next game automatically begin once the previous game's window
closes. The match list, dates and prices are re-scraped automatically every 10
minutes, so newly-listed matches (e.g. group-stage games added later) get
picked up on their own.

No third-party packages required — it uses only the Python standard library.

---

## 1. One-time setup

### a) Add your Gmail credentials

Emails are sent through Gmail's SMTP server, which needs a Google **App
Password** (not your normal password):

1. Turn on 2-Step Verification: <https://myaccount.google.com/security>
2. Create an App Password: <https://myaccount.google.com/apppasswords>
   (choose "Mail" → "Other", name it e.g. `WC2026`). You'll get a 16-char code.
3. Copy the template and fill it in:

```bash
cd wc2026_notifier
cp config.example.json config.json
```

Edit `config.json`:

```json
{
  "gmail_address": "the-account-that-sends@gmail.com",
  "gmail_app_password": "the 16 char app password",
  "recipient": "azzamsidhu2@gmail.com"
}
```

The sending account can be any Gmail you own; the `recipient` is where alerts
land (already set to `azzamsidhu2@gmail.com`).

### b) Confirm it works

```bash
python3 notifier.py schedule     # scrapes + prints all matches & alert windows
python3 notifier.py test-email   # sends one test email to the recipient
python3 notifier.py preview      # prints the email that would be sent right now
```

---

## 2. Run it automatically (macOS)

```bash
cd wc2026_notifier
./setup_autorun.sh
```

This installs a LaunchAgent that:
- starts the notifier now,
- restarts it automatically at login,
- restarts it if it ever crashes.

Watch it working:

```bash
tail -f data/notifier.log
```

Stop / start / status:

```bash
launchctl unload ~/Library/LaunchAgents/com.azzam.wc2026notifier.plist   # stop
launchctl load   ~/Library/LaunchAgents/com.azzam.wc2026notifier.plist   # start
launchctl list | grep wc2026notifier                                     # status
```

> Note: the Mac must be powered on (and not fully asleep) for emails to send at
> the scheduled times. A LaunchAgent runs while you're logged in.

---

## 3. Commands

| Command | What it does |
|---|---|
| `python3 notifier.py run` | Run forever (used by the auto-run service). |
| `python3 notifier.py once` | Do a single check pass (handy for cron). |
| `python3 notifier.py schedule` | Scrape + print every match and its alert window. |
| `python3 notifier.py test-email` | Send one test email. |
| `python3 notifier.py preview` | Print the email(s) that would be sent right now. |

---

## 4. How it works

- `schedule_source.py` — fetches the **authoritative kickoff times** from the
  [openfootball](https://github.com/openfootball/world-cup.json) dataset (cached
  daily) and keys them by FIFA match number (M1–M104). Ticombo's seller-entered
  times drift, so these official times are used for all scheduling/countdowns;
  Ticombo's time is only a fallback if a match number isn't found.
- `scraper.py` — calls Ticombo's JSON API
  (`/prod/discovery/search/events?keyword=World Cup 2026`), keeps only real
  men's WC-2026 football matches (those with a match number and a confirmed
  date/time), and normalises kickoff time (real UTC) and venue. Saved to
  `data/matches.json`. At send time it also fetches each event's individual
  listings (`/prod/discovery/events/{id}/listings`) and returns the 3 cheapest
  tickets (ranked by the EUR price the buyer pays), including Category, Section
  and Row.
- `notifier.py` — every 60 s checks which matches are inside their
  `[kickoff-90m, kickoff+45m]` window and sends an email if 15 minutes have
  passed since the last one for that match. State is stored in `data/state.json`
  so restarts never double-send.
- `emailer.py` — builds a clean HTML + plain-text email and sends it via Gmail.
- `config.py` — all settings and timing rules.

Timing rules live at the top of `config.py` (`LEAD_MINUTES`, `TRAIL_MINUTES`,
`INTERVAL_MINUTES`) if you ever want to tweak them.
