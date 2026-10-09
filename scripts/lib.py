"""Shared code for the Prozorro drone/EW price digest. Python + requests only.

Layout of this module
  1. API layer      public API (official) + site API (unofficial, behind an adapter) + feed-walk fallback
  2. cache          one JSON file per tender in data/tenders/, contracts in data/contracts/
  3. text utils     Latin/Cyrillic homoglyph normaliser, CPV-boilerplate stripper
  4. classifiers    guess()        coarse product class for any tender (18 classes)
                    classify_item() precise price types (matrice_4t, fpv_10_day/thermal/fiber)
  5. characteristics  TECHNICAL_FEATURES criteria and bid requirementResponses, per item
"""
import json, os, re, time, glob, statistics
import requests

PUBLIC = "https://public-api.prozorro.gov.ua/api/2.5"
SITE = "https://prozorro.gov.ua/api"          # unofficial; only used inside the `site_*` adapter functions
DATA = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
TENDERS_DIR = os.path.join(DATA, "tenders"); CONTRACTS_DIR = os.path.join(DATA, "contracts")
os.makedirs(TENDERS_DIR, exist_ok=True); os.makedirs(CONTRACTS_DIR, exist_ok=True)

S = requests.Session()
S.headers.update({"User-Agent": "Mozilla/5.0 (prozorro-drone-digest research script)", "Accept": "application/json"})
TERMINAL = {"complete", "unsuccessful", "cancelled"}

# ---------------------------------------------------------------- 1. API layer
def _get(url, params=None, tries=6, timeout=60):
    """GET with 429 backoff. Returns Response (may be non-200) or raises after `tries`."""
    for attempt in range(tries):
        r = S.get(url, params=params, timeout=timeout)
        if r.status_code == 429:
            ra = r.headers.get("Retry-After"); time.sleep(float(ra) if ra else 2 * (attempt + 1)); continue
        return r
    return r

def public_tender(hex_id):
    r = _get(f"{PUBLIC}/tenders/{hex_id}")
    return r.json()["data"] if r.status_code == 200 else None

def public_contract(contract_id):
    r = _get(f"{PUBLIC}/contracts/{contract_id}")
    return r.json()["data"] if r.status_code == 200 else None

def public_feed(offset=None, limit=1000, descending=False, opt_fields="dateCreated,status,procurementMethodType,procuringEntity"):
    """One page of the official feed. offset: ISO date, unix ts, or next_page.offset token."""
    params = {"limit": limit, "opt_fields": opt_fields}
    if offset: params["offset"] = offset
    if descending: params["descending"] = 1
    r = _get(f"{PUBLIC}/tenders", params=params)
    return r.json() if r.status_code == 200 else None

# --- site API adapter (unofficial). Everything that touches prozorro.gov.ua/api goes through these two functions.
def site_search(params):
    """POST /api/search/tenders. Query-string params: text, cpv[], page, sort_by, order, date[tender][start]...
    Returns dict {page, per_page(20), total(≤10000), data:[{tenderID,title,status,value,procuringEntity,...}]} or None."""
    for attempt in range(6):
        r = S.post(f"{SITE}/search/tenders", params=params, timeout=60)
        if r.status_code == 429: time.sleep(2 * (attempt + 1)); continue
        return r.json() if r.status_code == 200 else None
    return None

def site_resolve(tender_id):
    """UA-YYYY-... → 32-hex id via /api/tenders/{tenderID}/summary (rate-limited: ~1 req/s is safe)."""
    r = _get(f"{SITE}/tenders/{tender_id}/summary")
    return r.json().get("id") if r.status_code == 200 else None

# --- candidate discovery: two implementations behind one interface -----------------------------
KEYWORDS = ["FPV", "дрон", "дрони", "БПЛА", "безпілотн", "квадрокоптер", "Mavic", "Matrice", "DJI", "Autel",
            "РЕБ", "радіоелектронн", "антидрон", "тепловізор", "тепловізійн", "БпАК"]
