# prozorro-drone-digest

Tracks how Ukrainian public buyers purchase drones, FPV kits, EW equipment and thermal imagers through Prozorro, and turns it into a weekly markdown digest with unit prices by product type. Python 3 + `requests`, no database, no framework. One JSON file per tender on disk. Benchmarks are medians of signed net-of-VAT unit prices over a rolling 30-day window. Flags mark contracts priced above benchmark, single-bidder awards, and budgets set far above the catalogue price, and pull the tender documents to say why.

**Who it's for:** producers and sellers of drones / EW / optics who want to see what communities, police, ДСНС and military units are buying, at what unit price, and which open tenders are worth a bid. Also anyone auditing municipal spending on this category.

Sample output from the 2026-09-20 run is in `data/digests/digest_2026-09-20.md`, with hand-written notes in `data/notes/`. Everything in it comes from public Prozorro records. The ⚠ flags are screening heuristics that say where to read the documents, they are not findings about any buyer or supplier.

Install: `pip install -r requirements.txt`, then run the weekly cycle below from the repository root.

## Weekly cycle

```
python3 scripts/refresh.py            # re-fetch every non-terminal tender (public API), discover new candidates (last 8 days)
python3 scripts/price_table.py        # rebuild data/price_table.csv and data/benchmarks.json (30-day window)
python3 scripts/digest.py             # data/digests/digest_<date>.md + data/state/{pending,reported,benchmarks_history}.json
```

`refresh.py --discover feed` swaps the site-search discovery for a walk of the official feed (slower, no unofficial endpoints). Optional: write `data/notes/notes_<date>.md` with `## <tenderID>` paragraphs before running `digest.py`; they are attached to the matching rows. Hand-labelled classifier samples go in `data/label_sample_40.csv` (`scripts/label_sample.py` draws a new stratified one, fixed seed).

First run from scratch: `scripts/harvest.py` + `scripts/fetch_full.py` (≈15 min for 30 days, rate-limited by the site API), then the three steps above.

## What the numbers are (30 days to 2026-09-20)

- 1,763 candidate tenders found by keyword + CPV search; ~1,250 are about the category after re-classification, ~500 are batteries, parts or noise. Roughly 130 drone-related tenders are created or modified per day across all buyers.
- Structured product data (Prozorro Market category, characteristics block, every bidder's unit price) exists only on `priceQuotation` tenders: 31 % of candidates. By buyer that is uneven — military units 62 %, all non-defense buyers 16 %, councils 21 %; for EW it is 0 %. Everything else is typed by regex on titles/descriptions and priced from `contract.value ÷ qty`.
- Benchmarks (signed, net of VAT, same-buyer-same-day split purchases collapsed): DJI Matrice 4T 172,500 (n=105); FPV 10" day 19,960 (n=5); FPV 10" thermal 50,700 (n=1); ESM «Чуйка» base/3.0 25,700 (n=14); «Чуйка 4.0» 50,400 (n=6); «Чуйка» kit 37,700 (n=3). Anything else (EW jammers, generic quadcopters, fixed-wing, thermal imagers) has no benchmark yet — too heterogeneous.
- Flags: ⚠P signed unit price > +15 % vs benchmark; ⚠S exactly one bid in a competitive procedure; ⚠B buyer's budget > +30 % vs benchmark. Independent; any of them triggers the document check.

## Known limitations

- Coverage is a search, not a census: the keyword + CPV harvest catches about 70 % of what a full feed walk finds (measured once on a 29k-tender feed sample). Product-part tenders with no drone word in the title are the main miss.
- The coarse classifier (18 classes) is regex; its precision is not yet measured — that is what the 40-row labelled sample is for. Expect noise like a 4,500 UAH "drone" that is a toy or a part.
- FPV drones are not one product: size, radio vs fiber-optic, day vs thermal camera move the price 12k → 50k. Only `priceQuotation` tenders state these in data; the rest need the documents.
- Bids are hidden until qualification, so a tender first seen open gets its prices weeks later; `pending.json` is re-fetched every run for that reason.
- VAT: the category is mostly exempt (п. 32 підрозділу 2 розділу XX ПКУ), but the VAT flag differs between tender, award, contract and contract item on the same purchase. Signed prices use the contract's `amountNet`. Everything is compared net.
- Document reading is heuristic: it finds the spec section and extracts bands, capacity, quantity, delivery, warranty, kit extras. It will misread, and the hand-written notes in `data/notes/` are the fallback, not the pipeline.
- Prozorro Market category ids are used raw; no API to resolve them to names was found.
- No Telegram, no scheduler, no tests. Run it by hand.

## Where the site API dependency sits

The official API (`public-api.prozorro.gov.ua/api/2.5`) has no search: it serves a `dateModified` feed of ids and full objects by hex id. Two calls on the site's own undocumented API (`prozorro.gov.ua/api`) are used for discovery only: `POST /search/tenders` (keyword and CPV search) and `GET /tenders/{UA-…}/summary` (human tenderID → hex id). Both live in `lib.site_search()` / `lib.site_resolve()`, called only from `lib.find_candidates_site()` and `lib.fetch_tender_by_tender_id()`. Every other step — refresh, contracts, documents, prices, digest — uses the official API by hex id. If the site API changes, `refresh.py --discover feed` is the replacement (`lib.find_candidates_feed()`, tested on one feed page only): walk the official feed, fetch every non-defense tender, classify after the fetch; ~2 minutes per feed-day at the measured throughput.

## Files

```
scripts/lib.py          API layer, cache, classifiers, characteristics, prices
scripts/refresh.py      weekly step 1      scripts/price_table.py   step 2      scripts/digest.py   step 3
scripts/docs.py         tender documents → spec facts / verdict     scripts/label_sample.py   labelled sample
scripts/harvest.py, fetch_full.py, classify.py, sample3.py         first-run and research scripts
data/tenders/           one JSON per tender (≈100 MB / 30 days, not committed)     data/contracts/  contract objects (not committed)
data/docs/<tenderID>/   downloaded documents + extracted text (not committed, rebuilt by scripts/docs.py)        data/notes/      hand-written notes per digest
data/benchmarks.json, price_table.csv, guessed_types_all.csv, label_sample_40.csv
data/state/             pending.json, reported.json, benchmarks_history.json, refresh_log.txt
data/digests/           digest_<date>.md
SOURCES.md              what the APIs return, verified field by field, with corrections kept in place
```
