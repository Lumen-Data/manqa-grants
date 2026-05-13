"""Shared Apify client wrapper for manqa-grants.

Usage:
    from shared.apify import run_actor

    items, err = run_actor("apify/facebook-posts-scraper", {"startUrls": [...]})
    if err:
        print(f"Apify failed: {err}")
"""

import os
import sys

try:
    from apify_client import ApifyClient
except ImportError:
    ApifyClient = None


def _load_token():
    """Load APIFY_API_TOKEN from environment or .env file."""
    token = os.environ.get("APIFY_API_TOKEN", "")
    if token:
        return token

    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("APIFY_API_TOKEN=") and not line.startswith("#"):
                    return line.split("=", 1)[1].strip()
    return ""


def run_actor(actor_id, run_input, timeout_secs=300):
    """Run an Apify actor synchronously and return its dataset items.

    Returns:
        (list, None) on success
        ([], str) on failure
    """
    if ApifyClient is None:
        return [], "apify-client not installed"

    token = _load_token()
    if not token:
        return [], "No APIFY_API_TOKEN configured"

    client = ApifyClient(token)
    try:
        run = client.actor(actor_id).call(
            run_input=run_input,
            timeout_secs=timeout_secs,
        )
        status = run.get("status", "UNKNOWN")
        if status != "SUCCEEDED":
            return [], f"Actor {actor_id} ended with status: {status}"

        items = client.dataset(run["defaultDatasetId"]).list_items().items
        return items, None

    except Exception as e:
        return [], f"Actor {actor_id} error: {e}"