CPV_CODES = ["34710000-7", "34711200-6", "34740000-6", "34741000-3", "35730000-0", "35720000-7", "35721000-4", "38630000-0"]

def find_candidates_site(cutoff_date, max_pages=500, log=print):
    """Keyword + CPV searches on the site API, newest-first by dateCreated, stop at cutoff (YYYY-MM-DD).
    Returns {tenderID: {"title","status","found_by":[...]}}. Cost: ~1 request per 20 hits."""
    out = {}
    def walk(label, base):
        page = 1
        while page <= max_pages:
            d = site_search({**base, "page": page, "sort_by": "dateCreated", "order": "desc"})
            if not d or not d.get("data"): break
            stop = False
            for x in d["data"]:
                if x["tenderID"][3:13] < cutoff_date: stop = True; break
                rec = out.setdefault(x["tenderID"], {"title": x.get("title"), "status": x.get("status"), "found_by": []})
                rec["found_by"].append(label)
            if stop: break
            page += 1; time.sleep(0.1)
        log(f"  search {label}: pages {page}, running total {len(out)}")
    for kw in KEYWORDS: walk(f"text:{kw}", {"text": kw})
    for cpv in CPV_CODES: walk(f"cpv:{cpv}", {"cpv[]": cpv})
    return out

def find_candidates_feed(since_iso, until_iso=None, kinds=("general", "authority", "special"), log=print, max_pages=None):
    """FALLBACK without the site API: walk the official feed from `since_iso` (dateModified order) and return
    hex ids of tenders whose procuringEntity.kind is in `kinds`. Cost: ~22 pages of 1000 per day of feed, then one
    GET per tender (≈ 1/3 of the feed for non-defense kinds; ~7k GETs/day at 57 req/s ≈ 2 min/day). No titles
    in the feed, so classification happens only after the full fetch. Tested on one page only (see PROCESS_LOG)."""
    ids, seen, pages, off = {}, set(), 0, since_iso
    while True:
        d = public_feed(offset=off)
        if not d or not d["data"]: break
        pages += 1
        for row in d["data"]:
            if until_iso and row["dateModified"] > until_iso: return ids
            if row["id"] in seen: continue
            seen.add(row["id"])
            pe = row.get("procuringEntity") or {}
            if pe.get("kind") in kinds: ids[row["id"]] = {"dateModified": row["dateModified"], "kind": pe.get("kind"), "name": pe.get("name")}
        off = d["next_page"]["offset"]
        if max_pages and pages >= max_pages: break
        if len(d["data"]) < 1000: break
    log(f"  feed walk: {pages} pages, {len(seen)} unique tenders seen, {len(ids)} with kind in {kinds}")
    return ids

# ---------------------------------------------------------------- 2. cache
def tender_path(tender_id): return os.path.join(TENDERS_DIR, f"{tender_id}.json")
def load_tender(tender_id):
    p = tender_path(tender_id); return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None
def save_tender(t): json.dump(t, open(tender_path(t["tenderID"]), "w", encoding="utf-8"), ensure_ascii=False)
def all_cached_tenders():
    for p in sorted(glob.glob(os.path.join(TENDERS_DIR, "*.json"))): yield json.load(open(p, encoding="utf-8"))

def fetch_tender_by_tender_id(tender_id, force=False):
    """tenderID → cached full tender; resolves hex id via the site adapter only when not cached."""
    t = load_tender(tender_id)
    if t and not force: return t
    hex_id = t["id"] if t else site_resolve(tender_id)
    if not hex_id: return None
    full = public_tender(hex_id)
    if full: save_tender(full)
    return full

def contract(contract_id):
    p = os.path.join(CONTRACTS_DIR, f"{contract_id}.json")
    if os.path.exists(p): return json.load(open(p, encoding="utf-8"))
    d = public_contract(contract_id)
    if d: json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False)
    return d

