"""Shared HTTP helpers for direct scraping sources."""

import re
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

# Crawl4AI singleton — lazy-loaded, reused across calls
_crawler = None
_crawl4ai_available = None


def fetch(url, params=None):
    """GET with error handling. Returns Response or None."""
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r
    except Exception as e:
        print(f"  warning  {url[:60]}... -- {e}", file=sys.stderr)
        return None


def fetch_rendered(url):
    """Fetch a JS-rendered page via Crawl4AI headless browser.

    Returns list of (title, href, snippet) tuples extracted from the
    rendered markdown.  Falls back to empty list if Crawl4AI is unavailable.
    """
    global _crawl4ai_available
    if _crawl4ai_available is False:
        return []

    try:
        import asyncio
        from crawl4ai import AsyncWebCrawler

        async def _crawl():
            async with AsyncWebCrawler() as crawler:
                return await crawler.arun(url=url)

        result = asyncio.run(_crawl())
        _crawl4ai_available = True

        if not result or not result.markdown:
            return []

        # Extract links from markdown: [title](url)
        links = re.findall(r'\[([^\]]{10,})\]\((https?://[^\)]+)\)', result.markdown)
        items = []
        seen = set()
        for title, href in links:
            title = title.strip()
            if href in seen or len(title) < 15:
                continue
            seen.add(href)
            # Get surrounding text as snippet (line containing the link)
            snippet = ""
            for line in result.markdown.split("\n"):
                if href in line and title in line:
                    snippet = re.sub(r'\[([^\]]*)\]\([^\)]*\)', r'\1', line).strip()[:300]
                    break
            items.append((title, href, snippet))
        return items

    except ImportError:
        _crawl4ai_available = False
        print("  [crawl4ai] not installed, skipping JS rendering", file=sys.stderr)
        return []
    except Exception as e:
        print(f"  [crawl4ai] error on {url[:60]}: {e}", file=sys.stderr)
        return []
