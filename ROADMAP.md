# Claude Usage Bar — Roadmap

A macOS menu bar app that shows claude.ai usage (5-hour session + weekly) at a glance.

**Project path:** `Documents/🐙💻⚙️/usage/`  
**Remote:** `github.com/sahandsorouri/nimbaha-traffic-bot` (branch `main`)

---

## Current state (May 2026)

### App behavior
- `claude_usage_bar.py` — rumps menu bar app (`LSUIElement`, no Dock icon).
- **Auth (temporary):** reads **Brave** cookies via `browser_cookie3.brave(domain_name="claude.ai")`.
- **API:** `/api/bootstrap` → `org_id` (cached), then `/api/organizations/{id}/usage` every **120s** via `curl_cffi` (Chrome impersonation).
- **Cache:** `~/.claude/usage_bar_cache.json`
- **Config:** `~/Library/Application Support/ClaudeUsageBar/config.json`
- **Dropdown:** SESSION / WEEKLY detail lines; macOS notifications on 5-hour / weekly reset.
- **Initial fetch:** ~1.5s after launch (no 2-minute wait on startup).

### Menu bar display (Phase 1 ✅)
Default mode is **`ring`** — compact 18×18 progress ring (session utilization).

| Mode | Bar shows |
|------|-----------|
| `ring` | Colored ring (default) |
| `percent` | e.g. `62%` |
| `dual` | e.g. `62%·18%` |
| `verbose` | e.g. `62% · 3h20m` |

Switch via **Display** submenu (checkmarks; persisted in config).

**Ring colors** (session % only):

| Session | Color |
|---------|--------|
| 0–50% | Green |
| 51–74% | Orange |
| ≥75% | Red |

Text modes (percent / dual / verbose) are not colored.

### Build & run
- **Do not use** `py2app -A` (alias) for distribution — Launch error from Finder (no bundled deps).
- **Use:** `bash scripts/build_app.sh` → semi-standalone `dist/Claude Usage Bar.app` (~28 MB).
- **Dev:** `python3.11 claude_usage_bar.py`
- **Login-at-startup:** `launch_wrapper.sh` (path resolves relative to script ✅)

### Repo layout
- Menu bar app at repo root.
- Legacy nimbaha Telegram bot → `legacy/` (not imported by the app).
- `login_once.py` — optional Playwright helper (not wired).
- `fetch_usage.py` — small API test script.

### Git history (menu bar work)
- `a8b3fa9` — Add Claude usage menu bar app; move Telegram bot to legacy/
- `58aa5d3` — Fix app packaging and tune ring color thresholds

---

## Decisions locked

| Topic | Decision |
|-------|----------|
| **Distribution** | Unsigned DMG first (right-click→Open Gatekeeper workaround). |
| **Login (target)** | WKWebView login → capture **only** claude.ai cookies → store in **app-scoped Keychain**. Stop reading the user's browser profile by default. See `AUTH.md`. |
| **Login (rejected for now)** | `ASWebAuthenticationSession` / default-browser OAuth — best UX in theory, but Anthropic does not expose OAuth for third-party claude.ai usage APIs; Safari cookies are not returned to native apps. |
| **Menu bar** | User-configurable display modes ✅ |
| **Build** | Semi-standalone py2app via `scripts/build_app.sh` |

---

## Phase 0 — Cleanup ✅ DONE
- [x] Fix `launch_wrapper.sh` path — resolves relative to the script.
- [x] Split legacy Telegram bot into `legacy/` (+ `legacy/README.md`).
- [x] New `requirements.txt` for the menu bar app.
- [x] `.gitignore` excludes `build/`, `dist/`, `.claude/`.

## Phase 1 — Configurable, compact menu bar ✅ DONE
- [x] Persist `display_mode` in Application Support config.
- [x] Modes: ring (default), percent, dual, verbose.
- [x] Display submenu with live switching + checkmarks.
- [x] Cooldown + error states are mode-aware.
- [x] Ring color thresholds: green ≤50%, orange 51–74%, red ≥75%.
- [x] Initial fetch shortly after launch.

## Phase 2 — Privacy-first login + secure storage
**Status:** Not started — design reviewed; see `AUTH.md`.

Recommended approach: **WKWebView PoC first**, then wire into main app.

- [ ] PoC: WKWebView login window; log cookie **names** only; store session in Keychain.
- [ ] Native WKWebView login in main app (PyObjC; already a dependency).
- [ ] On login, read **only** claude.ai cookies from `WKHTTPCookieStore`.
- [ ] Store session cookie in app-scoped macOS Keychain (Security framework or `keyring`).
- [ ] `fetch_*` read cookie from Keychain; expired → **Re-login** menu item.
- [ ] First-run: no credential → auto-open login window.
- [ ] Optional fallbacks only (not default): manual paste, opt-in Brave import via `browser_cookie3`.

## Phase 3 — Packaging & unsigned DMG
**Status:** Partially done.

- [x] Semi-standalone py2app build that launches from Finder (`scripts/build_app.sh`).
- [x] `LSUIElement`, bundle id `com.threehandss.claude-usage-bar`.
- [x] `emulate_shell_environment` + package `excludes` in `setup.py`.
- [ ] Custom app icon (still default Python/py2app icon).
- [ ] Build `.dmg` with `create-dmg` (drag-to-Applications).
- [ ] README: install, right-click→Open, update/rebuild instructions, auth requirements.
- [ ] Fully standalone build (no system Python dependency) — semi-standalone still uses system Python framework.

## Phase 4 — Polish & reliability
- [ ] Configurable refresh interval (Refresh now exists ✅).
- [ ] Graceful offline / error state in the bar (currently `!`).
- [ ] Launch-at-login toggle (replaces `launch_wrapper.sh`).
- [ ] Optional auto-update check against hosted version JSON.

## Phase 5 — Real distribution (deferred)
- [ ] Apple Developer ID → codesign → notarize → staple.
- Revisit after Phases 2–3 are solid.

---

## Suggested order

```
Phase 0 ✅ → Phase 1 ✅ → Phase 2 (PoC → integrate) → Phase 3 (DMG) → Phase 4 → Phase 5
```

**Alternative:** Phase 3 DMG now with Brave auth, Phase 2 later — OK for quick sharing, not ideal long-term.

---

## Quick commands

```bash
cd "$(dirname "$0")"   # repo root
bash scripts/build_app.sh
open "dist/Claude Usage Bar.app"
python3.11 claude_usage_bar.py
```
