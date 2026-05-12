"""Grants & funding module — Bolivia and Latin America eligible opportunities.

Sources:
    Tier 1 (direct scrape): FundsForNGOs LATAM, DevelopmentAid, IAF, Tinker,
        McKnight, CAF, IFAD, US Embassy Bolivia, EU Delegation, GIZ, Swiss/COSUDE,
        Ford Foundation, Green Climate Fund, UNDP
    Tier 2 (Google Search via Apify): US govt (Grants.gov, SAM.gov, USAID, NED),
        multilateral (IDB Lab, FONPLATA), bilateral cooperation
"""

import sys
import os
from urllib.parse import urljoin

from bs4 import BeautifulSoup

_pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _pkg_dir not in sys.path:
    sys.path.insert(0, _pkg_dir)

from scoring import matches_keywords, MANQA_CONEXION_KEYWORDS, opp
from sources._helpers import fetch
from sources.google_search import google_search_apify


# ---------------------------------------------------------------------------
# Country / relevance filter
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

OTHER_LATAM_COUNTRIES = [
    "haiti", "haití", "colombia", "ecuador", "brazil", "brasil",
    "chile", "argentina", "paraguay", "uruguay", "mexico", "méxico",
    "peru", "perú", "guatemala", "honduras", "el salvador",
    "nicaragua", "costa rica", "panama", "panamá",
    "dominican republic", "república dominicana", "jamaica",
    "trinidad", "guyana", "suriname", "belize", "cuba",
    "venezuela", "caribbean", "caribe",
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

    # Reject junk titles
    if any(junk in title_lower for junk in JUNK_GRANT_TITLES):
        return False

    # If it mentions Bolivia explicitly, always keep
    if "bolivia" in text:
        return True

    # If it's region-wide / global / open, keep
    if any(kw in text for kw in BOLIVIA_OR_OPEN):
        # But only if it's NOT pinned to a single other country
        other_hits = [c for c in OTHER_LATAM_COUNTRIES if c in text]
        if len(other_hits) <= 1 and any(
            kw in text for kw in [
                "latin america", "latinoamérica", "south america",
                "sudamérica", "andean", "americas", "global",
                "worldwide", "international", "regional",
                "all countries", "eligible countries",
                "developing countries", "región andina",
            ]
        ):
            return True
        # Single other-country mention without a broad signal = not for us
        if other_hits and not any(
            kw in text for kw in [
                "latin america", "latinoamérica", "south america",
                "sudamérica", "andean", "americas", "global",
                "worldwide", "international", "regional",
            ]
        ):
            return False
        return True

    # If it mentions a non-LATAM country, reject
    if any(c in text for c in NON_LATAM_COUNTRIES):
        return False

    # If it mentions another LATAM country without Bolivia or broad signals, reject
    if any(c in text for c in OTHER_LATAM_COUNTRIES):
        return False

    # No geographic signal at all — require at least one Bolivia/open indicator
    # to avoid letting through random grants from unknown countries
    return False


def _grant_opp(title, url, source, snippet="", keywords=None, deadline=None):
    """Build a grant opportunity, applying relevance filter."""
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
            kw = matches_keywords(f"{title} {snippet}", MANQA_CONEXION_KEYWORDS)
        if not kw:
            kw = ["grant"]
        item = _grant_opp(title, href, source_name, snippet=snippet, keywords=kw)
        if item:
            results.append(item)
    return results


# ---------------------------------------------------------------------------
# Tier 1: Direct scrape sources
# ---------------------------------------------------------------------------

def _scrape_fundsforngos():
    """FundsForNGOs — LATAM category only."""
    results = []
    r = fetch("https://www2.fundsforngos.org/category/latin-america-and-the-caribbean/")
    if not r:
        return results
    soup = BeautifulSoup(r.text, "html.parser")
    for article in soup.select("article, .post"):
        a_tag = article.select_one("h2 a, h3 a, .entry-title a")
        if not a_tag:
            continue
        title = a_tag.get_text(strip=True)
        href = urljoin("https://www2.fundsforngos.org", a_tag.get("href", ""))
        if not title or len(title) <= 15:
            continue
        excerpt = article.select_one(".entry-summary, .excerpt, p")
        snippet = excerpt.get_text(strip=True)[:300] if excerpt else ""
        kw = matches_keywords(f"{title} {snippet}") or ["funding"]
        item = _grant_opp(title, href, "FundsForNGOs", snippet=snippet, keywords=kw)
        if item:
            results.append(item)
    return results


def _scrape_developmentaid():
    """DevelopmentAid — Bolivia grants."""
    return _scrape_listing_page(
        "https://www.developmentaid.org/grants-in-bolivia",
        "DevelopmentAid",
        "a.grant-title, .grant-item a, h3 a, h4 a, .card a",
        parent_selector="div",
    )


def _scrape_iaf():
    """Inter-American Foundation — LATAM grassroots grants."""
    return _scrape_listing_page(
        "https://www.iaf.gov/grants/",
        "IAF",
        "h2 a, h3 a, .card a, article a",
        parent_selector="article",
    )


def _scrape_tinker():
    """Tinker Foundation — LATAM-focused."""
    return _scrape_listing_page(
        "https://www.tinker.org/grants",
        "Tinker Foundation",
        "h2 a, h3 a, .field a, article a",
        parent_selector="article",
    )


def _scrape_mcknight():
    """McKnight Foundation — agriculture, food systems."""
    return _scrape_listing_page(
        "https://www.mcknight.org/grants/",
        "McKnight Foundation",
        "h2 a, h3 a, .card a, article a",
        parent_selector="article",
    )


def _scrape_caf():
    """CAF — Banco de Desarrollo de América Latina calls."""
    results = []
    urls = [
        "https://www.caf.com/en/currently/calls/",
        "https://www.caf.com/es/actualidad/convocatorias/",
    ]
    for url in urls:
        results.extend(_scrape_listing_page(
            url, "CAF",
            "h2 a, h3 a, .card a, article a, .convocatoria a",
            parent_selector="article",
        ))
    return results


def _scrape_ifad():
    """IFAD/FIDA — agricultural development calls."""
    return _scrape_listing_page(
        "https://www.ifad.org/en/calls-for-proposals",
        "IFAD/FIDA",
        "h2 a, h3 a, .card a, article a",
        parent_selector="article",
    )


def _scrape_us_embassy():
    """US Embassy Bolivia — grants and programs."""
    results = []
    urls = [
        "https://bo.usembassy.gov/education-culture/grant-opportunities/",
        "https://bo.usembassy.gov/business/getting-started/",
    ]
    for url in urls:
        results.extend(_scrape_listing_page(
            url, "US Embassy Bolivia",
            "h2 a, h3 a, .entry-title a, article a",
            parent_selector="article",
        ))
    return results


def _scrape_eu_grants():
    """EU grants portal — calls open to Latin America."""
    results = []
    # DG INTPA (international partnerships) calls
    for url in [
        "https://webgate.ec.europa.eu/online-services/#/latam",
        "https://international-partnerships.ec.europa.eu/funding-and-technical-assistance/funding-opportunities_en",
    ]:
        results.extend(_scrape_listing_page(
            url, "EU Grants Portal",
            "h2 a, h3 a, .card a, article a, .ecl-link",
            parent_selector="article",
        ))
    return results


def _scrape_giz():
    """GIZ Bolivia — German cooperation."""
    return _scrape_listing_page(
        "https://www.giz.de/en/worldwide/382.html",
        "GIZ Bolivia",
        "h2 a, h3 a, .teaser a, article a",
        parent_selector="article",
    )


def _scrape_cosude():
    """Swiss Cooperation / COSUDE — Bolivia."""
    return _scrape_listing_page(
        "https://www.eda.admin.ch/countries/bolivia/en/home/international-cooperation.html",
        "Swiss/COSUDE",
        "h2 a, h3 a, article a, .teaser a",
        parent_selector="article",
    )


def _scrape_ford():
    """Ford Foundation — social justice, LATAM."""
    return _scrape_listing_page(
        "https://www.fordfoundation.org/grants/",
        "Ford Foundation",
        "h2 a, h3 a, .card a, article a",
        parent_selector="article",
    )


def _scrape_gcf():
    """Green Climate Fund — Bolivia eligible."""
    return _scrape_listing_page(
        "https://www.greenclimate.fund/projects/rfps",
        "Green Climate Fund",
        "h2 a, h3 a, .card a, article a, table a",
        parent_selector="tr",
    )


# ---------------------------------------------------------------------------
# Tier 1b: New bilateral & multilateral direct scrapers
# ---------------------------------------------------------------------------

def _scrape_jica():
    """JICA — Japan cooperation, Bolivia projects."""
    results = []
    for url in [
        "https://www.jica.go.jp/english/our_work/types_of_assistance/tech/projects/index.html",
        "https://www.jica.go.jp/Resource/bolivia/english/index.html",
    ]:
        results.extend(_scrape_listing_page(
            url, "JICA Bolivia",
            "h2 a, h3 a, .card a, article a, li a",
            parent_selector="li",
        ))
    return results


def _scrape_unicef_innovation():
    """UNICEF Innovation Fund — open-source tech for developing countries."""
    return _scrape_listing_page(
        "https://www.unicefinnovationfund.org/apply",
        "UNICEF Innovation Fund",
        "h2 a, h3 a, .card a, article a, a.btn",
        parent_selector="article",
    )


def _scrape_fao():
    """FAO — agriculture, food systems, data calls."""
    return _scrape_listing_page(
        "https://www.fao.org/partnerships/calls-for-proposals/en/",
        "FAO",
        "h2 a, h3 a, .card a, article a, li a",
        parent_selector="article",
    )


def _scrape_paho():
    """PAHO/WHO — health systems, data, procurement."""
    return _scrape_listing_page(
        "https://www.paho.org/en/procurement",
        "PAHO/WHO",
        "h2 a, h3 a, .card a, article a, td a",
        parent_selector="tr",
    )


def _scrape_japan_embassy():
    """Japan Embassy Bolivia — Kusanone small grants."""
    return _scrape_listing_page(
        "https://www.bo.emb-japan.go.jp/itpr_es/cooperacion.html",
        "Japan Embassy Bolivia",
        "h2 a, h3 a, article a, li a",
        parent_selector="article",
    )


def _scrape_canada_embassy():
    """Canada Embassy Bolivia — CFLI fund."""
    return _scrape_listing_page(
        "https://www.international.gc.ca/country-pays/bolivia-bolivie/relations.aspx?lang=eng",
        "Canada Embassy Bolivia",
        "h2 a, h3 a, article a, li a",
        parent_selector="article",
    )


def _scrape_oas():
    """OAS/OEA — fellowships, project funding."""
    results = []
    for url in [
        "https://www.oas.org/en/scholarships/",
        "https://www.oas.org/en/sedi/dhdee/default.asp",
    ]:
        results.extend(_scrape_listing_page(
            url, "OAS/OEA",
            "h2 a, h3 a, .card a, article a, li a, td a",
            parent_selector="article",
        ))
    return results


def _scrape_reliefweb():
    """ReliefWeb — humanitarian/development funding Bolivia."""
    return _scrape_listing_page(
        "https://reliefweb.int/updates?advanced-search=(PC159)_(TY4610)",
        "ReliefWeb",
        "h2 a, h3 a, article a, .rw-river-article__title a",
        parent_selector="article",
    )


def _scrape_undp():
    """UNDP procurement notices — Bolivia."""
    results = []
    r = fetch("https://procurement-notices.undp.org/view_notice.cfm?notice_type=request_for_proposal&country=BOL")
    if not r:
        return results
    soup = BeautifulSoup(r.text, "html.parser")
    for row in soup.select("table tr"):
        link = row.select_one("a[href*='view_notice']")
        if not link:
            continue
        title = link.get_text(strip=True)
        href = urljoin("https://procurement-notices.undp.org/", link.get("href", ""))
        if not title or len(title) <= 15:
            continue
        cells = row.select("td")
        snippet = " | ".join(c.get_text(strip=True) for c in cells[:4])
        # Try to get deadline from table cells
        deadline = None
        for c in cells:
            text = c.get_text(strip=True)
            if "/" in text and len(text) <= 12:
                deadline = text
        kw = matches_keywords(f"{title} {snippet}") or ["UNDP"]
        item = _grant_opp(title, href, "UNDP Bolivia", snippet=snippet,
                          keywords=kw, deadline=deadline)
        if item:
            results.append(item)
    return results


# ---------------------------------------------------------------------------
# Tier 2: Google Search via Apify
# ---------------------------------------------------------------------------

def _scrape_grants_google():
    """Broader grant discovery via Google Search — Bolivia & LATAM focused."""
    return google_search_apify([
        # Bolivia-specific
        "Bolivia grant call for proposals 2026",
        "Bolivia convocatoria becas fondos cooperación 2026",
        "USAID Bolivia funding opportunity 2026",
        # LATAM regional
        "Latin America grant funding opportunity 2026",
        "convocatoria cooperación latinoamérica 2026",
        "IDB Lab innovation grant Latin America 2026",
        # Multilateral
        "FONPLATA convocatoria 2026",
        "NED National Endowment Democracy Bolivia grant",
        # US Government
        "site:grants.gov Latin America Bolivia",
        # Foundations — existing
        "Rockefeller Foundation Latin America grant 2026",
        "Inter-American Foundation grant 2026",
        "Open Society Foundations Latin America grant",
        # Bilateral cooperation — new
        "JICA Bolivia cooperation project 2026",
        "KOICA Latin America Bolivia grant 2026",
        "IDRC Canada Latin America grant research 2026",
        "SIDA Sweden Bolivia grant cooperation 2026",
        "Netherlands RVO Latin America grant 2026",
        # UN agencies — new
        "UNICEF Innovation Fund call for proposals 2026",
        "FAO call for proposals Latin America 2026",
        "PAHO WHO Bolivia health data grant 2026",
        "UNESCO Latin America technology education grant 2026",
        "ILO social protection Bolivia grant 2026",
        # Tech/innovation funders — new
        "Google.org Latin America grant technology 2026",
        "Microsoft AI for Good Latin America grant 2026",
        "GSMA Innovation Fund mobile developing countries 2026",
        "Mozilla Foundation Latin America open source grant",
        "Luminate digital rights Latin America grant 2026",
        "LACNIC innovation grant Latin America 2026",
        "Ashoka fellowship Latin America 2026",
        "Endeavor Latin America social enterprise",
        # EU programs — new
        "Euroclima Latin America climate technology grant 2026",
        "EU-LAC Digital Alliance call for proposals 2026",
        "Horizon Europe Latin America international cooperation 2026",
        "DG INTPA Latin America call for proposals 2026",
        # Bolivia-local — new
        "Embajada Japón Bolivia proyecto cooperación Kusanone 2026",
        "Embajada Canadá Bolivia CFLI fondo 2026",
        "PROCOSI Bolivia salud convocatoria 2026",
        "Fundación PUMA Bolivia medio ambiente convocatoria",
        # Broader profile dimensions (non-tech)
        # Academic / seminary / theology
        "Bolivia scholarship fellowship 2026",
        "seminary theology scholarship Latin America 2026",
        "beca teología estudios bíblicos latinoamérica 2026",
        "Christian education grant Latin America 2026",
        # Entrepreneurship / fintech / Chaskiy
        "Bolivia small business entrepreneur grant 2026",
        "Latin America fintech inclusion innovation fund 2026",
        "Bolivia emprendimiento fondo semilla startup 2026",
        "mobile payments financial inclusion grant developing countries 2026",
        # Publishing / cultural / Editorial Vildoso
        "Bolivia cultural arts publishing grant 2026",
        "Latin America book publishing fund grant 2026",
        "Bolivia fondo cultural editorial publicación 2026",
        # General Bolivia development
        "Bolivia education development grant 2026",
        "Bolivia social development cooperation fund 2026",
        # Manq'a — food security, gastronomy, youth
        "Bolivia food security grant funding 2026",
        "seguridad alimentaria Bolivia convocatoria fondo 2026",
        "youth culinary training grant Latin America 2026",
        "social gastronomy grant developing countries 2026",
        "urban agriculture nutrition Bolivia grant 2026",
        "IFAD FIDA food systems Latin America call 2026",
        "FAO food sovereignty Bolivia grant 2026",
        # Conexion — youth development, digital inclusion, social empowerment
        "youth development empowerment Bolivia grant 2026",
        "digital inclusion rural Bolivia grant 2026",
        "social enterprise Bolivia grant funding 2026",
        "emprendimiento social Bolivia fondo cooperación 2026",
        "gender equality youth Bolivia grant 2026",
        "agriculture development Bolivia small farmers grant 2026",
        "bioeconomy Latin America grant 2026",
        "climate resilience agriculture Bolivia grant 2026",
    ], "Grants (via Google)", opp_type="grant")


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# New direct scrapers: IDRC, CGIAR, FONPLATA, SEGIB
# ---------------------------------------------------------------------------

def _scrape_idrc():
    """IDRC Canada — research grants, food systems, LATAM."""
    return _scrape_listing_page(
        "https://idrc.ca/en/funding",
        "IDRC Canada",
        "h2 a, h3 a, .card a, article a, li a",
        parent_selector="article",
    )


def _scrape_cgiar():
    """CGIAR — agricultural research funding calls."""
    return _scrape_listing_page(
        "https://www.cgiar.org/funders/funding-calls/",
        "CGIAR",
        "h2 a, h3 a, .card a, article a, li a",
        parent_selector="article",
    )


def _scrape_fonplata():
    """FONPLATA — Plata Basin development bank."""
    results = []
    for url in [
        "https://www.fonplata.org/en/calls/",
        "https://www.fonplata.org/es/convocatorias/",
    ]:
        results.extend(_scrape_listing_page(
            url, "FONPLATA",
            "h2 a, h3 a, .card a, article a, li a",
            parent_selector="article",
        ))
    return results


# All individual scrapers
# NOTE: Sources returning 404/403/SSL errors removed 2026-05-12.
# Their orgs are still covered by the ~55 Google Search queries below.
# Removed: DevelopmentAid(403), Tinker(404), GCF(404), CAF(SSL),
#   IFAD(404), UNICEF Innovation(403), FAO(404), PAHO(404),
#   US Embassy(404), EU Grants(503/404), COSUDE(403),
#   Japan Embassy(403), FONPLATA(404)
_GRANT_SCRAPERS = [
    # Aggregators (working)
    ("FundsForNGOs LATAM", _scrape_fundsforngos),
    ("ReliefWeb", _scrape_reliefweb),
    # Foundations (working)
    ("IAF", _scrape_iaf),
    ("McKnight Foundation", _scrape_mcknight),
    ("Ford Foundation", _scrape_ford),
    # Multilateral (working)
    ("UNDP Bolivia", _scrape_undp),
    ("OAS/OEA", _scrape_oas),
    # Bilateral (working)
    ("GIZ Bolivia", _scrape_giz),
    ("JICA Bolivia", _scrape_jica),
    ("Canada Embassy Bolivia", _scrape_canada_embassy),
    # Research & regional (working)
    ("IDRC Canada", _scrape_idrc),
    ("CGIAR", _scrape_cgiar),
    # Google Search — covers all removed sources + more
    ("Grants Google Search", _scrape_grants_google),
]


def scrape_all_grants():
    """Run all grant sources, applying country filter to every result."""
    all_results = []
    for label, scraper_fn in _GRANT_SCRAPERS:
        try:
            hits = scraper_fn()
            all_results.extend(hits)
            if hits:
                print(f"    [{label}] -> {len(hits)} grants", file=sys.stderr)
        except Exception as e:
            print(f"    !! {label} failed: {e}", file=sys.stderr)
    return all_results
