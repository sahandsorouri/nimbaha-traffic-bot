#!/usr/bin/env python3.11
import browser_cookie3, json
from curl_cffi import requests

# کوکی‌های Brave + TLS fingerprint واقعی Chrome
cj      = browser_cookie3.brave(domain_name='claude.ai')
cookies = {c.name: c.value for c in cj}

r = requests.get(
    "https://claude.ai/api/usage_limit_status",
    cookies=cookies,
    impersonate="chrome131",
)
print(r.status_code)
print(json.dumps(r.json(), indent=2))
