"""
Malibu Agent API — Fair market value estimation for Malibu luxury real estate.

Endpoints:
  GET  /api/listings          — All active listings with valuations
  GET  /api/listing/{address} — Single listing detail + valuation
  GET  /api/neighborhoods     — Neighborhood stats and descriptions
  GET  /api/valuation/{address} — Deep valuation with comps and reasoning
  GET  /                      — Serves the frontend
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import pandas as pd
import os
from data_loader import load_data, NEIGHBORHOODS
from valuation import estimate_fair_value, valuate_all_active
from analysis import (
    market_overview, find_deals, find_overpriced, find_stale,
    fmt_price, neighborhood_color,
)

app = FastAPI(title="Malibu Agent", version="1.0.0")

# ── Load data once at startup ────────────────────────────────────────────────
active, sold = load_data()

# Pre-compute valuations for all active listings
_valuations_cache = None


def _get_valuations():
    global _valuations_cache
    if _valuations_cache is None:
        _valuations_cache = valuate_all_active(active, sold)
    return _valuations_cache


# ── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/listings")
def get_listings(
    neighborhood: str = Query(None),
    min_price: int = Query(None),
    max_price: int = Query(None),
    sort: str = Query("price_diff_pct"),  # price, value, price_diff_pct, dom
):
    """All active listings with fair value estimates."""
    results = _get_valuations()

    if neighborhood:
        results = [r for r in results if r["neighborhood"] == neighborhood]
    if min_price:
        results = [r for r in results if r.get("listed_price") and r["listed_price"] >= min_price]
    if max_price:
        results = [r for r in results if r.get("listed_price") and r["listed_price"] <= max_price]

    # Sort
    def sort_key(r):
        if sort == "price":
            return r.get("listed_price") or 0
        elif sort == "value":
            return r.get("estimated_value") or 0
        elif sort == "price_diff_pct":
            return r.get("price_diff_pct") or 0
        elif sort == "dom":
            return r.get("dom") or 0
        return 0

    if sort == "price_diff_pct":
        results = sorted(results, key=sort_key)  # Most underpriced first
    else:
        results = sorted(results, key=sort_key, reverse=(sort != "dom"))

    return {"count": len(results), "listings": results}


@app.get("/api/listing/{address}")
def get_listing(address: str):
    """Single listing detail with valuation."""
    match = active[active["address"].str.contains(address, case=False, na=False)]
    if match.empty:
        raise HTTPException(404, f"No listing found matching '{address}'")

    row = match.iloc[0]
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
    return val


@app.get("/api/neighborhoods")
def get_neighborhoods():
    """Neighborhood stats and descriptions."""
    overview = market_overview(active, sold)
    result = []
    for name, info in NEIGHBORHOODS.items():
        stats = overview.get(name, {})
        result.append({
            "name": name,
            "description": info["description"],
            "color": neighborhood_color(name),
            "active_count": stats.get("active_count", 0),
            "sold_count": stats.get("sold_count", 0),
            "active_med_price": stats.get("active_med_price"),
            "sold_med_price": stats.get("sold_med_price"),
            "active_med_ppsf": stats.get("active_med_ppsf"),
            "sold_med_ppsf": stats.get("sold_med_ppsf"),
        })
    return {"neighborhoods": result}


@app.get("/api/valuation/{address}")
def get_valuation(address: str):
    """Deep valuation for a specific property."""
    return get_listing(address)


@app.get("/api/deals")
def get_deals():
    """Properties priced below estimated fair value."""
    results = _get_valuations()
    deals = [
        r for r in results
        if r.get("price_assessment") == "underpriced" and r.get("price_diff_pct") is not None
    ]
    deals.sort(key=lambda r: r["price_diff_pct"])
    return {"count": len(deals), "deals": deals}


@app.get("/api/overpriced")
def get_overpriced():
    """Properties priced above estimated fair value."""
    results = _get_valuations()
    over = [
        r for r in results
        if r.get("price_assessment") == "overpriced" and r.get("price_diff_pct") is not None
    ]
    over.sort(key=lambda r: r["price_diff_pct"], reverse=True)
    return {"count": len(over), "overpriced": over}


# ── Serve frontend ───────────────────────────────────────────────────────────

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def serve_frontend():
    index = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return {"message": "Malibu Agent API", "docs": "/docs"}
