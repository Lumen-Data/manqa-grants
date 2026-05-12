"""Google Search via Serper.dev with Google News RSS fallback.

Serper.dev: 2,500 free searches/month, ~2s per query, REST API.
Replaces Apify google-search-scraper (was 15s/query, burned credits).
"""

import os
import re
import sys
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests

_pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from scoring import matches_keywords, MANQA_CONEXION_KEYWORDS, opp
from sources._helpers import fetch

_no_search = False


def set_no_apify(flag):
    """Disable Google Search for this run (kept for CLI compat)."""
    global _no_search
    _no_search = flag


# ---------------------------------------------------------------------------
# Serper.dev API
# ---------------------------------------------------------------------------

def _get_serper_key():
    """Load SERPER_API_KEY from env or .env file."""
    key = os.environ.get("SERPER_API_KEY", "")
    if key:
        return key
    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("SERPER_API_KEY=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip()
    return ""


def _serper_search(queries):
    """Run queries through Serper.dev. Returns list of {title, link, snippet} dicts."""
    key = _get_serper_key()
    if not key:
        return None, "No SERPER_API_KEY configured"

    all_results = []
    for query in queries:
        try:
            r = requests.post(
                "https://google.serper.dev/search",
                json={"q": query, "gl": "bo", "hl": "es", "num": 10},
                headers={"X-API-KEY": key},
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                for item in data.get("organic", []):
                    all_results.append({
                        "title": item.get("title", ""),
                        "link": item.get("link", ""),
                        "snippet": item.get("snippet", ""),
                    })
            elif r.status_code == 429:
                print(f"  [serper] Rate limited, stopping queries", file=sys.stderr)
                break
            else:
                print(f"  [serper] HTTP {r.status_code} for: {query[:50]}", file=sys.stderr)
        except Exception as e:
            print(f"  [serper] Error: {e}", file=sys.stderr)

    if all_results:
        return all_results, None
    return None, "No results from Serper"


# ---------------------------------------------------------------------------
# Stale result detection
# ---------------------------------------------------------------------------

_STALE_SIGNALS = re.compile(
    r'\b(inactive|closed|expired|archived|cancelled|canceled)\b', re.IGNORECASE
)

_STALE_DOMAINS = ['sam.gov/workspace', 'sam.gov/opp']


def _is_stale_result(title, snippet, url):
    """Detect stale Google results by signals or known domains."""
    text = f"{title} {snippet}"
    if _STALE_SIGNALS.search(text):
        return True
    if any(domain in url for domain in _STALE_DOMAINS):
        return True
    return False


# ---------------------------------------------------------------------------
# Google News RSS fallback
# ---------------------------------------------------------------------------

def _scrape_google_news_rss(queries, source_label):
    """Fallback: Google News RSS scraper."""
    results = []
    for query in queries:
        rss_url = (
            "https://news.google.com/rss/search"
            f"?q={quote_plus(query)}&hl=es-419&gl=BO&ceid=BO:es-419"
        )
        r = fetch(rss_url)
        if not r:
            continue
        try:
            root = ET.fromstring(r.text)
        except ET.ParseError:
            continue
        for item in root.findall(".//item"):
            title_el = item.find("title")
            link_el = item.find("link")
            if title_el is None or link_el is None:
                continue
            title = (title_el.text or "").strip()
            href = (link_el.text or "").strip()
            if not title or len(title) <= 15:
                continue
            kw = matches_keywords(title)
            if not kw:
                kw = matches_keywords(title, MANQA_CONEXION_KEYWORDS)
            if kw:
                results.append(opp(title, href, source_label,
                                   keywords=kw, opp_type="grant"))
    return results


# ---------------------------------------------------------------------------
# Main Google Search function
# ---------------------------------------------------------------------------

def google_search_apify(queries, source_label, opp_type="grant"):
    """Run Google Search via Serper.dev, falling back to Google News RSS.

    Function name kept as google_search_apify for backward compatibility
    with grant_sources.py and food_sources.py imports.
    """
    if _no_search:
        print(f"  Search disabled (--no-apify), using RSS...", file=sys.stderr)
        return _scrape_google_news_rss(queries, source_label)

    items, err = _serper_search(queries)

    if items:
        results = []
        seen = set()
        for item in items:
            title = item.get("title", "")
            url = item.get("link", "")
            snippet = item.get("snippet", "")
            if not title or not url or url in seen:
                continue
            seen.add(url)
            if _is_stale_result(title, snippet, url):
                continue
            kw = matches_keywords(f"{title} {snippet}")
            if not kw:
                kw = matches_keywords(f"{title} {snippet}", MANQA_CONEXION_KEYWORDS)
            if kw:
                results.append(opp(title, url, source_label,
                                   snippet=snippet, keywords=kw, opp_type=opp_type))
        return results

    # Fallback to Google News RSS
    print(f"  Serper fallback ({err}), using Google News RSS...", file=sys.stderr)
    return _scrape_google_news_rss(queries, source_label)
