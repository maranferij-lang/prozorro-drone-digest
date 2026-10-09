# SOURCES.md — Prozorro data for a drone / EW / thermal-imager price digest

Written 2026-09-20 (updated 10:45 Kyiv: documents, digest v1.1 with summary + defense appendix) after probing the live APIs from Python (`requests` 2.33.1).
Everything below marked **verified** was observed in an actual HTTP response during development.
Things I did *not* test are marked **not tested**. Nothing here is from memory of documentation.

Scripts that produced these findings are in `scripts/`.

---

## 1. Two APIs, not one

| | Public API (official) | Site API (undocumented, used by prozorro.gov.ua SPA) |
|---|---|---|
| Base | `https://public-api.prozorro.gov.ua/api/2.5` | `https://prozorro.gov.ua/api` |
| Auth | none | none (sends `User-Agent: Mozilla/5.0 …`; not tested without it) |
| What it's for | full tender / contract objects, change feed | full-text search, tenderID → hex id mapping |
| Filtering | **none** (no CPV, no text, no buyer) — only a dateModified-ordered feed | `text`, `cpv[]`, `status[]`, `proc_type[]`, `date[...]`, `sort_by`, `order` |
| Rate limiting seen | none observed: ≈2,000 GETs at 8 parallel in my run; the earlier run in this container measured **57 req/s with 20 threads, 200/200 OK, no `Retry-After`** (`probes/05_ratelimit.out`) | **HTTP 429** on `/tenders/{id}/summary` at 8 parallel workers; fine at ~1 req/s with `sleep(0.15)` plus backoff (14 × 429 over 837 requests). No `Retry-After` header. |
| Stability | official, versioned | reverse-engineered from the SPA bundle (`ParamsBuilder-*.js`, `TenderPage-*.js`); can change without notice |

**Practical pipeline (verified end-to-end on 1,746 tenders):**
site search → `tenderID` (UA-2026-…) → `GET prozorro.gov.ua/api/tenders/{tenderID}/summary` → hex `id` → `GET public-api…/tenders/{id}` → `GET public-api…/contracts/{contract.id}` for signed unit prices.

---

## 2. Public API — feed and pagination (verified)

`GET /api/2.5/tenders`

- Returns `{"data":[{"id": <32-hex>, "dateModified": ...}], "next_page": {"offset", "path", "uri"}, "prev_page": {...}}`.
- Feed is ordered by **`dateModified`**, not `dateCreated`. Every modification (new bid, award, contract, question…) re-emits the tender, so the feed has many duplicates per tender.
- `limit`: default 100; **hard cap 1000** (asked 5000, got 1000).
- `descending=1` flips order (newest modification first).
- `offset` accepts three forms, all verified:
  - ISO datetime with tz: `offset=2026-08-21T00:00:00+03:00`
  - Unix timestamp float: `offset=1787263894.11`
  - Opaque token from `next_page.offset`, e.g. `1787259605.493.1.ca3cbc…` — this is what you should pass when paging.
- `feed=changes` and `mode=_all_` returned the same shape; I did not find a behavioural difference during development (**not tested** deeply — `mode=_all_` is meant to include test tenders).
- `opt_fields=` lets you inline fields into the feed, but only from a **whitelist**. Verified accepted: `status, tenderID, dateCreated, procurementMethodType, procuringEntity, tenderPeriod, lots`. Verified **silently dropped**: `title, value, items, awards, bids, contracts, description, mainProcurementCategory, numberOfBids, owner, enquiryPeriod, auctionPeriod, date`. So you cannot classify drones from the feed alone — `title` and `items` require a full GET per tender.
- Volume: **21,496** feed entries for the single day 2026-09-18 (22 pages of 1000, 27 s). ≈ 650k entries / 30 days. Walking the feed + fetching every tender to find drones is not practical for a weekly hobby job; use the site search for recall and the public API for detail.
- `GET /tenders/UA-2026-09-17-009508-a` → **404**. The public API only accepts the 32-hex `id`, not the human `tenderID`.

## 3. Public API — tender object (verified on real tenders)

`GET /api/2.5/tenders/{hex_id}` → `{"data": {...}}`

Top-level keys seen: `awardCriteria, awardPeriod, awards, bids, complaintPeriod, contractChangeRationaleTypes, contracts, criteria, date, dateCreated, dateModified, description, documents, enquiryPeriod, guarantee, id, items, lots, mainProcurementCategory, milestones, noticePublicationDate, owner, plans, procurementMethod, procurementMethodType, procuringEntity, questions, status, submissionMethod, tenderID, tenderPeriod, title, value` (exact set varies by procedure type).

Fields that matter for unit prices:

