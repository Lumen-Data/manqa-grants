"""Claude API enrichment for Manq'a Grants.

Two-pass architecture:
  Pass 1 (Haiku): Quick score from title + snippet only — all new items
  Pass 2 (Haiku): Deep enrich from page content — high-potential items only

Validation pass (Haiku): Smart scheduling for active items.

Graceful degradation: skips silently if ANTHROPIC_API_KEY is not set.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests

BOT = timezone(timedelta(hours=-4))

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PASS1_MODEL = "claude-haiku-4-5-20251001"
PASS2_MODEL = "claude-sonnet-4-5-20250514"
VALIDATE_MODEL = "claude-haiku-4-5-20251001"

PASS1_THRESHOLD = 25
PASS1_MAX_ITEMS = 250
PASS2_MAX_ITEMS = 40
VALIDATE_MAX_ITEMS = 50
VALIDATE_MAX_AGE_HOURS = 48
VALIDATE_DEADLINE_DAYS = 14

DIMENSIONS = [
    "food_security", "culinary_training", "youth_employment",
    "social_enterprise", "agriculture", "climate", "gender_inclusion",
]

_client = None
_page_cache = {}


def _get_client():
    """Lazy-init Anthropic client. Returns None if unavailable."""
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("ANTHROPIC_API_KEY=") and not line.startswith("#"):
                        api_key = line.split("=", 1)[1].strip()
                        break
    if not api_key:
        return None

    try:
        from anthropic import Anthropic
        _client = Anthropic(api_key=api_key)
        return _client
    except ImportError:
        print("  [enrichment] anthropic package not installed, skipping", file=sys.stderr)
        return None


def _load_profile():
    """Load manqa_profile.json from project root."""
    profile_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "manqa_profile.json")
    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print("  [enrichment] manqa_profile.json not found, using default", file=sys.stderr)
        return {"name": "Manq'a Sostenibles", "location": "La Paz, Bolivia"}


def _fetch_page_text(url, max_chars=4000):
    """Fetch URL and extract text content. Cached per-run."""
    if url in _page_cache:
        return _page_cache[url]

    try:
        from bs4 import BeautifulSoup
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        }
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)[:max_chars]
        _page_cache[url] = text
        return text
    except Exception:
        _page_cache[url] = ""
        return ""


def _call_claude(model, system_prompt, user_prompt, max_tokens=500):
    """Call Claude API and parse JSON response. Returns dict or None."""
    client = _get_client()
    if not client:
        return None

    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(text)
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        print(f"  [enrichment] JSON parse error: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(f"  [enrichment] API error: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Pass 1: Quick score (Haiku, title + snippet only)
# ---------------------------------------------------------------------------

PASS1_SYSTEM = """You are scoring grant/funding opportunities for relevance to a social enterprise organization.
Return ONLY valid JSON, no other text."""


def _pass1_prompt(item, profile):
    return f"""Score this grant opportunity for the following organization.

Organization:
{json.dumps(profile, indent=2)}

Opportunity:
Title: {item['title']}
Source: {item['source']}
Snippet: {item.get('snippet', '')}

Return JSON:
{{
  "match_score": 0-100,
  "category": "food_security|culinary_training|youth_employment|social_enterprise|agriculture|climate|gender_inclusion",
  "summary": "one-line description in Spanish",
  "bolivia_applicable": true or false,
  "is_funding_opportunity": true or false,
  "quick_reason": "one sentence explaining the score"
}}

IMPORTANT: Set is_funding_opportunity to TRUE only if this is an actual grant, fellowship, prize, call for proposals, or funding application that an organization can apply to. Set FALSE if it is a news article, blog post, organizational overview, project description, or general information page about funding.

Score generously across ALL organization dimensions:
- food_security (seguridad alimentaria, nutrición, sistemas alimentarios)
- culinary_training (gastronomía, escuelas de cocina, formación culinaria)
- youth_employment (empleo juvenil, capacitación, desarrollo de habilidades)
- social_enterprise (emprendimiento social, restaurante social, empresa social)
- agriculture (agricultura urbana, ingredientes locales, agroecología)
- climate (resiliencia climática, sostenibilidad, bioeconomía)
- gender_inclusion (género, inclusión, mujeres, comunidades vulnerables)

