"""
Quick test — run this directly to see what the scraper finds.
Usage: python debug_scraper.py
"""

import asyncio
import getpass
from scraper import fetch_traffic, LoginError


async def main():
    print("=== Nimbaha Scraper Debug ===\n")
    username = input("Username: ").strip()
    password = getpass.getpass("Password: ").strip()

    print("\nLogging in…")
    try:
        info = await fetch_traffic(username, password)
    except LoginError as e:
        print(f"\n[LOGIN ERROR] {e}")
        return
    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        return

    print(f"\nService  : {info.service_number}")
    print(f"Remaining: {info.remaining}")
    print(f"Total    : {info.total}")
    print(f"Used     : {info.used}")
    print(f"Expiry   : {info.expiry}")
    print(f"\n--- Raw dashboard text (first 1000 chars) ---")
    print(info.raw_text[:1000])


if __name__ == "__main__":
    asyncio.run(main())
