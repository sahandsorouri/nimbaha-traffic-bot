# Claude Usage Bar — Roadmap

A macOS menu bar app that shows claude.ai usage (5-hour session + weekly) at a glance.

## Current state

- `claude_usage_bar.py` — rumps menu bar app. Reads **Brave** cookies via
  `browser_cookie3`, finds `org_id` from `/api/bootstrap` (cached to
  `~/.claude/usage_bar_cache.json`), polls `/api/organizations/{id}/usage` every
  120s with `curl_cffi` (Chrome impersonation). Bar title: `62% · 3h20m`.
  Dropdown: SESSION / WEEKLY lines. Notifications + timers on window reset.
- `login_once.py` — standalone Playwright login helper (separate Brave profile).
- `setup.py` — py2app config (alias + standalone). Bundle id
  `com.threehandss.claude-usage-bar`, `LSUIElement=True`.
- `launch_wrapper.sh` — login-at-startup shim. **BUG: stale path**
  (`Documents/GitHub/usage`), project moved to current dir.
- Legacy / unrelated: `bot.py`, `scraper.py`, `database.py`, `auth.py`,
  `Dockerfile`, `docker-compose.yml` (old "nimbaha" Telegram bot).

### Decisions locked
- **Distribution:** unsigned DMG first (right-click→Open Gatekeeper workaround).
- **Login:** native **WKWebView** login window → capture only claude.ai cookies →
  store session token in **macOS Keychain**. (Most privacy-respecting + no heavy
  deps; avoids reading the user's real browser and avoids bundling Chromium.)
- **Menu bar:** user-configurable display modes.

---

## Phase 0 — Cleanup (quick) ✅ DONE
- [x] Fix `launch_wrapper.sh` path — now resolves relative to the script.
- [x] Split the legacy Telegram bot into `legacy/` (+ `legacy/README.md`).
- [x] New `requirements.txt` for the menu bar app (was bot-only).
- [x] Confirmed `python3.11 setup.py py2app -A` builds the `.app`.

## Phase 1 — Configurable, compact menu bar ✅ DONE
- [x] Persist a `display_mode` pref in
      `~/Library/Application Support/ClaudeUsageBar/config.json`.
- [x] Modes:
  - `ring` — rendered NSImage gauge, fills with %, colored green/orange/red (default, most compact)
  - `percent` — `62%`
  - `dual` — `62%·18%` (session·weekly)
  - `verbose` — `62% · 3h20m` (previous default)
- [x] "Display" submenu switches live (with checkmarks); cooldown + error
      states are mode-aware too.

## Phase 2 — Privacy-first login + secure storage
- [ ] Native WKWebView login window (PyObjC; already a dependency).
- [ ] On login, read **only** claude.ai cookies from `WKHTTPCookieStore`.
- [ ] Store session cookie in macOS Keychain (`keyring` or Security framework);
      stop reading the user's browser profile.
- [ ] `fetch_*` read cookie from Keychain. Detect expired cookie → "Re-login"
      menu item that reopens the login window.
- [ ] First-run onboarding: no cookie → auto-open login window.
- [ ] Keep `browser_cookie3` as an optional fallback only.

## Phase 3 — Packaging & unsigned DMG
- [ ] Finalize standalone py2app build (icon, LSUIElement).
- [ ] Build `.dmg` with `create-dmg` (background + drag-to-Applications).
- [ ] README: right-click→Open first-run note; how to update.
- [ ] Drop `python3.11` shebang hard dependency for end users (bundle runtime).

## Phase 4 — Polish & reliability
- [ ] Configurable refresh interval + "Refresh now".
- [ ] Graceful offline / error state in the bar.
- [ ] Launch-at-login toggle (replaces the wrapper script).
- [ ] Optional auto-update check against a hosted version JSON.

## Phase 5 — Real distribution (deferred)
- [ ] Apple Developer ID → codesign → notarize → staple, so the DMG opens
      cleanly on any Mac. Revisit after 1–3 are solid.

---

## Suggested order
Phase 0 → 1 (visible win) → 2 (core privacy fix) → 3 (ship) → 4 → 5.
