#!/usr/bin/env python3
"""Check the eMAG product price and email the result."""
from __future__ import annotations

import json
import os
import re
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PRODUCT_URL = "https://www.emag.ro/uscator-de-rufe-bosch-pompa-de-caldura-8-kg-15-programe-autodry-technology-antivibration-filtru-easyclean-clasa-d-alb-negru-wth8520bby/pd/DK77M73BM/"
PRODUCT_NAME = "Bosch WTH8520BBY heat-pump tumble dryer"


def get_page() -> str:
    request = Request(PRODUCT_URL, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
        "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept": "text/html,application/xhtml+xml",
    })
    with urlopen(request, timeout=25) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def parse_price(page: str) -> tuple[str, str]:
    # Prefer JSON-LD product offers, which are less ambiguous than visible page text.
    scripts = re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page, flags=re.I | re.S
    )
    for match in scripts:
        try:
            data = json.loads(unescape(match.group(1)).strip())
        except json.JSONDecodeError:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            if "@graph" in item:
                stack.append(item["@graph"])
            offers = item.get("offers")
            if offers:
                offers = offers if isinstance(offers, list) else [offers]
                for offer in offers:
                    if not isinstance(offer, dict):
                        continue
                    price = offer.get("price")
                    currency = offer.get("priceCurrency", "RON")
                    if price is None and isinstance(offer.get("priceSpecification"), dict):
                        price = offer["priceSpecification"].get("price")
                    if price is not None and re.fullmatch(r"\d+(?:[.,]\d{1,2})?", str(price)):
                        return str(price).replace(",", "."), str(currency)

    # Common metadata fallbacks.
    patterns = [
        r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']',
        r'"price"\s*:\s*"?(\d+(?:[.,]\d{1,2})?)"?',
    ]
    for pattern in patterns:
        match = re.search(pattern, page, flags=re.I)
        if match:
            value = match.group(1).replace(",", ".")
            try:
                if float(value) > 0:
                    return value, "RON"
            except ValueError:
                pass
    raise ValueError("Could not confidently find the product price. eMAG may have changed the page structure or served an anti-bot page.")


def send_email(subject: str, body: str) -> None:
    required = ["SMTP_HOST", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD", "EMAIL_FROM", "EMAIL_TO"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        raise RuntimeError("Missing email configuration: " + ", ".join(missing) + ". Add these as GitHub Actions repository secrets.")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ["EMAIL_FROM"]
    message["To"] = os.environ["EMAIL_TO"]
    message.set_content(body)
    with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ["SMTP_PORT"]), timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(os.environ["SMTP_USERNAME"], os.environ["SMTP_PASSWORD"])
        smtp.send_message(message)


def main() -> int:
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        price, currency = parse_price(get_page())
        send_email(
            f"eMAG price check: {price} {currency} — Bosch WTH8520BBY",
            f"Product: {PRODUCT_NAME}\nCurrent listed price: {price} {currency}\nChecked at: {checked_at}\n\nProduct link: {PRODUCT_URL}\n\nPrice and availability may change before checkout."
        )
        print(f"Price found: {price} {currency}; email sent.")
        return 0
    except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError, OSError, smtplib.SMTPException) as exc:
        print(f"Price check failed: {exc}", file=sys.stderr)
        try:
            send_email(
                "eMAG price check FAILED — Bosch WTH8520BBY",
                f"The daily price check failed at {checked_at}.\nReason: {type(exc).__name__}: {exc}\n\nProduct link: {PRODUCT_URL}\n"
            )
            print("Failure notification email sent.", file=sys.stderr)
        except Exception as mail_exc:
            print(f"Could not send failure notification: {mail_exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
