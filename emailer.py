"""Sends the notification emails through Gmail's SMTP server."""

import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config


def _fmt_price(value):
    if value in (None, ""):
        return "-"
    try:
        return "{:,.2f}".format(float(value))
    except (TypeError, ValueError):
        return str(value)


def _humanise_delta(minutes):
    minutes = int(round(minutes))
    if minutes == 0:
        return "kicking off now"
    if minutes > 0:
        h, m = divmod(minutes, 60)
        parts = []
        if h:
            parts.append("{}h".format(h))
        if m or not parts:
            parts.append("{}m".format(m))
        return "in " + " ".join(parts)
    minutes = -minutes
    h, m = divmod(minutes, 60)
    parts = []
    if h:
        parts.append("{}h".format(h))
    if m or not parts:
        parts.append("{}m".format(m))
    return " ".join(parts) + " ago"


def _price_label(listing):
    """Full buyer total, e.g. '$500.00' or '$543.11 (EUR 402.30)' if converted."""
    cur = listing.get("currency") or config.DISPLAY_CURRENCY
    label = "${}".format(_fmt_price(listing.get("price"))) if cur == "USD" else "{} {}".format(
        cur, _fmt_price(listing.get("price"))
    )
    native_cur = listing.get("native_currency")
    native_val = listing.get("native_value")
    if native_cur and native_cur != cur and native_val is not None:
        label += " ({} {})".format(native_cur, _fmt_price(native_val))
    return label


