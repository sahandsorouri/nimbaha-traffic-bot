# Claude Usage Bar

A tiny macOS **menu bar** app that shows your [claude.ai](https://claude.ai) usage
(5-hour session + weekly limits) at a glance — the same numbers as
`claude.ai/settings/usage`, no calibration needed.

<sub>Menu bar app · no Dock icon · macOS 11+ · Apple Silicon & Intel</sub>

---

## Install (DMG)

1. Download **`Claude-Usage-Bar.dmg`** and open it.
2. Drag **Claude Usage Bar** onto the **Applications** folder.
3. The app is **unsigned**, so the first launch needs the Gatekeeper bypass:
   **right-click the app → Open → Open**. (Double-clicking the first time will
   be blocked — that's expected for unsigned apps.)
4. The icon appears in your menu bar. There is **no Dock icon** by design.

After the first right-click→Open, you can launch it normally.

---

## First run & login

On first launch the app has no session, so it opens a **"Sign in to Claude"**
window (a Dock icon appears only while this window is open). Log in with your
normal Claude account; the window closes itself and your usage appears in the
menu bar.

- The login uses an in-app web view that loads `https://claude.ai/login`.
- Only the `claude.ai` **session cookie** is captured.
- It is stored in an app-scoped file:
  `~/Library/Application Support/ClaudeUsageBar/session.json` (owner-only `0600`).
- **No macOS Keychain**, no system password prompts.

To sign in again later (e.g. session expired): **menu ▸ Account ▸ Log in to Claude…**

---

## Menu bar display

Default is a compact **ring** showing session utilization. Switch modes in
**menu ▸ Display**:

| Mode | Shows |
|------|-------|
| **Ring** (default) | Colored progress ring — green ≤50%, orange 51–74%, red ≥75% |
| **Percent** | `62%` |
| **Session · Weekly** | `62%·18%` |
| **Percent · time** | `62% · 3h20m` |

The dropdown always lists SESSION and WEEKLY detail lines, and you get a macOS
notification when your 5-hour or weekly window resets.

---

## Privacy

- The app talks **only to claude.ai**. Nothing is sent anywhere else.
- By default it does **not** read your browser profile.
- *Optional* fallback for power users: **menu ▸ Account ▸ Use Brave cookies**
  imports the session from a logged-in Brave profile via `browser_cookie3`.
  Off by default.

See [`AUTH.md`](AUTH.md) for the full design and rationale.

---

## Build from source

Requires **Python 3.11** (system `/usr/local/bin/python3.11`).

```bash
pip3.11 install -r requirements.txt

# Run from source (dev):
python3.11 claude_usage_bar.py

# Build the .app bundle (semi-standalone, ~28 MB):
bash scripts/build_app.sh

# Build the distributable DMG (drag-to-Applications):
bash scripts/build_dmg.sh        # -> dist/Claude-Usage-Bar.dmg

# Regenerate the app icon:
python3.11 make_icon.py          # -> AppIcon.icns
```

Notes:
- The build is **semi-standalone**: dependencies are bundled, but it still uses
  the system Python framework. A fully standalone build is future work.
- The DMG is unsigned. Real distribution (Developer ID → notarize → staple) is
  deferred; see [`ROADMAP.md`](ROADMAP.md).

---

## Project layout

| Path | Purpose |
|------|---------|
| `claude_usage_bar.py` | The menu bar app (rumps). |
| `auth_session.py` | File-backed session storage + WKWebView login window. |
| `make_icon.py` | Generates `AppIcon.icns`. |
| `setup.py` | py2app build config. |
| `scripts/build_app.sh` | Build the `.app`. |
| `scripts/build_dmg.sh` | Build the `.dmg`. |
| `ROADMAP.md` / `AUTH.md` | Status and authentication design. |
| `legacy/` | Unrelated older Telegram bot (not used by the app). |

---

## Troubleshooting

- **"App is damaged / can't be opened"** — Gatekeeper on an unsigned app. Use
  right-click → Open, or clear quarantine: `xattr -cr "/Applications/Claude Usage Bar.app"`.
- **Bar shows `!`** — a fetch failed (offline, or the session expired). Try
  **Account ▸ Log in to Claude…**.
- **Bar shows `Log in`** — no stored session; open the login window from
  **Account ▸ Log in to Claude…**.
