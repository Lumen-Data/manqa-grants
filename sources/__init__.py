"""Source registry for Manq'a Grants — grants only."""

from sources.grant_sources import scrape_all_grants
from sources.food_sources import scrape_all_food_grants

SOURCES = {
    "grants": ("Grants & Funding (existing sources)", scrape_all_grants),
    "food":   ("Food & Social Enterprise Grants", scrape_all_food_grants),
}
