# Malibu Agent

Valuation engine for Malibu's $10M+ luxury real estate market. Takes Redfin listing data (87 active, 142 sold comps) and estimates fair market value for each property using comparable sales adjustment -- the same method licensed appraisers use, just automated.

The model finds the most similar recent sales, then adjusts each comp's price for differences in size (power-law, because $/sqft drops for larger homes), construction age (0.85x for pre-1970 up to 1.10x for new builds), beach proximity, and neighborhood. Malibu Colony even/odd house numbers matter -- evens face the ocean. Nine micro-neighborhoods are classified by street name and coordinates, from Carbon Beach to Western Malibu.

For ultra-luxury listings ($30M+) where comparable sales barely exist, a scarcity adjustment pulls the estimate toward listed price with reduced confidence rather than anchoring to $12M comps. Scraped listing details (images, descriptions, keywords like "oceanfront" or "burned") feed back into the model -- a renovated 1963 house gets less age penalty, a confirmed beachfront property in a non-beach neighborhood gets a location boost.

The frontend is a single HTML file that fetches from the FastAPI backend and displays a grid of listing cards with property thumbnails, listed price, estimated fair value, and percentage delta. Filter by neighborhood.

Built with Python, FastAPI, Pandas, and NumPy. Frontend is vanilla HTML/CSS/JS. Data comes from Redfin CSV exports and a custom scraper that pulls listing images and descriptions.

```
pip install fastapi uvicorn pandas numpy
uvicorn api:app --reload
```

Open localhost:8000. All data is in `data/`.
