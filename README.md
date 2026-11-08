# Deal Finder

Finds UK property deals automatically, values each one against real sold prices, works out the numbers for
every common investment strategy, and ranks them in a dashboard on your Mac.

**What it does on every scan**

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

Dashboard: ranked table, a filter button per strategy, map, detail page with the sold-price evidence,
CSV export and a one-click PDF deal pack.

## Setup (once)

You need Python 3.11 or newer. On a Mac, open **Terminal** and run these one at a time:

```bash
cd ~/deal-finder
```

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

```bash
cp config.example.yaml config.yaml && cp .env.example .env
```

Then open `config.yaml` and `.env` in TextEdit and fill them in (next section).

## Connecting your sources

**Apify (Rightmove / Zoopla).**

1. Create an account at apify.com. Copy your API token from Settings → API & Integrations into `.env` as
   `APIFY_TOKEN=...`.
2. In the Apify Store, search "Rightmove" (and/or "Zoopla"). Pick a scraper with good recent reviews and runs.
3. Open it, copy its ID (looks like `someone~rightmove-scraper`) into `config.yaml` under `sources → apify →
   runs → actor_id`.
4. Copy the input it expects into `input:`. Most take Rightmove search URLs: do your search on rightmove.co.uk,
   copy the address bar, paste it as the `url`.
5. Run `python -m dealfinder scan`. If listings come in without prices or addresses, open one run's output in the
   Apify console and tell whoever maintains this which field names it uses (add them in
   `dealfinder/sources/apify.py`, `FIELD_NAMES`).

Scraping breaks Rightmove's and Zoopla's terms of use. Rightmove can block or change its site at any time, so
an Apify scraper can stop working without warning. Keep the email-alert source switched on as a backup, use it
for your own research, and don't republish the scraped data.

**Your own portal alert emails (backup, free).** Make a separate Gmail account, turn on 2-step verification and
create an App Password. Put `ALERTS_IMAP_HOST=imap.gmail.com`, the address and the App Password in `.env`. Set up
saved-search email alerts on Rightmove / Zoopla / OnTheMarket to that address, then set
`email_alerts: enabled: true` in `config.yaml`.

**PropertyData (optional, paid).** Put your key in `.env` as `PROPERTYDATA_API_KEY`. It's used for rent
estimates, so you get yield and cashflow figures. Without it, those numbers are left blank rather than guessed.

**Auctions and anything else.** Save an auction catalogue (or any list) as CSV into `imports/` — see
`imports/example.csv` for the columns.

**Email alerts to you.** Fill in `SMTP_*` in `.env` (Gmail: `smtp.gmail.com`, port 587, the App Password),
then set `alerts: enabled: true` and your address in `config.yaml`.

## Running it

```bash
source .venv/bin/activate && python -m dealfinder run
```

Open http://127.0.0.1:8000. Press **Scan now** for an immediate scan. While `run` is open, it scans daily at
the time in `config.yaml`. To scan once without the dashboard: `python -m dealfinder scan`.

## Checking the numbers

Every assumption — mortgage rate, LTV, running costs, refurb £/m², BMV threshold, stamp duty bands — is in
`config.yaml`. **Stamp duty bands are England's residential rates as of 2025; check gov.uk before relying on
them** (Wales uses Land Transaction Tax, which this doesn't calculate yet).

All figures are estimates to help you shortlist, not advice. Always check the listing, the comparables and the
legal pack yourself.

## Tests

```bash
python -m pytest
```

Tests cover stamp duty, finance, valuation, strategy flags, every source's parsing, a full scan with mocked
APIs, the dashboard, CSV export and the PDF. The live Land Registry, postcodes.io, PropertyData and Apify calls
haven't been run against the real services yet — the first real scan is the test of those.

## Not built yet

- The Gazette (probate / insolvency notices), planning data, Companies House and Land Registry company
  ownership lead sources.
- Floor area from EPC data.
- Wales Land Transaction Tax.

## Data licence

Contains HM Land Registry data © Crown copyright and database right. This data is licensed under the Open
Government Licence v3.0.
