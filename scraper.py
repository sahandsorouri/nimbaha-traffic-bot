"""
API client for users.nimbaha.info (cloudius.net backend).

The frontend is a React SPA — all data comes from a clean JSON API.
No HTML scraping needed.

Endpoints
---------
POST /User/Login?Type=User          — returns Bearer token
POST /User/Dashboard?Type=User      — remaining traffic, expiry, etc.
POST /User/Traffic/Cardex?Type=User — per-day traffic history
POST /User/Consume/Dashboard?Type=User — per-day consumption chart data

Auth
----
Login returns a Bearer token.  We cache it (encrypted) in the DB so the
raw password is only sent when the token expires (status -103).
"""

import re
from dataclasses import dataclass, field

import httpx

API_BASE     = "https://140.cloudius.net"
STATIC_TOKEN = "#EFA0C786FFC94861B1479A6E6E2253CA#"

_BASE_HEADERS = {
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (compatible; NimbahaBot/1.0)",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TrafficInfo:
    remaining:      str       # "4.73 GB"
    total:          str       # "5 GB"  (initial allocation)
    used:           str       # "270 MB" (calculated)
    expiry:         str       # "1405/02/25 22:36:16"
    days_left:      str       # "28"
    service_number: str
    is_zero:        bool = False
    auth_token:     str  = ""  # Bearer token — store encrypted in DB


@dataclass
class DailyUsage:
    date:     str   # "1405/01/27"
    consume:  str   # "233.66 MB"
    download: str
    upload:   str


class LoginError(Exception):
    pass


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------

_UNIT = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}


def _to_bytes(s: str) -> float | None:
    """Parse "4.73 GB" or "-90 MB" → bytes as float.  Returns None on failure."""
    s = s.strip()
    negative = s.startswith("-")
    m = re.match(r"-?([\d.,]+)\s*([a-zA-Z]+)?", s)
    if not m:
        return None
    num  = float(m.group(1).replace(",", "."))
    unit = (m.group(2) or "b").lower()
    val  = num * _UNIT.get(unit, 1)
    return -val if negative else val


def _fmt_bytes(b: float) -> str:
    """Format bytes back to a human-readable string."""
    for unit, size in [("TB", 1024**4), ("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)]:
        if b >= size:
            return f"{b / size:.2f} {unit}"
    return f"{b:.0f} B"


def _calc_used(total: str, remaining: str) -> str:
    t = _to_bytes(total)
    r = _to_bytes(remaining)
    if t is None or r is None:
        return "N/A"
    # If remaining is negative the user went over quota — used = total + overage
    diff = t - r  # e.g. 8 GB - (-90 MB) = 8.09 GB
    return _fmt_bytes(max(0.0, diff))


def _is_zero(remaining: str) -> bool:
    """True when remaining is 0 or negative (over quota)."""
    b = _to_bytes(remaining)
    return b is not None and b <= 0


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

async def _login(username: str, password: str) -> str:
    """POST credentials → Bearer token.  Raises LoginError on failure."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{API_BASE}/User/Login?Type=User",
            headers=_BASE_HEADERS,
            json={
                "UserName":    username,
                "Password":    password,
                "StaticToken": STATIC_TOKEN,
                "DeviceID":    "",
                "Info":        "",
                "languageID":  "1",
            },
        )
        resp.raise_for_status()
        data = resp.json()

    if str(data.get("Status")) != "0":
        raise LoginError(data.get("Message") or "نام کاربری یا رمز عبور اشتباه است")

    return data["Data"][0]["Token"]


def _auth_headers(token: str) -> dict:
    return {**_BASE_HEADERS, "Authorization": f"Bearer {token}"}


async def _dashboard(token: str) -> dict | None:
    """Fetch dashboard data.  Returns None if the token has expired."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{API_BASE}/User/Dashboard?Type=User",
            headers=_auth_headers(token),
            json={"languageId": 1},
        )
        resp.raise_for_status()
        data = resp.json()

    if str(data.get("Status")) == "-103":
        return None          # token expired
    if not data.get("Data"):
        return None
    return data["Data"][0]


async def _cardex(token: str) -> list[dict]:
    """Fetch Traffic/Cardex — daily usage + allocation entries."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{API_BASE}/User/Traffic/Cardex?Type=User",
            headers=_auth_headers(token),
            json={"languageId": 1},
        )
        resp.raise_for_status()
        return resp.json().get("Data", [])


async def _consume_dashboard(token: str) -> list[dict]:
    """Fetch per-day consumption chart data."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{API_BASE}/User/Consume/Dashboard?Type=User",
            headers=_auth_headers(token),
            json={"languageId": 1},
        )
        resp.raise_for_status()
        return resp.json().get("Data", [])


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

async def fetch_traffic(
    username: str,
    password: str,
    cached_token: str | None = None,
) -> TrafficInfo:
    """
    Return TrafficInfo for the account.

    Uses `cached_token` if provided; falls back to a fresh login if the
    token is missing or expired.  TrafficInfo.auth_token always contains
    the up-to-date token for re-caching.
    """
    token = cached_token

    # 1 — try cached token
    dash = None
    if token:
        try:
            dash = await _dashboard(token)
        except Exception:
            pass

    # 2 — fresh login if needed
    if dash is None:
        token = await _login(username, password)
        dash  = await _dashboard(token)

    if not dash:
        raise LoginError("دریافت اطلاعات داشبورد ممکن نشد.")

    remaining = dash.get("RemainedTraffic") or "N/A"
    expiry    = dash.get("ExpirationTime")  or "N/A"
    days_left = dash.get("RemainedTime")    or "N/A"
    expired   = dash.get("Expired", 0)

    # Find total allocation from Cardex (first row with a non-empty Traffic)
    total = "N/A"
    try:
        for entry in await _cardex(token):
            if entry.get("Traffic"):
                total = entry["Traffic"]
                break
    except Exception:
        pass

    used    = _calc_used(total, remaining)
    is_zero = _is_zero(remaining) or bool(expired)

    return TrafficInfo(
        remaining=remaining,
        total=total,
        used=used,
        expiry=expiry,
        days_left=days_left,
        service_number=username,
        is_zero=is_zero,
        auth_token=token,
    )


async def fetch_daily_usage(auth_token: str) -> list[DailyUsage]:
    """
    Return per-day usage list, most-recent day first.
    Uses the Consume/Dashboard endpoint (no extra login required).
    """
    rows = await _consume_dashboard(auth_token)
    return [
        DailyUsage(
            date=r.get("TimeStamp", ""),
            consume=r.get("Consume", ""),
            download=r.get("Download", ""),
            upload=r.get("Upload", ""),
        )
        for r in reversed(rows)   # API returns oldest first
    ]
