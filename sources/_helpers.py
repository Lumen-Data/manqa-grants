"""Shared HTTP helpers for direct scraping sources."""

import sys

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "es-BO,es;q=0.9,en;q=0.8",
}

TIMEOUT = 20


def fetch(url, params=None):
    """GET with error handling. Returns Response or None."""
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  warning  {url[:60]}... -- {e}", file=sys.stderr)
        return None
