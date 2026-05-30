#!/usr/bin/env python3.11
"""
Privacy-first auth for Claude Usage Bar (Phase 2).

Stores the claude.ai session cookie in a plain, app-scoped file under
Application Support (owner-only permissions) — no macOS Keychain, no system
password prompts. Provides a native WKWebView login window that captures ONLY
claude.ai cookies. Cookie values are never logged.

Import-safe for the menu bar app (no NSApplication is created on import) and
also runnable standalone:

    python3.11 auth_session.py login     # open login window
    python3.11 auth_session.py status    # is a session stored?
    python3.11 auth_session.py delete     # remove stored session
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

SESSION_FILE = (
    Path.home()
    / "Library"
    / "Application Support"
    / "ClaudeUsageBar"
    / "session.json"
)
LOGIN_URL = "https://claude.ai/login"
SESSION_COOKIE_NAME = "sessionKey"
COOKIE_HOST = "claude.ai"


# --------------------------------------------------------------------------- #
# File-backed storage (owner-only, app-scoped)
# --------------------------------------------------------------------------- #
def save_session(value: str) -> None:
    """Write the session cookie to an owner-only file (mode 0600)."""
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({SESSION_COOKIE_NAME: value})
    # Create/truncate with 0600 from the start so the secret is never briefly
    # world-readable.
    fd = os.open(SESSION_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, payload.encode("utf-8"))
    finally:
        os.close(fd)
    try:
        os.chmod(SESSION_FILE, 0o600)
    except OSError:
        pass


def load_session() -> str | None:
    """Return the stored session cookie value, or None if not present."""
    try:
        data = json.loads(SESSION_FILE.read_text())
    except (OSError, ValueError):
        return None
    value = data.get(SESSION_COOKIE_NAME)
    return value or None


def delete_session() -> None:
    """Remove the stored session file (no error if absent)."""
    try:
        SESSION_FILE.unlink(missing_ok=True)
    except OSError:
        pass


def has_session() -> bool:
    """True if a session cookie is stored."""
    return bool(load_session())


def session_cookies() -> dict | None:
    """Return cookies dict for API calls from the stored session, or None."""
    value = load_session()
    if not value:
        return None
    return {SESSION_COOKIE_NAME: value}


# --------------------------------------------------------------------------- #
# Cookie helpers
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CapturedCookie:
    name: str
    value: str
    domain: str


def is_claude_cookie(cookie) -> bool:
    domain = str(cookie.domain() or "").lstrip(".").lower()
    return domain == COOKIE_HOST or domain.endswith(f".{COOKIE_HOST}")


def to_captured_cookie(cookie) -> CapturedCookie:
    return CapturedCookie(
        name=str(cookie.name()),
        value=str(cookie.value()),
        domain=str(cookie.domain() or ""),
    )


# --------------------------------------------------------------------------- #
# WKWebView login window
# --------------------------------------------------------------------------- #
# Imported lazily inside present_login() so importing this module never pulls in
# AppKit/WebKit unless a login window is actually requested.
_active_controllers: list = []


def present_login(on_complete=None):
    """
    Open a native WKWebView login window inside the *currently running*
    NSApplication (e.g. the rumps menu bar app) and return its controller.

    on_complete(success: bool) is called on the main thread once the user
    finishes logging in (session stored) or closes the window without a
    session. The returned controller is retained internally so the caller does
    not have to keep a reference.
    """
    import objc
    from AppKit import (
        NSBackingStoreBuffered,
        NSFloatingWindowLevel,
        NSMakeRect,
        NSViewHeightSizable,
        NSViewWidthSizable,
        NSWindow,
        NSWindowStyleMaskClosable,
        NSWindowStyleMaskMiniaturizable,
        NSWindowStyleMaskResizable,
        NSWindowStyleMaskTitled,
    )
    from Foundation import NSURL, NSURLRequest, NSObject, NSTimer
    from WebKit import WKWebView, WKWebViewConfiguration, WKWebsiteDataStore

    class _LoginController(NSObject):
        def initWithCompletion_(self, completion):
            self = objc.super(_LoginController, self).init()
            if self is None:
                return None
            self._completion = completion
            self._timer = None
            self._window = None
            self._webview = None
            self._done = False
            self._seen_names = set()
            return self

        def show(self):
            style = (
                NSWindowStyleMaskTitled
                | NSWindowStyleMaskClosable
                | NSWindowStyleMaskResizable
                | NSWindowStyleMaskMiniaturizable
            )
            frame = NSMakeRect(140, 140, 1040, 760)
            self._window = (
                NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                    frame, style, NSBackingStoreBuffered, False
                )
            )
            self._window.setTitle_("Sign in to Claude — this window closes automatically")
            self._window.setDelegate_(self)
            self._window.setLevel_(NSFloatingWindowLevel)
            self._window.setReleasedWhenClosed_(False)
            self._window.center()

            config = WKWebViewConfiguration.alloc().init()
            config.setWebsiteDataStore_(WKWebsiteDataStore.defaultDataStore())
            self._webview = WKWebView.alloc().initWithFrame_configuration_(
                self._window.contentView().bounds(), config
            )
            self._webview.setAutoresizingMask_(
                NSViewWidthSizable | NSViewHeightSizable
            )
            self._window.setContentView_(self._webview)
            self._window.makeKeyAndOrderFront_(None)

            request = NSURLRequest.requestWithURL_(NSURL.URLWithString_(LOGIN_URL))
            self._webview.loadRequest_(request)

            self._timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
                1.5, self, "checkCookies:", None, True
            )

        def windowWillClose_(self, _notification):
            self._finish_(False)

        def checkCookies_(self, _timer):
            if self._done:
                return
            store = (
                self._webview.configuration().websiteDataStore().httpCookieStore()
            )
            store.getAllCookies_(self.gotCookies_)

        def gotCookies_(self, cookies):
            if self._done:
                return
            captured = [
                to_captured_cookie(c) for c in cookies if is_claude_cookie(c)
            ]
            session = next(
                (c for c in captured if c.name == SESSION_COOKIE_NAME), None
            )
            if session is None:
                return

            try:
                save_session(session.value)
                if load_session() != session.value:
                    raise RuntimeError("Session round-trip mismatch")
            except Exception as exc:
                print(f"Session storage failed: {exc}", flush=True)
                return

            self._finish_(True)

        def _finish_(self, success):
            if self._done:
                return
            self._done = True
            if self._timer is not None:
                self._timer.invalidate()
                self._timer = None
            if self._window is not None:
                self._window.setDelegate_(None)
                self._window.close()
                self._window = None
            self._webview = None
            if self._completion is not None:
                try:
                    self._completion(bool(success))
                except Exception:
                    pass
            if self in _active_controllers:
                _active_controllers.remove(self)

    controller = _LoginController.alloc().initWithCompletion_(on_complete)
    _active_controllers.append(controller)
    controller.show()
    return controller


# --------------------------------------------------------------------------- #
# Standalone CLI
# --------------------------------------------------------------------------- #
def _run_login_standalone() -> int:
    from AppKit import NSApplication, NSApplicationActivationPolicyRegular
    from PyObjCTools import AppHelper

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)

    def _done(success):
        print(
            "Login complete." if success else "Login window closed without a session.",
            flush=True,
        )
        AppHelper.callAfter(app.terminate_, None)

    present_login(on_complete=_done)
    app.activateIgnoringOtherApps_(True)
    AppHelper.runEventLoop()
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "login"
    if cmd == "status":
        print("session stored" if has_session() else "no session")
        return 0 if has_session() else 1
    if cmd == "delete":
        delete_session()
        print("Deleted stored session.")
        return 0
    if cmd == "login":
        return _run_login_standalone()
    print(f"Unknown command: {cmd!r}. Use login | status | delete.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