A food security grant, a youth culinary training fund, a social enterprise award, and an agriculture development call are ALL relevant."""


def quick_score(item, profile):
    """Pass 1: Quick score from title + snippet only."""
    result = _call_claude(PASS1_MODEL, PASS1_SYSTEM, _pass1_prompt(item, profile), max_tokens=200)
    if not result:
        return None
    return {
        "match_score": result.get("match_score", 0),
        "category": result.get("category", item.get("category", "general")),
        "summary": result.get("summary", ""),
        "bolivia_applicable": result.get("bolivia_applicable", True),
        "is_funding_opportunity": result.get("is_funding_opportunity", True),
        "quick_reason": result.get("quick_reason", ""),
        "enriched": True,
        "enriched_deep": False,
    }


# ---------------------------------------------------------------------------
# Pass 2: Deep enrich (Haiku, page content)
# ---------------------------------------------------------------------------

PASS2_SYSTEM = """You are analyzing a grant opportunity in depth for a social enterprise in Bolivia.
Return ONLY valid JSON, no other text."""


def _pass2_prompt(item, profile, page_text):
    return f"""Analyze this grant opportunity in depth for the following organization.

Organization:
{json.dumps(profile, indent=2)}

Opportunity:
Title: {item['title']}
Source: {item['source']}
Snippet: {item.get('snippet', '')}

Page content:
{page_text}

Return JSON:
{{
  "match_score": 0-100,
  "match_reason": "2-3 sentences in Spanish explaining fit",
  "match_dimensions": {{
    "food_security": 0-100,
    "culinary_training": 0-100,
    "youth_employment": 0-100,
    "social_enterprise": 0-100,
    "agriculture": 0-100,
    "climate": 0-100,
    "gender_inclusion": 0-100
  }},
  "category": "food_security|culinary_training|youth_employment|social_enterprise|agriculture|climate|gender_inclusion",
  "summary": "one-line description in Spanish",
  "deadline": "YYYY-MM-DD or null",
  "requirements": ["key requirement 1", "key requirement 2"],
  "bolivia_applicable": true or false,
  "bolivia_reason": "why or why not applicable to Bolivia",
  "is_funding_opportunity": true or false,
  "opportunity_type": "grant|fellowship|prize|accelerator|call_for_proposals|other",
  "status": "active|expired|closed|unclear",
  "action_tip": "what to emphasize if applying, or why to skip"
}}

IMPORTANT: Set is_funding_opportunity to TRUE only if this page is an actual grant, fellowship, prize, call for proposals, or funding application. Set FALSE if it is a news article, blog post, organizational overview, project report, or general information page. Read the page content carefully to determine this."""


def deep_enrich(item, profile):
    """Pass 2: Deep enrich from page content."""
    page_text = _fetch_page_text(item["url"])
    if not page_text:
        return None
    result = _call_claude(PASS2_MODEL, PASS2_SYSTEM, _pass2_prompt(item, profile, page_text), max_tokens=600)
    if not result:
        return None
    return {
        "match_score": result.get("match_score", 0),
        "match_reason": result.get("match_reason", ""),
        "match_dimensions": result.get("match_dimensions", {}),
        "category": result.get("category", item.get("category", "general")),
        "summary": result.get("summary", ""),
        "deadline": result.get("deadline"),
        "requirements": result.get("requirements", []),
        "bolivia_applicable": result.get("bolivia_applicable", True),
        "bolivia_reason": result.get("bolivia_reason", ""),
        "is_funding_opportunity": result.get("is_funding_opportunity", True),
        "opportunity_type": result.get("opportunity_type", "grant"),
        "status": result.get("status", "active"),
        "action_tip": result.get("action_tip", ""),
        "enriched": True,
        "enriched_deep": True,
    }


# ---------------------------------------------------------------------------
# Validation pass (Haiku)
# ---------------------------------------------------------------------------

VALIDATE_SYSTEM = """You are checking if a grant opportunity is still active or has expired.
Return ONLY valid JSON, no other text."""


def _validate_prompt(item, page_text):
    return f"""Check if this grant opportunity is still active.

Title: {item['title']}
Original deadline: {item.get('deadline', 'unknown')}
Date found: {item.get('date_found', 'unknown')}

Page content:
{page_text[:2000]}

