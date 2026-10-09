"""Tender documents → technical spec excerpt → one-line verdict for flagged digest rows.
Downloads from public-docs.prozorro.gov.ua (URLs come from tender.documents[].url, pre-signed), caches in data/docs/<tenderID>/.
Text extraction: .docx via zipfile (stdlib); .pdf via `pdftotext` and .doc via `soffice --convert-to txt` when those
binaries exist, otherwise the document is reported as unreadable. python3 scripts/docs.py UA-2026-08-31-012180-a [type]
"""
import sys, os, re, io, zipfile, subprocess, shutil, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib

DOCS_DIR = os.path.join(lib.DATA, "docs"); os.makedirs(DOCS_DIR, exist_ok=True)
SPEC_TITLE = re.compile(r"техн|специф|характерист|обґрунт|обгрунт|додаток\s*(№\s*)?2\b|\bтз\b|вимог", re.I)
SPEC_HEAD = re.compile(r"(технічн[іа] (та якісн[іа] )?(характеристики|специфікаці|вимоги)|технічна специфікація|характеристики предмета закупівлі|"
                       r"інформація про (необхідні )?технічні|specification)", re.I)

def _docx(b):
    try:
        xml = zipfile.ZipFile(io.BytesIO(b)).read("word/document.xml").decode("utf-8")
    except (zipfile.BadZipFile, KeyError):
        return None
    xml = re.sub(r"</w:p>", "\n", xml); xml = re.sub(r"</w:tc>", " | ", xml); xml = re.sub(r"<w:tab/>", "\t", xml)
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", "", xml)).replace("&quot;", '"').replace("&amp;", "&")

def _odt(b):
    try:
        xml = zipfile.ZipFile(io.BytesIO(b)).read("content.xml").decode("utf-8")
    except (zipfile.BadZipFile, KeyError):
        return None
    xml = re.sub(r"</text:p>|</text:h>", "\n", xml); xml = re.sub(r"</table:table-cell>", " | ", xml); xml = re.sub(r"<text:tab/>", "\t", xml)
    return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", "", xml)).replace("&quot;", '"').replace("&amp;", "&").replace("&apos;", "'")

def _pdf(path):
    if not shutil.which("pdftotext"): return None
    r = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, timeout=120)
    return r.stdout if r.returncode == 0 else None

def _doc(path):
    if not shutil.which("soffice"): return None
    out = os.path.dirname(path)
    r = subprocess.run(["soffice", "--headless", "--convert-to", "txt:Text (encoded):UTF8", "--outdir", out, path], capture_output=True, text=True, timeout=180)
    txt = os.path.splitext(path)[0] + ".txt"
    return open(txt, encoding="utf-8", errors="replace").read() if os.path.exists(txt) else None

def fetch_texts(t, max_docs=4):
    """[(title, documentType, text|None)] for the spec-relevant documents of a tender, cached on disk."""
    docs = [d for d in t.get("documents", []) if (d.get("format") or "") != "application/pkcs7-signature"]
    def prio(d):
        return (0 if d.get("documentType") == "technicalSpecifications" else
                1 if SPEC_TITLE.search(d.get("title", "")) else
                2 if d.get("documentType") == "biddingDocuments" else 3)
    docs.sort(key=prio)
    out = []; tdir = os.path.join(DOCS_DIR, t["tenderID"]); os.makedirs(tdir, exist_ok=True)
    for d in docs[:max_docs]:
        fmt = (d.get("format") or "").lower()
        ext = ("odt" if "opendocument" in fmt else "docx" if fmt.endswith("document") else "pdf" if "pdf" in fmt else "doc" if "msword" in fmt else None)
        if not ext: out.append((d["title"], d.get("documentType"), None)); continue
        path = os.path.join(tdir, f"{d['id']}.{ext}"); cached = path + ".txt"
        if os.path.exists(cached): out.append((d["title"], d.get("documentType"), open(cached, encoding="utf-8").read())); continue
        try:
            r = lib.S.get(d["url"], timeout=120)
            if r.status_code != 200: out.append((d["title"], d.get("documentType"), None)); continue
            open(path, "wb").write(r.content)
            text = _docx(r.content) if ext == "docx" else _odt(r.content) if ext == "odt" else _pdf(path) if ext == "pdf" else _doc(path)
        except Exception as e:
            text = None
        if text: open(cached, "w", encoding="utf-8").write(text)
        out.append((d["title"], d.get("documentType"), text))
    return out

def spec_section(text, n=3000):
    m = SPEC_HEAD.search(text or "")
    return text[m.start(): m.start() + n] if m else (text or "")[:n]