# ---------------------------------------------------------------- 3. text utils
_HOMO = str.maketrans("aceiopxyABCEHIKMOPTX", "асеіорхуАВСЕНІКМОРТХ")
def norm(s):
    """Map Latin look-alike letters to Cyrillic inside mixed-script words ('Прожeктop' → 'Прожектор'); Latin-only words untouched."""
    out = []
    for w in (s or "").split():
        latin = any(c.isascii() and c.isalpha() for c in w); cyr = any('Ѐ' <= c <= 'ӿ' for c in w)
        out.append(w.translate(_HOMO) if (latin and cyr) else w)
    return " ".join(out)

def strip_cpv_boilerplate(text, item=None):
    text = re.sub(r"(код(ом)?\s*)?(за\s*)?ДК\s*021[:\s-]*2015[^«»]*?«[^»]*»", " ", text)
    text = re.sub(r"\d{8}-\d\s*[-–—]?\s*", " ", text)
    name = ((item or {}).get("classification") or {}).get("description") or ""
    return text.replace(name, " ") if name else text

def item_text(t, it):
    return norm(strip_cpv_boilerplate(f"{t.get('title','')} {it.get('description','')}", it)).lower()

# ---------------------------------------------------------------- 4. classifiers
CAT_QUAD = "34710000-259894-40996564"   # Prozorro Market: Квадрокоптери
CAT_FPV = "34710000-331552-40996564"    # Prozorro Market: БпЛА мультироторного типу (FPV)
MARKET_CAT = {CAT_QUAD: "quadcopter", CAT_FPV: "fpv_drone", "31430000-888358-40996564": "drone_battery",
              "b9d2c60fd2ec49aab4f338bb95cedb1c": "drone_parts", "34740000-241144-40996564": "drone_parts",
              "34740000-572349-40996564": "fpv_goggles", "38630000-497369-32348248": "thermal_imager",
              "7ffd3bbca167431284aa984655106372": "drone_battery", "32320000-777386-32348248": "not_relevant"}
DRONE_CTX = re.compile(r"дрон|квадрокоптер|бпла|бпак|безпілотн|fpv|фпв|dji|mavic|matrice|autel|uav|літальн", re.I)
DRONE_CPV_PREFIX = ("3471", "3474", "3473", "3561")
PRODUCT_CLASSES = {"matrice_4t", "matrice_other", "mavic", "autel", "quadcopter", "quadcopter_other", "fpv_drone",
                   "fixed_wing_uav", "ew_jammer", "ew_detector", "thermal_imager", "ground_robot"}
PARTS_CLASSES = {"drone_battery", "drone_parts", "fpv_goggles"}
RULES = [  # order matters
    ("service_repair",     r"послуг|ремонт|обслуговув|страхув|навчанн|експертн"),
    ("training_simulator", r"тренаж|симулятор|навчальн(ий|е|а) (обладн|комплекс)|страйкбол"),
    ("ew_detector",        r"чуйка|детектор|виявлення (сигнал|дрон|fpv|бпла)|реб[- ]?тестер|електронної підтримки|радіоелектронної розвідки|\bрер\b|сканер"),
    ("ew_jammer",          r"\bреб\b|радіоелектронної боротьби|антидрон|глушил|подавлюва|станці[яї] завад|купол|dronopad|rebster"),
    ("drone_battery",      r"акумул|батаре|battery|\bакб\b|li-?ion|lipo|li-?po"),
    ("fpv_goggles",        r"окуляр|goggles|шолом fpv"),
    ("drone_parts",        r"пропелер|пульт|controller|антен|підсилюв|прожектор|гучномов|speaker|кейс|сумк|заряд|карт[аи] пам|ретранслятор|скид|кабель|рам[аи] |мотор|регулятор|esc\b|камер[аи] |vtx|vrx|приймач|передавач|політн(ий|і) контролер|комплектуюч|запчаст|запасн|плат[аи] |модул|обладнання (для|до) (бпла|безпілотн|дрон|квадрокоптер)"),
    ("thermal_imager",     r"тепловіз(ор|ійн)(?!.*(дрон|бпла|квадрокоптер|matrice|mavic))|прилад нічного бачення|\bпнб\b|приціл"),
    ("matrice_4t",         r"matrice\s*4\s*t\b|матріс 4т"),
    ("matrice_other",      r"matrice|матріс"),
    ("mavic",              r"mavic|мавік"),
    ("autel",              r"autel|аутел"),
    ("fpv_drone",          r"(fpv|фпв).*(дрон|бпла|апарат|квадрокоптер)|(дрон|бпла|апарат|квадрокоптер).*(fpv|фпв)|мультироторного типу"),
    ("fixed_wing_uav",     r"крил|літаков|бпак|авіаційний комплекс|розвідувальн"),
    ("ground_robot",       r"наземн(ий|ого) робот|нрк"),
    ("quadcopter_other",   r"квадрокоптер|дрон|бпла|безпілотн|uav|dji"),
]

