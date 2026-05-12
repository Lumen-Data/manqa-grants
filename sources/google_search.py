"""Google Search via Apify with Google News RSS fallback.

Extracted from bolivia-opportunities/sources/apify_sources.py — only the
Google Search pipeline, no SICOES/LinkedIn/job scrapers.
"""

import re
import sys
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import os
_pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from scoring import matches_keywords, MANQA_CONEXION_KEYWORDS, opp
from sources._helpers import fetch

# Lazy-load to avoid import errors when apify-client isn't installed
_apify_available = None
_no_apify = False


def set_no_apify(flag):
    """Disable Apify for this run (used by --no-apify CLI flag)."""
    global _no_apify
    _no_apify = flag


# Only these actors use Apify; everything else falls back to RSS
_APIFY_ALLOWLIST = {
    "apify/google-search-scraper",
}


def _run_actor(actor_id, run_input, timeout_secs=300):
    """Run an Apify actor, returning (items, error). Respects --no-apify flag and allowlist."""
    if _no_apify:
        return [], "Apify disabled (--no-apify)"

    if actor_id not in _APIFY_ALLOWLIST:
        return [], f"Skipped (not in allowlist): {actor_id}"

    global _apify_available
    if _apify_available is False:
        return [], "Apify not available"

    try:
        project_root = os.path.join(os.path.dirname(__file__), "..")
        if project_root not in sys.path:
            sys.path.insert(0, os.path.abspath(project_root))

        from shared.apify import run_actor
        items, err = run_actor(actor_id, run_input, timeout_secs)
        if err and ("not installed" in err or "No APIFY_API_TOKEN" in err):
            _apify_available = False
        else:
            _apify_available = True
        return items, err
    except ImportError:
        _apify_available = False
        return [], "shared.apify module not found"


# ---------------------------------------------------------------------------
# Stale result detection
# ---------------------------------------------------------------------------

_STALE_SIGNALS = re.compile(
    r'\b(inactive|closed|expired|archived|cancelled|canceled)\b', re.IGNORECASE
)

_OLD_DATE = re.compile(r'\b(20[01][0-9]|202[0-4])\b')

_STALE_DOMAINS = ['sam.gov/workspace', 'sam.gov/opp']


def _is_stale_result(title, snippet, url):
    """Detect stale Google results by signals, old dates, or known domains."""
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
    """Run Google Search via Apify actor, falling back to Google News RSS."""
    items, err = _run_actor("apify/google-search-scraper", {
        "queries": "\n".join(queries),
        "maxPagesPerQuery": 1,
        "resultsPerPage": 10,
        "languageCode": "es",
        "countryCode": "bo",
    })

    if items:
        results = []
        seen = set()
        for page in items:
            for organic in page.get("organicResults", []):
                title = organic.get("title", "")
                url = organic.get("url", "")
                snippet = organic.get("description", "")
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
    print(f"  Apify fallback ({err}), using Google News RSS...", file=sys.stderr)
    return _scrape_google_news_rss(queries, source_label)
