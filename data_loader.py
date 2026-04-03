"""
Data loader for Malibu Agent.
Reads Redfin CSVs, normalizes columns, and classifies Malibu micro-neighborhoods.
"""

import pandas as pd
import glob
import os

# ── Malibu Micro-Neighborhoods ──────────────────────────────────────────────
#
# Classification uses street names (primary) + coordinates (secondary).
# Malibu stretches along PCH from Carbon Beach (~-118.66) to Broad Beach (~-118.87).
# The further east (toward LA), the higher the prestige per dollar of beachfront.

NEIGHBORHOODS = {
    "Malibu Colony": {
        "streets": ["malibu colony rd", "malibu colony", "case st", "case ct"],
        "description": "Gated beachfront enclave. The most exclusive address in Malibu.",
        "lat_range": (34.030, 34.035),
        "lng_range": (-118.705, -118.680),
    },
    "Carbon Beach": {
        "streets": ["carbon beach", "carbon mesa", "villa costera", "rambla vis",
                     "rambla pacifico", "harbor vista"],
        "description": "Billionaire's Beach. Ultra-premium beachfront east of the Colony.",
        "lat_range": (34.039, 34.046),
        "lng_range": (-118.695, -118.640),
    },
    "Malibu Road": {
        "streets": ["malibu rd"],
        "description": "Central beachfront strip. Mix of older beach cottages and new builds.",
        "lat_range": (34.028, 34.035),
        "lng_range": (-118.730, -118.688),
    },
    "Serra Retreat": {
        "streets": ["serra rd", "sweetwater mesa", "retreat ct", "cross creek",
                     "puerco canyon"],
        "description": "Gated hillside community above central Malibu. Privacy, no beach.",
        "lat_range": (34.040, 34.050),
        "lng_range": (-118.690, -118.670),
    },
    "Malibu Cove Colony": {
        "streets": ["malibu cove colony"],
        "description": "Gated oceanfront community near the pier. Smaller lots, strong community.",
        "lat_range": (34.024, 34.027),
        "lng_range": (-118.768, -118.754),
    },
    "Escondido Beach": {
        "streets": ["escondido beach", "sea vista", "tantalus"],
        "description": "Paradise Cove area. Secluded beach access, fewer neighbors.",
        "lat_range": (34.023, 34.031),
        "lng_range": (-118.775, -118.758),
    },
    "Point Dume": {
        "streets": ["cliffside dr", "birdview", "dume dr", "zumirez", "grayfox",
                     "bison ct", "wildlife rd", "fernhill", "grasswood", "sea ranch",
                     "whitesands", "zuma view", "larkspur", "selfridge", "baden",
                     "sea lane dr", "bonsall", "murphy way", "ramirez canyon",
                     "kanan dume", "deerhead", "filaree", "latigo shore"],
        "description": "Dramatic bluff-top setting. Panoramic ocean views, whale watching, iconic cliffs.",
        "lat_range": (34.000, 34.035),
        "lng_range": (-118.830, -118.780),
    },
    "Broad Beach": {
        "streets": ["broad beach rd", "sea level dr", "west sea level", "victoria point",
                     "point lechuza", "ellice st", "harvester", "morning view",
                     "andromeda", "cuthbert", "philip ave"],
        "description": "Wide sandy beach on the west end. Large lots, newer construction.",
        "lat_range": (34.025, 34.055),
        "lng_range": (-118.875, -118.830),
    },
    "Western Malibu": {
        "streets": ["trancas canyon", "guernsey", "encinal canyon", "cotharin",
                     "yellow hill", "mulholland hwy", "avenida del mar", "charles rd",
                     "corral canyon"],
        "description": "Past Broad Beach toward Ventura. Larger acreage, ranch-style. Less prestige but more land for the money.",
        "lat_range": (34.035, 34.100),
        "lng_range": (-118.970, -118.830),
    },
}

# Priority-ordered list for classification (most specific first)
NEIGHBORHOOD_PRIORITY = [
    "Malibu Colony", "Carbon Beach", "Malibu Cove Colony", "Escondido Beach",
    "Serra Retreat", "Malibu Road", "Point Dume", "Broad Beach", "Western Malibu",
]

