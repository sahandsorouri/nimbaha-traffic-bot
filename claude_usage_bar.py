#!/usr/bin/env python3.11
"""
Claude usage menu bar — reads directly from the claude.ai API.
Auth: an in-app WKWebView login stores the session in the macOS Keychain
(see auth_keychain.py). Brave cookie import is an opt-in fallback only.
No calibration needed. Exact same data as claude.ai/settings/usage.

Optional: set CLAUDE_USAGE_BAR_TEST_MENU=1 to add menu items that fire the
same notifications as real session / weekly resets (for checking macOS alerts).
"""

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

import rumps
from AppKit import NSBezierPath, NSColor, NSImage
from curl_cffi import requests as cf_requests
from Foundation import NSMakePoint, NSMakeRect, NSMakeSize
from PyObjCTools import AppHelper

import auth_session as auth

CACHE_FILE = Path.home() / ".claude" / "usage_bar_cache.json"
CONFIG_FILE = (
    Path.home() / "Library" / "Application Support" / "ClaudeUsageBar" / "config.json"
)
REFRESH_SECONDS = 120

DISPLAY_MODES = ("ring", "percent", "dual", "verbose")
DEFAULT_MODE = "ring"


def brave_cookies():
    # Optional opt-in fallback only; imported lazily so the app does not depend
    # on browser_cookie3 unless the user explicitly enables Brave import.
    import browser_cookie3

    cj = browser_cookie3.brave(domain_name="claude.ai")
    return {c.name: c.value for c in cj}


def get_cookies(config: dict) -> dict | None:
    """Cookie source: Keychain session first; Brave only if opted in."""
    cookies = auth.session_cookies()
    if cookies:
        return cookies
    if config.get("use_brave_fallback"):
        try:
            return brave_cookies()
        except Exception:
            return None
    return None


def clear_org_cache() -> None:
    try:
        CACHE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


def fetch_org_id(cookies) -> str | None:
    if CACHE_FILE.exists():
        try:
            cached = json.loads(CACHE_FILE.read_text())
            if cached.get("org_id"):
                return cached["org_id"]
        except Exception:
            pass

    r = cf_requests.get(
        "https://claude.ai/api/bootstrap",
        cookies=cookies,
        impersonate="chrome131",
        timeout=10,
    )
    if r.status_code != 200:
        return None

    for m in r.json()["account"].get("memberships", []):
        org_id = m["organization"]["uuid"]
        test = cf_requests.get(
            f"https://claude.ai/api/organizations/{org_id}/usage",
            cookies=cookies,
            impersonate="chrome131",
            timeout=10,
        )
        if test.status_code == 200:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(json.dumps({"org_id": org_id}))
            return org_id
    return None


def fetch_usage(cookies, org_id) -> dict | None:
    r = cf_requests.get(
        f"https://claude.ai/api/organizations/{org_id}/usage",
        cookies=cookies,
        impersonate="chrome131",
        timeout=10,
    )
    if r.status_code == 200:
        return r.json()
    return None


def time_left(resets_at_iso: str) -> str:
    try:
        resets = datetime.fromisoformat(resets_at_iso)
        secs = max(int((resets - datetime.now(timezone.utc)).total_seconds()), 0)
        if secs < 60:
            return "soon"
        h, rem = divmod(secs, 3600)
        m = rem // 60
        return f"{h}h{m:02d}m" if h else f"{m}m"
    except Exception:
        return "?"


def reset_day(resets_at_iso: str) -> str:
    try:
        resets = datetime.fromisoformat(resets_at_iso)
        return resets.astimezone().strftime("%a")
    except Exception:
        return "?"


def reset_clock(resets_at_iso: str) -> str:
    try:
        resets = datetime.fromisoformat(resets_at_iso)
        return resets.astimezone().strftime("%H:%M")
    except Exception:
        return "?"


def pct(utilization) -> str:
    return f"{round(float(utilization))}%" if utilization is not None else "?%"


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    try:
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg))
    except Exception:
        pass


def _ring_color(value: float):
    if value >= 75:
        return NSColor.systemRedColor()
    if value > 50:
        return NSColor.systemOrangeColor()
    return NSColor.systemGreenColor()


