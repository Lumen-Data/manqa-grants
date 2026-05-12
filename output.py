"""Output formatting and persistence for Manq'a Grants."""

import json
import os
import sys
from datetime import datetime, date, timezone, timedelta

from scoring import JUNK_TITLES, is_junk

BOT = timezone(timedelta(hours=-4))


def dedup(results):
    """Remove duplicates by URL and filter junk."""
    seen = set()
    unique = []
    for r in results:
        if is_junk(r["title"]):
            continue
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)
    return unique


def print_results(results):
    """Pretty-print results to terminal, sorted by relevance."""
    if not results:
        print("\n  No matching opportunities found this scan.\n")
        return

    filtered = list(results)
    filtered.sort(key=lambda r: r.get("relevance", 0), reverse=True)

    top_picks = [r for r in filtered if r.get("relevance", 0) >= 15]
    rest = [r for r in filtered if r.get("relevance", 0) < 15]

    print(f"\n{'='*60}")
    print(f"  Found {len(filtered)} grants — {date.today().isoformat()}")
    print(f"{'='*60}")

    if top_picks:
        print(f"\n  TOP PICKS ({len(top_picks)} high-relevance matches)")
        print(f"  {'='*50}")
        for item in top_picks:
            _print_item(item, show_score=True)
        print()

    if rest:
        by_source = {}
        for r in rest:
            by_source.setdefault(r["source"], []).append(r)

        print(f"  OTHER RESULTS ({len(rest)})")
        print(f"  {'-'*50}")
        for source, items in by_source.items():
            print(f"\n  [{source}] ({len(items)} results)")
            for item in items:
                _print_item(item, show_score=False)
        print()


def _print_item(item, show_score=False):
    """Print a single opportunity item."""
    kw_str = ", ".join(item["keywords"][:3])
    type_tag = f" [{item['type']}]" if item.get("type") else ""
    score_tag = f" (score: {item.get('relevance', 0)})" if show_score else ""
    print(f"  *{type_tag}{score_tag} {item['title'][:80]}")
    if item["snippet"]:
        print(f"    {item['snippet'][:120]}")
    print(f"    {item['url']}")
    print(f"    Keywords: {kw_str}")
    print()


def _merge_with_existing(results):
    """Preserve date_found for previously seen URLs, mark new items.
    Also cleans junk from existing data on merge."""
    existing_path = "docs/latest.json"
    prev_by_url = {}
    if os.path.exists(existing_path):
        try:
            with open(existing_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            prev = raw.get("items", raw) if isinstance(raw, dict) else raw
            # Clean junk from existing items and carry over good ones
            for item in prev:
                if is_junk(item.get("title", "")):
                    continue
                prev_by_url[item["url"]] = item
        except (json.JSONDecodeError, KeyError):
            pass

    new_count = 0
    result_urls = {item["url"] for item in results}
    for item in results:
        prev_item = prev_by_url.get(item["url"])
        if prev_item:
            # Keep enrichment data from previous runs
            item["date_found"] = prev_item["date_found"]
            item["is_new"] = False
            for key in ("enriched", "enriched_deep", "match_score", "match_reason",
                        "match_dimensions", "category", "summary", "deadline",
                        "requirements", "bolivia_applicable", "bolivia_reason",
                        "is_funding_opportunity", "opportunity_type", "status",
                        "action_tip", "last_validated", "quick_reason"):
                if key in prev_item and key not in item:
                    item[key] = prev_item[key]
                elif key in prev_item and prev_item.get("enriched") and not item.get("enriched"):
                    item[key] = prev_item[key]
        else:
            item["is_new"] = True
            new_count += 1

    # Carry over enriched items from previous run that weren't re-scraped
    # (source might have rotated listings but the grant is still active)
    for url, prev_item in prev_by_url.items():
        if url not in result_urls and prev_item.get("enriched"):
            status = prev_item.get("status", "active")
            if status not in ("expired", "closed", "filled", "not_found"):
                prev_item["is_new"] = False
                results.append(prev_item)

    junk_cleaned = len(prev) - len(prev_by_url) if 'prev' in dir() else 0
    if junk_cleaned > 0:
        print(f"  Cleaned {junk_cleaned} junk items from existing data", file=sys.stderr)
    print(f"  {new_count} new, {len(results) - new_count} returning", file=sys.stderr)
    return results


def save_results(results):
    """Save to results/ directory and site/ for GitHub Pages."""
    os.makedirs("results", exist_ok=True)
    os.makedirs("docs", exist_ok=True)
    results = _merge_with_existing(results)
    scan_time = datetime.now(BOT).strftime("%Y-%m-%d %H:%M BOT")
    wrapper = {"scan_timestamp": scan_time, "items": results}
    with open("results/latest.json", "w", encoding="utf-8") as f:
        json.dump(wrapper, f, ensure_ascii=False, indent=2)
    with open("docs/latest.json", "w", encoding="utf-8") as f:
        json.dump(wrapper, f, ensure_ascii=False, indent=2)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(f"results/scan_{stamp}.json", "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  Saved {len(results)} grants to results/ and docs/", file=sys.stderr)
