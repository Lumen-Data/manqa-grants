"""Food security, social enterprise, and youth development grant sources.

NEW sources not covered by the existing grant module, focused on
Manq'a's mission areas: food, gastronomy, youth, social enterprise.

Tier 1 (direct scrape): GlobalGiving, WFP Innovation, GAIN, Hivos,
    Slow Food, Feed the Future, CCRP McKnight, Ashoka, Skoll
Tier 2 (Google Search): ~30 food/social-specific queries
"""

import sys
import os
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from scoring import matches_keywords, MANQA_CONEXION_KEYWORDS, MANQA_FOOD_KEYWORDS, opp
from sources._helpers import fetch, fetch_rendered
from sources.google_search import google_search_apify


# ---------------------------------------------------------------------------
# Country / relevance filter (same as grant_sources)
# ---------------------------------------------------------------------------

NON_LATAM_COUNTRIES = [
    "australia", "bangladesh", "pakistan", "philippines",
    "united kingdom", "new zealand", "nigeria",
    "india", "kenya", "south africa", "uganda", "tanzania",
    "cambodia", "myanmar", "nepal", "sri lanka", "vietnam",
    "thailand", "indonesia", "malaysia", "singapore",
    "ireland", "scotland", "wales",
]

BOLIVIA_OR_OPEN = [
    "bolivia", "latin america", "latinoamérica", "south america",
    "sudamérica", "andean", "americas", "global", "worldwide",
    "developing countries", "international", "all countries",
    "eligible countries", "low-income", "middle-income",
    "central america", "región andina",
    "países en desarrollo", "regional",
]

JUNK_GRANT_TITLES = [
    "search for grants in", "search results", "login", "sign up",
    "create account", "register", "privacy policy", "terms of",
    "cookie", "subscribe", "newsletter",
]


def _is_relevant_grant(title, snippet="", url=""):
    """Reject grants not open to Bolivia."""
    text = f"{title} {snippet} {url}".lower()
    title_lower = title.lower()

    if any(junk in title_lower for junk in JUNK_GRANT_TITLES):
        return False
    if "bolivia" in text:
        return True
    if any(kw in text for kw in BOLIVIA_OR_OPEN):
        return True
    if any(c in text for c in NON_LATAM_COUNTRIES):
        return False

    # For food-specific sources, be more permissive — many grants are
    # global/regional and don't mention specific countries
    food_kws = MANQA_FOOD_KEYWORDS + MANQA_CONEXION_KEYWORDS
    if any(kw.lower() in text for kw in food_kws):
        return True

    return False


def _food_opp(title, url, source, snippet="", keywords=None, deadline=None):
    """Build a food/social grant opportunity, applying relevance filter."""
    if not _is_relevant_grant(title, snippet, url=url):
        return None
    return opp(title, url, source, snippet=snippet,
               keywords=keywords, opp_type="grant", deadline=deadline)


def _scrape_listing_page(page_url, source_name, link_selector, parent_selector=None):
    """Generic scraper for simple grant listing pages."""
    results = []
    r = fetch(page_url)
    if not r:
        return results
    soup = BeautifulSoup(r.text, "html.parser")
    seen = set()
    for link in soup.select(link_selector):
        title = link.get_text(strip=True)
        href = urljoin(page_url, link.get("href", ""))
        if not title or len(title) <= 15 or href in seen:
            continue
        seen.add(href)
        snippet = ""
        if parent_selector:
            parent = link.find_parent(parent_selector)
            if parent:
                snippet = parent.get_text(strip=True)[:300]
        kw = matches_keywords(f"{title} {snippet}")
        if not kw:
            kw = matches_keywords(f"{title} {snippet}", MANQA_FOOD_KEYWORDS)
        if not kw:
            kw = matches_keywords(f"{title} {snippet}", MANQA_CONEXION_KEYWORDS)
        if not kw:
            kw = ["grant"]
        item = _food_opp(title, href, source_name, snippet=snippet, keywords=kw)
        if item:
            results.append(item)
    return results


