# Deal Finder

Finds UK property deals automatically, values each one against real sold prices, works out the numbers for
every common investment strategy, and ranks them in a dashboard on your Mac.

**Searching**

Type any UK postcode or district (e.g. `BS5 6HN` or `M14`), pick a radius, price range, bedrooms and property
types, and tick the deal types you want — BMV, Repossession, Short lease, Probate, Auction, Cash only,
Refurb / BRRR, Flip, HMO potential, Motivated seller, Negative equity, Lease option, Strong BTL, Problem property,
Title split, Conversion, Serviced accommodation. Press **Search**: Deal Finder reads Rightmove's results for that
area (free, built in — or through a paid Apify scraper if you add one), values every property against Land Registry
sold prices nearby, and shows the ones that match your ticks, best first. A search takes about a minute; changing
the ticks afterwards, or repeating the search within 12 hours, is instant.

**Send to Deal Finder button.** Drag the button on the search page to your bookmarks bar. While you browse
Rightmove yourself, click it on any results page and every listing on that page is analysed in Deal Finder.
**Save search** re-runs it every day and emails you new high-scoring deals.

**What it does on every search or scan**

1. Pulls listings from your sources: Apify scrapers (Rightmove / Zoopla), your portal alert emails, and any CSV
   you drop in `imports/` (auction catalogues etc.).
2. Keeps the ones in your areas, price range and property types.
3. Values each one from HM Land Registry sold prices of the same type nearby (last 24 months, radius widening
   400 m → 2 km until there are 8 sales).
4. Works out BMV %, stamp duty, rent (PropertyData, optional), yield, cashflow, ROI, refurb, flip profit and BRRR
   cash left in, previous sales of the address and a negative-equity flag.
5. Flags strategies: BMV, Strong BTL, Cash only, Refurb / BRRR, Flip, Problem property, HMO potential,
   Motivated seller, Probate, Repossession, Auction, Short lease, Negative equity, Lease option candidate,
   Title split, Conversion / development, Serviced accommodation.
6. Scores every deal 0–100, stores everything (so price drops and time on market are tracked) and emails you
   anything above your score threshold.

**Deal posts.** Every property has a **Create deal post** button: an investor post (purchase price, refurb, GDV,
money left in, equity, rent, cashflow) built from Deal Finder's numbers, editable, with one-click copy. Selling
points like "quote provided" or "hands off" only appear when you tick them. Set your contact line and sourcing fee
in Settings.

Dashboard: ranked table, a filter button per strategy, map, detail page with the sold-price evidence,
CSV export and a one-click PDF deal pack.

## Getting it on your Mac (no Terminal needed)

1. Download **DealFinder-mac.zip** and double-click it to unzip.
2. Drag **Deal Finder.app** into your Applications folder and double-click it.
3. The first time, macOS says it can't check the app, because it isn't from the App Store. Click **Done**, open
   **System Settings → Privacy & Security**, scroll down and click **Open Anyway** next to Deal Finder. Open the
   app again and click **Open**. You only do this once.
4. The first launch sets itself up (a few minutes, needs internet), then opens the dashboard in your browser.
5. Click **Settings**, add your Apify token and scraper IDs (below), save, go back and search a postcode.

Deal Finder keeps running in the background so it can scan every day at the time you choose. Open the app again to
get back to the dashboard; click **Stop** on the dashboard to turn it off. Your settings and deals are saved in
`~/Library/Application Support/Deal Finder` (the log file there, `dealfinder.log`, shows what happened if
something goes wrong).

To rebuild the zip from this repo: `macos/build_app.sh` → `dist/DealFinder-mac.zip`.

## Settings page

**1. Free Rightmove reader** (on by default). Reads Rightmove's ordinary results pages for each search — up to
3 pages (72 listings) with a pause of a few seconds between pages — and opens leasehold properties' own pages to
find lease lengths. It identifies itself honestly and does nothing to get round Rightmove's protections: if
Rightmove limits it, it stops and tells you. This is against Rightmove's terms of use, and Rightmove could
temporarily limit your home connection; keep searches modest and use the email-alert backup.

**Optional: Apify (paid; the only way to add Zoopla).** Create an account at apify.com and paste your API token. In the Apify Store,
search "Rightmove" (and "Zoopla" if you want both), pick a scraper with good recent reviews **that accepts search
result page URLs**, and paste its ID (from the page address, e.g. `someone/rightmove-scraper`). Deal Finder sends
it `{"startUrls": [{"url": "<the Rightmove search link>"}], "maxItems": 100}`; if your scraper names its inputs
differently, change that under *Advanced*.

If listings come in without prices or addresses, that scraper uses field names Deal Finder doesn't know yet — add
them to `FIELD_NAMES` in `dealfinder/sources/apify.py`.

Scraping breaks Rightmove's and Zoopla's terms of use. They can block scrapers or change their site at any time,
so an Apify scraper can stop working without warning. Keep the email-alert backup on, use it for your own research,
and don't republish the scraped data.

**2. Filters for your other sources** (alert emails and imported CSVs). Area searches use the search page instead.

**3. Rent estimates.** A PropertyData API key (paid) gives every deal a rent estimate, yield and cashflow. Without
it, those are left blank rather than guessed.

**4. Your own alert emails (backup, free).** Set up Rightmove / Zoopla / OnTheMarket email alerts to a Gmail
address, create a Gmail App Password, and enter them here.

**5. Deal alerts.** Emails you any deal above the score you choose.

**6. Deal maths** and **7. Daily scan time.**

**Auctions and other lists:** use **Import** on the search page to add a CSV (see `imports/example.csv` for the
columns), then press **Scan now**.

## Running from Terminal (developers)

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

```bash
python -m dealfinder run --open
```

## Checking the numbers

BMV compares the asking price with the median sold price of the same property type nearby. Two safeguards:
student pods, shared-ownership shares, retirement flats, garages/plots, park homes and ground-rent investments
are never flagged as BMV (they sell far below ordinary homes, so the comparison is meaningless), and auction
lots are labelled "auction guide price" and count for half in the score, because guide prices are set low on
purpose.


Every assumption — mortgage rate, LTV, running costs, refurb £/m², BMV threshold — is on the Settings page;
stamp duty bands are in `config.yaml`. **Stamp duty bands are England's residential rates as of 2025; check gov.uk before relying on
them** (Wales uses Land Transaction Tax, which this doesn't calculate yet).

All figures are estimates to help you shortlist, not advice. Always check the listing, the comparables and the
legal pack yourself.

## Tests

```bash
python -m pytest
```

Tests cover stamp duty, finance, valuation, strategy flags, every source's parsing, a full scan with mocked
APIs, the dashboard, CSV export and the PDF. The live Land Registry, postcodes.io, PropertyData and Apify calls
haven't been run against the real services yet — the first real scan is the test of those. The Mac app's
launcher was tested in a simulation, not on a real Mac.

## Not built yet

- Repossessions are found from listing wording ("repossession", "mortgagee", "receivers") and auction
  catalogues you import; there is no public database of repossessed homes.

- The Gazette (probate / insolvency notices), planning data, Companies House and Land Registry company
  ownership lead sources.
- Floor area from EPC data.
- Wales Land Transaction Tax.

## Data licence

Contains HM Land Registry data © Crown copyright and database right. This data is licensed under the Open
Government Licence v3.0.
