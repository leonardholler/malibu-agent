"""
Redfin listing scraper.

Fetches listing descriptions and image URLs from Redfin property pages.
Uses the URLs already in our CSV data — no API key needed.

Rate-limited to 1 request per 2 seconds to be polite.
Caches results in data/listing_details.json so we don't re-scrape.

Usage:
    python3 scraper.py              # scrape all active + sold with URLs
    python3 scraper.py --active     # scrape only active listings
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error


CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "listing_details.json")
DELAY = 2.0  # seconds between requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}


def load_cache():
    """Load cached listing details."""
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    """Persist listing details to disk."""
    os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def scrape_listing(url):
    """
    Fetch a Redfin listing page and extract:
    - description: the agent's listing remarks
    - images: list of image URLs
    - property_type: single family, condo, land, etc.
    - keywords: extracted from description (ocean view, beachfront, etc.)
    """
    req = urllib.request.Request(url, headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=15)
    html = resp.read().decode("utf-8", errors="replace")

    result = {"url": url, "scraped": True}

    # Extract description
    desc_match = re.search(r'"description":"(.*?)"', html)
    if desc_match:
        desc = desc_match.group(1)
        # Unescape JSON string
        desc = desc.replace("\\n", "\n").replace("\\t", " ").replace('\\"', '"')
        result["description"] = desc

    # Extract listing remarks (sometimes different from description)
    remarks_match = re.search(r'"listingRemarks":"(.*?)"', html)
    if remarks_match:
        remarks = remarks_match.group(1)
        remarks = remarks.replace("\\n", "\n").replace("\\t", " ").replace('\\"', '"')
        if len(remarks) > len(result.get("description", "")):
            result["description"] = remarks

    # Extract image URLs from the page data
    img_matches = re.findall(r'"(https://ssl\.cdn-redfin\.com/photo/[^"]+)"', html)
    if img_matches:
        # Deduplicate and take unique images
        seen = set()
        images = []
        for img in img_matches:
            # Normalize to get the base image (remove size variants)
            base = re.sub(r'_\d+x\d+', '', img)
            if base not in seen:
                seen.add(base)
                images.append(img)
        result["images"] = images[:20]  # Cap at 20 images

    # Extract keywords from description for classification
    desc_lower = result.get("description", "").lower()
    keywords = []
    keyword_patterns = [
        ("ocean_view", r"ocean\s*view|panoramic.*ocean|sweeping.*view|water\s*view"),
        ("beachfront", r"beach\s*front|on the beach|beach\s*access|steps to.*beach|private.*beach"),
        ("oceanfront", r"ocean\s*front|oceanfront"),
        ("mountain_view", r"mountain\s*view|canyon\s*view|hillside"),
        ("no_view", r"no ocean view|no water view|no beach view|faces the mountain|faces.*lagoon"),
        ("new_build", r"new\s*construction|newly\s*built|brand\s*new|just\s*completed"),
        ("renovated", r"renovated|remodeled|updated|restored"),
        ("teardown", r"tear\s*down|fixer|needs.*work|as[\s-]is|sold.*as.*land"),
        ("land_only", r"land\s*only|vacant\s*land|lot\s*only|build\s*your|unimproved"),
        ("burned", r"burned|fire\s*damage|woolsey|fire\s*loss"),
        ("gated", r"gated|private\s*gate|security\s*gate"),
        ("pool", r"pool|swimming"),
        ("guest_house", r"guest\s*house|guest\s*suite|separate.*dwelling|casita"),
        ("bluff", r"bluff|cliff\s*top|blufftop|perched"),
    ]
    for tag, pattern in keyword_patterns:
        if re.search(pattern, desc_lower):
            keywords.append(tag)
    result["keywords"] = keywords

    return result


def get_urls_from_csvs():
    """Load all Redfin URLs from CSV files."""
    import glob
    import pandas as pd

    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    csvs = glob.glob(os.path.join(data_dir, "*.csv"))

    all_rows = []
    for csv_file in csvs:
        df = pd.read_csv(csv_file)
        url_col = [c for c in df.columns if "URL" in c]
        if url_col:
            for _, row in df.iterrows():
                url = row.get(url_col[0])
                address = row.get("ADDRESS", "")
                if isinstance(url, str) and url.startswith("http"):
                    all_rows.append({"address": address, "url": url})
    return all_rows


def scrape_all(active_only=False):
    """Scrape all listings, using cache for already-scraped ones."""
    cache = load_cache()
    listings = get_urls_from_csvs()
    total = len(listings)
    scraped = 0
    skipped = 0
    errors = 0

    print(f"Found {total} listings with URLs")
    print(f"Cache has {len(cache)} entries")

    for i, listing in enumerate(listings):
        url = listing["url"]
        address = listing["address"]

        if url in cache:
            skipped += 1
            continue

        try:
            print(f"[{i+1}/{total}] Scraping: {address}...", end=" ", flush=True)
            details = scrape_listing(url)
            details["address"] = address
            cache[url] = details

            desc_len = len(details.get("description", ""))
            n_images = len(details.get("images", []))
            keywords = details.get("keywords", [])
            print(f"OK ({desc_len} chars, {n_images} images, tags: {keywords})")

            scraped += 1
            save_cache(cache)  # Save after each to not lose progress
            time.sleep(DELAY)

        except urllib.error.HTTPError as e:
            print(f"HTTP {e.code}")
            errors += 1
            if e.code == 403:
                print("  Blocked by Redfin. Waiting 10s...")
                time.sleep(10)
            elif e.code == 429:
                print("  Rate limited. Waiting 30s...")
                time.sleep(30)
        except Exception as e:
            print(f"Error: {e}")
            errors += 1

    print(f"\nDone: {scraped} scraped, {skipped} cached, {errors} errors")
    return cache


if __name__ == "__main__":
    active_only = "--active" in sys.argv
    cache = scrape_all(active_only=active_only)
    print(f"\nTotal cached listings: {len(cache)}")

    # Summary of keywords found
    all_keywords = {}
    for entry in cache.values():
        for kw in entry.get("keywords", []):
            all_keywords[kw] = all_keywords.get(kw, 0) + 1

    if all_keywords:
        print("\nKeyword distribution:")
        for kw, count in sorted(all_keywords.items(), key=lambda x: -x[1]):
            print(f"  {kw}: {count}")
