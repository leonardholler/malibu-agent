"""
Malibu Luxury Valuation Engine

Estimates fair market value for Malibu $10M+ properties by analyzing:
1. Micro-neighborhood comparable sales (sparse comps problem)
2. Construction age premium/depreciation — standing quality homes are
   worth significantly more than teardowns because Malibu permits are
   brutal and builds take years
3. Ocean-facing vs mountain-facing (e.g. Colony odd vs even numbers)
4. Land parcel vs improved property (separate valuation logic)
5. Size-adjusted comp-price methodology (appraiser approach)

This is NOT a Zestimate clone. It's built for a market where:
- Comps are sparse (maybe 5-15 relevant sales per neighborhood per year)
- A 1960s teardown and a 2024 new build on the same street can differ 3x
- Land value often exceeds improvement value
- Building permits in Malibu take 2-5 years and sometimes get denied
- Micro-location (beachfront vs bluff, odd vs even on Colony) matters hugely
- $/sqft drops sharply as property size increases
"""

import re
import pandas as pd
import numpy as np
from data_loader import load_data, NEIGHBORHOODS, CONSTRUCTION_ERAS


# Minimum viable sqft — below this is a land parcel, not a home
MIN_COMP_SQFT = 500
# Max credible $/sqft — above this is a data error
MAX_COMP_PPSF = 12_000


# ── Colony odd/even distinction ─────────────────────────────────────────────
# On Malibu Colony Road, even-numbered addresses face the ocean.
# Odd-numbered addresses face the mountains (Malibu Lagoon side).
# This is one of the biggest price differentiators on the entire street.

def _colony_ocean_facing(address):
    """
    Returns True if the property is on the ocean side of Malibu Colony Road.
    Even numbers face the ocean, odd numbers face the mountains.
    """
    if "malibu colony" not in address.lower():
        return None
    m = re.match(r"(\d+)", address)
    if not m:
        return None
    return int(m.group(1)) % 2 == 0


def _colony_multiplier(address):
    """
    Ocean-facing Colony homes command a significant premium over
    mountain-facing homes. Odd addresses face the lagoon/mountains
    and should be valued ~30% below even (ocean) addresses.
    """
    facing = _colony_ocean_facing(address)
    if facing is None:
        return 1.0
    return 1.0 if facing else 0.72  # mountain-facing discount


# ── Construction & Location multipliers ─────────────────────────────────────

def _construction_multiplier(year_built):
    """
    Premium for standing quality improvements. In Malibu, building from
    scratch takes 2-5+ years (permits, coastal commission, environmental
    review). A standing, permitted, quality home is therefore worth
    significantly more per sqft than a teardown on the same lot.

    Range: 1.15x (new build) to 0.65x (pre-1970 teardown candidate).
    """
    if pd.isna(year_built):
        return 1.0
    if year_built >= 2020:
        return 1.15
    if year_built >= 2010:
        return 1.08
    if year_built >= 2000:
        return 1.0
    if year_built >= 1990:
        return 0.92
    if year_built >= 1980:
        return 0.82
    if year_built >= 1970:
        return 0.72
    return 0.65


def _beach_proximity_multiplier(neighborhood):
    """
    Beachfront neighborhoods command a premium over hillside/canyon.
    Moderate range — combined with construction multiplier, max total
    factor is ~1.15 × 1.18 = 1.36x.
    """
    premiums = {
        "Malibu Colony": 1.18,
        "Carbon Beach": 1.18,
        "Malibu Road": 1.10,
        "Malibu Cove Colony": 1.06,
        "Escondido Beach": 1.03,
        "Point Dume": 1.0,
        "Broad Beach": 1.06,
        "Serra Retreat": 0.90,
        "Western Malibu": 0.88,
    }
    return premiums.get(neighborhood, 0.95)


# ── Development difficulty discount ─────────────────────────────────────────
# Malibu is one of the hardest places in the US to get building permits.
# Coastal Commission reviews, ESHA (environmentally sensitive habitat),
# view preservation ordinances, septic requirements, fire rebuilds...
# A lot without a standing home is worth significantly less than one with,
# because you're buying 2-5 years of permitting risk on top of construction.