def build_bodies(match, minutes_to_kickoff, listings):
    name = match.get("name") or "World Cup 2026 match"
    local = match.get("local_time") or ""
    if local:
        local = local.replace("T", " ").replace(".000Z", "")
    tz = match.get("timezone") or ""
    venue = match.get("venue") or ""
    city = match.get("city") or ""
    url = match.get("url") or ""
    when = _humanise_delta(minutes_to_kickoff)
    verified = match.get("time_source") == "official"
    time_note = " - verified schedule" if verified else ""
    listings = listings or []

    # ---- plain text ----
    lines = [
        name,
        "Kickoff: {} {} ({}){}".format(local, tz, when, time_note).strip(),
        "Venue: {} {}".format(venue, ("- " + city) if city else "").strip(),
        "",
        "{} cheapest tickets (total price incl. fees):".format(len(listings)) if listings else "No tickets currently listed.",
    ]
    for i, l in enumerate(listings, 1):
        lines.append(
            "  {}. {}  |  Category: {}  |  Section: {}  |  Row: {}  |  Qty: {}".format(
                i,
                _price_label(l),
                l.get("category") or "-",
                l.get("section") or "-",
                l.get("row") or "-",
                l.get("quantity") if l.get("quantity") is not None else "-",
            )
        )
    lines += ["", "Buy / view: {}".format(url)]
    text = "\n".join(lines)

    # ---- html ----
    if listings:
        rows = "".join(
            "<tr>"
            "<td style='padding:8px 10px;border-bottom:1px solid #eee;font-weight:800;color:#503fa5'>{price}</td>"
            "<td style='padding:8px 10px;border-bottom:1px solid #eee'>{cat}</td>"
            "<td style='padding:8px 10px;border-bottom:1px solid #eee;text-align:center'>{sec}</td>"
            "<td style='padding:8px 10px;border-bottom:1px solid #eee;text-align:center'>{row}</td>"
            "<td style='padding:8px 10px;border-bottom:1px solid #eee;text-align:center'>{qty}</td>"
            "</tr>".format(
                price=_price_label(l),
                cat=l.get("category") or "-",
                sec=l.get("section") or "-",
                row=l.get("row") or "-",
                qty=l.get("quantity") if l.get("quantity") is not None else "-",
            )
            for l in listings
        )
        table = """\
    <table style="width:100%;border-collapse:collapse;font-size:14px;margin-top:8px">
      <thead><tr>
        <th style="text-align:left;padding:8px 10px;color:#888;font-weight:600">Price</th>
        <th style="text-align:left;padding:8px 10px;color:#888;font-weight:600">Category</th>
        <th style="text-align:center;padding:8px 10px;color:#888;font-weight:600">Section</th>
        <th style="text-align:center;padding:8px 10px;color:#888;font-weight:600">Row</th>
        <th style="text-align:center;padding:8px 10px;color:#888;font-weight:600">Qty</th>
      </tr></thead>
      <tbody>{rows}</tbody>
    </table>""".format(rows=rows)
    else:
        table = "<p style='color:#999;margin-top:8px'>No tickets currently listed.</p>"

    html = """\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;margin:auto;color:#222">
  <div style="background:#29cca2;color:#000;padding:16px 20px;border-radius:10px 10px 0 0">
    <div style="font-size:13px;letter-spacing:1px;text-transform:uppercase;opacity:.8">FIFA World Cup 2026 &middot; Ticombo alert</div>
    <div style="font-size:22px;font-weight:800;margin-top:4px">{name}</div>
  </div>
  <div style="border:1px solid #e3e6e8;border-top:none;padding:20px;border-radius:0 0 10px 10px">
    <p style="margin:0 0 6px"><b>Kickoff:</b> {local} {tz} <span style="color:#503fa5;font-weight:700">({when})</span>{verified_badge}</p>
    <p style="margin:0 0 6px"><b>Venue:</b> {venue}{city}</p>
    <div style="font-size:16px;font-weight:800;margin:16px 0 0">{count} cheapest tickets <span style="font-size:12px;font-weight:400;color:#888">(total price incl. fees)</span></div>
    {table}
    <p style="margin:20px 0 0">
      <a href="{url}" style="background:#000;color:#fff;text-decoration:none;padding:12px 22px;border-radius:32px;font-weight:700;display:inline-block">View tickets on Ticombo</a>
    </p>
    <p style="margin:16px 0 0;font-size:12px;color:#999">Prices are the full buyer total in {currency} (seller price + Ticombo's buyer fee), converted from the listing currency where needed. You get this alert whenever the cheapest price changes, from {lead} min before kickoff until {trail} min after.</p>
  </div>
</div>""".format(
        name=name,
        local=local,
        tz=tz,
        when=when,
        verified_badge=(
            " <span style='background:#eafaf4;color:#1d8b6f;font-size:11px;font-weight:700;padding:2px 6px;border-radius:4px'>verified schedule</span>"
            if verified else ""
        ),
        venue=venue,
        city=(" &middot; " + city) if city else "",
        count=len(listings),
        table=table,
        url=url,
        currency=config.DISPLAY_CURRENCY,
        interval=config.INTERVAL_MINUTES,
        lead=config.LEAD_MINUTES,
        trail=config.TRAIL_MINUTES,
    )
    return text, html


def send(subject, text_body, html_body, recipient=None):
    if not config.credentials_ok():
        raise RuntimeError(
            "Gmail credentials missing. Set gmail_address + gmail_app_password "
            "in config.json (see config.example.json)."
        )
    recipient = recipient or config.RECIPIENT
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.GMAIL_ADDRESS
    msg["To"] = recipient
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    with smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, context=context) as server:
        server.login(config.GMAIL_ADDRESS, config.GMAIL_APP_PASSWORD)
        server.sendmail(config.GMAIL_ADDRESS, [recipient], msg.as_string())


def send_match_alert(match, minutes_to_kickoff, listings, recipient=None):
    text, html = build_bodies(match, minutes_to_kickoff, listings)
    when = _humanise_delta(minutes_to_kickoff)
    cheapest = ""
    if listings:
        cheapest = " (from {})".format(_price_label(listings[0]))
    subject = "World Cup 2026: {} - kickoff {}{}".format(
        match.get("name"), when, cheapest
    )
    send(subject, text, html, recipient=recipient)


def send_test(recipient=None):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    text = "Test email from your World Cup 2026 notifier. Sent {}.".format(now)
    html = "<p>{}</p>".format(text)
    send("World Cup 2026 notifier - test email", text, html, recipient=recipient)
