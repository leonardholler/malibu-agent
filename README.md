# Malibu Agent

Fair market valuation engine for Malibu's $10M+ luxury real estate. Estimates what each property is actually worth by analyzing comparable sales, construction age, micro-neighborhood positioning, and development difficulty — insights you can't get on Zillow or Redfin.

## What it does

Malibu's luxury market isn't one market — it's nine distinct micro-markets where identical square footage can range from $2,000/sqft to $15,000/sqft depending on exact location, ocean-facing vs mountain-facing, and whether the structure is a 2024 new build or a 1960s teardown.

### Valuation engine

The core is a **comparable sales adjustment model** (the same method real appraisers use):

1. **Find comps** — Matches each property to recent sales in the same micro-neighborhood, weighted by similarity in size, lot, construction era, and bed count
2. **Adjust for size** — $/sqft drops sharply for larger homes (a 1,600 sqft beach cottage at $6,700/sqft ≠ an 8,500 sqft mansion at $1,500/sqft). Uses a power-law adjustment
3. **Adjust for construction** — New builds command 15% premium; pre-1970 construction trades at 35% discount. Standing quality homes are worth significantly more than teardowns because Malibu permits take 2-5+ years
4. **Adjust for micro-location** — Colony beachfront vs Colony mountain-side (odd/even house numbers), Carbon Beach vs Western Malibu
5. **Development difficulty** — Land parcels get a 55% discount because building in Malibu means Coastal Commission reviews, ESHA restrictions, view preservation ordinances, and years of permitting

### Key features

- **Fair market value estimate** for every active $10M+ listing with confidence rating
- **Colony odd/even detection** — Even addresses face the ocean; odd face the mountains (30%+ price impact)
- **Land parcel identification** — Burned lots and unimproved land valued separately from improved homes
- **Price assessment** — Flags underpriced deals and overpriced listings
- **Land vs improvement breakdown** — Shows what percentage of value is dirt vs structure
- **Comparable sales** — Every estimate shows the 5 comps used and their adjustments
- **Nine micro-neighborhoods** classified by street name + coordinates + PCH address number

### The neighborhoods

| Neighborhood | Character | Beach Mult. |
|---|---|---|
| **Malibu Colony** | Gated beachfront enclave. Most exclusive address. | 1.18x |
| **Carbon Beach** | Billionaire's Beach. Ultra-premium beachfront. | 1.18x |
| **Malibu Road** | Central beachfront strip. Old cottages + new builds. | 1.10x |
| **Malibu Cove Colony** | Gated oceanfront near the pier. | 1.06x |
| **Broad Beach** | Wide sandy beach, west end. Larger lots. | 1.06x |
| **Escondido Beach** | Paradise Cove area. Secluded beach access. | 1.03x |
| **Point Dume** | Dramatic bluff-top. Panoramic views, iconic cliffs. | 1.00x |
| **Serra Retreat** | Gated hillside. Privacy, no beach. | 0.90x |
| **Western Malibu** | Past Broad Beach. Larger acreage, ranch-style. | 0.88x |

## Architecture

```
FastAPI backend (api.py)
├── valuation.py    — Core valuation engine (comp adjustment model)
├── data_loader.py  — Redfin CSV pipeline + neighborhood classification
├── analysis.py     — Market overview, deal/overpriced/stale detection
└── static/
    └── index.html  — Single-file frontend (vanilla HTML/CSS/JS)
```

**No framework dependencies.** The frontend is a single HTML file with inline CSS/JS that fetches from the FastAPI REST API. Dark theme, responsive, professional.

### API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/listings` | All active listings with valuations. Filter by `neighborhood`, `assessment` |
| `GET /api/listing/{address}` | Single listing with full valuation + comps |
| `GET /api/neighborhoods` | Neighborhood stats and descriptions |
| `GET /api/deals` | Properties priced below estimated fair value |
| `GET /api/overpriced` | Properties priced above estimated fair value |

## Setup

```bash
pip install -r requirements.txt
uvicorn api:app --reload
```

Open `http://localhost:8000` in your browser.

### Data

Drop Redfin CSV exports into `data/`. The tool expects $10M+ Malibu listings:
- Active listings: Redfin → Malibu → $10M min → Download CSV
- Sold listings: Same filter → Sold → Download CSV

The neighborhood classifier uses a 3-pass algorithm: street name → lat/lng coordinates → PCH address number.

## Technical decisions

- **Comp-price adjustment over $/sqft multiplication** — In a market where 1,600 sqft and 8,500 sqft homes are both "luxury," extracting $/sqft and multiplying back produces absurd estimates. Instead, we adjust each comp's sale price directly for size, age, and location differences.
- **Odd/even Colony detection** — On Malibu Colony Road, even numbers face the ocean and odd numbers face the mountains/lagoon. This single-digit distinction can mean $5-10M in value difference.
- **Development difficulty as a first-class factor** — Unlike most markets, Malibu's permitting environment means an empty lot is NOT "a blank canvas" — it's 2-5 years of Coastal Commission reviews before you can break ground.
- **Median-fallback for high-variance neighborhoods** — Carbon Beach has comps ranging from $10M to $51M. When comp coefficient of variation exceeds 0.5, we use median instead of weighted average to prevent outlier anchoring.