def _development_difficulty_discount(target):
    """
    Returns a multiplier (< 1.0) ONLY for actual land parcels where the
    buyer would need to build from scratch. Reflects the real cost and
    risk of Malibu permitting (2-5+ years).

    IMPORTANT: Old houses (even pre-1970 teardown candidates) do NOT get
    this discount — they have a standing, permitted structure which has
    real value. The construction multiplier already handles age/condition.
    A standing house means you can live in it, rent it, or use the existing
    permit footprint for renovation. An empty lot means years of permitting.
    """
    is_land = target.get("is_land_parcel", False)
    sqft = target.get("sqft")
    year = target.get("year_built")

    # Only actual land parcels (no structure at all)
    if is_land or (pd.isna(sqft) and pd.isna(year)):
        return 0.45  # Land-only: ~45% of improved value

    return 1.0  # Standing structure — no development discount


# ── Core valuation ──────────────────────────────────────────────────────────

def _clean_comps(df):
    """Remove data-quality outliers that would skew the valuation."""
    mask = pd.Series(True, index=df.index)
    if "sqft" in df.columns:
        mask &= df["sqft"].isna() | (df["sqft"] >= MIN_COMP_SQFT)
    if "price_per_sqft" in df.columns:
        mask &= df["price_per_sqft"].isna() | (df["price_per_sqft"] <= MAX_COMP_PPSF)
    # Exclude land parcels from house comps
    if "is_land_parcel" in df.columns:
        mask &= ~df["is_land_parcel"].fillna(False)
    return df[mask].copy()


