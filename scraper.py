"""
Login to users.nimbaha.info and scrape traffic information from the dashboard.

Session-token strategy (better privacy)
----------------------------------------
After the first successful password login, the server returns session cookies.
We encrypt and cache those cookies. On the next check we load the cookies and
try to reach the dashboard directly — without sending the password again.
If the session has expired (redirect back to login), we fall back to a fresh
password login and refresh the cookie cache.

This means the raw password is used as rarely as possible: only when a new
session needs to be established (typically once a day or after a long idle).

Zero-traffic detection
-----------------------
`TrafficInfo.is_zero` is True when remaining traffic is 0 GB / 0 MB.
The bot uses this flag to ask the user if they want to remove the service.
"""

import json
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://users.nimbaha.info"
LOGIN_URL = f"{BASE_URL}/"
DASHBOARD_URL = f"{BASE_URL}/dashboard"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class TrafficInfo:
    remaining: str                              # e.g. "12.5 GB"
    total: str                                  # e.g. "50 GB"
    used: str                                   # e.g. "37.5 GB"
    expiry: str                                 # e.g. "2025-08-01"
    service_number: str                         # username / service id
    raw_text: str                               # first 2000 chars of dashboard text
    is_zero: bool = False                       # True when remaining == 0
    session_cookies: dict = field(default_factory=dict)  # cookies to cache


class LoginError(Exception):
    pass


def _find_csrf(soup: BeautifulSoup) -> dict[str, str]:
    hidden = {}
    for inp in soup.find_all("input", type="hidden"):
        name = inp.get("name") or inp.get("id")
        if name:
            hidden[name] = inp.get("value", "")
    return hidden


def _detect_zero(remaining: str) -> bool:
    """True if remaining traffic is zero (0 GB, 0 MB, 0 KB, or bare "0")."""
    if remaining in ("N/A", ""):
        return False
    stripped = remaining.strip().lower()
    # Match "0", "0 gb", "0.0 mb", "0.00 tb", etc.
    return bool(re.match(r"^0(\.0+)?\s*(gb|mb|kb|tb|گیگ|مگ)?$", stripped))


def _parse_dashboard(html: str, username: str) -> TrafficInfo:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(" ", strip=True)

    def first_match(patterns: list[str], source: str) -> str:
        for p in patterns:
            m = re.search(p, source, re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return "N/A"

    remaining = first_match(
        [
            r"(?:remaining|باقی‌مانده|باقیمانده)[^\d]*(\d+[\.,]?\d*\s*(?:GB|MB|TB|KB|گیگ|مگ))",
            r"(?:remaining|traffic left)[^\d]*(\d+[\.,]?\d*\s*(?:GB|MB|TB|KB))",
        ],
        text,
    )
    total = first_match(
        [r"(?:total|حجم کل|package)[^\d]*(\d+[\.,]?\d*\s*(?:GB|MB|TB|گیگ))"],
        text,
    )
    used = first_match(
        [r"(?:used|مصرف شده|استفاده شده)[^\d]*(\d+[\.,]?\d*\s*(?:GB|MB|TB|گیگ))"],
        text,
    )
    expiry = first_match(
        [
            r"(?:expir|انقضا|پایان)[^\d]*(\d{4}[-/]\d{1,2}[-/]\d{1,2})",
            r"(\d{4}[-/]\d{2}[-/]\d{2})",
        ],
        text,
    )

    for row in soup.find_all("tr"):
        cells = [td.get_text(strip=True) for td in row.find_all(["td", "th"])]
        if len(cells) >= 2:
            label, value = cells[0].lower(), cells[1]
            if any(k in label for k in ["remain", "باقی"]) and remaining == "N/A":
                remaining = value
            elif any(k in label for k in ["total", "حجم کل"]) and total == "N/A":
                total = value
            elif any(k in label for k in ["used", "مصرف"]) and used == "N/A":
                used = value
            elif any(k in label for k in ["expir", "انقضا"]) and expiry == "N/A":
                expiry = value

    return TrafficInfo(
        remaining=remaining,
        total=total,
        used=used,
        expiry=expiry,
        service_number=username,
        raw_text=text[:2000],
        is_zero=_detect_zero(remaining),
    )


async def _login_with_password(
    client: httpx.AsyncClient, username: str, password: str
) -> str:
    """
    Perform a full password login. Returns the dashboard HTML.
    Raises LoginError on failure.
    """
    resp = await client.get(LOGIN_URL)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    form = soup.find("form")
    hidden = _find_csrf(soup)

    username_field = "username"
    password_field = "password"
    if form:
        for inp in form.find_all("input"):
            t = (inp.get("type") or "").lower()
            n = (inp.get("name") or inp.get("id") or "").lower()
            if t == "text" or "user" in n or "name" in n or "login" in n:
                username_field = inp.get("name") or username_field
            elif t == "password" or "pass" in n:
                password_field = inp.get("name") or password_field

    payload = {**hidden, username_field: username, password_field: password}
    post_url = LOGIN_URL
    if form and form.get("action"):
        action = form["action"]
        post_url = action if action.startswith("http") else BASE_URL + action

    login_resp = await client.post(post_url, data=payload)
    login_resp.raise_for_status()

    if login_resp.headers.get("content-type", "").startswith("application/json"):
        data = login_resp.json()
        if not data.get("success", True) or data.get("error"):
            raise LoginError(f"Login failed: {data.get('message', data)}")
        dash_resp = await client.get(DASHBOARD_URL)
        dash_resp.raise_for_status()
        return dash_resp.text
    else:
        if "dashboard" in login_resp.url.path or "dashboard" in login_resp.text.lower():
            return login_resp.text
        dash_resp = await client.get(DASHBOARD_URL)
        dash_resp.raise_for_status()
        if "login" in str(dash_resp.url).lower() or "password" in dash_resp.text.lower()[:500]:
            raise LoginError("Login failed — please check your username and password.")
        return dash_resp.text


def cookies_to_json(cookies: httpx.Cookies) -> str:
    return json.dumps({k: v for k, v in cookies.items()})


def json_to_cookies(raw: str) -> dict[str, str]:
    return json.loads(raw)


async def fetch_traffic(
    username: str,
    password: str,
    cached_cookies_json: str | None = None,
) -> TrafficInfo:
    """
    Fetch traffic info.

    1. If `cached_cookies_json` is provided, try reaching the dashboard
       with those session cookies (no password needed).
    2. If the session is expired or no cache exists, fall back to a fresh
       password login and capture the new session cookies.

    `TrafficInfo.session_cookies` always contains the up-to-date cookies
    (as a plain dict) so the caller can re-encrypt and cache them.
    """
    async with httpx.AsyncClient(
        headers=HEADERS,
        follow_redirects=True,
        timeout=30,
    ) as client:
        dashboard_html: str | None = None

        # --- try cached session first ---
        if cached_cookies_json:
            try:
                saved = json_to_cookies(cached_cookies_json)
                for name, value in saved.items():
                    client.cookies.set(name, value)
                dash_resp = await client.get(DASHBOARD_URL)
                # If we landed on login, the session expired
                if "login" not in str(dash_resp.url).lower() and \
                   "password" not in dash_resp.text.lower()[:300]:
                    dashboard_html = dash_resp.text
            except Exception:
                pass  # fall through to password login

        # --- password login (first time or session expired) ---
        if dashboard_html is None:
            client.cookies.clear()
            dashboard_html = await _login_with_password(client, username, password)

        info = _parse_dashboard(dashboard_html, username)
        info.session_cookies = {k: v for k, v in client.cookies.items()}
        return info
