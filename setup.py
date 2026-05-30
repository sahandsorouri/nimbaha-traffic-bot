"""
py2app build script for Claude Usage Bar.

Alias mode (-A) — use while developing:
    python3.11 setup.py py2app -A

    The .app is a thin launcher: it runs claude_usage_bar.py from this repo
    every time you open it. After editing the .py file you do NOT need to
    rebuild; quit the menu bar app and open the .app again (or kill + relaunch).

Standalone (no -A) — for copying to another Mac or a fixed release:
    python3.11 setup.py py2app

    Code is bundled inside the .app; any change to claude_usage_bar.py
    requires running py2app again (full rebuild).
"""

from setuptools import setup

APP = ["claude_usage_bar.py"]

OPTIONS = {
    "argv_emulation": False,
    "plist": {
        "CFBundleName": "Claude Usage Bar",
        "CFBundleDisplayName": "Claude Usage Bar",
        "CFBundleIdentifier": "com.threehandss.claude-usage-bar",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
    },
    "packages": [
        "rumps",
        "browser_cookie3",
        "curl_cffi",
        "objc",
    ],
    "includes": [
        "AppKit",
        "Foundation",
        "PyObjCTools.AppHelper",
        "PyObjCTools.Conversion",
    ],
}

setup(
    app=APP,
    name="Claude Usage Bar",
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