def guess(t, it=None):
    """Coarse product class for a tender (first item by default). Returns (class, how)."""
    it = it or t["items"][0]
    text = item_text(t, it)
    cat = MARKET_CAT.get(it.get("category") or "")
    drone_ctx = bool(DRONE_CTX.search(text)) or it["classification"]["id"][:4] in DRONE_CPV_PREFIX or bool(cat and cat != "not_relevant")
    for typ, rx in RULES:
        if re.search(rx, text, re.I):
            if typ in ("drone_parts", "drone_battery", "fpv_goggles", "service_repair", "training_simulator") and not drone_ctx:
                return "not_relevant", f"{typ} without drone context"
            if cat and cat != typ and typ in ("quadcopter_other", "fpv_drone", "drone_parts", "drone_battery"): return cat, "market category over regex"
            if typ == "quadcopter_other" and re.search(r"matrice\s*4\s*t", text): return "matrice_4t", "regex"
            return typ, "regex"
    if cat: return cat, "market category"
    return "not_relevant", "no rule matched"

# --- precise price types ---------------------------------------------------------------------
DRONE_NOUN = r"квадрокоптер|дрон|бпла|бпак|безпілотн|літальн|uav"
ACCESSORY = re.compile(
    r"акумул|батаре|battery|пропелер|кейс|сумк|гучномов|speaker|антен|пульт|controller|заряд|світл|ліхтар|прожектор|підсилюв|"
    r"карт[аи] пам|модул|кабель|ремонт|обслуг|rc plus|rc-plus|окуляр|goggles|станці[яї]|зап(асн|част)|комплектуюч|тренаж|симулятор|"
    r"навчальн|послуг|страхув|dock|док-станц|підвіс|об'єктив|дисплей|монітор|трим|кріплен|фільтр|чохол|ремінь|enterprise kit|care|"
    r"скид|скидач|парашут|ретранслятор|репітер|repeater|для (бпла|квадрокоптер|дрон|безпілотн)", re.I)
M4T = re.compile(r"matrice\s*4\s*t\b|матріс\s*4\s*т|\bm4t\b", re.I)
FPV = re.compile(r"\bfpv\b|фпв|мультироторного типу", re.I)
INCH10 = re.compile(r"(?<![\d,.])10\s*[\"”″']{1,2}|(?<![\d,.])10\s*[- ]?(дюйм|inch|in\b)", re.I)

def num(x):
    try: return float(str(x).replace(",", "."))
    except (TypeError, ValueError): return None

