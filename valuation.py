"""
Malibu Luxury Valuation Engine

Estimates fair market value for Malibu $10M+ properties using a
comparable-sales adjustment model (the same method licensed appraisers use).

Key design decisions:
1. Price-tier-aware comp selection — a $60M listing never pulls $11M comps
2. Log-ratio scoring — penalizes comps from different price tiers symmetrically
3. Moderate construction multipliers — real data shows pre-1970 trades at only
   ~10-15% below new builds in beachfront Malibu, not 35%
4. Scraped-keyword intelligence — burned lots, no-view properties, confirmed
   oceanfront all adjust the estimate
5. Ultra-luxury scarcity adjustment — when comps are thin (>2.5x gap), uses a
   damped pull toward listed price with forced low confidence
6. Confidence-based divergence cap — prevents embarrassing 400% errors
"""

import re
import pandas as pd
import numpy as np
from data_loader import load_data, NEIGHBORHOODS, CONSTRUCTION_ERAS


MIN_COMP_SQFT = 500
MAX_COMP_PPSF = 15_000


# ── Colony odd/even distinction ─────────────────────────────────────────────

def _colony_ocean_facing(address):
    """Even numbers face ocean, odd face mountains on Malibu Colony Road."""
    if "malibu colony" not in address.lower():
        return None
    m = re.match(r"(\d+)", address)
    if not m:
        return None
    return int(m.group(1)) % 2 == 0


def _colony_multiplier(address):
    """Ocean-facing Colony = 1.0x, mountain-facing = 0.72x."""
    facing = _colony_ocean_facing(address)
    if facing is None:
        return 1.0
    return 1.0 if facing else 0.72


# ── Construction & Location multipliers ─────────────────────────────────────

def _construction_multiplier(year_built):
    """
    Moderated range: 1.10x (new build) to 0.85x (pre-1970).

    Real sold data shows pre-1970 beachfront trades at only ~10-15% below
    equivalent new builds. The old 0.65x multiplier was 3x too harsh.
    Standing structures in Malibu have enormous permit value.
    """
    if pd.isna(year_built):
        return 1.0
    if year_built >= 2020:
        return 1.10
    if year_built >= 2010:
        return 1.05
    if year_built >= 2000:
        return 1.0
    if year_built >= 1990:
        return 0.95
    if year_built >= 1980:
        return 0.92
    if year_built >= 1970:
        return 0.88
    return 0.85


def _beach_proximity_multiplier(neighborhood):
    """Beachfront premium over hillside/canyon."""
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

def _development_difficulty_discount(target):
    """
    0.45x ONLY for confirmed land parcels. Uses scraped keywords to avoid
    false positives — properties with "burned" tag treated as land,
    properties with "pool"/"guest_house" etc. are NOT land even if CSV
    data is missing sqft/year.
    """
    is_land = target.get("is_land_parcel", False)
    sqft = target.get("sqft")
    year = target.get("year_built")
    keywords = target.get("scraped_keywords", [])
    if not isinstance(keywords, list):
        keywords = []

    # Burned = land parcel (structure is destroyed)
    if "burned" in keywords:
        return 0.45

    # Scraped description indicates improvements exist → not land
    improvement_indicators = {"pool", "guest_house", "renovated", "new_build",
                              "gated", "bluff"}
    if improvement_indicators & set(keywords):
        return 1.0  # Has improvements, not a land parcel

    # Only actual land parcels (no structure)
    if is_land or (pd.isna(sqft) and pd.isna(year)):
        # Check if listed price suggests improvements (land parcels rarely list >$20M)
        price = target.get("price")
        if pd.notna(price) and price > 25_000_000:
            return 0.75  # Likely improved, just missing data
        return 0.55

    return 1.0


def _scraped_beach_adjustment(neighborhood, keywords):
    """Adjust beach premium based on scraped listing description."""
    if not isinstance(keywords, list) or not keywords:
        return 1.0

    beachfront_hoods = {"Malibu Colony", "Carbon Beach", "Malibu Road",
                        "Broad Beach", "Malibu Cove Colony", "Escondido Beach"}

    if neighborhood not in beachfront_hoods:
        return 1.0

    if "no_view" in keywords and "ocean_view" not in keywords:
        return 0.88

    if "oceanfront" in keywords or "beachfront" in keywords:
        return 1.04

    return 1.0


# ── Core valuation ──────────────────────────────────────────────────────────

