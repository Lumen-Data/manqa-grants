"""Keywords, relevance scoring, and matching helpers for Manq'a Grants."""

import json
import os
import re
from datetime import date, datetime, timezone, timedelta

# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------

GRANT_KEYWORDS = [
    "beca", "fondo", "subvención", "cooperación", "financiamiento",
    "grant", "funding", "fellowship", "scholarship", "donación",
    "convocatoria de fondos", "cofinanciamiento", "fondo concursable",
    "cooperación internacional", "ayuda oficial", "seed fund",
]

MANQA_CONEXION_KEYWORDS = [
    # Food / gastronomy / nutrition
    "food security", "seguridad alimentaria", "gastronomy", "gastronomía",
    "nutrition", "nutrición", "urban agriculture", "agricultura urbana",
    "food sovereignty", "soberanía alimentaria", "culinary", "culinaria",
    "food systems", "sistemas alimentarios", "cocina", "alimentación",
    # Youth / social development
    "youth", "juventud", "jóvenes", "empleo juvenil", "youth employment",
    "social enterprise", "emprendimiento social", "social development",
    "desarrollo social", "social empowerment", "empoderamiento",
    "digital inclusion", "inclusión digital", "rural development",
    "desarrollo rural", "agriculture development", "desarrollo agrícola",
    "gender", "género", "bioeconomy", "bioeconomía",
    "climate resilience", "resiliencia climática",
    "capacitación", "formación", "training",
]

MANQA_FOOD_KEYWORDS = [
    # Deep food/social terms beyond the base list
    "social gastronomy", "gastronomía social", "cooking school",
    "escuela de cocina", "culinary school", "culinary training",
    "capacitación culinaria", "chef training", "formación de chefs",
    "local food", "alimentos locales", "food production",
    "producción alimentaria", "malnutrition", "desnutrición",
    "food bank", "banco de alimentos", "food waste",
    "desperdicio alimentario", "food value chain", "cadena de valor",
    "agroecology", "agroecología", "permaculture", "permacultura",
    "school feeding", "alimentación escolar", "food education",
    "educación alimentaria", "social restaurant", "restaurante social",
    "social enterprise", "empresa social", "youth empowerment",
    "empoderamiento juvenil", "vocational training", "formación técnica",
    "skill development", "desarrollo de habilidades",
    "sustainable food", "alimentación sostenible",
    "food sovereignty", "soberanía alimentaria",
    "indigenous food", "alimentación indígena",
    "community kitchen", "cocina comunitaria",
]

FELLOWSHIP_KEYWORDS = [
    "fellowship", "beca", "award", "premio", "competition",
    "competencia", "accelerator", "aceleradora", "incubator",
    "incubadora", "pitch", "innovation challenge",
    "convocatoria", "call for proposals", "apply now",
    "seed funding", "fondo semilla", "prize", "contest",
]

ALL_KEYWORDS = GRANT_KEYWORDS + MANQA_CONEXION_KEYWORDS + MANQA_FOOD_KEYWORDS + FELLOWSHIP_KEYWORDS

# ---------------------------------------------------------------------------
# Category dimension keywords (for category assignment)
# ---------------------------------------------------------------------------

_profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manqa_profile.json")
try:
    with open(_profile_path, "r", encoding="utf-8") as _f:
        _PROFILE = json.load(_f)
    CATEGORY_KEYWORDS = {
        dim: data["keywords"]
        for dim, data in _PROFILE["dimensions"].items()
    }
    CATEGORY_WEIGHTS = {
        dim: data["weight"]
        for dim, data in _PROFILE["dimensions"].items()
    }
except (FileNotFoundError, KeyError):
    CATEGORY_KEYWORDS = {}
    CATEGORY_WEIGHTS = {}

# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------

def matches_keywords(text, keyword_list=None):
    """Return list of matched keywords in text, using word-boundary matching."""
    if keyword_list is None:
        keyword_list = ALL_KEYWORDS
    lower = text.lower()
    matched = []
    for kw in keyword_list:
        kw_lower = kw.lower()
        if len(kw) <= 3:
            if re.search(r'\b' + re.escape(kw_lower) + r'\b', lower):
                matched.append(kw)
        else:
            if kw_lower in lower:
                matched.append(kw)
    return list(dict.fromkeys(matched))


# ---------------------------------------------------------------------------
# Relevance scoring & category assignment
# ---------------------------------------------------------------------------

def compute_relevance(item):
    """Score 0-100 relevance for Manq'a's mission: food security, youth
    culinary training, social enterprise, agriculture, climate, inclusion."""
    text = f"{item['title']} {item['snippet']}".lower()
    scores = {}

    for dim, kw_list in CATEGORY_KEYWORDS.items():
        dim_score = 0
        for kw in kw_list:
            if kw.lower() in text:
                dim_score += 10
        weight = CATEGORY_WEIGHTS.get(dim, 10)
        scores[dim] = min(dim_score, 100) * (weight / 100)

    total = min(int(sum(scores.values())), 100)

    # Assign category based on highest-scoring dimension
    category = "general"
    if scores:
        category = max(scores, key=scores.get)
        if scores[category] == 0:
            category = "general"

    # Bolivia bonus
    if "bolivia" in text:
        total = min(total + 10, 100)
    if "la paz" in text or "el alto" in text:
        total = min(total + 5, 100)

    return total, category


# ---------------------------------------------------------------------------
# Opportunity builder
# ---------------------------------------------------------------------------

JUNK_TITLES = {"skip to main content", "home", "menu", "search", "login",
               "contact", "about", "inicio", "buscar", "cerrar", ""}


def _auto_classify(title, snippet, opp_type):
    """All items are grants in this pipeline."""
    return "grant"


# ---------------------------------------------------------------------------
# Deadline extraction
# ---------------------------------------------------------------------------

_DEADLINE_PATTERNS = [
    # "Presentación: 14-05-2026" (SICOES format)
    r'[Pp]resentaci[oó]n:\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
    # "Deadline: May 15, 2026" or "Deadline: 2026-05-15"
    r'[Dd]eadline:\s*(\d{4}[-/]\d{1,2}[-/]\d{1,2})',
    r'[Dd]eadline:\s*(\w+ \d{1,2},?\s*\d{4})',
    # "Fecha límite: 15/05/2026"
    r'[Ff]echa l[ií]mite:\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
    # "Closes: 15 May 2026"
    r'[Cc]loses?:\s*(\d{1,2}\s+\w+\s+\d{4})',
    # "Cierre: 15-05-2026"
    r'[Cc]ierre:\s*(\d{1,2}[-/]\d{1,2}[-/]\d{4})',
]


def extract_deadline(text):
    """Try to extract a deadline date from text. Returns string or None."""
    for pattern in _DEADLINE_PATTERNS:
        m = re.search(pattern, text)
        if m:
            return m.group(1).strip()
    return None


def opp(title, url, source, snippet="", keywords=None, opp_type="grant", deadline=None):
    """Build an opportunity dict with category assignment."""
    if deadline is None:
        deadline = extract_deadline(f"{title} {snippet}")
    item = {
        "title": title.strip(),
        "url": url.strip(),
        "source": source,
        "snippet": snippet.strip()[:300],
        "keywords": keywords or [],
        "type": "grant",
        "date_found": datetime.now(timezone(timedelta(hours=-4))).strftime("%Y-%m-%d %H:%M BOT"),
        "deadline": deadline,
    }
    relevance, category = compute_relevance(item)
    item["relevance"] = relevance
    item["category"] = category
    return item
