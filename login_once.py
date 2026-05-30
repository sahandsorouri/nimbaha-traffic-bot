#!/usr/bin/env python3.11
from playwright.sync_api import sync_playwright
from pathlib import Path

BRAVE    = "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"
SESSION  = str(Path.home() / ".claude" / "usage_browser_session")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        SESSION,
        headless=False,
        executable_path=BRAVE,
        args=["--no-sandbox"],
    )
    page = ctx.new_page()
    page.goto("https://claude.ai/settings/usage")
    input("بعد از login کردن اینجا Enter بزن...")
    ctx.close()