COLUMN_MAP = {
    "SALE TYPE": "sale_type",
    "SOLD DATE": "sold_date",
    "PROPERTY TYPE": "property_type",
    "ADDRESS": "address",
    "CITY": "city",
    "STATE OR PROVINCE": "state",
    "ZIP OR POSTAL CODE": "zip",
    "PRICE": "price",
    "BEDS": "beds",
    "BATHS": "baths",
    "LOCATION": "location",
    "SQUARE FEET": "sqft",
    "LOT SIZE": "lot_size",
    "YEAR BUILT": "year_built",
    "DAYS ON MARKET": "dom",
    "$/SQUARE FEET": "price_per_sqft",
    "HOA/MONTH": "hoa",
    "STATUS": "status",
    "URL (SEE https://www.redfin.com/buy-a-home/comparative-market-analysis FOR INFO ON PRICING)": "url",
    "SOURCE": "source",
    "MLS#": "mls",
    "LATITUDE": "lat",
    "LONGITUDE": "lng",
}

# ── Construction era thresholds ──────────────────────────────────────────────
CONSTRUCTION_ERAS = [
    (0, 1970, "Pre-1970 (Classic)"),
    (1970, 1990, "1970-1990"),
    (1990, 2010, "1990-2010"),
    (2010, 2030, "2010+ (New Build)"),
]


def classify_neighborhood(row):
    """Classify a Malibu property into a micro-neighborhood."""
    address = str(row.get("address", "")).lower()
    lat = row.get("lat")
    lng = row.get("lng")

    # Pass 1: street name matching (most reliable)
    for hood_name in NEIGHBORHOOD_PRIORITY:
        hood = NEIGHBORHOODS[hood_name]
        for street in hood["streets"]:
            if street in address:
                return hood_name

    # Pass 2: coordinate matching
    if pd.notna(lat) and pd.notna(lng):
        for hood_name in NEIGHBORHOOD_PRIORITY:
            hood = NEIGHBORHOODS[hood_name]
            lat_min, lat_max = hood["lat_range"]
            lng_min, lng_max = hood["lng_range"]
            if lat_min <= lat <= lat_max and lng_min <= lng <= lng_max:
                return hood_name

    # Pass 3: PCH properties — use address number (more reliable than coordinates)
    if "pacific coast hwy" in address:
        import re
        num_match = re.match(r"(\d+)", address)
        if num_match:
            addr_num = int(num_match.group(1))
            if 21000 <= addr_num <= 22700:
                return "Carbon Beach"
            elif 22700 < addr_num <= 23800:
                return "Malibu Colony"  # PCH near the Colony
            elif 23800 < addr_num <= 26500:
                return "Malibu Road"
            elif 26500 < addr_num <= 28500:
                return "Point Dume"
            elif 28500 < addr_num <= 31500:
                return "Broad Beach"
            elif addr_num > 31500:
                return "Western Malibu"
            # addr_num < 21000 = eastern Malibu, not a defined neighborhood

        # Fallback to longitude if no address number match
        if pd.notna(lng):
            if -118.670 < lng <= -118.630:
                return "Carbon Beach"
            elif -118.700 < lng <= -118.670:
                return "Malibu Road"
            elif -118.800 < lng <= -118.750:
                return "Point Dume"
            elif -118.860 < lng <= -118.800:
                return "Broad Beach"
            elif lng <= -118.860:
                return "Western Malibu"

    return "Malibu (Other)"


def get_construction_era(year):
    """Categorize a property by construction era."""
    if pd.isna(year):
        return "Unknown"
    for low, high, label in CONSTRUCTION_ERAS:
        if low <= year < high:
            return label
    return "Unknown"


def estimate_land_value_ratio(row):
    """
    Estimate what portion of the price is land vs improvements.

    Logic: In Malibu's $10M+ market, old construction on prime land means
    the buyer is paying mostly for land (teardown candidate). New construction
    means the improvements carry significant value.

    Returns a float 0-1 representing estimated land value as % of price.
    """
    year = row.get("year_built")
    sqft = row.get("sqft")
    price = row.get("price")
    price_per_sqft = row.get("price_per_sqft")
    hood = row.get("neighborhood", "")

    if pd.isna(year) or pd.isna(price):
        return None

    # Base land ratio by construction age
    if year >= 2015:
        base = 0.40  # New build — improvements are 60% of value
    elif year >= 2000:
        base = 0.55
    elif year >= 1985:
        base = 0.65
    elif year >= 1970:
        base = 0.75
    else:
        base = 0.85  # Pre-1970 — you're basically buying dirt

    # Beach-adjacent neighborhoods have higher land value ratios
    beach_hoods = ["Malibu Colony", "Carbon Beach", "Malibu Road", "Broad Beach",
                   "Malibu Cove Colony", "Escondido Beach"]
    if hood in beach_hoods:
        base = min(base + 0.05, 0.95)

    # If $/sqft is very high relative to construction cost (~$800-1200/sqft for
    # luxury in Malibu), the excess is land premium
    if pd.notna(price_per_sqft) and price_per_sqft > 3000:
        base = min(base + 0.10, 0.95)

    return round(base, 2)


