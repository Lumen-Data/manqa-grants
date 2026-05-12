#!/usr/bin/env python3
"""
Manq'a Grants Scraper
Monitors grant, funding, and social enterprise opportunities
relevant to Manq'a Sostenibles in Bolivia.

Uses existing grant sources + new food/social enterprise sources.

Usage:
    python3 scraper.py                  # scan all sources
    python3 scraper.py --json           # output JSON to stdout
    python3 scraper.py --save           # save results to results/ and docs/
    python3 scraper.py --source grants  # scan only one source group
    python3 scraper.py --no-apify       # force direct scraping (skip Apify)

Sources:
    grants   Existing grant sources (22 sub-sources)
    food     Food & social enterprise grants (10 sub-sources)
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from sources import SOURCES
from sources.google_search import set_no_apify
from output import dedup, print_results, save_results


def main():
    parser = argparse.ArgumentParser(
        description="Manq'a Grants Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Sources:
  grants   Existing grant sources (IAF, UNDP, CAF, etc.)
  food     Food & social enterprise grants (GlobalGiving, WFP, etc.)

Examples:
  python3 scraper.py                        # scan everything
  python3 scraper.py --source food          # just food/social sources
  python3 scraper.py --save --json          # save + JSON output
  python3 scraper.py --no-apify             # force direct scraping
        """)
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    parser.add_argument("--save", action="store_true", help="Save results to results/ and docs/")
    parser.add_argument("--source", choices=list(SOURCES.keys()),
                        help="Scan only one source group")
    parser.add_argument("--no-apify", action="store_true",
                        help="Skip Apify actors, use direct scraping only")
    parser.add_argument("--no-enrich", action="store_true",
                        help="Skip Claude API enrichment (keyword fallback)")
    parser.add_argument("--validate-only", action="store_true",
                        help="Only validate existing items, no scraping")
    args = parser.parse_args()

    if args.no_apify:
        set_no_apify(True)

    try:
        from claude_enrichment import enrich_new_items, validate_active_items
    except ImportError:
        enrich_new_items = None
        validate_active_items = None

    # Validate-only mode
    if args.validate_only:
        if validate_active_items:
            existing_path = os.path.join("docs", "latest.json")
            if os.path.exists(existing_path):
                with open(existing_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                items = raw.get("items", raw) if isinstance(raw, dict) else raw
                validate_active_items(items)
                save_results(items)
            else:
                print("  No existing data to validate", file=sys.stderr)
        else:
            print("  Enrichment not available, skipping validation", file=sys.stderr)
        return

    # Discovery mode: scrape sources
    all_results = []
    sources_to_run = {args.source: SOURCES[args.source]} if args.source else SOURCES

    for key, (label, scraper_fn) in sources_to_run.items():
        if not args.json:
            print(f"  Scanning {label}...", file=sys.stderr, flush=True)
        try:
            hits = scraper_fn()
            all_results.extend(hits)
            if not args.json:
                print(f"    -> {len(hits)} results", file=sys.stderr)
        except Exception as e:
            print(f"    !!  {label} failed: {e}", file=sys.stderr)

    all_results = dedup(all_results)

    if args.json:
        print(json.dumps(all_results, ensure_ascii=False, indent=2))
    else:
        print_results(all_results)

    if args.save:
        save_results(all_results)

        # Enrich new items + validate existing
        if not args.no_enrich and enrich_new_items:
            with open("docs/latest.json", "r", encoding="utf-8") as f:
                raw = json.load(f)
            wrapper = raw if isinstance(raw, dict) and "items" in raw else {"items": raw}
            merged = wrapper["items"]
            enrich_new_items(merged)
            if validate_active_items:
                validate_active_items(merged)
            from output import BOT
            wrapper["items"] = merged
            wrapper["scan_timestamp"] = datetime.now(BOT).strftime("%Y-%m-%d %H:%M BOT")
            with open("docs/latest.json", "w", encoding="utf-8") as f:
                json.dump(wrapper, f, ensure_ascii=False, indent=2)
            with open("results/latest.json", "w", encoding="utf-8") as f:
                json.dump(wrapper, f, ensure_ascii=False, indent=2)
            print(f"  Saved enriched data ({len(merged)} items)", file=sys.stderr)


if __name__ == "__main__":
    main()