def estimate_fair_value(target, active, sold):
    """
    Estimate fair market value for a property using the comparable
    sales adjustment method (same approach real appraisers use).

    Instead of extracting $/sqft and multiplying back (which breaks on
    size-variant comps), we adjust each comp's sale price directly for
    differences in size, construction age, location, and ocean-facing.
    """
    hood = target.get("neighborhood", "Malibu (Other)")
    t_sqft = target.get("sqft")
    t_lot = target.get("lot_size")
    t_year = target.get("year_built")
    t_price = target.get("price")
    t_beds = target.get("beds")
    t_address = target.get("address", "")
    is_land = target.get("is_land_parcel", False)

    # ── Step 1: Find comparable sold properties ──────────────────────────
    hood_sold = _clean_comps(sold[sold["neighborhood"] == hood])

    adjacent = {
        "Malibu Colony": ["Carbon Beach", "Malibu Road"],
        "Carbon Beach": ["Malibu Colony", "Malibu Road"],
        "Malibu Road": ["Malibu Colony", "Carbon Beach", "Escondido Beach"],
        "Malibu Cove Colony": ["Escondido Beach", "Point Dume"],
        "Escondido Beach": ["Malibu Cove Colony", "Malibu Road"],
        "Point Dume": ["Malibu Cove Colony", "Broad Beach"],
        "Broad Beach": ["Point Dume", "Western Malibu"],
        "Serra Retreat": ["Malibu Road", "Carbon Beach"],
        "Western Malibu": ["Broad Beach"],
        "Malibu (Other)": ["Carbon Beach", "Malibu Colony", "Malibu Road"],
    }

    if len(hood_sold) < 3 and hood in adjacent:
        for adj_hood in adjacent[hood]:
            adj_sold = _clean_comps(sold[sold["neighborhood"] == adj_hood])
            hood_sold = pd.concat([hood_sold, adj_sold])

    if hood_sold.empty:
        return {
            "estimated_value": None,
            "confidence": "insufficient_data",
            "reasoning": f"No comparable sales found in or near {hood}.",
        }

    # ── Step 2: Score comps by similarity ────────────────────────────────
    hood_sold = hood_sold.copy()
    hood_sold["_score"] = 0.0

    # Same neighborhood bonus
    hood_sold["_score"] += (hood_sold["neighborhood"] != hood).astype(float) * 5

    # Sqft similarity (high weight — size drives price in luxury)
    if pd.notna(t_sqft) and t_sqft > 0:
        hood_sold["_score"] += ((hood_sold["sqft"] - t_sqft).abs() / t_sqft).fillna(2) * 5

    # Lot size similarity
    if pd.notna(t_lot) and t_lot > 0:
        hood_sold["_score"] += ((hood_sold["lot_size"] - t_lot).abs() / t_lot).fillna(2) * 2

    # Construction era similarity
    if pd.notna(t_year):
        hood_sold["_score"] += ((hood_sold["year_built"] - t_year).abs() / 20).fillna(2) * 3

    # Beds similarity
    if pd.notna(t_beds):
        hood_sold["_score"] += (hood_sold["beds"] - t_beds).abs().fillna(2) * 0.5

    # Colony ocean-facing match (huge penalty for mixing ocean/mountain)
    t_colony_facing = _colony_ocean_facing(t_address)
    if t_colony_facing is not None:
        for idx, row in hood_sold.iterrows():
            c_facing = _colony_ocean_facing(str(row.get("address", "")))
            if c_facing is not None and c_facing != t_colony_facing:
                hood_sold.at[idx, "_score"] += 8  # Heavy penalty

    # Take top comps
    top_comps = hood_sold.nsmallest(8, "_score")
    best_comps = top_comps.head(5)
    comp_count = len(best_comps[best_comps["price"].notna()])

    # ── Step 3: Comp-price adjustment (appraiser method) ────────────────
    usable_comps = best_comps[best_comps["price"].notna()].copy()
    if usable_comps.empty:
        usable_comps = hood_sold[hood_sold["price"].notna()].head(10)

    if usable_comps.empty:
        return {
            "estimated_value": None,
            "confidence": "insufficient_data",
            "reasoning": f"No price data available for comps in {hood}.",
        }

    target_mult = _construction_multiplier(t_year)
    beach_mult = _beach_proximity_multiplier(hood)
    colony_mult = _colony_multiplier(t_address)
    dev_discount = _development_difficulty_discount(target)

    usable_comps["_comp_construction"] = usable_comps["year_built"].apply(
        _construction_multiplier
    )
    usable_comps["_comp_beach"] = usable_comps["neighborhood"].apply(
        _beach_proximity_multiplier
    )
    usable_comps["_comp_colony"] = usable_comps["address"].apply(
        lambda a: _colony_multiplier(str(a))
    )

    # For each comp, adjust its sale price as if it were the target property
    adjusted_prices = []
    for _, c in usable_comps.iterrows():
        adj = c["price"]

        # Size adjustment: price scales sub-linearly with sqft
        # (exponent 0.7 → doubling sqft = 1.62x price, not 2x)
        c_sqft = c.get("sqft")
        if pd.notna(t_sqft) and t_sqft > 0 and pd.notna(c_sqft) and c_sqft > 0:
            adj *= (t_sqft / c_sqft) ** 0.7

        # Construction age adjustment
        if c["_comp_construction"] > 0:
            adj *= target_mult / c["_comp_construction"]

        # Location adjustment (if comp is from different neighborhood)
        if c["_comp_beach"] > 0:
            adj *= beach_mult / c["_comp_beach"]

        # Colony ocean-facing adjustment
        if c["_comp_colony"] > 0:
            adj *= colony_mult / c["_comp_colony"]

        adjusted_prices.append(adj)

    usable_comps["_adjusted_price"] = adjusted_prices

    # Remove outlier adjusted prices (>2x or <0.4x the median)
    med_adj = usable_comps["_adjusted_price"].median()
    inlier_mask = (
        (usable_comps["_adjusted_price"] <= med_adj * 2.0)
        & (usable_comps["_adjusted_price"] >= med_adj * 0.4)
    )
    if inlier_mask.sum() >= 2:
        usable_comps = usable_comps[inlier_mask].copy()

    # Use median when comp variance is high (CV > 0.5)
    adj_prices = usable_comps["_adjusted_price"]
    cv = adj_prices.std() / adj_prices.mean() if adj_prices.mean() > 0 else 0
    high_variance = cv > 0.5

    if high_variance or len(usable_comps) <= 2:
        estimated_value = adj_prices.median()
    else:
        weights = 1 / (usable_comps["_score"] + 0.1)
        estimated_value = np.average(adj_prices, weights=weights)

    # Apply development difficulty discount (land parcels, teardowns)
    estimated_value *= dev_discount

    # Compute effective $/sqft for display
    if pd.notna(t_sqft) and t_sqft > 0:
        adjusted_ppsf = estimated_value / t_sqft
    else:
        med_ppsf = usable_comps["price_per_sqft"].median()
        adjusted_ppsf = med_ppsf if pd.notna(med_ppsf) else 0
    baseline_ppsf = adjusted_ppsf / max(target_mult * beach_mult, 0.01)

    # ── Step 4: Land vs improvement split ────────────────────────────────
    if is_land or (pd.isna(t_sqft) and pd.isna(t_year)):
        land_pct = 0.95  # Land parcel: almost all land value
    elif pd.notna(t_year):
        if t_year >= 2015:
            land_pct = 0.40
        elif t_year >= 2000:
            land_pct = 0.55
        elif t_year >= 1985:
            land_pct = 0.65
        elif t_year >= 1970:
            land_pct = 0.75
        else:
            land_pct = 0.85
    else:
        land_pct = 0.60

    if hood in ["Malibu Colony", "Carbon Beach", "Malibu Road", "Broad Beach"]:
        land_pct = min(land_pct + 0.05, 0.95)

    land_value = estimated_value * land_pct
    improvement_value = estimated_value * (1 - land_pct)

    # ── Step 5: Confidence assessment ────────────────────────────────────
    same_hood_comps = len(best_comps[best_comps["neighborhood"] == hood])
    has_sqft = pd.notna(t_sqft) and t_sqft >= MIN_COMP_SQFT

    if comp_count >= 4 and same_hood_comps >= 3 and has_sqft and not high_variance:
        confidence = "high"
    elif comp_count >= 2 and has_sqft and not high_variance:
        confidence = "medium"
    else:
        confidence = "low"

    # ── Step 6: Price assessment ─────────────────────────────────────────
    price_assessment = None
    price_diff_pct = None
    if pd.notna(t_price) and estimated_value:
        price_diff_pct = ((t_price - estimated_value) / estimated_value) * 100
        if price_diff_pct > 15:
            price_assessment = "overpriced"
        elif price_diff_pct < -10:
            price_assessment = "underpriced"
        else:
            price_assessment = "fair"

    # ── Step 7: Build reasoning ──────────────────────────────────────────
    reasoning_parts = []
    reasoning_parts.append(
        f"Based on {comp_count} comparable sales in {hood}"
        + (f" and nearby areas" if same_hood_comps < comp_count else "")
        + "."
    )

    if is_land or (pd.isna(t_sqft) and pd.isna(t_year)):
        reasoning_parts.append(
            "This appears to be a land parcel or unimproved lot. "
            "Valued at a significant discount to improved properties because "
            "Malibu development permits typically take 2-5+ years."
        )

    if pd.notna(t_year):
        era_label = (
            "new build" if t_year >= 2015
            else "recent renovation" if t_year >= 2000
            else "older construction" if t_year >= 1985
            else "vintage/teardown candidate"
        )
        reasoning_parts.append(
            f"Built in {int(t_year)} ({era_label}) — construction multiplier {target_mult:.2f}x."
        )

    # Colony-specific reasoning
    colony_facing = _colony_ocean_facing(t_address)
    if colony_facing is not None:
        side = "ocean-facing (even side)" if colony_facing else "mountain/lagoon-facing (odd side)"
        reasoning_parts.append(
            f"Malibu Colony {side}. "
            + ("Premium location with direct beach access." if colony_facing
               else "No ocean frontage — valued below ocean-side comparables.")
        )

    if dev_discount < 1.0:
        discount_pct = round((1 - dev_discount) * 100)
        reasoning_parts.append(
            f"Development difficulty discount: {discount_pct}% reduction reflecting "
            f"Malibu's 2-5 year permit timeline and Coastal Commission requirements."
        )

    reasoning_parts.append(
        f"Estimated land value: ${land_value:,.0f} ({land_pct:.0%}) | "
        f"Improvement value: ${improvement_value:,.0f} ({1-land_pct:.0%})."
    )

    if price_assessment and pd.notna(t_price):
        if price_assessment == "overpriced":
            reasoning_parts.append(
                f"Listed at ${t_price:,.0f} — {price_diff_pct:+.0f}% above estimated fair value. "
                f"Consider negotiating or waiting for a price reduction."
            )
        elif price_assessment == "underpriced":
            reasoning_parts.append(
                f"Listed at ${t_price:,.0f} — {price_diff_pct:+.0f}% below estimated fair value. "
                f"Potential value opportunity."
            )
        else:
            reasoning_parts.append(
                f"Listed at ${t_price:,.0f} — {price_diff_pct:+.0f}% vs estimate. Priced in line with market."
            )

    # Format comps for output
    comp_list = []
    for _, c in best_comps.iterrows():
        comp_list.append({
            "address": c.get("address", ""),
            "price": int(c["price"]) if pd.notna(c.get("price")) else None,
            "sqft": int(c["sqft"]) if pd.notna(c.get("sqft")) else None,
            "price_per_sqft": int(c["price_per_sqft"]) if pd.notna(c.get("price_per_sqft")) else None,
            "year_built": int(c["year_built"]) if pd.notna(c.get("year_built")) else None,
            "neighborhood": c.get("neighborhood", ""),
            "sold_date": c.get("sold_date", ""),
        })

    return {
        "estimated_value": round(estimated_value),
        "adjusted_ppsf": round(adjusted_ppsf),
        "confidence": confidence,
        "price_assessment": price_assessment,
        "price_diff_pct": round(price_diff_pct, 1) if price_diff_pct is not None else None,
        "value_breakdown": {
            "land_value": round(land_value),
            "land_pct": round(land_pct * 100),
            "improvement_value": round(improvement_value),
            "improvement_pct": round((1 - land_pct) * 100),
        },
        "construction_analysis": {
            "year_built": int(t_year) if pd.notna(t_year) else None,
            "multiplier": target_mult,
            "beach_multiplier": beach_mult,
            "colony_multiplier": colony_mult if colony_mult != 1.0 else None,
            "dev_discount": dev_discount if dev_discount < 1.0 else None,
            "baseline_ppsf": round(baseline_ppsf),
        },
        "ocean_facing": colony_facing,
        "is_land_parcel": bool(is_land) if is_land else None,
        "comp_count": comp_count,
        "comps": comp_list,
        "reasoning": " ".join(reasoning_parts),
    }


def valuate_all_active(active, sold):
    """Run valuation on all active listings. Returns list of results."""
    results = []
    for idx, row in active.iterrows():
        val = estimate_fair_value(row, active, sold)
        val["address"] = row.get("address", "")
        val["listed_price"] = int(row["price"]) if pd.notna(row.get("price")) else None
        val["neighborhood"] = row.get("neighborhood", "")
        val["beds"] = int(row["beds"]) if pd.notna(row.get("beds")) else None
        val["baths"] = float(row["baths"]) if pd.notna(row.get("baths")) else None
        val["sqft"] = int(row["sqft"]) if pd.notna(row.get("sqft")) else None
        val["lot_size"] = int(row["lot_size"]) if pd.notna(row.get("lot_size")) else None
        val["year_built"] = int(row["year_built"]) if pd.notna(row.get("year_built")) else None
        val["dom"] = int(row["dom"]) if pd.notna(row.get("dom")) else None
        val["url"] = row.get("url", "")
        results.append(val)
    return results