def make_ring_image(value: float) -> NSImage:
    """A small colored progress ring for the menu bar (session utilization)."""
    value = min(max(float(value or 0), 0), 100)
    size = 18.0
    line = 2.5
    inset = line / 2 + 0.5
    diameter = size - 2 * inset

    img = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
    img.lockFocus()
    try:
        rect = NSMakeRect(inset, inset, diameter, diameter)
        track = NSBezierPath.bezierPathWithOvalInRect_(rect)
        track.setLineWidth_(line)
        NSColor.tertiaryLabelColor().setStroke()
        track.stroke()

        if value > 0:
            center = NSMakePoint(size / 2, size / 2)
            radius = diameter / 2
            start = 90.0
            end = 90.0 - 360.0 * value / 100.0
            arc = NSBezierPath.bezierPath()
            arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                center, radius, start, end, True
            )
            arc.setLineWidth_(line)
            _ring_color(value).setStroke()
            arc.stroke()
    finally:
        img.unlockFocus()
    img.setTemplate_(False)
    return img


class App(rumps.App):
    def __init__(self):
        super().__init__("Claude Usage", title="…", quit_button="Quit")
        self._org_id = None
        self._cooldown_until: datetime | None = None
        self._reset_timer: threading.Timer | None = None
        self._weekly_cooldown_until: datetime | None = None
        self._weekly_reset_timer: threading.Timer | None = None
        self._login_in_progress = False
        self._prompted_login = False

        self._config = load_config()
        mode = self._config.get("display_mode", DEFAULT_MODE)
        self._display_mode = mode if mode in DISPLAY_MODES else DEFAULT_MODE
        self._last_u5: float = 0.0
        self._last_u7: float = 0.0

        self._s1 = rumps.MenuItem("", callback=None)
        self._w1 = rumps.MenuItem("", callback=None)
        self._ts = rumps.MenuItem("", callback=None)

        self.menu = [
            self._s1,
            self._w1,
            rumps.separator,
            rumps.MenuItem("Refresh", callback=self.do_refresh),
            self._build_display_menu(),
            self._build_account_menu(),
            self._ts,
        ]
        if os.environ.get("CLAUDE_USAGE_BAR_TEST_MENU"):
            self.menu.extend(
                [
                    rumps.separator,
                    rumps.MenuItem(
                        "Test: session reset notification",
                        callback=self.test_notif_session,
                    ),
                    rumps.MenuItem(
                        "Test: weekly reset notification",
                        callback=self.test_notif_weekly,
                    ),
                ]
            )

        # Show real data shortly after launch instead of waiting a full cycle.
        initial = threading.Timer(1.5, lambda: AppHelper.callAfter(self._do_fetch))
        initial.daemon = True
        initial.start()

    def _build_display_menu(self):
        parent = rumps.MenuItem("Display")
        self._mode_items: dict[str, rumps.MenuItem] = {}
        labels = [
            ("ring", "Ring (compact)"),
            ("percent", "Percent"),
            ("dual", "Session · Weekly"),
            ("verbose", "Percent · time"),
        ]
        for key, label in labels:
            item = rumps.MenuItem(label, callback=self._make_mode_setter(key))
            item.state = 1 if key == self._display_mode else 0
            self._mode_items[key] = item
            parent.add(item)
        return parent

    def _make_mode_setter(self, key: str):
        def _cb(_):
            self._display_mode = key
            self._config["display_mode"] = key
            save_config(self._config)
            for k, item in self._mode_items.items():
                item.state = 1 if k == key else 0
            self._do_fetch(force=True)

        return _cb

    def _build_account_menu(self):
        parent = rumps.MenuItem("Account")
        parent.add(rumps.MenuItem("Log in to Claude…", callback=self.do_login))
        brave = rumps.MenuItem(
            "Use Brave cookies (fallback)", callback=self._toggle_brave
        )
        brave.state = 1 if self._config.get("use_brave_fallback") else 0
        self._brave_item = brave
        parent.add(brave)
        return parent

    def _toggle_brave(self, _):
        enabled = not bool(self._config.get("use_brave_fallback"))
        self._config["use_brave_fallback"] = enabled
        save_config(self._config)
        self._brave_item.state = 1 if enabled else 0
        self._do_fetch(force=True)

    def do_login(self, _=None):
        """Open the WKWebView login window (re-login safe)."""
        if self._login_in_progress:
            return
        self._login_in_progress = True
        self._set_status_text("…")
        try:
            auth.present_login(on_complete=self._on_login_done)
            # Accessory (LSUIElement) apps must be activated to show a window.
            from AppKit import NSApplication

            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        except Exception:
            self._login_in_progress = False
            self._set_status_text("!")

    def _on_login_done(self, success: bool):
        self._login_in_progress = False
        if success:
            # A fresh session may belong to a different account; drop cached org.
            clear_org_cache()
            self._org_id = None
            self._notify("Signed in to Claude", "Usage will appear in the menu bar.")
            self._do_fetch(force=True)
        else:
            self._render_logged_out()

    def _render_logged_out(self):
        self._set_status_text("Log in")
        self._s1.title = "Not logged in — open Account ▸ Log in to Claude…"
        self._w1.title = ""
        self._ts.title = "no session"

    def _status_button(self):
        try:
            return self._nsapp.nsstatusitem.button()
        except Exception:
            return None

    def _set_status_text(self, text: str):
        """Plain-text bar state; clears any ring image first."""
        btn = self._status_button()
        if btn is not None:
            btn.setImage_(None)
        self.title = text

    def _apply_bar(self, u5: float, u7: float, tl5: str):
        """Set the menu bar item according to the chosen display mode."""
        mode = self._display_mode
        btn = self._status_button()
        if mode == "ring":
            if btn is not None:
                try:
                    btn.setImage_(make_ring_image(u5))
                    self.title = ""
                    return
                except Exception:
                    pass
            self.title = pct(u5)
            return
        if btn is not None:
            btn.setImage_(None)
        if mode == "percent":
            self.title = pct(u5)
        elif mode == "dual":
            self.title = f"{pct(u5)}·{pct(u7)}"
        else:  # verbose
            self.title = f"{pct(u5)} · {tl5}"

    def _apply_bar_maxed(self, tl: str, weekly: bool = False):
        """Bar rendering for the 100% cooldown states, mode-aware."""
        mode = self._display_mode
        btn = self._status_button()
        if mode == "ring":
            if btn is not None:
                try:
                    btn.setImage_(make_ring_image(100.0))
                    self.title = ""
                    return
                except Exception:
                    pass
            self.title = "100%"
            return
        if btn is not None:
            btn.setImage_(None)
        if mode == "percent":
            self.title = "100%"
        elif mode == "dual":
            if weekly:
                self.title = f"{pct(self._last_u5)}·100%"
            else:
                self.title = f"100%·{pct(self._last_u7)}"
        else:  # verbose
            prefix = "W" if weekly else ""
            self.title = f"{prefix}100% · {tl}"

    def _render(self, data: dict):
        fh = data.get("five_hour", {}) or {}
        wk = data.get("seven_day", {}) or {}
        u5 = fh.get("utilization", 0)
        u7 = wk.get("utilization", 0)
        tl5 = time_left(fh.get("resets_at", ""))
        tl7 = time_left(wk.get("resets_at", ""))
        p5 = pct(u5)
        p7 = pct(u7)
        day7 = reset_day(wk.get("resets_at", ""))

        clock5 = reset_clock(fh.get("resets_at", ""))

        self._last_u5 = float(u5 or 0)
        self._last_u7 = float(u7 or 0)
        self._apply_bar(self._last_u5, self._last_u7, tl5)
        self._s1.title = f"SESSION  ·  {p5}  ·  resets {clock5}"
        self._w1.title = f"WEEKLY  ·  {p7}  ·  resets {day7}  ·  {tl7}"

        self._ts.title = f"updated {datetime.now().strftime('%H:%M:%S')}"

    def _notify(self, title: str, message: str, sound: str = "Glass"):
        try:
            safe_title = title.replace('"', '\\"')
            safe_message = message.replace('"', '\\"')
            script = (
                f'display notification "{safe_message}" '
                f'with title "{safe_title}" sound name "{sound}"'
            )
            subprocess.run(["osascript", "-e", script], check=False, timeout=5)
        except Exception:
            pass

    def test_notif_session(self, _):
        self._notify(
            "Claude is back",
            "Your 5-hour window has reset — start using again!",
        )

    def test_notif_weekly(self, _):
        self._notify(
            "Weekly usage reset",
            "Your weekly limit has rolled over — check the menu bar.",
        )

    def _render_cooldown(self):
        now = datetime.now(timezone.utc)
        secs = max(int((self._cooldown_until - now).total_seconds()), 0)
        h, rem = divmod(secs, 3600)
        m = rem // 60
        tl = f"{h}h{m:02d}m" if h else f"{m}m"
        clock = self._cooldown_until.astimezone().strftime("%H:%M")
        self._apply_bar_maxed(tl)
        self._s1.title = f"SESSION  ·  100%  ·  resets {clock}"
        self._ts.title = f"session paused · {tl} left"

    def _render_weekly_cooldown(self):
        now = datetime.now(timezone.utc)
        secs = max(int((self._weekly_cooldown_until - now).total_seconds()), 0)
        h, rem = divmod(secs, 3600)
        m = rem // 60
        tl = f"{h}h{m:02d}m" if h else f"{m}m"
        day = self._weekly_cooldown_until.astimezone().strftime("%a")
        self._apply_bar_maxed(tl, weekly=True)
        self._w1.title = f"WEEKLY  ·  100%  ·  resets {day}  ·  {tl}"
        self._ts.title = f"weekly max · {tl} until reset"

    def _cancel_5h_reset_timer(self):
        if self._reset_timer is not None:
            self._reset_timer.cancel()
            self._reset_timer = None

    def _cancel_weekly_reset_timer(self):
        if self._weekly_reset_timer is not None:
            self._weekly_reset_timer.cancel()
            self._weekly_reset_timer = None

    def _schedule_reset(self, resets: datetime):
        if self._reset_timer is not None:
            self._reset_timer.cancel()
            self._reset_timer = None

        delay = (resets - datetime.now(timezone.utc)).total_seconds() + 3
        if delay <= 0:
            AppHelper.callAfter(self._on_reset_fired)
            return

        def _fire():
            AppHelper.callAfter(self._on_reset_fired)

        self._reset_timer = threading.Timer(delay, _fire)
        self._reset_timer.daemon = True
        self._reset_timer.start()

    def _schedule_weekly_reset(self, resets: datetime):
        self._cancel_weekly_reset_timer()
        delay = (resets - datetime.now(timezone.utc)).total_seconds() + 3
        if delay <= 0:
            AppHelper.callAfter(self._on_weekly_reset_fired)
            return

        def _fire():
            AppHelper.callAfter(self._on_weekly_reset_fired)

        self._weekly_reset_timer = threading.Timer(delay, _fire)
        self._weekly_reset_timer.daemon = True
        self._weekly_reset_timer.start()

    def _on_reset_fired(self):
        self._cooldown_until = None
        self._cancel_5h_reset_timer()
        self._notify(
            "Claude is back",
            "Your 5-hour window has reset — start using again!",
        )
        self._do_fetch(force=True)

    def _on_weekly_reset_fired(self):
        self._weekly_cooldown_until = None
        self._cancel_weekly_reset_timer()
        self._notify(
            "Weekly usage reset",
            "Your weekly limit has rolled over — check the menu bar.",
        )
        self._do_fetch(force=True)

    def _do_fetch(self, force: bool = False):
        now = datetime.now(timezone.utc)

        if self._weekly_cooldown_until and not force:
            if now < self._weekly_cooldown_until:
                self._render_weekly_cooldown()
                return
            self._on_weekly_reset_fired()
            return

        if self._cooldown_until and not force:
            if now < self._cooldown_until:
                self._render_cooldown()
                return
            self._on_reset_fired()
            return

        if self._login_in_progress:
            return

        cookies = get_cookies(self._config)
        if not cookies:
            self._render_logged_out()
            # First run with no stored session: open the login window once.
            if not self._prompted_login:
                self._prompted_login = True
                self.do_login()
            return

        try:
            self._org_id = self._org_id or fetch_org_id(cookies)
            if not self._org_id:
                self._set_status_text("!")
                return
            data = fetch_usage(cookies, self._org_id)
            if not data:
                self._set_status_text("!")
                return

            self._render(data)

            wk = data.get("seven_day", {}) or {}
            u7 = wk.get("utilization") or 0
            resets_weekly = wk.get("resets_at", "")
            try:
                weekly_maxed = float(u7) >= 100
            except (TypeError, ValueError):
                weekly_maxed = False
            if weekly_maxed and resets_weekly:
                try:
                    w_reset = datetime.fromisoformat(resets_weekly)
                    if w_reset > now:
                        self._weekly_cooldown_until = w_reset
                        self._cancel_5h_reset_timer()
                        self._cooldown_until = None
                        self._render_weekly_cooldown()
                        self._schedule_weekly_reset(w_reset)
                        return
                except Exception:
                    pass
            else:
                self._weekly_cooldown_until = None
                self._cancel_weekly_reset_timer()

            fh = data.get("five_hour", {}) or {}
            u5 = fh.get("utilization") or 0
            resets_at = fh.get("resets_at", "")
            try:
                maxed = float(u5) >= 100
            except (TypeError, ValueError):
                maxed = False
            if maxed and resets_at:
                try:
                    resets = datetime.fromisoformat(resets_at)
                    if resets > now:
                        self._cooldown_until = resets
                        self._render_cooldown()
                        self._schedule_reset(resets)
                except Exception:
                    pass
        except Exception:
            self._set_status_text("!")

    @rumps.timer(REFRESH_SECONDS)
    def auto_refresh(self, _):
        self._do_fetch()

    def do_refresh(self, _):
        self._do_fetch(force=True)


if __name__ == "__main__":
    App().run()