def classify_item(t, it, answers, exp):
    """Precise price type for one tender item → (type, how) or (None, reason).
    answers: list of {requirement title: value} per bid (this item); exp: {title: expected} for this item."""
    desc = norm(it["description"].strip()); cat = it.get("category") or ""
    models = " ".join(f"{a.get('Бренд','')} {a.get('Модель','')}" for a in answers)
    # EW ESM device «Чуйка»: version decides the price (base/3.0 ≈ 25,700 net; 4.0 ≈ 50,400 net; kits 36–38k)
    if re.search(r"чуйк", desc + " " + t["title"], re.I) and not re.search(r"послуг|обслуг|ремонт", desc, re.I):
        tx = desc + " " + t["title"]
        if re.search(r"в комплект", tx, re.I): return "esm_chuika_kit", "regex чуйка + в комплекті"
        m = re.search(r"чуйк\w*\s*[«\"“”']?\s*(\d)(?:\.\d)?", tx, re.I)
        return (f"esm_chuika_{m.group(1)}" if m else "esm_chuika_3"), "regex чуйка + version (base counted as 3.0)"
    is_drone_noun = re.search(DRONE_NOUN, desc, re.I)
    starts_with_drone = re.match(rf"^\W*({DRONE_NOUN}|dji|fpv)", desc, re.I)
    accessory = bool(ACCESSORY.search(desc)) and not (starts_with_drone and not re.search(r"для (бпла|квадрокоптер|дрон|безпілотн)", desc, re.I))
    if cat == CAT_QUAD and not accessory and (M4T.search(desc) or M4T.search(models)): return "matrice_4t", "market cat Квадрокоптери + model"
    if accessory: return None, "accessory"
    if M4T.search(desc) and is_drone_noun: return "matrice_4t", "description"
    if M4T.search(desc): return None, "m4t-mentioned-not-drone"
    size = exp.get("Розмір") or (answers[0].get("Розмір") if answers else None)
    fiber = str(exp.get("Управління за допомогою оптоволоконного кабелю", "")).lower() in ("так", "true") or bool(re.search(r"оптоволок|fiber", desc + " " + t["title"], re.I))
    thermal = exp.get("Тепловізор") is True or bool(re.search(r"тепловіз|нічн", desc, re.I))
    sub = "fiber" if fiber else ("thermal" if thermal else "day")
    if cat == CAT_FPV and num(size) == 10: return f"fpv_10_{sub}", "market cat FPV + Розмір=10"
    if cat == CAT_FPV: return None, f"fpv-other-size-{size}"
    if FPV.search(desc) and INCH10.search(desc) and is_drone_noun: return f"fpv_10_{sub}", "description regex"
    if FPV.search(desc) and INCH10.search(t["title"]) and is_drone_noun: return f"fpv_10_{sub}", "title regex"
    return None, None

# ---------------------------------------------------------------- 5. characteristics
def _tech_criteria(t, item_id=None):
    for c in t.get("criteria", []) or []:
        if "TECHNICAL_FEATURES" not in (c.get("classification") or {}).get("id", ""): continue
        if item_id and c.get("relatedItem") and c["relatedItem"] != item_id: continue
        yield c

def req_expected(t, item_id=None):
    """{requirement title: expectedValue | expectedValues | minValue} for one item."""
    m = {}
    for c in _tech_criteria(t, item_id):
        for g in c.get("requirementGroups", []):
            for r in g.get("requirements", []):
                ev = r.get("expectedValue")
                val = ev if ev is not None else (r.get("expectedValues") or r.get("minValue"))
                m[r.get("title", "").strip()] = val[0] if isinstance(val, list) and len(val) == 1 else val
    return m

def req_ids_for_item(t, item_id):
    return {r.get("id") for c in _tech_criteria(t, item_id) for g in c.get("requirementGroups", []) for r in g.get("requirements", [])}

def resp_map(bid, req_ids=None):
    """bid requirementResponses → {title: value}, optionally restricted to one item's requirement ids."""
    m = {}
    for r in bid.get("requirementResponses", []) or []:
        req = r.get("requirement") or {}
        if req_ids and req.get("id") not in req_ids: continue
        vs = r.get("values"); m[req.get("title", "").strip()] = vs[0] if vs else r.get("value")
    return m

# ---------------------------------------------------------------- prices
def active_bids(t): return [b for b in t.get("bids", []) if b.get("status") in ("active", None)]