# ---------------------------------------------------------------------------
# JS-rendered scraper (Crawl4AI)
# ---------------------------------------------------------------------------

def _scrape_js_page(urls, source_name):
    """Scrape JS-rendered pages via Crawl4AI headless browser.

    Falls back to BeautifulSoup if Crawl4AI is unavailable.
    """
    if isinstance(urls, str):
        urls = [urls]

    results = []
    for url in urls:
        # Try Crawl4AI first (handles JS rendering)
        items = fetch_rendered(url)
        if items:
            for title, href, snippet in items:
                kw = matches_keywords(f"{title} {snippet}")
                if not kw:
                    kw = matches_keywords(f"{title} {snippet}", MANQA_FOOD_KEYWORDS)
                if not kw:
                    kw = matches_keywords(f"{title} {snippet}", MANQA_CONEXION_KEYWORDS)
                if not kw:
                    continue  # Skip irrelevant links from rendered page
                item = _food_opp(title, href, source_name, snippet=snippet, keywords=kw)
                if item:
                    results.append(item)
        else:
            # Fallback to BeautifulSoup
            results.extend(_scrape_listing_page(
                url, source_name,
                "h2 a, h3 a, .card a, article a, a.btn, li a",
                parent_selector="article",
            ))
    return results


# ---------------------------------------------------------------------------
# Tier 1: Direct scrape sources (JS-rendered via Crawl4AI)
# ---------------------------------------------------------------------------

def _scrape_globalgiving():
    """GlobalGiving — Bolivia projects via public API."""
    import requests as _req
    API_KEY = os.environ.get("GLOBALGIVING_API_KEY", "7e121bcd-f5c4-4ec3-aa70-4bde2231c136")
    results = []

    # Search for Bolivia food/social projects
    for query in ["Bolivia food", "Bolivia youth", "Bolivia education", "Bolivia agriculture"]:
        try:
            r = _req.get(
                "https://api.globalgiving.org/api/public/services/search/projects",
                params={"api_key": API_KEY, "q": query},
                headers={"Accept": "application/json"},
                timeout=20,
            )
            if r.status_code != 200:
                continue
            projects = (r.json()
                        .get("search", {})
                        .get("response", {})
                        .get("projects", {})
                        .get("project", []))
            for p in projects:
                if not p.get("active"):
                    continue
                title = p.get("title", "")
                href = p.get("projectLink", "")
                summary = p.get("summary", "")[:300]
                themes = [t.get("name", "") for t in p.get("themes", {}).get("theme", [])]
                kw = matches_keywords(f"{title} {summary} {' '.join(themes)}")
                if not kw:
                    kw = matches_keywords(f"{title} {summary}", MANQA_FOOD_KEYWORDS)
                if not kw:
                    kw = themes[:3] or ["grant"]
                item = _food_opp(title, href, "GlobalGiving", snippet=summary, keywords=kw)
                if item:
                    results.append(item)
        except Exception as e:
            print(f"    !! GlobalGiving API error: {e}", file=sys.stderr)
    # Dedup by URL
    seen = set()
    return [r for r in results if r["url"] not in seen and not seen.add(r["url"])]


def _scrape_wfp_innovation():
    """WFP Innovation Accelerator — food systems."""
    return _scrape_js_page(
        "https://innovation.wfp.org/apply",
        "WFP Innovation",
    )


def _scrape_gain():
    """GAIN — Global Alliance for Improved Nutrition."""
    return _scrape_js_page(
        "https://www.gainhealth.org/opportunities",
        "GAIN Nutrition",
    )


def _scrape_hivos():
    """Hivos — food systems, sustainable diets."""
    return _scrape_js_page(
        ["https://hivos.org/programs/food-systems/",
         "https://hivos.org/tenders-calls/"],
        "Hivos",
    )


def _scrape_slow_food():
    """Slow Food Foundation — food biodiversity, local food."""
    return _scrape_js_page(
        "https://www.slowfood.com/what-we-do/",
        "Slow Food Foundation",
    )