BANDS = re.compile(r"(\d{3,4})\s*[-–—]\s*(\d{3,4})\s*(МГц|MHz)", re.I)
MAH = re.compile(r"(\d{3,5})\s*m?[aA]h", re.I)
EXTRAS = {
    "esm": [("виносна антена", r"виносн\w* антен"), ("підсумок", r"підсумок|чохол"), ("автотримач", r"автомобільн\w* тримач"), ("кріплення", r"кріплен"),
            ("павербанк/зарядний", r"павербанк|power ?bank|зарядн"), ("додаткова комплектація", r"додаткова комплектація|в комплекті")],
    "drone": [("додаткові акумулятори", r"(\d+)\s*(шт\.?\s*)?акумулятор|акумулятор\w*\s*[-–—]?\s*(\d+)\s*шт"), ("зарядний хаб", r"зарядн\w* (хаб|станці|пристр)"),
              ("Care/страхування", r"\bcare\b|страхув"), ("RC Plus", r"rc plus|rc-plus"), ("кейс", r"кейс|сумк"), ("комплект", r"в комплекті|комплектація|fly more|combo")],
}

DELIVERY = re.compile(r"(строк|термін)\w* поставки[^\n;]{0,120}?(до|—|-|:)\s*[«\"]?\d{1,2}[.\s»\"]*(\d{1,2}|[а-яії]+)[.\s]*20\d\d[^\n;]{0,30}|(строк|термін)\w* поставки[^\n;]{0,80}?протягом \d+ (робочих |календарних )?дн\w+[^\n;]{0,60}", re.I)
PLACE = re.compile(r"місце поставки[^\n;]{0,25}?[:—-]\s*([^\n;|]{5,120})", re.I)
WARRANTY = re.compile(r"гарантійн\w* (термін|строк)[^\n.;]{0,120}", re.I)
RANGE_M = re.compile(r"(дальн\w*|радіус\w*|відстан\w*)[^\n.;]{0,25}?(\d[\d\s,.]*)\s*(м\b|км|метр)", re.I)
POWER_W = re.compile(r"потужн\w*\s*(випромін|передавач|модул|вихідн)\w*[^\n.;]{0,40}?(\d[\d,.]*)\s*(Вт|W)\b", re.I)
CLASS_HINTS = [("купол / стаціонарний РЕБ", r"купол|стаціонарн"), ("автомобільний РЕБ", r"автомобільн|на транспортн|бортов"), ("аеродинамічний (на БпЛА)", r"аеродинамічн"),
               ("носимий / ранцевий РЕБ", r"носим|ранцев|портативн|переносн"), ("детектор / ESM", r"детектор|електронної підтримки|радіоелектронної розвідки|виявлення"),
               ("окопний РЕБ", r"окопн"), ("антидрон-рушниця", r"рушниц|antidrone gun")]

def spec_facts(t, texts=None):
    """Structured facts from the best spec document: {doc, class, bands, range, power, qty, delivery, warranty, unusual}. Never raises."""
    facts = {"doc": None}
    try:
        texts = texts if texts is not None else fetch_texts(t)
    except Exception as e:
        facts["error"] = f"download failed ({e.__class__.__name__})"; return facts
    readable = [(ti, ty, tx) for ti, ty, tx in texts if tx]
    if not readable:
        facts["error"] = f"{len(texts)} attached, none readable ({', '.join(sorted({(d.get('format') or '?')[-25:] for d in t.get('documents', [])}))})" if texts else "no documents"
        return facts
    # prefer technicalSpecifications, else the doc whose text contains a spec heading
    readable.sort(key=lambda x: (0 if x[1] == "technicalSpecifications" else 1 if SPEC_HEAD.search(x[2] or "") else 2))
    title, dtype, text = readable[0]; spec = spec_section(text, 6000); low = spec.lower()
    facts["doc"] = f"{dtype or 'untyped'}: «{title[:45]}»"
    facts["class"] = [name for name, rx in CLASS_HINTS if re.search(rx, low)]
    bands = BANDS.findall(spec); facts["bands"] = sorted({f"{a}–{b}" for a, b, _ in bands})[:8]
    ghz = re.findall(r"(\d(?:[.,]\d)?)\s*ГГц", spec); facts["ghz"] = sorted({g.replace(",", ".") for g in ghz})[:8]
    m = RANGE_M.search(spec); facts["range"] = f"{m.group(2).strip()} {m.group(3)}" if m else None
    pw = POWER_W.findall(spec); facts["power_w"] = sorted({p.replace(",", ".") for _, p, _ in pw})[-3:] if pw else []
    mah = MAH.search(spec); facts["mah"] = mah.group(1) if mah else None
    facts["qty"] = f"{t['items'][0]['quantity']:.0f} {t['items'][0]['unit']['name']}" + (f" (+{len(t['items'])-1} items)" if len(t["items"]) > 1 else "")
    full_low = text.lower()
    dl = None
    for ti, ty, tx in readable:           # delivery date is usually in the contract proforma or the ТД, not the spec
        dl = DELIVERY.search(tx or "")
        if dl: break
    facts["delivery"] = re.sub(r"\s+", " ", dl.group(0))[:120] if dl else None
    pl = None
    for ti, ty, tx in readable:
        pl = PLACE.search(tx or "")
        if pl: break
    facts["place"] = re.sub(r"\s+", " ", pl.group(1))[:90] if pl else None
    wr = WARRANTY.search(text); facts["warranty"] = re.sub(r"\s+", " ", wr.group(0))[:100] if wr else None
    unusual = []
    for name, rx in [("навчання персоналу", r"навчанн\w* (персоналу|операторів)"), ("сервіс/ремонт у ціні", r"післяпродажн|сервісн\w* обслуговуванн"),
                     ("лист від виробника", r"авторизаційн\w* лист|лист (від )?виробника"), ("кодифікація МОУ", r"кодифік"), ("сертифікат/висновок", r"сертифікат відповідності|експертн\w* висновок"),
                     ("оптоволокно", r"оптоволок"), ("дистанційне керування", r"дистанційн\w* керуван"), ("автономне живлення", r"акумулятор|автономн\w* живлен"),
                     ("за кошти місцевого бюджету", r"місцев\w* бюджет"), ("для ЗСУ / військових", r"для потреб (зсу|військов)")]:
        if re.search(rx, full_low): unusual.append(name)
    facts["unusual"] = unusual
    facts["excerpt"] = re.sub(r"\s+", " ", spec[:700])
    return facts

