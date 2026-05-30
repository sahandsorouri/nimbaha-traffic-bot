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

### Primary path (Phase 2): WKWebView + app Keychain
1. User opens an in-app login window (`https://claude.ai/login`).
2. On success, read **only** `claude.ai` cookies from `WKHTTPCookieStore`.
3. Store the session cookie in **app-scoped Keychain** (service e.g. `ClaudeUsageBar`).
4. All API calls use Keychain cookie; never read Brave unless user explicitly opts in.

### Rejected as primary (for now): ASWebAuthenticationSession
User-friendly, but **does not return Safari cookies** to the native app — only OAuth redirect parameters. Anthropic does not register third-party OAuth clients for claude.ai usage. Revisit if Anthropic adds official OAuth or a usage API.

### Optional fallbacks (explicit opt-in only)
- **Re-login** menu item (WKWebView).
- **Paste session token** for power users.
- **Import from Brave** via `browser_cookie3` behind a menu toggle.

### Drop as default
Silent `browser_cookie3` reading on every launch.

---

## Phase 2 implementation plan

1. **PoC** (`login_poc.py` or similar) — separate from main app:
   - WKWebView window → login
   - Print cookie **names** to stdout (never values)
   - Store session in Keychain; verify bootstrap + usage API
2. **Integrate** into `claude_usage_bar.py`:
   - No credential → auto-open login
   - 401 / auth failure → Re-login
   - Remove Brave as default path
3. **Rebuild:** `bash scripts/build_app.sh`

---

## Privacy summary

| | browser_cookie3 | WKWebView + Keychain |
|---|-----------------|----------------------|
| Reads real browser profile | Yes | No |
| Cookie scope | All claude.ai cookies from Brave | Only cookies from app login session |
| Network | claude.ai only | claude.ai only |
| Survives browser encryption changes | Increasingly no | Yes |

Both are **local-only** for network (data goes to claude.ai only, not to us). WKWebView is **strictly narrower** in local scope.
