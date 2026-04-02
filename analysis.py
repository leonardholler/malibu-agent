"""
Analysis functions for Malibu Agent.
Pure data functions — no printing, no side effects. Return DataFrames and dicts.
"""

import pandas as pd
from data_loader import NEIGHBORHOODS, CONSTRUCTION_ERAS


def fmt_price(p):
    """Format a price for display."""
    if pd.isna(p):
        return "N/A"
    if p >= 1_000_000:
        return f"${p / 1_000_000:,.1f}M"
    return f"${p:,.0f}"


def market_overview(active, sold):
    """
    Returns a dict of neighborhood stats.
    {
        "Malibu Colony": {
            "active_count": 5, "sold_count": 8,
            "active_med_price": 17.5M, "sold_med_price": 16.0M,
            "active_med_ppsf": 4500, "sold_med_ppsf": 4200,
            "active_med_dom": 90,
            "description": "...",
            "med_year_built": 1985, "pct_new_build": 0.20,
            "med_land_value_ratio": 0.70,
        }, ...
    }
    """
    stats = {}
    for hood_name in NEIGHBORHOODS:
        a = active[active["neighborhood"] == hood_name]
        s = sold[sold["neighborhood"] == hood_name]
        if a.empty and s.empty:
            continue

        stats[hood_name] = {
            "description": NEIGHBORHOODS[hood_name]["description"],
            "active_count": len(a),
            "sold_count": len(s),
            "active_med_price": a["price"].median() if not a.empty else None,
            "sold_med_price": s["price"].median() if not s.empty else None,
            "active_avg_price": a["price"].mean() if not a.empty else None,
            "sold_avg_price": s["price"].mean() if not s.empty else None,
            "active_med_ppsf": a["price_per_sqft"].median() if not a.empty else None,
            "sold_med_ppsf": s["price_per_sqft"].median() if not s.empty else None,
            "active_med_dom": a["dom"].median() if not a.empty else None,
            "med_year_built": a["year_built"].median() if not a.empty and a["year_built"].notna().any() else None,
            "pct_new_build": (a["year_built"] >= 2010).sum() / len(a) if not a.empty and a["year_built"].notna().any() else None,
            "med_land_value_ratio": a["land_value_ratio"].median() if not a.empty and a["land_value_ratio"].notna().any() else None,
        }
    return stats


def find_comps(target_row, candidates, n=5):
    """
    Find the n most similar listings to target_row from candidates.
    Returns a DataFrame sorted by similarity score (lower = more similar).
    """
    others = candidates[candidates.index != target_row.name].copy()
    if others.empty:
        return others

    others["_score"] = 0.0

    # Same neighborhood is critical
    others["_score"] += (others["neighborhood"] != target_row.get("neighborhood", "")).astype(float) * 10

    # Size similarity
    t_sqft = target_row.get("sqft")
    if pd.notna(t_sqft) and t_sqft > 0:
        others["_score"] += ((others["sqft"] - t_sqft).abs() / t_sqft).fillna(2) * 3

    # Lot size
    t_lot = target_row.get("lot_size")
    if pd.notna(t_lot) and t_lot > 0:
        others["_score"] += ((others["lot_size"] - t_lot).abs() / t_lot).fillna(2) * 2

    # Price
    t_price = target_row.get("price")
    if pd.notna(t_price) and t_price > 0:
        others["_score"] += ((others["price"] - t_price).abs() / t_price).fillna(2) * 2

    # Construction era
    t_year = target_row.get("year_built")
    if pd.notna(t_year):
        others["_score"] += ((others["year_built"] - t_year).abs() / 30).fillna(1)

    # Beds
    t_beds = target_row.get("beds")
    if pd.notna(t_beds):
        others["_score"] += (others["beds"] - t_beds).abs().fillna(2) * 0.5

    return others.nsmallest(n, "_score").drop(columns=["_score"])


def find_sold_comps(target_row, sold, n=5):
    """
    Find sold comps for an active listing.
    Returns (comps_df, sold_median_ppsf, premium_pct).
    """
    hood = target_row.get("neighborhood", "")
    hood_sold = sold[sold["neighborhood"] == hood].copy()

    if hood_sold.empty:
        return pd.DataFrame(), None, None

    # Score by similarity
    hood_sold["_score"] = 0.0
    t_sqft = target_row.get("sqft")
    if pd.notna(t_sqft) and t_sqft > 0:
        hood_sold["_score"] += ((hood_sold["sqft"] - t_sqft).abs() / t_sqft).fillna(2) * 3
    t_lot = target_row.get("lot_size")
    if pd.notna(t_lot) and t_lot > 0:
        hood_sold["_score"] += ((hood_sold["lot_size"] - t_lot).abs() / t_lot).fillna(2) * 2
    t_beds = target_row.get("beds")
    if pd.notna(t_beds):
        hood_sold["_score"] += (hood_sold["beds"] - t_beds).abs().fillna(2) * 0.5

    top = hood_sold.nsmallest(n, "_score").drop(columns=["_score"])

    sold_med_ppsf = hood_sold["price_per_sqft"].median()
    listing_ppsf = target_row.get("price_per_sqft")

    premium_pct = None
    if pd.notna(sold_med_ppsf) and pd.notna(listing_ppsf) and sold_med_ppsf > 0:
        premium_pct = ((listing_ppsf - sold_med_ppsf) / sold_med_ppsf) * 100

    return top, sold_med_ppsf, premium_pct