def _scrape_feed_the_future():
    """Feed the Future / USAID — food security."""
    return _scrape_js_page(
        "https://www.feedthefuture.gov/opportunities/",
        "Feed the Future/USAID",
    )


def _scrape_ccrp():
    """CCRP McKnight — Collaborative Crop Research Program."""
    return _scrape_js_page(
        "https://www.ccrp.org/grants/",
        "CCRP McKnight",
    )


def _scrape_ashoka():
    """Ashoka — social enterprise fellowship."""
    return _scrape_js_page(
        "https://www.ashoka.org/en-us/program/ashoka-fellowship",
        "Ashoka Fellowship",
    )


def _scrape_skoll():
    """Skoll Foundation — social enterprise awards."""
    return _scrape_js_page(
        "https://skoll.org/about/skoll-awards/",
        "Skoll Foundation",
    )


# ---------------------------------------------------------------------------
# Tier 2: Google Search — food/social-specific queries
# ---------------------------------------------------------------------------

def _scrape_food_google():
    """Food security and social enterprise grants via Google Search."""
    return google_search_apify([
        # Food security / nutrition
        "food security grant Latin America Bolivia 2026",
        "seguridad alimentaria grant convocatoria Bolivia 2026",
        "nutrition program grant developing countries 2026",
        "social gastronomy grant funding 2026",
        "school feeding program grant Latin America 2026",
        "GAIN nutrition grant call for proposals 2026",
        "WFP innovation accelerator call 2026",
        "Slow Food Foundation grant 2026",
        "food systems transformation grant 2026",
        "food sovereignty grant Latin America 2026",
        # Social enterprise / youth
        "social enterprise grant Latin America 2026",
        "Ashoka fellowship Latin America 2026",
        "Skoll Foundation social enterprise award 2026",
        "youth culinary training grant 2026",
        "youth empowerment food grant developing countries 2026",
        "vocational training youth grant Bolivia 2026",
        # Agriculture / climate
        "agroecology grant Latin America 2026",
        "urban agriculture grant developing countries 2026",
        "climate resilience food systems grant 2026",
        "smallholder farmer grant Bolivia Latin America 2026",
        # Manq'a-adjacent / founder network
        "Melting Pot Foundation grant 2026",
        "Claus Meyer social gastronomy 2026",
        "ICCO cooperation food Latin America grant 2026",
        "Hivos food systems grant Latin America 2026",
        # Food industry foundations
        "Cargill Foundation food security grant 2026",
        "Nestle Creating Shared Value grant 2026",
        "Barilla Foundation food nutrition grant 2026",
        "IFPRI research grant food policy 2026",
        "Global FoodBanking Network grant 2026",
        # Bolivia local food/social
        "Bolivia seguridad alimentaria fondo convocatoria 2026",
        "Bolivia gastronomía social emprendimiento fondo 2026",
        "Bolivia capacitación juvenil cocina convocatoria 2026",
    ], "Food Grants (via Google)", opp_type="grant")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

_FOOD_SCRAPERS = [
    ("GlobalGiving Bolivia", _scrape_globalgiving),
    ("WFP Innovation", _scrape_wfp_innovation),
    ("GAIN Nutrition", _scrape_gain),
    ("Hivos", _scrape_hivos),
    ("Slow Food Foundation", _scrape_slow_food),
    ("Feed the Future/USAID", _scrape_feed_the_future),
    ("CCRP McKnight", _scrape_ccrp),
    ("Ashoka Fellowship", _scrape_ashoka),
    ("Skoll Foundation", _scrape_skoll),
    ("Food Google Search", _scrape_food_google),
]


def scrape_all_food_grants():
    """Run all food/social enterprise grant sources."""
    all_results = []
    for label, scraper_fn in _FOOD_SCRAPERS:
        try:
            hits = scraper_fn()
            all_results.extend(hits)
            if hits:
                print(f"    [{label}] -> {len(hits)} grants", file=sys.stderr)
        except Exception as e:
            print(f"    !! {label} failed: {e}", file=sys.stderr)
    return all_results
