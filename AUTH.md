# Claude Usage Bar — Authentication Design

How the app gets a session to call claude.ai usage APIs, and what we chose not to do.

---

## What we need

The app calls **private claude.ai web APIs**:

- `GET /api/bootstrap` → organization id
- `GET /api/organizations/{org_id}/usage` → 5-hour + weekly utilization

These require an **authenticated session** (HttpOnly cookies such as `sessionKey`), sent with each request.

There is **no public OAuth or API** today for third-party apps to read claude.ai **subscription** usage (Pro/Max 5-hour / weekly limits). Anthropic **Console API keys** cover API billing, not the same data.

**Conclusion:** some session credential is unavoidable. The goal is **how** we obtain and store it — not whether we need one.

---

## Two separate problems

| Problem | Question |
|---------|----------|
| **Acquisition** | How does the app get a valid session? |
| **Storage** | Where is it kept between launches? |

Reading **Brave’s cookie database** (current approach) is an **acquisition** problem — invasive and fragile.

Storing **our own token in Keychain** is normal app behavior (app-scoped secret). It is **not** the same as decrypting the browser’s “Safe Storage” Keychain entry.

Alternatives to Keychain (plain file in Application Support) are **less secure**, not more private.

---

## Options compared

| Approach | UX | Privacy / scope | Works today? |
|----------|----|-----------------|--------------|
| **browser_cookie3 (current default)** | Zero setup if Brave logged in | Reads full Brave profile + browser Keychain key | ⚠️ Yes, but fragile (app-bound cookie encryption) and Brave-only |
| **WKWebView login (recommended)** | Good — same claude.ai login page in app window | Isolated; only claude.ai cookies from WebView | ✅ Yes |
| **ASWebAuthenticationSession (default browser)** | Best in theory — Safari, passkeys | No browser profile read | ❌ No — cookies stay in browser; no Anthropic OAuth for usage APIs |
| **Manual paste session cookie** | Poor | Fully transparent; user-controlled | ✅ Yes — good optional fallback |
| **Anthropic Console API key** | N/A | N/A | ❌ Wrong data (API usage ≠ claude.ai limits) |
| **Browser extension → localhost** | Two installs | App never touches cookies | ⚠️ Overkill for this project |

---

## Decisions

### Primary path (Phase 2): WKWebView + app-scoped file
1. User opens an in-app login window (`https://claude.ai/login`).
2. On success, read **only** `claude.ai` cookies from `WKHTTPCookieStore`.
3. Store the session cookie in an **app-scoped file**:
   `~/Library/Application Support/ClaudeUsageBar/session.json`, mode `0600`.
4. All API calls use that session; never read Brave unless the user opts in.

**Keychain was prototyped and then dropped.** It is more hardened at rest, but
on an unsigned/ad-hoc build it triggers macOS "allow access" prompts and ties
the secret to the code signature — poor UX for this app. A plain owner-only
file under the app's own Application Support folder is self-contained, prompt-
free, and survives app updates. (Storing the secret *inside* the `.app`/`.dmg`
is not possible — those are read-only and replaced on update.)

### Rejected as primary (for now): ASWebAuthenticationSession
User-friendly, but **does not return Safari cookies** to the native app — only OAuth redirect parameters. Anthropic does not register third-party OAuth clients for claude.ai usage. Revisit if Anthropic adds official OAuth or a usage API.

### Optional fallbacks (explicit opt-in only)
- **Re-login** menu item (WKWebView).
- **Paste session token** for power users.
- **Import from Brave** via `browser_cookie3` behind a menu toggle.

### Drop as default
Silent `browser_cookie3` reading on every launch.

---

## Phase 2 implementation — ✅ DONE

The WKWebView login flow was validated end-to-end first (live `/api/bootstrap`
→ 200 and `/api/organizations/{id}/usage` → 200 with real utilization).
Multi-org note: one membership returned **403**; the org-resolution loop
correctly skips it and uses the org that returns 200.

1. **Module** (`auth_session.py`) — reusable:
   - File store: `save_session` / `load_session` / `delete_session` +
     `session_cookies()` + `has_session()` (file mode `0600`).
   - Captures **only** `claude.ai` cookies; never logs cookie values.
   - `present_login(on_complete)` opens the WKWebView **inside the running rumps
     event loop**; also runnable standalone (`python3.11 auth_session.py login`).
2. **Integrated** into `claude_usage_bar.py`:
   - The stored file session is the default cookie source (`get_cookies()`).
   - No credential → auto-open login once; **Account ▸ Log in to Claude…** for
     re-login; a confirmation notification fires on success.
   - Brave demoted to **opt-in** toggle (Account ▸ Use Brave cookies), off by default.
3. **Rebuilt:** `bash scripts/build_app.sh` — bundle includes WebKit, launches
   from Finder.

---

## Privacy summary

| | browser_cookie3 | WKWebView + app file |
|---|-----------------|----------------------|
| Reads real browser profile | Yes | No |
| Cookie scope | All claude.ai cookies from Brave | Only cookies from app login session |
| Network | claude.ai only | claude.ai only |
| Storage at rest | Browser's own DB | `session.json`, owner-only `0600` |
| Survives browser encryption changes | Increasingly no | Yes |

Both are **local-only** for network (data goes to claude.ai only, not to us). WKWebView is **strictly narrower** in local scope.