def _clean_comps(df):
    """Remove data-quality outliers that would skew the valuation."""
    mask = pd.Series(True, index=df.index)
    if "sqft" in df.columns:
        mask &= df["sqft"].isna() | (df["sqft"] >= MIN_COMP_SQFT)
    if "price_per_sqft" in df.columns:
        mask &= df["price_per_sqft"].isna() | (df["price_per_sqft"] <= MAX_COMP_PPSF)
    if "is_land_parcel" in df.columns:
        mask &= ~df["is_land_parcel"].fillna(False)
    return df[mask].copy()


def estimate_fair_value(target, active, sold):
    """
    Estimate fair market value using comparable sales adjustment.

    Key improvements over naive $/sqft:
    - Price-tier-aware comp selection (log-ratio penalty)
    - Sub-linear size adjustment (power-law 0.7)
    - Ultra-luxury scarcity detection with damped adjustment
    - Confidence-based divergence cap
    """
    hood = target.get("neighborhood", "Malibu (Other)")
    t_sqft = target.get("sqft")
    t_lot = target.get("lot_size")
    t_year = target.get("year_built")
    t_price = target.get("price")
    t_beds = target.get("beds")
    t_address = target.get("address", "")
    is_land = target.get("is_land_parcel", False)
    t_keywords = target.get("scraped_keywords", [])
    if not isinstance(t_keywords, list):
        t_keywords = []

    # ── Step 1: Find comparable sold properties ──────────────────────────
    hood_sold = _clean_comps(sold[sold["neighborhood"] == hood])

    adjacent = {
        "Malibu Colony": ["Carbon Beach", "Malibu Road"],
        "Carbon Beach": ["Malibu Colony", "Malibu Road"],
        "Malibu Road": ["Malibu Colony", "Carbon Beach", "Escondido Beach"],
        "Malibu Cove Colony": ["Escondido Beach", "Point Dume"],
        "Escondido Beach": ["Malibu Cove Colony", "Malibu Road"],
        "Point Dume": ["Malibu Cove Colony", "Broad Beach", "Escondido Beach"],
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

    # Price-tier scoring (LOG-RATIO — the key fix for ultra-luxury)
    # A $12M comp for a $60M listing gets penalized; $40M comp is preferred
    if pd.notna(t_price) and t_price > 0:
        price_ratio = (hood_sold["price"] / t_price).clip(0.1, 10)
        hood_sold["_score"] += price_ratio.apply(lambda r: abs(np.log(r))) * 4

    # Sqft similarity (reduced NaN penalty from 2.0 to 0.8)
    if pd.notna(t_sqft) and t_sqft > 0:
        hood_sold["_score"] += ((hood_sold["sqft"] - t_sqft).abs() / t_sqft).fillna(0.8) * 5

    # Lot size similarity
    if pd.notna(t_lot) and t_lot > 0:
        hood_sold["_score"] += ((hood_sold["lot_size"] - t_lot).abs() / t_lot).fillna(0.8) * 2

    # Construction era similarity
    if pd.notna(t_year):
        hood_sold["_score"] += ((hood_sold["year_built"] - t_year).abs() / 20).fillna(1) * 2

    # Beds similarity
    if pd.notna(t_beds):
        hood_sold["_score"] += (hood_sold["beds"] - t_beds).abs().fillna(1) * 0.5

    # Colony ocean-facing match
    t_colony_facing = _colony_ocean_facing(t_address)
    if t_colony_facing is not None:
        for idx, row in hood_sold.iterrows():
            c_facing = _colony_ocean_facing(str(row.get("address", "")))
            if c_facing is not None and c_facing != t_colony_facing:
                hood_sold.at[idx, "_score"] += 8

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
    scraped_adj = _scraped_beach_adjustment(hood, t_keywords)
    beach_mult *= scraped_adj
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

    adjusted_prices = []
    for _, c in usable_comps.iterrows():
        adj = c["price"]

        # Size adjustment (power-law 0.7)
        c_sqft = c.get("sqft")
        if pd.notna(t_sqft) and t_sqft > 0 and pd.notna(c_sqft) and c_sqft > 0:
            adj *= (t_sqft / c_sqft) ** 0.7

        # Construction age adjustment
        if c["_comp_construction"] > 0:
            adj *= target_mult / c["_comp_construction"]

        # Location adjustment
        if c["_comp_beach"] > 0:
            adj *= beach_mult / c["_comp_beach"]

        # Colony ocean-facing adjustment
        if c["_comp_colony"] > 0:
            adj *= colony_mult / c["_comp_colony"]

        adjusted_prices.append(adj)

    usable_comps["_adjusted_price"] = adjusted_prices

    # Remove outlier adjusted prices (>2.5x or <0.35x the median)
    med_adj = usable_comps["_adjusted_price"].median()
    inlier_mask = (
        (usable_comps["_adjusted_price"] <= med_adj * 2.5)
        & (usable_comps["_adjusted_price"] >= med_adj * 0.35)
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

    # ── Ultra-luxury scarcity adjustment ─────────────────────────────────
    # When listed price >> comp median, comps are from a different tier.
    # Use a damped pull toward listed price (not blind trust, but
    # acknowledgement that the comp pool is inadequate).
    ultra_luxury_applied = False
    if pd.notna(t_price) and t_price > 0 and estimated_value > 0:
        price_to_comp = t_price / estimated_value
        if price_to_comp > 2.0:
            # Damped adjustment: pull toward listed price but don't trust it fully
            scarcity_mult = min(price_to_comp ** 0.40, 2.5)
            estimated_value = estimated_value * scarcity_mult
            ultra_luxury_applied = True

    # Apply development difficulty discount
    estimated_value *= dev_discount

    # ── Confidence assessment ────────────────────────────────────────────
    same_hood_comps = len(best_comps[best_comps["neighborhood"] == hood])
    has_sqft = pd.notna(t_sqft) and t_sqft >= MIN_COMP_SQFT

    if ultra_luxury_applied:
        confidence = "low"  # Always low when scarcity adjustment was needed
    elif comp_count >= 4 and same_hood_comps >= 3 and has_sqft and not high_variance:
        confidence = "high"
    elif comp_count >= 2 and has_sqft and not high_variance:
        confidence = "medium"
    else:
        confidence = "low"

    # ── Confidence-based divergence cap ──────────────────────────────────
    # Prevents embarrassing 400% errors by capping how far the estimate
    # can diverge from listed price based on confidence level.
    if pd.notna(t_price) and t_price > 0 and estimated_value > 0:
        divergence = abs(estimated_value - t_price) / t_price
        max_divergence = {"high": 0.40, "medium": 0.35, "low": 0.30}
        cap = max_divergence.get(confidence, 0.50)
        if divergence > cap:
            if estimated_value > t_price:
                estimated_value = t_price * (1 + cap)
            else:
                estimated_value = t_price * (1 - cap)

    # Effective $/sqft
    if pd.notna(t_sqft) and t_sqft > 0:
        adjusted_ppsf = estimated_value / t_sqft
    else:
        med_ppsf = usable_comps["price_per_sqft"].median()
        adjusted_ppsf = med_ppsf if pd.notna(med_ppsf) else 0
    baseline_ppsf = adjusted_ppsf / max(target_mult * beach_mult, 0.01)

    # ── Land vs improvement split ────────────────────────────────────────
    if is_land or (pd.isna(t_sqft) and pd.isna(t_year)):
        land_pct = 0.95
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

    # ── Price assessment ─────────────────────────────────────────────────
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

    # ── Reasoning ────────────────────────────────────────────────────────
    reasoning_parts = []
    reasoning_parts.append(
        f"Based on {comp_count} comparable sales in {hood}"
        + (f" and nearby areas" if same_hood_comps < comp_count else "")
        + "."
    )

    if ultra_luxury_applied:
        reasoning_parts.append(
            "Ultra-luxury tier: comparable sales are sparse at this price point. "
            "Estimate uses scarcity-adjusted valuation with reduced confidence."
        )

    if is_land or (pd.isna(t_sqft) and pd.isna(t_year)):
        if not any(k in t_keywords for k in ("pool", "guest_house", "renovated", "gated")):
            reasoning_parts.append(
                "Appears to be a land parcel or unimproved lot. "
                "Valued at a discount reflecting Malibu's 2-5+ year permit timeline."
            )

    if pd.notna(t_year):
        era_label = (
            "new build" if t_year >= 2015
            else "recent construction" if t_year >= 2000
            else "older construction" if t_year >= 1985
            else "vintage construction"
        )
        reasoning_parts.append(
            f"Built in {int(t_year)} ({era_label}) — construction multiplier {target_mult:.2f}x."
        )

    colony_facing = _colony_ocean_facing(t_address)
    if colony_facing is not None:
        side = "ocean-facing (even side)" if colony_facing else "mountain/lagoon-facing (odd side)"
        reasoning_parts.append(
            f"Malibu Colony {side}. "
            + ("Premium location with direct beach access." if colony_facing
               else "No ocean frontage — valued below ocean-side comparables.")
        )

    if "burned" in t_keywords:
        reasoning_parts.append(
            "Listing data indicates fire damage — valued as a land parcel."
        )
    if scraped_adj < 1.0:
        reasoning_parts.append(
            "Listing description indicates no ocean view — beach premium reduced."
        )
    elif scraped_adj > 1.0:
        reasoning_parts.append(
            "Listing confirms direct oceanfront/beachfront — premium applied."
        )

    if dev_discount < 1.0:
        discount_pct = round((1 - dev_discount) * 100)
        reasoning_parts.append(
            f"Development difficulty discount: {discount_pct}% reflecting "
            f"Malibu permitting risk."
        )

    reasoning_parts.append(
        f"Land value: ${land_value:,.0f} ({land_pct:.0%}) | "
        f"Improvement value: ${improvement_value:,.0f} ({1-land_pct:.0%})."
    )

    if price_assessment and pd.notna(t_price):
        if price_assessment == "overpriced":
            reasoning_parts.append(
                f"Listed at ${t_price:,.0f} — {price_diff_pct:+.0f}% above fair value."
            )
        elif price_assessment == "underpriced":
            reasoning_parts.append(
                f"Listed at ${t_price:,.0f} — {price_diff_pct:+.0f}% below fair value. "
                f"Potential value opportunity."
            )
        else:
            reasoning_parts.append(
                f"Listed at ${t_price:,.0f} — priced in line with market."
            )

    # ── "Why This Price" — human-readable explanation ─────────────────────
    explain_parts = []

    # Opening sentence with estimate and comp basis
    if estimated_value and comp_count:
        est_str = f"${estimated_value / 1e6:,.1f}M"
        hood_label = hood if same_hood_comps >= comp_count else f"{hood} and nearby areas"
        explain_parts.append(
            f"Estimated at {est_str} based on {comp_count} comparable sale{'s' if comp_count > 1 else ''} in {hood_label}."
        )

    # Adjustments applied
    adjustments = []
    if target_mult != 1.0 and pd.notna(t_year):
        pct = round((target_mult - 1.0) * 100)
        direction = "+" if pct > 0 else ""
        label = "new construction premium" if pct > 0 else f"age (built {int(t_year)})"
        adjustments.append(f"{direction}{pct}% for {label}")
    if beach_mult != 1.0:
        pct = round((beach_mult - 1.0) * 100)
        direction = "+" if pct > 0 else ""
        if scraped_adj > 1.0:
            adjustments.append(f"{direction}{pct}% for ocean frontage")
        elif scraped_adj < 1.0:
            adjustments.append(f"{direction}{pct}% for location (no ocean view)")
        else:
            label = "beachfront premium" if pct > 0 else "non-beachfront location"
            adjustments.append(f"{direction}{pct}% for {label}")
    if colony_mult != 1.0:
        pct = round((colony_mult - 1.0) * 100)
        direction = "+" if pct > 0 else ""
        side = "ocean-facing" if colony_mult == 1.0 else "mountain-side"
        adjustments.append(f"{direction}{pct}% for Colony {side}")
    if dev_discount < 1.0:
        pct = round((1.0 - dev_discount) * 100)
        adjustments.append(f"-{pct}% development/land discount")

    if adjustments:
        explain_parts.append("Adjusted " + ", ".join(adjustments) + ".")

    if ultra_luxury_applied:
        explain_parts.append(
            "Scarcity adjustment applied — few comparable sales exist at this price tier."
        )

    # Closest comp
    if not usable_comps.empty:
        closest = usable_comps.iloc[0]
        c_addr = closest.get("address", "")
        c_price = closest.get("price")
        c_date = closest.get("sold_date", "")
        if c_addr and pd.notna(c_price):
            date_str = f" in {c_date}" if c_date else ""
            explain_parts.append(
                f"Closest comp: {c_addr} sold at ${c_price / 1e6:,.1f}M{date_str}."
            )

    why_this_price = " ".join(explain_parts)

    # Format comps
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
        "why_this_price": why_this_price,
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
        val["lat"] = float(row["lat"]) if pd.notna(row.get("lat")) else None
        val["lng"] = float(row["lng"]) if pd.notna(row.get("lng")) else None
        results.append(val)
    return results
