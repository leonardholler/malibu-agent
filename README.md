# Malibu Agent

Market intelligence for Malibu's $10M+ residential real estate. Interactive web dashboard that classifies properties into nine micro-neighborhoods and provides pricing analysis, construction-era insights, and land value estimates.

**[Live Demo](https://malibu-agent.streamlit.app)** (update this URL after deploying)

## What it does

Malibu's luxury market isn't one market — it's nine distinct micro-markets where identical square footage can range from $2,000/sqft to $15,000/sqft depending on exact location. This tool breaks it down.

### The neighborhoods

- **Malibu Colony** — Gated beachfront enclave. The most exclusive address in Malibu.
- **Carbon Beach** — Billionaire's Beach. Ultra-premium beachfront east of the Colony.
- **Malibu Road** — Central beachfront strip. Mix of older beach cottages and new builds.
- **Serra Retreat** — Gated hillside community above central Malibu. Privacy, no beach.
- **Malibu Cove Colony** — Gated oceanfront community near the pier.
- **Escondido Beach** — Paradise Cove area. Secluded beach access, fewer neighbors.
- **Point Dume** — Dramatic bluff-top setting. Panoramic ocean views, iconic cliffs.
- **Broad Beach** — Wide sandy beach on the west end. Larger lots, newer construction.
- **Western Malibu** — Past Broad Beach. Larger acreage, ranch-style properties.

### Key features

- Interactive map color-coded by neighborhood with price-scaled markers
- Price per square foot analysis by neighborhood and construction era
- Land value ratio estimates (old construction = you're buying dirt, new builds = you're paying for the house)
- Teardown candidate detection (pre-1990 homes where 75%+ of value is land)
- Deal finder (active listings below sold median $/sqft)
- Overpriced detection (40%+ above sold comps)
- Stale listing tracker (high days on market by price segment)
- Property comp search with active and sold comparisons

## Setup

```bash
pip install -r requirements.txt
streamlit run app.py
```

Drop Redfin CSV exports into `data/`. The tool expects $10M+ Malibu listings (active + sold).

## Deploy to Streamlit Cloud (free)

1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repo, set main file to `app.py`
4. Deploy — you'll get a public URL in about 2 minutes

## Data

Uses standard Redfin CSV exports. Filter to Malibu, $10M minimum, download active and sold separately. The neighborhood classifier uses street names + lat/lng coordinates to map each property to its micro-market.
