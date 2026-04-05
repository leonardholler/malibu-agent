# Malibu Agent

Fair market value estimation for Malibu luxury real estate ($10M+) using comparable sales adjustment — the same method licensed appraisers use, applied computationally to 87 active listings and 142 sold comps.

## What it does

Ingests Redfin listing data and scraped property details (images, descriptions, keywords) for Malibu's nine micro-neighborhoods: Carbon Beach, Malibu Colony, Malibu Road, Point Dume, Broad Beach, and others. Runs a comp-based valuation on every active listing and serves an interactive dashboard with:

- **Valuation engine** -- Price-tier-aware comp selection using log-ratio scoring, so a $60M listing doesn't pull $12M comps. Adjustments for construction age, beach proximity, Colony ocean-facing, lot development difficulty, and scraped keyword intelligence (burned lots, gated estates, oceanfront confirmation).
- **"Why This Price" explanations** -- Every estimate includes a human-readable breakdown: which comps were used, what adjustments were applied, and why.
- **Interactive map** -- Leaflet.js with color-coded markers (green = underpriced, red = overpriced). Hover for price/value/delta tooltip, click to see full detail with image carousel.
- **Neighborhood comparison** -- Side-by-side stats for each micro-market: median price, $/sqft, days on market, fair value, and the best deal in each area.
- **Market analytics** -- Listed Price vs Fair Value scatter plot with diagonal reference, median $/sqft by neighborhood bar chart.

## Methodology

Each listing is valued by finding the most similar sold properties (scored by price tier, size, lot, age, beds, and neighborhood), then adjusting each comp's sale price for differences in construction age (0.85x-1.10x), beach proximity, and lot characteristics. The adjusted comp prices are combined using similarity-weighted averaging. An ultra-luxury scarcity adjustment handles cases where the listing price far exceeds available comps (common above $30M where only a handful of sales exist per year). Confidence-based divergence caps prevent runaway estimates.

Key design choices: power-law size adjustment (0.7 exponent) because $/sqft drops sharply for larger homes; Colony odd/even detection since even addresses face the ocean; and development difficulty discounts for land parcels because Malibu permits take 2-5+ years through the Coastal Commission.

## Stack

Python, FastAPI, Pandas/NumPy, Leaflet.js, Chart.js. Single-file vanilla frontend (no build step). Redfin CSV data pipeline with scraped listing details cache (270 properties with images and descriptions).

## Run it

```
pip install fastapi uvicorn pandas numpy
uvicorn api:app --reload
```

Open http://localhost:8000. Data is included in `data/`.