Return JSON:
{{
  "status": "active|expired|closed|filled|not_found",
  "reason": "brief explanation",
  "updated_deadline": "YYYY-MM-DD or null if changed or unknown"
}}"""


def validate_item(item):
    """Check if an opportunity is still active."""
    page_text = _fetch_page_text(item["url"], max_chars=2000)
    result = _call_claude(VALIDATE_MODEL, VALIDATE_SYSTEM, _validate_prompt(item, page_text), max_tokens=150)
    if not result:
        return None
    now = datetime.now(BOT).strftime("%Y-%m-%d %H:%M BOT")
    fields = {
        "status": result.get("status", "unclear"),
        "last_validated": now,
    }
    if result.get("updated_deadline"):
        fields["deadline"] = result["updated_deadline"]
    return fields


def _needs_validation(item):
    """Determine if an item needs validation based on smart scheduling."""
    status = item.get("status", "active")
    if status in ("expired", "closed", "filled", "not_found"):
        return False

    last = item.get("last_validated", "")
    if last:
        try:
            last_dt = datetime.strptime(last.replace(" BOT", ""), "%Y-%m-%d %H:%M")
            last_dt = last_dt.replace(tzinfo=BOT)
            age_hours = (datetime.now(BOT) - last_dt).total_seconds() / 3600
            if age_hours < VALIDATE_MAX_AGE_HOURS:
                return False
        except ValueError:
            pass

    deadline = item.get("deadline")
    if deadline:
        try:
            dl = datetime.strptime(deadline, "%Y-%m-%d").replace(tzinfo=BOT)
            days_until = (dl - datetime.now(BOT)).days
            if 0 < days_until <= VALIDATE_DEADLINE_DAYS:
                return True
            if days_until <= 0:
                return False
        except ValueError:
            pass

    date_found = item.get("date_found", "")
    if date_found:
        try:
            found_str = date_found.replace(" BOT", "").split(" ")[0]
            found_dt = datetime.strptime(found_str, "%Y-%m-%d").replace(tzinfo=BOT)
            age_days = (datetime.now(BOT) - found_dt).days
            if age_days >= 5:
                return True
        except ValueError:
            pass

    return False


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def enrich_new_items(items):
    """Run two-pass enrichment on new items. Modifies items in place."""
    client = _get_client()
    if not client:
        print("  [enrichment] No API key, skipping enrichment", file=sys.stderr)
        return

    profile = _load_profile()
    new_items = [i for i in items if i.get("is_new") and not i.get("enriched")]

    # Backfill: if budget remains, enrich older items that missed the cap
    backfill = [i for i in items if not i.get("is_new") and not i.get("enriched")]
    if backfill:
        backfill.sort(key=lambda i: i.get("relevance", 0), reverse=True)

    to_enrich = new_items + backfill

    if not to_enrich:
        print("  [enrichment] No items to enrich", file=sys.stderr)
        return

    if len(to_enrich) > PASS1_MAX_ITEMS:
        # Prioritize new items, then backfill
        to_enrich = to_enrich[:PASS1_MAX_ITEMS]

    backfill_count = sum(1 for i in to_enrich if not i.get("is_new"))
    new_count = len(to_enrich) - backfill_count
    print(f"  [enrichment] Pass 1: {new_count} new + {backfill_count} backfill = {len(to_enrich)} items", file=sys.stderr)
    new_items = to_enrich

    print(f"  [enrichment] Pass 1: Quick scoring {len(new_items)} new items...", file=sys.stderr)
    pass2_candidates = []

    for item in new_items:
        result = quick_score(item, profile)
        if result:
            item.update(result)
            if result["match_score"] >= PASS1_THRESHOLD:
                pass2_candidates.append(item)
        else:
            item["enriched"] = False

    if len(pass2_candidates) > PASS2_MAX_ITEMS:
        pass2_candidates.sort(key=lambda i: i.get("match_score", 0), reverse=True)
        pass2_candidates = pass2_candidates[:PASS2_MAX_ITEMS]

    print(f"  [enrichment] Pass 2: Deep enriching {len(pass2_candidates)} items...", file=sys.stderr)

    for item in pass2_candidates:
        result = deep_enrich(item, profile)
        if result:
            item.update(result)

    enriched = sum(1 for i in new_items if i.get("enriched"))
    deep = sum(1 for i in new_items if i.get("enriched_deep"))
    print(f"  [enrichment] Done: {enriched} enriched, {deep} deep enriched", file=sys.stderr)


def validate_active_items(items):
    """Run validation on active items that need it. Modifies items in place."""
    client = _get_client()
    if not client:
        print("  [enrichment] No API key, skipping validation", file=sys.stderr)
        return

    now = datetime.now(BOT)
    for item in items:
        deadline = item.get("deadline")
        if deadline and item.get("status", "active") == "active":
            try:
                dl = datetime.strptime(deadline, "%Y-%m-%d").replace(tzinfo=BOT)
                if dl < now:
                    item["status"] = "expired"
                    item["last_validated"] = now.strftime("%Y-%m-%d %H:%M BOT")
            except ValueError:
                pass

    to_validate = [i for i in items if _needs_validation(i)]

    if not to_validate:
        print("  [enrichment] No items need validation", file=sys.stderr)
        return

    if len(to_validate) > VALIDATE_MAX_ITEMS:
        to_validate = to_validate[:VALIDATE_MAX_ITEMS]

    print(f"  [enrichment] Validating {len(to_validate)} items...", file=sys.stderr)

    for item in to_validate:
        result = validate_item(item)
        if result:
            item.update(result)

    updated = sum(1 for i in to_validate if i.get("last_validated"))
    expired = sum(1 for i in to_validate if i.get("status") in ("expired", "closed", "filled"))
    print(f"  [enrichment] Done: {updated} validated, {expired} expired/closed", file=sys.stderr)