def find_overpriced(active, sold, threshold=1.4):
    """
    Flag active listings where $/sqft is significantly above neighborhood sold median.
    Returns a DataFrame with premium_pct column.
    """
    results = []
    for hood in active["neighborhood"].unique():
        hood_active = active[
            (active["neighborhood"] == hood) & active["price_per_sqft"].notna()
        ]
        hood_sold = sold[
            (sold["neighborhood"] == hood) & sold["price_per_sqft"].notna()
        ]

        if hood_sold.empty or hood_active.empty:
            continue

        baseline = hood_sold["price_per_sqft"].median()
        over = hood_active[hood_active["price_per_sqft"] > baseline * threshold].copy()
        if not over.empty:
            over["premium_pct"] = ((over["price_per_sqft"] - baseline) / baseline * 100).round(0)
            over["baseline_ppsf"] = baseline
            results.append(over)

    if results:
        return pd.concat(results).sort_values("premium_pct", ascending=False)
    return pd.DataFrame()


def find_stale(active):
    """Find listings with high DOM relative to their price segment."""
    segments = [
        (10_000_000, 20_000_000, "$10M-$20M", 90),
        (20_000_000, 40_000_000, "$20M-$40M", 120),
        (40_000_000, float("inf"), "$40M+", 150),
    ]
    results = []
    for low, high, label, threshold in segments:
        segment = active[
            (active["price"] >= low) &
            (active["price"] < high) &
            active["dom"].notna() &
            (active["dom"] > threshold)
        ].copy()
        if not segment.empty:
            segment["price_segment"] = label
            segment["dom_threshold"] = threshold
            results.append(segment)

    if results:
        return pd.concat(results).sort_values("dom", ascending=False)
    return pd.DataFrame()


def find_deals(active, sold):
    """
    Cross-reference active listings against sold $/sqft.
    Flags anything listed below the neighborhood's sold median $/sqft.
    """
    results = []
    for hood in active["neighborhood"].unique():
        hood_active = active[
            (active["neighborhood"] == hood) & active["price_per_sqft"].notna()
        ]
        hood_sold = sold[
            (sold["neighborhood"] == hood) & sold["price_per_sqft"].notna()
        ]

        if hood_sold.empty or hood_active.empty:
            continue

        sold_median = hood_sold["price_per_sqft"].median()
        deals = hood_active[hood_active["price_per_sqft"] < sold_median].copy()
        if not deals.empty:
            deals["discount_pct"] = ((deals["price_per_sqft"] - sold_median) / sold_median * 100).round(0)
            deals["sold_median_ppsf"] = sold_median
            results.append(deals)

    if results:
        return pd.concat(results).sort_values("discount_pct")
    return pd.DataFrame()


def find_teardown_candidates(active):
    """
    Identify likely teardown candidates: old construction on expensive land
    where the land value ratio is very high (buyer is paying for dirt, not the house).
    """
    candidates = active[
        active["land_value_ratio"].notna() &
        (active["land_value_ratio"] >= 0.75) &
        (active["year_built"] < 1990)
    ].copy()

    if not candidates.empty:
        candidates = candidates.sort_values("land_value_ratio", ascending=False)

    return candidates


def construction_analysis(active, sold):
    """
    Compare pricing by construction era across neighborhoods.
    Returns a DataFrame suitable for charting.
    """
    combined = pd.concat([
        active.assign(dataset="Active"),
        sold.assign(dataset="Sold")
    ])

    grouped = combined.groupby(["neighborhood", "construction_era"]).agg(
        count=("price", "size"),
        med_price=("price", "median"),
        med_ppsf=("price_per_sqft", "median"),
        avg_ppsf=("price_per_sqft", "mean"),
    ).reset_index()

    return grouped


def neighborhood_color(hood):
    """Return a consistent color for each neighborhood."""
    colors = {
        "Malibu Colony": "#3B82F6",      # Blue
        "Carbon Beach": "#F59E0B",        # Amber
        "Malibu Road": "#10B981",         # Emerald
        "Serra Retreat": "#8B5CF6",       # Purple
        "Malibu Cove Colony": "#EC4899",  # Pink
        "Escondido Beach": "#06B6D4",     # Cyan
        "Point Dume": "#EF4444",          # Red
        "Broad Beach": "#F97316",         # Orange
        "Western Malibu": "#6B7280",      # Gray
        "Malibu (Other)": "#9CA3AF",      # Light gray
    }
    return colors.get(hood, "#9CA3AF")


def neighborhood_color_rgb(hood):
    """Return RGB list for pydeck."""
    colors = {
        "Malibu Colony": [59, 130, 246],
        "Carbon Beach": [245, 158, 11],
        "Malibu Road": [16, 185, 129],
        "Serra Retreat": [139, 92, 246],
        "Malibu Cove Colony": [236, 72, 153],
        "Escondido Beach": [6, 182, 212],
        "Point Dume": [239, 68, 68],
        "Broad Beach": [249, 115, 22],
        "Western Malibu": [107, 114, 128],
        "Malibu (Other)": [156, 163, 175],
    }
    return colors.get(hood, [156, 163, 175])