def _default_data_dir():
    """Resolve the data/ directory relative to this file, not CWD."""
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load_csvs(data_dir=None):
    """Load all Redfin CSVs from the data directory."""
    if data_dir is None:
        data_dir = _default_data_dir()
    csv_files = glob.glob(os.path.join(data_dir, "*.csv"))
    if not csv_files:
        print(f"No CSV files found in {data_dir}/")
        return pd.DataFrame()

    frames = []
    for f in csv_files:
        df = pd.read_csv(f, comment='"', on_bad_lines="skip")
        frames.append(df)

    return pd.concat(frames, ignore_index=True)


def normalize(df):
    """Rename columns, clean types, classify neighborhoods, add derived fields."""
    df = df.rename(columns={k: v for k, v in COLUMN_MAP.items() if k in df.columns})

    # Clean numeric columns
    for col in ["price", "sqft", "lot_size", "year_built", "dom",
                "price_per_sqft", "hoa", "beds", "baths", "lat", "lng"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # ── Data corrections for known bad records ─────────────────────────
    # These are verified against Redfin/public records.
    _corrections = {
        "32300 Pacific Coast Hwy": {
            # Redfin shows sqft=10 — actual property is 11,000 sqft Cape Cod estate
            # on ~3 acres (130,680 sqft lot), 8 bed / 9.5 bath
            "sqft": 11000,
            "lot_size": 130680,
            "beds": 8,
            "baths": 9.5,
        },
        "31460 Broad Beach Rd": {
            # sqft=1 in data — this is a land parcel, not a house
            "sqft": float("nan"),
        },
    }
    for addr, fixes in _corrections.items():
        mask = df["address"].str.contains(addr, case=False, na=False)
        for col, val in fixes.items():
            if col in df.columns:
                df.loc[mask, col] = val

    # Flag land parcels: no sqft, no year_built, or extremely low sqft
    df["is_land_parcel"] = (
        (df["sqft"].isna() | (df["sqft"] < 500))
        & (df["year_built"].isna())
    )

    # Compute price_per_sqft where missing
    mask = df["price_per_sqft"].isna() & df["price"].notna() & df["sqft"].notna() & (df["sqft"] > 0)
    df.loc[mask, "price_per_sqft"] = (df.loc[mask, "price"] / df.loc[mask, "sqft"]).round(0)

    # Classify neighborhoods
    df["neighborhood"] = df.apply(classify_neighborhood, axis=1)

    # Construction era
    df["construction_era"] = df["year_built"].apply(get_construction_era)

    # Property age
    df["age"] = 2026 - df["year_built"]

    # Land value ratio estimate
    df["land_value_ratio"] = df.apply(estimate_land_value_ratio, axis=1)
    df["est_land_value"] = (df["price"] * df["land_value_ratio"]).round(0)
    df["est_improvement_value"] = (df["price"] * (1 - df["land_value_ratio"])).round(0)

    # Parse sold dates
    if "sold_date" in df.columns:
        df["sold_date_parsed"] = pd.to_datetime(df["sold_date"], format="%B-%d-%Y", errors="coerce")

    # Clean status
    if "status" in df.columns:
        df["status"] = df["status"].fillna("Unknown")

    return df


def load_data(data_dir=None):
    """Main entry point: load, normalize, split into active and sold."""
    raw = load_csvs(data_dir)
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame()

    df = normalize(raw)

    active = df[df["status"].str.contains("Active", case=False, na=False)].copy()
    sold = df[df["status"].str.contains("Sold", case=False, na=False)].copy()

    return active, sold