def facts_line(f):
    if f.get("error"): return f"docs: {f['error']}"
    parts = []
    if f.get("class"): parts.append("class: " + ", ".join(f["class"]))
    if f.get("bands"): parts.append("bands: " + ", ".join(f["bands"]) + " MHz")
    elif f.get("ghz"): parts.append("bands: " + ", ".join(f["ghz"]) + " ГГц")
    if f.get("range"): parts.append("range: " + f["range"])
    if f.get("power_w"): parts.append("power: " + "/".join(f["power_w"]) + " W")
    if f.get("mah"): parts.append(f["mah"] + " mAh")
    parts.append("qty: " + f["qty"])
    if f.get("delivery"): parts.append("delivery: " + f["delivery"])
    if f.get("place"): parts.append("to: " + f["place"])
    if f.get("warranty"): parts.append(f["warranty"])
    if f.get("unusual"): parts.append("note: " + ", ".join(f["unusual"]))
    return f"spec ({f['doc']}): " + "; ".join(parts)

def verdict(t, ptype=None):
    """One line: what the spec says vs the benchmark type. Never raises."""
    exp = lib.req_expected(t)
    if exp:   # catalogue tender: the characteristics block is the spec
        keys = [k for k in ("Бренд", "Модель", "Розмір", "Тепловізор", "Корисне навантаження", "Акумуляторів у комплекті", "Акумуляторів в комплекті", "Час польоту", "Ємність акумулятора") if k in exp]
        return "characteristics block: " + "; ".join(f"{k}={exp[k]}" for k in keys)[:200], ""
    try:
        texts = fetch_texts(t)
    except Exception as e:
        return f"docs: download failed ({e.__class__.__name__})", ""
    readable = [(ti, ty, tx) for ti, ty, tx in texts if tx]
    if not texts: return "docs: no documents attached", ""
    if not readable: return f"docs: {len(texts)} attached, none readable ({', '.join(sorted({(ty or 'untyped') for ti, ty, tx in texts}))})", ""
    title, dtype, text = readable[0]; spec = spec_section(text)
    low = spec.lower()
    fam = "esm" if (ptype or "").startswith("esm_") or re.search(r"чуйк|електронної підтримки|радіоелектронної розвідки|детектор", low) else \
          "drone" if (ptype or "").startswith(("matrice", "fpv", "mavic", "quad")) or re.search(r"квадрокоптер|дрон|бпла|matrice|mavic", low) else "generic"
    found = [name for name, rx in EXTRAS.get(fam, []) if re.search(rx, low)]
    facts = []
    if fam == "esm":
        bands = BANDS.findall(spec); mah = MAH.search(spec)
        if bands: facts.append(f"{len(bands)} bands " + "/".join(f"{a}–{b}" for a, b, _ in bands[:4]) + " MHz")
        if mah: facts.append(f"{mah.group(1)} mAh")
    if fam == "drone":
        sz = re.search(r"(\d{1,2})\s*(дюйм|\"|inch)", low); th = re.search(r"тепловіз|нічн", low); fb = re.search(r"оптоволок", low)
        if sz: facts.append(f'{sz.group(1)}"')
        if th: facts.append("thermal")
        if fb: facts.append("fiber-optic")
    src = f"{dtype or 'untyped'}: «{title[:40]}»"
    if found:
        line = f"spec ({src}): {', '.join(facts) or 'core spec found'}; extras: {', '.join(found)} → bundle, compare with a kit benchmark"
    elif facts:
        line = f"spec ({src}): {', '.join(facts)}; no extras found → looks like the base item"
    else:
        line = f"spec ({src}): no spec section recognised — read manually"
    return line, spec

if __name__ == "__main__":
    tid = sys.argv[1]; ptype = sys.argv[2] if len(sys.argv) > 2 else None
    t = lib.load_tender(tid) or lib.fetch_tender_by_tender_id(tid)
    line, spec = verdict(t, ptype)
    print(line); print("-" * 80)
    f = spec_facts(t); print(facts_line(f)); print("-" * 80); print(f.get("excerpt", "")); print("-" * 80); print(spec[:2500])
