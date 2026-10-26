#!/usr/bin/env python3
"""Check the eMAG product price and send the result through the Gmail API."""
from __future__ import annotations

import base64
import json
import os
import re
import sys
from datetime import datetime, timezone
from email.message import EmailMessage
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

PRODUCT_URL = "https://www.emag.ro/uscator-de-rufe-bosch-pompa-de-caldura-8-kg-15-programe-autodry-technology-antivibration-filtru-easyclean-clasa-d-alb-negru-wth8520bby/pd/DK77M73BM/"
PRODUCT_NAME = "Bosch WTH8520BBY heat-pump tumble dryer"
TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


def get_page() -> str:
    """Load the listing in a real Chromium browser instead of a plain HTTP request."""
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context_options = {
                    "locale": "ro-RO",
                    "timezone_id": "Europe/Bucharest",
                    "viewport": {"width": 1440, "height": 1000},
                }
                storage_state_json = os.getenv("EMAG_STORAGE_STATE", "").strip()
                if storage_state_json:
                    try:
                        context_options["storage_state"] = json.loads(storage_state_json)
                    except json.JSONDecodeError as exc:
                        raise RuntimeError(
                            "EMAG_STORAGE_STATE is not valid JSON. Paste the complete "
                            "contents of the Playwright storage-state file into the GitHub secret."
                        ) from exc
                context = browser.new_context(**context_options)
                page = context.new_page()
                response = page.goto(
                    PRODUCT_URL,
                    wait_until="domcontentloaded",
                    timeout=45000,
                )
                if response is not None and response.status >= 400:
                    # Report non-sensitive diagnostics only; never log cookies or storage state.
                    final_url = page.url
                    try:
                        title = page.title()[:160]
                    except Exception:
                        title = "(unavailable)"
                    server = response.headers.get("server", "(not provided)")
                    request_id = (
                        response.headers.get("x-request-id")
                        or response.headers.get("x-correlation-id")
                        or "(not provided)"
                    )
                    raise RuntimeError(
                        f"eMAG returned HTTP {response.status}; final_url={final_url}; "
                        f"title={title!r}; server={server!r}; request_id={request_id!r}."
                    )
                # Allow client-rendered product data a moment to appear.
                page.wait_for_timeout(2500)
                return page.content()
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(f"Timed out while loading the eMAG product page: {exc}") from exc

def parse_price(page: str) -> tuple[str, str]:
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

    patterns = [
        r'<meta[^>]+property=["\']product:price:amount["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']',
        r'"price"\s*:\s*"?([0-9]+(?:[.,][0-9]{1,2})?)"?',
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


def required_env(*names: str) -> dict[str, str]:
    values = {name: os.getenv(name, "").strip() for name in names}
    missing = [name for name, value in values.items() if not value]
    if missing:
        raise RuntimeError("Missing GitHub Actions repository secrets: " + ", ".join(missing))
    return values


def get_access_token() -> str:
    credentials = required_env("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN")
    body = urlencode({
        "client_id": credentials["GOOGLE_CLIENT_ID"],
        "client_secret": credentials["GOOGLE_CLIENT_SECRET"],
        "refresh_token": credentials["GOOGLE_REFRESH_TOKEN"],
        "grant_type": "refresh_token",
    }).encode("utf-8")
    request = Request(TOKEN_URL, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }, method="POST")
    try:
        with urlopen(request, timeout=25) as response:
            token_data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        # Avoid printing credentials; Google error responses do not require secrets to diagnose.
        raise RuntimeError(f"Google OAuth token refresh failed (HTTP {exc.code}): {details[:1000]}") from exc
    token = token_data.get("access_token")
    if not token:
        raise RuntimeError("Google OAuth response did not include an access token.")
    return token


def send_email(subject: str, body: str) -> None:
    config = required_env("EMAIL_FROM", "EMAIL_TO")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["EMAIL_FROM"]
    message["To"] = config["EMAIL_TO"]
    message.set_content(body)
    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
    access_token = get_access_token()
    payload = json.dumps({"raw": encoded_message}).encode("utf-8")
    request = Request(GMAIL_SEND_URL, data=payload, headers={
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }, method="POST")
    try:
        with urlopen(request, timeout=25) as response:
            if response.status not in (200, 201):
                raise RuntimeError(f"Gmail API returned unexpected HTTP status {response.status}.")
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gmail API send failed (HTTP {exc.code}): {details[:1000]}") from exc


def main() -> int:
    checked_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    try:
        price, currency = parse_price(get_page())
        send_email(
            f"eMAG price check: {price} {currency} — Bosch WTH8520BBY",
            f"Product: {PRODUCT_NAME}\nCurrent listed price: {price} {currency}\nChecked at: {checked_at}\n\nProduct link: {PRODUCT_URL}\n\nPrice and availability may change before checkout."
        )
        print(f"Price found: {price} {currency}; email sent through Gmail API.")
        return 0
    except (HTTPError, URLError, TimeoutError, ValueError, RuntimeError, OSError) as exc:
        print(f"Price check failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        try:
            send_email(
                "eMAG price check FAILED — Bosch WTH8520BBY",
                f"The daily price check failed at {checked_at}.\nReason: {type(exc).__name__}: {exc}\n\nProduct link: {PRODUCT_URL}\n"
            )
            print("Failure notification email sent through Gmail API.", file=sys.stderr)
        except Exception as mail_exc:
            print(f"Could not send failure notification: {type(mail_exc).__name__}: {mail_exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