def bid_unit_prices(t, it):
    """Sorted list of bidder unit prices for an item (bids[].items[].unit.value, else bid total / qty for single-item
    tenders). Bids below 20 % of the tender's median are returned separately as implausible (real case: 173 for 173,000)."""
    qty = it["quantity"]; n_items = len(t["items"]); out = []
    for b in active_bids(t):
        bi = next((x for x in b.get("items", []) if x.get("id") == it["id"]), None)
        uv = (((bi or {}).get("unit") or {}).get("value") or {}).get("amount") if bi else None
        total = (b.get("value") or {}).get("amount")
        if uv is None and n_items == 1 and total and qty: uv = round(total / qty, 2)
        if uv is not None: out.append(uv)
    out.sort()
    med = statistics.median(out) if out else None
    implausible = [x for x in out if med and x < 0.2 * med]
    return [x for x in out if x not in implausible], implausible

def signed_unit_price(t, it, cdoc=None):
    """(net unit price, source, dateSigned). Net of VAT using the CONTRACT's own flag (it can differ from the tender's:
    tender net 504,000 → contract 604,800 with VAT, amountNet 504,000 — seen on UA-2026-08-27-002779-a).
    Order: contract items unit.value → contract amountNet/qty → items.unit.value → award/qty."""
    qty = it["quantity"]; n_items = len(t["items"])
    if cdoc is None:
        for c in t.get("contracts", []):
            if c["status"] in ("active", "pending"): cdoc = contract(c["id"]); break
    if cdoc:
        signed_date = (cdoc.get("dateSigned") or "")[:10]; cv = cdoc.get("value") or {}
        c_vat = cv.get("valueAddedTaxIncluded"); note = " gross÷1.2" if c_vat else ""
        ci = next((x for x in cdoc.get("items", []) if x.get("id") == it["id"]), None)
        if ci and (ci.get("unit") or {}).get("value"):
            # item-level VAT flag is unreliable (seen False on a price that equals gross total / qty); use the contract's
            factor = (cv["amountNet"] / cv["amount"]) if (c_vat and cv.get("amountNet") and cv.get("amount")) else (1 / 1.2 if c_vat else 1)
            return round(ci["unit"]["value"]["amount"] * factor, 2), "contract.items.unit.value" + (" ×amountNet/amount" if c_vat else ""), signed_date
        if n_items == 1 and qty and cv.get("amount"):
            amt = cv.get("amountNet") if (c_vat and cv.get("amountNet")) else (cv["amount"] / 1.2 if c_vat else cv["amount"])
            return round(amt / qty, 2), "contract.amountNet/qty" if c_vat else "contract.value/qty", signed_date
    t_vat = (t.get("value") or {}).get("valueAddedTaxIncluded")
    if (it.get("unit") or {}).get("value"):
        uv = it["unit"]["value"]; u_vat = uv.get("valueAddedTaxIncluded", t_vat)
        return (round(uv["amount"] / 1.2, 2) if u_vat else uv["amount"]), "items.unit.value" + (" gross÷1.2" if u_vat else ""), ""
    award = next((a for a in t.get("awards", []) if a["status"] == "active"), None)
    if award and n_items == 1 and qty:
        a_vat = (award.get("value") or {}).get("valueAddedTaxIncluded", t_vat)
        return round(award["value"]["amount"] / (1.2 if a_vat else 1) / qty, 2), "award.value/qty" + (" gross÷1.2" if a_vat else ""), ""
    return None, "", ""

def net(amount, vat_included):
    """Compare net only: VAT-included amounts are divided by 1.2 (martial-law exemption not applied by that buyer)."""
    if amount is None: return None, ""
    return (round(amount / 1.2, 2), "gross÷1.2") if vat_included else (amount, "")

def buyer_region(t): return ((t["procuringEntity"].get("address") or {}).get("region") or "").replace(" область", " обл.")
def link(t): return f"https://prozorro.gov.ua/tender/{t['tenderID']}"