| Field | Notes (verified) |
|---|---|
| `tenderID` | `UA-YYYY-MM-DD-NNNNNN-a`. The date in it equalled `dateCreated[:10]` in 1746/1746 tenders → safe to use as a creation-date cutoff without fetching. |
| `value.amount`, `.currency`, `.valueAddedTaxIncluded` | Expected (budget) value. `valueAddedTaxIncluded` was `False` in 1422/1746, `True` in 302, missing in 22. Net-of-VAT is the norm for this category, not a data glitch: buyers cite п. 32 підрозділу 2 розділу XX Податкового кодексу (martial-law VAT exemption for defence goods; Буринь's description says so verbatim). **Compare everything net.** "Чуйка" at 25,700 net vs 30,840 gross (= ×1.2) is the same price with and without the exemption applied. |
| `items[]` | `description, quantity, unit{name, code}, classification{scheme:"ДК021", id, description}, deliveryAddress, deliveryDate, relatedLot, id`. 766/969 sampled tenders had exactly 1 item. `unit.code` is UN/CEFACT: `H87` штука, `KT` комплект, `E50` одиниця, `E48` послуга. |
| `items[].unit.value` | Explicit per-unit price. Present only in some **`reporting`** (direct-contract) tenders: 197/626 in my sample. Absent in all competitive procedures. |
| `items[].additionalClassifications` | Never populated in my 1,746 tenders (0 occurrences). |
| `items[].category`, `items[].profile` | **Prozorro Market ids, present on all 545 `priceQuotation` tenders** (category always, profile 130/545) and on 3 others. The category is a stable product-class id, e.g. `34710000-259894-40996564` = Квадрокоптери (274 tenders in 30 days), `34710000-331552-40996564` = БпЛА мультироторного типу (FPV) (16), `31430000-888358-40996564` = Акумулятори для FPV дронів (141), `b9d2c60fd2ec49aab4f338bb95cedb1c` = Пропелери для дронів (31), `34740000-241144-40996564` = Пульти керування дронами (21), `34740000-572349-40996564` = Окуляри FPV (13), `38630000-497369-32348248` = Тепловізори (8). Names above are inferred from the item descriptions that carry them; I did **not** find a working Market API to resolve ids (`market-api.prozorro.gov.ua/api/1.0/categories/{id}` → 404 nginx; wrong path or not public). `tender.agreement.id` → `GET /api/2.5/agreements/{id}` works (`agreementType: electronicCatalogue`) but has no product names either. |
| `criteria[]` | Tender criteria. The one that matters: `classification.id = CRITERION.OTHER.SUBJECT_OF_PROCUREMENT.TECHNICAL_FEATURES`, `relatesTo: "item"`, **`relatedItem` = item id** (per-item when the tender has several items), `requirementGroups[].requirements[]{id, title, dataType, expectedValue | expectedValues[] | minValue/maxValue, unit}`. This is the "Технічні характеристики" block on the tender page. Present on **545/545 `priceQuotation`** tenders and 2 `belowThreshold`; absent from `reporting`. Most common requirement titles across the 30-day drone set: Бренд (525), Модель (412), Максимальна висота польоту (178), Ємність акумулятора (176), **Тепловізор (171, boolean)**, Акумуляторів у комплекті (166), Час польоту (164), Тип двигуна (163), Тип (136), Формфактор (131); FPV profiles add Розмір (дюйм), Корисне навантаження (кг), Протокол прийому сигналу, Відеозв'язок, Дальність, Управління за допомогою оптоволоконного кабелю, Котушка з оптоволокном. Use this, not regex, wherever it exists. |
| **No top-level CPV** on the tender — classification lives only on items. |
| `procuringEntity` | `name, identifier{scheme:"UA-EDR", id=ЄДРПОУ, legalName}, address{locality, region…}, contactPoint, kind`. `kind` ∈ `defense / general / authority / special` — the cleanest way to separate військові частини (`defense`) from municipalities and other civil buyers. Tagged sample: defense 765, general 289, authority 182, special 16. |
| `procurementMethodType` | Sample: `priceQuotation` 492, `reporting` 318, `belowThreshold` 228, `aboveThreshold` 198, `negotiation` 14, `negotiation.quick` 2. **`reporting` tenders have no `tenderPeriod` (0/626)**, no bids, no auction; they go straight to `awards`+`contracts`. |
| `status` | `active.enquiries → active.tendering → active.auction → active.qualification → active.awarded → complete`, or `unsuccessful` / `cancelled`. `reporting` tenders use `active → complete`. |
| `bids[]` | **Absent from the JSON while `status = active.tendering`** (key not present), `[]` during `active.auction` in the one case seen; populated from qualification onward. Each bid: `status, date, submissionDate, initialValue, tenderers[{name, identifier}], value{amount}` **or** `lotValues[{relatedLot, value{amount}}]` for multi-lot tenders (then `bid.value` is `None`), `items[]`, `requirementResponses[]`, `documents[]`. |
| `bids[].items[]` | **Carry per-bidder unit prices: `unit.value{amount, currency, valueAddedTaxIncluded}`**, plus the bidder's own `description` of the offered product, `quantity`, and `product` (Prozorro Market product id). `bids[].items[].id` equals the tender `items[].id` (4,035/4,035 matched) — join on it. Verified: Луцьк 12,000 / 13,948 / 17,700; Буринь 169,780 … 178,000. Present in **383/383 `priceQuotation` tenders that have bids**, and only 5/130 `belowThreshold`, 3/70 `aboveThreshold`. So at qualification stage you have **every bidder's** unit price, not just the winner's. *(Correction 2026-09-20 02:30: the first version of this file said bid items carry no prices — I had checked that bid items exist, not their `unit.value`. Wrong, caught by the user on the Луцьк page.)* One real-data trap: `UA-2026-09-10-009033-a` has a bid with `unit.value = 173` (total 17,300 UAH for 100 Matrice 4T — bidder typed 173 for 173,000; awarded, then disqualified). Flag bids < 20 % of the tender's median bid as implausible rather than trusting them. |
| `bids[].requirementResponses[]` | The bidder's answers to the tender's `criteria` requirements: `{requirement{id, title}, value | values[]}`. For `TECHNICAL_FEATURES` this is where **Бренд → "DJI", Модель → "Matrice 4T", Розмір → 10, Протокол → "ELRS", Відеозв'язок → "аналоговий"** live. Join `requirement.id` to `criteria[].requirementGroups[].requirements[].id` to know which item it describes. |
| `awards[]` | `status (pending/active/cancelled/unsuccessful), value{amount}, suppliers[{name, identifier{id}}], bid_id, lotID, date`. `status=active` = the winner. |
| `contracts[]` (embedded) | Only `id, contractID, awardID, status, value, title, date` — **no items**. |
| `lots[]` | Present in 318/969; then `items[].relatedLot` and `bids[].lotValues` are per-lot. |
| `numberOfBids` | was `None` on every tender I looked at — don't rely on it. |

## 4. Public API — contract object (verified)

`GET /api/2.5/contracts/{contract.id}` → keys: `awardID, buyer, contractID, contractNumber, date, dateCreated, dateModified, dateSigned, description, documents, id, items, milestones, owner, period, status, suppliers, tender_id, title, value`.

- `value.amount`, `value.amountNet`, `value.valueAddedTaxIncluded`. **The contract's VAT flag can differ from the tender's**: `UA-2026-08-27-002779-a` — tender and award net (504,000), contract signed at 604,800 with `valueAddedTaxIncluded: true`, `amountNet: 504,000`. Read VAT at the contract level and use `amountNet`.
- `items[].unit.value.valueAddedTaxIncluded` at the contract level is **unreliable**: on the same contract it says `false` on a unit price of 60,480 that equals the gross total ÷ qty. Scale contract item prices by `amountNet / amount` when the contract is VAT-included, ignore the item-level flag.
- **`items[].unit.value.amount` = the signed per-unit price.** Verified arithmetic: 22 × 3,950 = 86,900 = contract value; 50 × 660 = 33,000; 20 × 12,000 = 240,000; 3 × 169,780 = 509,340.
- Not every contract has `unit.value` (Ірпінь РЕБ contract below has `items[].unit.value = None`); fall back to `contract.value.amount / quantity` for single-item tenders.

Also verified: `GET https://prozorro.gov.ua/api/tenders/{hex_id}/summary` → `{"tenderID": ...}` and `GET https://prozorro.gov.ua/api/tenders/{tenderID}/summary` → `{"id": <hex>, "tenderID", "title", "status", "value", "procuringEntity", "dateModified", "procurementMethodType", "tabCounters", …}` (both directions work).

## 5. Site search API (undocumented, verified)

`POST https://prozorro.gov.ua/api/search/tenders` — `GET` returns 405.

- Parameters can go in the **query string** or as a **JSON body**; both work for `text`, `page`, `sort_by`, `order`, `cpv`. **`date[...]` only worked as a query string** (`date[tender][start]=2026-08-20`); the nested JSON form `{"date":{"tender":{...}}}` was ignored. `cpv` must be an array (`cpv[]=…` in query string, or `"cpv":[...]` in JSON); bare `cpv=…` in query string is ignored.
- Response: `{"page", "per_page": 20, "total", "data": [{"tenderID", "title", "status", "value", "procuringEntity{name, identifier.legalName, address.locality}", "tenderPeriod.endDate"}]}`.
- `per_page` is **fixed at 20** (`per_page=100` ignored). `total` caps at **10,000**. Deep pages work (page 500 returned data). `page=0` → 422; `cpv[]=35613000` (8 chars) → 422 "must be 10 characters" — pass the full `35613000-4`.
- Param names from the SPA's `ParamsBuilder`: `text, cpv[], cpv_mask[], status[], proc_type[], buyer[] (ЄДРПОУ), tenderer[], supplier[], region, date[tender|enquiry|auction|award|qualification|publication][start|end], value[amount][start|end], sort_by, order, page`. `sort_by=dateCreated&order=desc|asc` verified. `cpv_mask` returned nothing for `3561` (**semantics not established**). `date[publication]` did not change totals (**appears ignored for tenders**).
- `cpv` search works as a JSON body with `sort_by=dateCreated&order=desc`, and is cheap. Tenders **created in the last 30 days** per code (verified 2026-09-20): 34710000-7 → 475 · 34740000-6 → 210 · 34711200-6 → 21 · 34741000-3 → 10 · 35730000-0 → 75 · 35720000-7 → 62 · 38630000-0 → 51 · 31430000-9 (batteries, mostly not drones) → 1,328. Whether `cpv` matches *any* item or only the first is **not established**.
- `date[tender]` filters on the tender period. **Because `reporting` tenders have no tenderPeriod, `date[tender]` excludes all direct contracts** — that's 36 % of my candidate set. Use `sort_by=dateCreated&order=desc` and stop when `tenderID` date < cutoff instead (that is what `scripts/harvest.py` does).
- The search is **fuzzy and searches item descriptions, not just titles**: `text=тепловізор` returned 282 hits in 30 days, only 18 with "тепловіз" in the title (the rest are телевізори); `text=FPV` matched "FPP" and tenders where FPV appears only in an item line. `FPV`, `дрон`, `дрони` all returned exactly 303 hits with only 175 overlapping. Treat it as a **recall** tool and re-filter on the full tender.

## 6. How drones / FPV / EW / thermal are actually classified (30 days, 2026-08-21 → 2026-09-20)

Method: 14 keyword searches → 1,746 unique tenders created in the window → full tender fetched for each → regex over `title + description + items[].description` → tally of `items[].classification.id`. Full numbers came from an exploratory script that is not included in this repository.

Tagged: drone 1,060 · FPV 284 · EW 123 · thermal 58. 494 of the 1,746 search hits were noise (TVs, software, cables, books…).

**Drones / FPV — item CPV codes (count of items):**

| CPV | Name | drone-tagged | FPV-tagged |
|---|---|---|---|
| 34710000-7 | Вертольоти, літаки, космічні та інші літальні апарати з двигуном | 552 | 55 |
| 34740000-6 | Обладнання для повітряних і космічних літальних апаратів, тренажери, симулятори… | 248 | 157 |
| 31430000-9 | Електричні акумулятори | 213 | 131 |
| 31440000-2 | Акумуляторні батареї | 61 | — |
| 35740000-3 | Симулятори бойових дій | 40 | 29 |
| 34711200-6 | Безпілотні літальні апарати | 39 | 15 |
| 34730000-3 | Частини повітряних і космічних літальних апаратів та вертольотів | 36 | — |
| 32350000-1 | Частини до аудіо- та відеообладнання | 36 | 9 |
| 34741000-3 | Обладнання для повітряних літальних апаратів | 17 | 14 |
| 35720000-7 | Системи розвідки, спостереження, виявлення цілі та рекогносцировки | 14 | — |
| 31434000-7 | Літієві акумуляторні батареї | 18 | — |
| 34711400-8 | (seen once: Mavic 4 Pro, Медведівська с/р) | | |

Takeaways:
- The obvious code **35613000-4 "Безпілотні літальні апарати" (military UAV) has 32 tenders in all of Prozorro history and 0 in the last 30 days.** Buyers overwhelmingly use **34710000-7** (manned-aircraft code) for complete drones and **34740000-6** for parts/kits/FPV components.
- A CPV-only filter on {34710000-7, 34711200-6, 34740000-6, 34741000-3, 34730000-3, 35613000-4, 35740000-3} catches **673 of 1,110 (60 %)** drone/FPV-tagged tenders. Batteries (31430000-9 / 31440000-2), cameras (32350000-1), radio (32230000-4, 32510000-1) hide the rest. → **Use CPV ∪ keywords, then classify by keywords.**
- Noise inside the drone CPV set: 34710000-7 tenders that are actually accessories (lights, propellers, cases at 2,760–16,000 UAH labelled "Matrice 4T"). Price clustering per model needs an accessory exclusion list.

**EW (РЕБ) — item CPV codes:** 35730000-0 "Електронні бойові комплекси та засоби радіоелектронного захисту" (65 items), 35720000-7 "Системи розвідки, спостереження…" (35 — this is where ESM/detector devices like «Чуйка» go), 35721000-4, 35723000-8, 38430000-8 / 38431000-5 "Детектори" (drone detectors «Кожан», «Видун»). 22113000-5 "Бібліотечні книги" (33) is a college library buying books about radio-electronics — exclude `kind` ≠ defense/authority plus a "радіоелектроніки" (genitive, the college name) vs "радіоелектронної боротьби" distinction in the regex.

**Thermal imagers — item CPV codes:** 38630000-0 "Астрономічні та оптичні прилади" (34), 38636000-2 "Спеціалізовані оптичні прилади" (3), 38631000-7 "Біноклі" (2), plus 34710000-7 / 34711200-6 (20 + 9) which are thermal-camera *drones* (Matrice 4T, Mavic 3T) — split those by keyword (`тепловізор` vs `matrice 4t|mavic 3t|тепловізійною камерою`). 44510000-8 "Знаряддя" (12) also appeared.

**Keywords that worked (regex on lower-cased title+description+item descriptions):**
- drone: `(?<![а-яіїє])дрон|квадрокоптер|безпілотн|бпла|бпак|\buav\b|\bmavic\b|\bautel\b|\bmatrice\b|\bdji\b|мультикоптер|гексакоптер|октокоптер|літальн(ий|их|ого|і) апарат` — the negative look-behind matters: a bare `дрон` matched "гі**дрон**асос" and a few pharmaceuticals in the raw feed.
- fpv: `\bfpv\b|фпв`
- ew: `\bреб\b|радіоелектронн(ої|а|ий|ого|их|у|і) (боротьб|захист|подавл|протиді)|антидрон|глушил|подавлюва|детектор (дрон|бпла)|постановник|станці[яї] завад|засіб реб`
- thermal: `тепловіз` (do **not** search "тепловізор" in the site search without re-filtering — it fuzzy-matches "телевізор")

Search keywords used for recall (site search): `FPV, дрон, дрони, БПЛА, безпілотн, квадрокоптер, Mavic, РЕБ, радіоелектронн, тепловізор, тепловізійн, антидрон, БпАК, Autel`. **Missing from that list and should be added: `DJI`, `Matrice`** (see recall check below).

**Recall check against the raw feed (independent of the site search).** The earlier run in this container left `data/sample_tenders.jsonl`: 29,383 tenders = every tender modified 2026-09-17 15:52 → 2026-09-20 00:42 (2.37 days), pulled straight from the public feed. Running the same regex + CPV classifier over it:
- 347 tagged tenders in 2.37 days → **≈130 drone-related and ≈147 total drone/EW/thermal tenders are created or modified per day** (feed-wide, all buyer kinds; 229 of 347 are `defense`, 78 `general`, 36 `authority`).
- Of the 338 tagged tenders created inside my 30-day window, the keyword harvest had **236 (69 %)**. The 102 misses split into: parts with no drone word in the title but a drone CPV (Hobbywing propellers, ESCs, antennas, Li-Ion packs under 34740000-6); DJI **Matrice** batteries/speakers (I never searched "Matrice"/"DJI"); airsoft/laser-trainer tenders under **35740000-3** (that code is *not* a drone code — drop it or treat as low-confidence); and my own regex false positives (`дрон` inside other words).
- → Harvest = union of keyword searches **and** CPV searches (34710000-7, 34711200-6, 34740000-6, 34741000-3, 35730000-0, 35720000-7, 35721000-4, 38630000-0), then classify on the full tender. Expect roughly 800–1,000 candidates per 30 days after de-duplication, ~40 % of them noise.

## 7. Unit-price comparison — does it work? (2026-09-20, `scripts/price_table.py` → `data/price_table.csv`)

Per **item** (tender items joined to bid items and contract items by item id). Product typing: Prozorro Market category + Бренд/Модель answers where they exist, description regex otherwise; accessories excluded by a regex that includes the "X для БпЛА <model>" pattern and a Latin→Cyrillic homoglyph normaliser (one buyer wrote "Прожeктop дл БпЛА" with Latin e/o/p). Signed price = `contract.items[].unit.value` (123/123 contract items joined by id), else `contract.value/qty`, else `items[].unit.value`, else `award.value/qty`. All amounts net of VAT (every row had `valueAddedTaxIncluded: false`).

| type | items | tenders | signed unit, median | IQR | min–max | n signed | all bidder unit prices, median (n) | lowest-bid → signed |
|---|---|---|---|---|---|---|---|---|
| **DJI Matrice 4T** | 150 | 149 (119 priceQuotation, 16 belowThreshold, 14 reporting) | **172,475** | 171,382–174,050 | 162,500–239,000 | 114 | 174,300 (618 bids) | +0–2 % |
| Matrice 4T, `kind = defense` | 138 | | 172,340 | 171,322–173,892 | 162,500–225,000 | 104 | | |
| Matrice 4T, `kind ≠ defense` | 12 | | 173,850 | 172,998–185,370 | 169,780–239,000 | 10 | | |
| **FPV 10" day (analog, radio)** | 11 | 11 | **19,960** | 18,100–23,950 | 12,000–25,000 | 10 | 19,960 (9 bids) | |
| FPV 10" with thermal camera | 2 | 2 | 50,700 | — | — | 1 | | |
| FPV 10" fiber-optic | 1 | 1 | — (still tendering) | | | 0 | | |

Reading:
- **Matrice 4T comparison works.** Expected (budget) median 179,866 vs signed 172,475 → buyers budget ~4 % above the market; 618 bidder prices sit in a 173–175k band; the max signed 239,000 is a 1-unit police purchase "в комплекті" (extra batteries/kit) — a multi-item kit sold as one item. Municipal buyers (n=10) pay the same as military units.
- **"FPV 10 дюймів" is not one product.** The characteristics block splits it: 10"/4 kg/analog/ELRS day drone 23,600 (VYRIY PRO 10), the same with a thermal camera 50,700 (VYRIY JOHNNY PRO 10), a 15"/8 kg one 46,800 — all three in one tender, `UA-2026-09-08-014877-a`. Луцьк's 12,000 "КУЛЯ" and Вінниця's 12,522 (2,000 units) are the cheap end. Any FPV price table needs at least size × link (radio/fiber) × camera (day/thermal) axes, which the `TECHNICAL_FEATURES` requirements give directly for priceQuotation tenders (`Розмір`, `Управління за допомогою оптоволоконного кабелю`, `Тепловізор`).
- **Split purchases inflate n.** ГУНП Полтавська ran 7 identical priceQuotation tenders of 5–10 FPV drones at 19,997 expected / 19,960 signed on the same day (UA-2026-09-09-012287 … 013914 + 010-005166). Count them as one observation for the digest, or the median is just that buyer.
- Coverage limit: 1,529 of the 1,746 candidates' first items are accessories/batteries/parts, and only 4 FPV tenders of other sizes (4", 7", 8", 15") exist in the set — FPV volume in this 30-day window is mostly military `reporting` tenders with generic descriptions and no characteristics block.

Structured typing coverage: 545/1,746 candidates (31 %) have Market category + characteristics + all bidders' unit prices. **But by buyer it is uneven** (product classes only, parts excluded):

| buyer set | n | priceQuotation | reporting | aboveThreshold | negotiation |
|---|---|---|---|---|---|
| all non-defense (general/authority/special) | 251 | 16 % | 36 % | 41 % | 5 % |
| councils only (міська/сільська/селищна рада, виконком, КП, ВА) | 95 | 21 % | 45 % | 27 % | 6 % |
| defense | 391 | 62 % | 18 % | 17 % belowThreshold | — |

Non-defense by class: Matrice 4T 12/17, FPV 11/17 and Mavic 8/12 go through the catalogue, but **EW 0/109** (detectors 32 reporting + 31 aboveThreshold; jammers 12 + 34), thermal imagers 2/17, fixed-wing 0/13. For DJI-class drones the structured data covers communities; for EW, thermal and non-DJI drones the price comes from `contract.value/qty` (+ `items.unit.value` in ~1/3 of `reporting`) or `bid.value/qty`, and the spec only from attached documents.

**Additional precise types added 2026-09-20 (EW ESM «Чуйка», the most common municipal EW purchase):** version decides the price and it is exact across buyers — `esm_chuika_3` (base or 3.0) **25,700 net** (n=14, IQR 25,700–25,700), `esm_chuika_4` **50,400 net** (n=6, all six identical once contract-level VAT is handled), `esm_chuika_kit` («в комплекті №N», military) 37,700 (n=3). Typed by regex on «Чуйка» + version — these tenders have no characteristics block.

Benchmarks live in `data/benchmarks.json` (median / IQR / min / max of signed net unit price, split purchases collapsed = same buyer ЄДРПОУ + same created date + same type → one observation): matrice_4t 172,600 (n=103), fpv_10_day 19,960 (n=5), fpv_10_thermal 50,700 (n=1), esm_chuika_3 25,700 (14), esm_chuika_4 50,400 (6), esm_chuika_kit 37,700 (3).

## 8. Three real tenders for manual checking

All three re-fetched live from the public API on 2026-09-20 and cross-checked against the signed contract object. Amounts in UAH, VAT **not** included (`valueAddedTaxIncluded: false` on value, award and contract in all three).

### 1) Луцьк — 20 × FPV drones 10"
- Link: https://prozorro.gov.ua/tender/UA-2026-08-25-003833-a
- Buyer: Виконавчий комітет Луцької міської ради (ЄДРПОУ 04051327, kind `general`)
- Procedure / status: `priceQuotation` / `complete`
- Item: «Безпілотний літальний апарат мультироторного типу (FPV) 10 дюймів, від 2,5 кг, ELRS/TBS Crossfire», CPV 34710000-7, **qty 20 шт**
- Expected value: **360,000** → 18,000 / unit
- Bids: 240,000 · 278,960 · 354,000 (3 bidders) → per-unit in `bids[].items[].unit.value`: **12,000 · 13,948 · 17,700**; bidder-described products: «КУЛЯ», BPK-10 WYVERN-D, GEPRC MARK4 LR10
- Characteristics (`criteria` TECHNICAL_FEATURES): Розмір 10 дюйм, Корисне навантаження ≥ 2.5 кг, Протокол прийому сигналу, Відеозв'язок; winner answered ELRS / аналоговий
- Award (active): 240,000 — ТОВ «ЗАХІД ДРО…» (ЄДРПОУ 45367584)
- Contract №555, signed 2026-08-31, value 240,000; contract item «…FPV 10 дюймів "КУЛЯ"», qty 20, **unit.value 12,000**
- Unit price: **12,000 UAH** signed (vs 18,000 expected)

### 2) Ірпінь — 6 × EW (РЕБ) units
- Link: https://prozorro.gov.ua/tender/UA-2026-09-08-013028-a
- Buyer: Виконавчий комітет Ірпінської міської ради (ЄДРПОУ 05408846, kind `general`)
- Procedure / status: `negotiation` / `complete` (no bids by design)
- Item: «Придбання засобів радіоелектронної боротьби (РЕБ)», CPV 35730000-0, **qty 6 шт**
- Expected value: **2,100,000**
- Award (active): 2,100,000 — ТОВ «ЛЕЛЕКА ДР…» (ЄДРПОУ 45514866)
- Contract №467, signed 2026-09-14, value 2,100,000; contract item has **no `unit.value`**
- Unit price: **350,000 UAH** (= 2,100,000 / 6, derived, not stated). The item description does not name a model, there is no characteristics block (`negotiation` procedure), and the only spec is in the attached `обгрунтування.pdf`. **Meaningless as a unit price until documents are read — parked.**

### 3) Буринь — 3 × DJI Matrice 4T
- Link: https://prozorro.gov.ua/tender/UA-2026-09-03-008514-a
- Buyer: Буринська міська рада (ЄДРПОУ 04058025, kind `authority`, м. Буринь, Конотопський р-н)
- Procedure / status: `priceQuotation` / `complete`
- Item: «Квадрокоптер DJI Matrice 4T (CP.EN.00000546.02)», CPV 34710000-7, **qty 3 шт**
- Expected value: **534,660** → 178,220 / unit
- Bids: 8 bidders, 509,340 … 534,000 → per-unit **169,780 · 171,000 · 172,000 · 175,000 · 176,000 · 176,900 · 177,000 · 178,000**
- Characteristics: Бренд → DJI, Модель → Matrice 4T (from the winner's `requirementResponses`); item `category` 34710000-259894-40996564 (Квадрокоптери); description states the price is set without VAT under п. 32 підрозділу 2 розділу XX ПКУ
- Award (active): 509,340 — ФОП Бечкало С. В.
- Contract №565, signed 2026-09-11, value 509,340; contract item qty 3, **unit.value 169,780**
- Unit price: **169,780 UAH** signed

## 9. Files from an earlier run in this container

`probes/01…07_*.py/.out` and `data/sample_tenders.jsonl` (74 MB) were already in the working directory when I started (timestamps ~30 min before my first command). I did not write them and cannot see the conversation that did. I read their outputs; they agree with mine on every overlapping point (opt_fields whitelist, `limit` cap, 404 on tenderID, `/summary`, contract `items[].unit.value`) and add two facts I have cited above: the 57 req/s public-API throughput and the 29k-tender feed sample used for the recall check. `06_scan.py` was interrupted at 29,383 of 40,000 tenders.

## 10. Digest v1 (2026-09-20)

`scripts/digest.py` → `data/digests/digest_YYYY-MM-DD.md`. Part 1: open tenders (enquiries/tendering/auction/qualification) for `kind ∈ {general, authority, special}`, product classes only, sorted by deadline (`tenderPeriod.endDate`; for qualification `awardPeriod.startDate`), expected net unit price vs benchmark where a precise type exists. Part 2: contracts with `dateSigned` in the window, signed net unit price vs benchmark, ⚠ when > +15 %. Split purchases collapsed in both parts (ГУНП Полтавська's 5 same-day FPV tenders become one row "43 in 5 tenders"). Rows typed by regex only are marked ~. Defense buyers are counted in the header, not listed. State: `data/state/pending.json` (non-terminal tenders, all kinds, re-fetched by `refresh.py`), `data/state/reported.json` (never list a closed tender twice). First run: 65 open rows, 46 closed rows, 1 flagged (ГУНП Хмельницька, «Чуйка 3.0» at 38,420 = +49 % — verified live: contract 422,620 / 11, no items unit price; the description says «Пристрій виявлення БПЛА», possibly a different bundle — worth opening).

**Documents (2026-09-20, `scripts/docs.py`).** `tender.documents[]` carry `url` (pre-signed link on `public-docs.prozorro.gov.ua`, downloadable with a plain GET), `documentType` (`technicalSpecifications`, `biddingDocuments`, `contractProforma`, `eligibilityCriteria`, `notice`…), `format`, `title`. The spec is usually a separate `technicalSpecifications` .docx titled «Додаток 2 …»; .docx is read with `zipfile` (stdlib), .doc via `soffice`, .pdf via `pdftotext` when present. For every **flagged** closed row the digest downloads up to 4 spec-relevant documents, extracts the section after «Технічні характеристики / технічна специфікація», and writes a one-line verdict: family (ESM/drone), core facts (bands, mAh, size, thermal, fiber), extras found («виносна антена», «підсумок», «автомобільний тримач», «в комплекті», extra batteries, RC Plus, Care…) → "bundle" vs "looks like the base item", plus bid count (single-bidder noted). Catalogue tenders skip the download — their characteristics block *is* the spec. Verified on the first flag: ГУНП Хмельницька «Чуйка 3.0» ×11 at 38,420 (+49 %) — spec has the same three bands and 4500 mAh as Городоцька's 25,700 spec **plus** a required 3 m remote antenna, pouch, mount, car holder and a video screen; 1 bid (ТОВ «Блюберд тех», the usual Чуйка supplier), no auction. → bundle, single bidder, −4 % vs a budget set at 39,990.

Flags (v1.2): three independent marks — ⚠P signed unit price > +15 % vs benchmark; ⚠S exactly one bid in a competitive procedure (aboveThreshold / belowThreshold / priceQuotation; visible from qualification on); ⚠B buyer's expected unit price > +30 % vs benchmark. Any of them triggers the document verdict. The top-5 open tenders by value get machine-extracted spec facts (`docs.spec_facts`) plus hand-written paragraphs from `data/notes/notes_<date>.md` when present. `.docx`/`.odt` are read with `zipfile`, `.doc` via `soffice`, `.pdf` via `pdftotext` (both installed here).

Digest layout (v1.1): **Summary** (open count + total expected value net, top-5 open by value, every flag with its doc verdict and bid count, benchmark changes vs the previous digest date from `data/state/benchmarks_history.json`) → §1 open (non-defense, by deadline; qualification rows say "in qualification", the award-period start is not a deadline) → §2 closed with verdict column → §3 benchmarks → **Appendix A: open defense tenders** (buyer, product, qty, expected value, deadline, link; no price comparison — military volume is > half the market and producers sell there first) → §4 state.

Weekly run order: `refresh.py` (re-fetch pending, discover new) → `price_table.py` (rebuild benchmarks) → `digest.py`. Discovery goes through the site adapter by default; `refresh.py --discover feed` uses the official feed instead (walk + fetch every non-defense tender, ~2 min per feed-day at the measured 57 req/s; tested only on a single feed page so far).

## 11. What I did NOT do / open questions

- Did not test the public API's `/contracts` feed, `/plans`, `/agreements`, or `/tenders/{id}/documents` beyond seeing `documents[]` inline.
- Did not test the OCDS export, bi.prozorro.org, or the Prozorro "infobox" — only the two APIs above.
- Did not stress-test the public API for rate limits; 8 parallel workers for ~300 requests produced no 429s from `public-api`, all 429s came from `prozorro.gov.ua/api`.
- Did not find the Prozorro Market API for resolving `category` / `profile` ids to names (one guessed path, 404).
- `cpv_mask` semantics and `date[publication]` for tenders remain unknown (both returned nothing / no change).
- Bids are hidden during `active.tendering`; a weekly digest will need to **re-fetch tenders seen in earlier weeks** until they reach `complete` / `unsuccessful` / `cancelled` to get signed prices.
- The site API is unofficial and must stay a replaceable adapter (user's rule: nothing that only works through it). Fallback is walking the public feed with `opt_fields=procuringEntity,procurementMethodType,status` and fetching full tenders only for buyers with `kind ∈ {general, authority}` — untested, and still ~thousands of GETs per day.
