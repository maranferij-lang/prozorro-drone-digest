"""Weekly digest v1 (markdown).
 Part 1  open now   – non-defense buyers, product classes, status enquiries/tendering/auction/qualification, sorted by deadline
 Part 2  closed     – contracts signed in the last 7 days, net unit price vs benchmark median, ⚠ if > +15 %
 State   data/state/pending.json  – tenderIDs seen that are not terminal yet (re-checked by refresh.py next week)
         data/state/reported.json – tenderIDs already listed in a "closed" section (never listed twice)
python3 scripts/digest.py [--end YYYY-MM-DD] [--days 7] [--include-defense]
"""
import sys, os, json, datetime, collections, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib, docs

args = sys.argv[1:]
END = datetime.date.fromisoformat(args[args.index("--end") + 1]) if "--end" in args else datetime.date.today()
DAYS = int(args[args.index("--days") + 1]) if "--days" in args else 7
START = END - datetime.timedelta(days=DAYS)
AUDIENCE = ("general", "authority", "special") + (("defense",) if "--include-defense" in args else ())
FLAG_PCT = 15            # ⚠P  signed unit price > +15 % above the type's benchmark median
BUDGET_PCT = 30          # ⚠B  buyer's expected unit price > +30 % above the benchmark
COMPETITIVE = {"aboveThreshold", "belowThreshold", "priceQuotation"}   # ⚠S  exactly one bid in one of these
TOP_N_DOCS = 5           # doc facts for the top-N open tenders by value
OPEN_STATUSES = {"active.enquiries", "active.tendering", "active.auction", "active.qualification"}
STATE_DIR = os.path.join(lib.DATA, "state"); os.makedirs(STATE_DIR, exist_ok=True)
DIGEST_DIR = os.path.join(lib.DATA, "digests"); os.makedirs(DIGEST_DIR, exist_ok=True)
bench = json.load(open(os.path.join(lib.DATA, "benchmarks.json"), encoding="utf-8"))
reported_path = os.path.join(STATE_DIR, "reported.json")
reported = json.load(open(reported_path)) if os.path.exists(reported_path) else {}

TYPE_LABEL = {"matrice_4t": "DJI Matrice 4T", "fpv_10_day": "FPV 10\" day", "fpv_10_thermal": "FPV 10\" thermal", "fpv_10_fiber": "FPV 10\" fiber-optic",
              "esm_chuika_3": "ESM «Чуйка» (base/3.0)", "esm_chuika_4": "ESM «Чуйка 4.0»", "esm_chuika_kit": "ESM «Чуйка» kit",
              "matrice_other": "DJI Matrice (other)", "mavic": "DJI Mavic", "autel": "Autel", "quadcopter": "quadcopter (catalogue)",
              "quadcopter_other": "drone (other/unclear)", "fpv_drone": "FPV drone (size n/a)", "fixed_wing_uav": "fixed-wing / БпАК",
              "ew_jammer": "EW jammer (РЕБ)", "ew_detector": "EW detector / ESM", "thermal_imager": "thermal imager", "ground_robot": "ground robot"}
def label(tp): return TYPE_LABEL.get(tp, tp)
def money(x): return f"{x:,.0f}" if x is not None else "—"
def d(s): return (s or "")[:10]

def type_items(t):
    """[(item, precise_type|None, coarse_class)] for a tender."""
    bids_all = lib.active_bids(t); out = []
    for it in t["items"]:
        exp = lib.req_expected(t, it["id"]); rids = lib.req_ids_for_item(t, it["id"])
        answers = [lib.resp_map(b, rids) for b in bids_all]
        ptype, _ = lib.classify_item(t, it, answers, exp)
        out.append((it, ptype, lib.guess(t, it)[0]))
    return out

def deadline(t):
    st = t["status"]
    if st in ("active.enquiries", "active.tendering"): return d((t.get("tenderPeriod") or {}).get("endDate")), "tender ends"
    if st == "active.auction": return d((t.get("auctionPeriod") or {}).get("startDate")), "auction"
    if st == "active.qualification": return "", "in qualification"
    return "", st

open_rows, closed_rows, defense_rows, pending, defense_open, defense_closed = [], [], [], {}, 0, 0
for t in lib.all_cached_tenders():
    kind = t["procuringEntity"].get("kind"); items = type_items(t)
    coarse = items[0][2]
    if coarse not in lib.PRODUCT_CLASSES and not any(pt for _, pt, _ in items): continue   # parts, services, noise: skipped
    # --- state
    if t["status"] not in lib.TERMINAL:
        pending[t["tenderID"]] = {"id": t["id"], "status": t["status"], "kind": kind, "class": coarse,
                                  "types": sorted({pt for _, pt, _ in items if pt}), "created": d(t["dateCreated"]),
                                  "last_checked": END.isoformat(), "first_seen": reported.get(t["tenderID"], {}).get("first_seen") or END.isoformat()}
    # --- part 1
    if t["status"] in OPEN_STATUSES:
        it, ptype, cls = next(((it, pt, c) for it, pt, c in items if pt), items[0])
        if kind not in AUDIENCE:
            if kind == "defense":
                defense_open += 1; dl, dl_kind = deadline(t); v = t.get("value") or {}
                defense_rows.append({"deadline": dl or "9999", "dl_kind": dl_kind, "buyer": t["procuringEntity"]["name"].strip(), "region": lib.buyer_region(t),
                                     "type": label(ptype or cls) + ("" if ptype else " ~"), "qty": it["quantity"], "n_items": len(t["items"]),
                                     "value": v.get("amount"), "procedure": t["procurementMethodType"], "status": t["status"].replace("active.", ""),
                                     "link": lib.link(t), "tenderID": t["tenderID"], "edrpou": t["procuringEntity"]["identifier"]["id"], "created": d(t["dateCreated"]), "exp_unit": None})
            continue
        v = t.get("value") or {}; qty = it["quantity"]
        exp_unit = lib.net(round(v["amount"] / qty, 2), v.get("valueAddedTaxIncluded"))[0] if (v.get("amount") and len(t["items"]) == 1 and qty) else None
        dl, dl_kind = deadline(t)
        b = bench.get(ptype); ratio = f"{exp_unit / b['median'] * 100 - 100:+.0f}% vs benchmark" if (b and exp_unit) else ""
        bratio = (exp_unit / b["median"] * 100 - 100) if (b and exp_unit) else None
        n_bids_open = len(lib.active_bids(t))
        open_rows.append({"flag_budget": bratio is not None and bratio > BUDGET_PCT,
                          "flag_single": t["procurementMethodType"] in COMPETITIVE and n_bids_open == 1, "n_bids": n_bids_open, "bratio": bratio, "t": t,"deadline": dl or "9999", "dl_kind": dl_kind, "status": t["status"].replace("active.", ""),
                          "buyer": t["procuringEntity"]["name"].strip(), "region": lib.buyer_region(t), "type": label(ptype or cls),
                          "precise": bool(ptype), "qty": qty, "n_items": len(t["items"]), "exp_unit": exp_unit, "ratio": ratio, "value": v.get("amount"), "value_net": lib.net(v.get("amount"), v.get("valueAddedTaxIncluded"))[0], "ptype": ptype,
                          "procedure": t["procurementMethodType"], "desc": it["description"].strip()[:70], "link": lib.link(t), "tenderID": t["tenderID"],
                          "edrpou": t["procuringEntity"]["identifier"]["id"], "created": d(t["dateCreated"])})
    # --- part 2: contracts signed in the window
    cdoc = None
    for c in t.get("contracts", []):
        if c["status"] in ("active", "pending"): cdoc = lib.contract(c["id"]); break
    if not cdoc: continue
    signed_on = d(cdoc.get("dateSigned")) or d(cdoc.get("dateCreated"))
    if not (START.isoformat() < signed_on <= END.isoformat()): continue
    if kind not in AUDIENCE:
        if kind == "defense": defense_closed += 1
        continue
    if reported.get(t["tenderID"], {}).get("reported_in", END.isoformat()) < END.isoformat(): continue   # listed in an EARLIER digest
    for it, ptype, cls in items:
        if not ptype and cls not in lib.PRODUCT_CLASSES: continue
        signed, src, _ = lib.signed_unit_price(t, it, cdoc)
        v = t.get("value") or {}; qty = it["quantity"]
        exp_unit = lib.net(round(v["amount"] / qty, 2), v.get("valueAddedTaxIncluded"))[0] if (v.get("amount") and len(t["items"]) == 1 and qty) else None
        bids, _ = lib.bid_unit_prices(t, it); bids = [lib.net(x, v.get("valueAddedTaxIncluded"))[0] for x in bids]
        b = bench.get(ptype); delta = (signed / b["median"] * 100 - 100) if (b and signed) else None
        closed_rows.append({"signed_on": signed_on, "buyer": t["procuringEntity"]["name"].strip(), "region": lib.buyer_region(t),
                            "type": label(ptype or cls), "precise": bool(ptype), "qty": qty, "n_items": len(t["items"]),
                            "signed": signed, "src": src, "exp_unit": exp_unit, "n_bids": len(bids),
                            "bench": b, "delta": delta, "flag": delta is not None and delta > FLAG_PCT, "ptype": ptype, "t": t,
                            "bratio": (exp_unit / b["median"] * 100 - 100) if (b and exp_unit) else None,
                            "flag_budget": bool(b and exp_unit and exp_unit / b["median"] * 100 - 100 > BUDGET_PCT),
                            "flag_single": t["procurementMethodType"] in COMPETITIVE and len(bids) == 1,
                            "procedure": t["procurementMethodType"], "supplier": (cdoc.get("suppliers") or [{}])[0].get("name", "")[:40],
                            "desc": it["description"].strip()[:70], "link": lib.link(t), "tenderID": t["tenderID"],
                            "edrpou": t["procuringEntity"]["identifier"]["id"], "created": d(t["dateCreated"])})
        reported[t["tenderID"]] = {"reported_in": END.isoformat(), "first_seen": pending.get(t["tenderID"], {}).get("first_seen", END.isoformat())}

def collapse(rows, datekey):
    """Split purchases: same buyer + same date + same type → one row (qty summed, price = median, links joined)."""
    by = collections.OrderedDict()
    for r in rows: by.setdefault((r["edrpou"], r[datekey], r["type"]), []).append(r)
    out = []
    for rs in by.values():
        if len(rs) == 1: out.append({**rs[0], "n_tenders": 1}); continue
        base = dict(rs[0]); base["n_tenders"] = len(rs); base["qty"] = sum(x["qty"] for x in rs)
        if "value" in base: base["value"] = sum(x["value"] or 0 for x in rs)
        if "value_net" in base: base["value_net"] = sum(x["value_net"] or 0 for x in rs)
        for k in ("exp_unit", "signed", "delta"):
            vals = [x[k] for x in rs if x.get(k) is not None]
            if k in base: base[k] = statistics.median(vals) if vals else None
        if "delta" in base: base["flag"] = base["delta"] is not None and base["delta"] > FLAG_PCT
        for fk in ("flag_budget", "flag_single"):
            if fk in base: base[fk] = any(x.get(fk) for x in rs)
        if "bratio" in base:
            vals = [x["bratio"] for x in rs if x.get("bratio") is not None]; base["bratio"] = statistics.median(vals) if vals else None
        if "n_bids" in base: base["n_bids"] = max(x["n_bids"] for x in rs)
        base["tenderID"] = rs[0]["tenderID"] + f" +{len(rs)-1}"; base["links"] = [x["link"] for x in rs]
        out.append(base)
    return out
open_rows = collapse(open_rows, "created"); closed_rows = collapse(closed_rows, "signed_on"); defense_rows = collapse(defense_rows, "created")
defense_rows.sort(key=lambda r: (r["deadline"], r["buyer"]))

# --- document verdicts for flagged closed rows (any of the three flags) + doc facts for the top-N open by value
KIT_OF = {"esm_chuika_3": "esm_chuika_kit", "esm_chuika_4": "esm_chuika_kit"}
def marks(r):
    return " ".join(m for m, on in (("⚠P", r.get("flag")), ("⚠S", r.get("flag_single")), ("⚠B", r.get("flag_budget"))) if on)
for r in closed_rows:
    if not (r["flag"] or r["flag_single"] or r["flag_budget"]): continue
    line, _ = docs.verdict(r["t"], r["ptype"]); r["verdict"] = line
    alt = bench.get(KIT_OF.get(r["ptype"], "")) if "bundle" in line else None
    if alt and r["signed"]:
        r["verdict"] += f" → vs {label(KIT_OF[r['ptype']])} {money(alt['median'])} (n={alt['n']}): {r['signed'] / alt['median'] * 100 - 100:+.0f}%"
    bids_n = len(lib.active_bids(r["t"])); r["verdict"] += f"; bids: {bids_n}" + (" (single bidder)" if bids_n == 1 else "")
top_open = sorted(open_rows, key=lambda r: -(r["value"] or 0))[:TOP_N_DOCS]
notes_path = os.path.join(lib.DATA, "notes", f"notes_{END.isoformat()}.md")
notes = {}
if os.path.exists(notes_path):
    cur = None
    for line in open(notes_path, encoding="utf-8"):
        if line.startswith("## "): cur = line[3:].strip(); notes[cur] = ""
        elif cur: notes[cur] += line
for r in top_open:
    tids = [r["tenderID"].split()[0]] + [u.rsplit("/", 1)[-1] for u in r.get("links", [])[1:]]
    facts, note = [], []
    for tid in tids:
        t_ = lib.load_tender(tid)
        if t_: facts.append((tid if len(tids) > 1 else "") + " " + docs.facts_line(docs.spec_facts(t_)))
        if notes.get(tid): note.append(((tid + ": ") if len(tids) > 1 else "") + notes[tid].strip())
    r["facts"] = "\n    - ".join(x.strip() for x in facts); r["note"] = "\n    - **Note:** ".join(note)

# --- benchmark changes since the previous digest run
bench_hist_path = os.path.join(STATE_DIR, "benchmarks_history.json")
bench_hist = json.load(open(bench_hist_path, encoding="utf-8")) if os.path.exists(bench_hist_path) else {}
earlier = sorted(k for k in bench_hist if k < END.isoformat())
bench_last = bench_hist[earlier[-1]] if earlier else None
bench_changes = []
if bench_last:
    for k, b in sorted(bench.items()):
        o = bench_last.get(k)
        if not o: bench_changes.append(f"{label(k)}: new, median {money(b['median'])} (n={b['n']})"); continue
        if o["median"] != b["median"] or o["n"] != b["n"]:
            bench_changes.append(f"{label(k)}: median {money(o['median'])} → {money(b['median'])} ({b['median'] / o['median'] * 100 - 100:+.1f}%), n {o['n']} → {b['n']}")
    for k in bench_last:
        if k not in bench: bench_changes.append(f"{label(k)}: dropped (no data)")
open_rows.sort(key=lambda r: (r["deadline"], r["buyer"]))
closed_rows.sort(key=lambda r: (-(r["delta"] if r["delta"] is not None else -999), r["signed_on"]))
def links(r):
    if r.get("n_tenders", 1) == 1: return f"[{r['tenderID']}]({r['link']})"
    return f"[{r['tenderID'].split()[0]}]({r['link']}) " + " ".join(f"[+{i+1}]({u})" for i, u in enumerate(r["links"][1:]))

# ---------------------------------------------------------------- markdown
L = []
L.append(f"# Prozorro drone / EW / thermal digest — week to {END.isoformat()}")
L.append(f"\nWindow: {START.isoformat()} → {END.isoformat()}. Buyers: `kind` ∈ {{{', '.join(AUDIENCE)}}} (municipalities, police, ДСНС, КП, universities…); "
         f"military units (`defense`) excluded from the lists — they had {defense_open} open and {defense_closed} signed in this window. "
         f"All prices **net of VAT** (VAT-included amounts ÷ 1.2). Product type from the Prozorro Market characteristics block where the tender has one, "
         f"otherwise from the title/description regex (marked ~). Benchmarks = median signed net unit price over the 30-day window, split purchases collapsed "
         f"(`data/benchmarks.json`). Generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} UTC; tender data as of the last `refresh.py` run (see `data/state/refresh_log.txt`).")

total_open_value = sum(r["value_net"] or 0 for r in open_rows)
n_open_t = sum(r.get("n_tenders", 1) for r in open_rows); n_closed_t = sum(r.get("n_tenders", 1) for r in closed_rows)
flagged = [r for r in closed_rows if r["flag"]]
L.append("\n## Summary\n")
L.append(f"- **Open:** {n_open_t} tenders ({len(open_rows)} rows after collapsing split purchases), expected value **{total_open_value/1e6:,.1f} M UAH** net. "
         f"**Closed last week:** {n_closed_t} contracts ({len(closed_rows)} rows). Military units: {defense_open} open (appendix A), {defense_closed} signed (not listed).")
L.append("- **Top 5 open by value:**")
for r in sorted(open_rows, key=lambda r: -(r["value"] or 0))[:5]:
    typ = r["type"] + ("" if r["precise"] else " ~"); dl = r["deadline"] if r["deadline"] != "9999" else "—"
    when = f"{r['dl_kind']} {dl}" if r["deadline"] != "9999" else r["dl_kind"]
    L.append(f"  - {money(r['value'])} UAH — {r['buyer'][:50]} ({r['region']}): {typ}, qty {r['qty']:.0f}" + (f" in {r['n_tenders']} tenders" if r.get("n_tenders", 1) > 1 else "") + f", {when}, {r['procedure']} {marks(r)} — {links(r)}")
flag_single = [r for r in closed_rows if r["flag_single"]]; flag_budget = [r for r in closed_rows if r["flag_budget"]]
open_budget = [r for r in open_rows if r["flag_budget"]]; open_single = [r for r in open_rows if r["flag_single"]]
def flagline(r, kind):
    core = f"{r['buyer'][:50]} ({r['region']}): {r['type']} ×{r['qty']:.0f}, {r['procedure']}"
    if kind == "P": core += f", signed **{money(r['signed'])}** vs benchmark {money(r['bench']['median'])} (n={r['bench']['n']}) = **{r['delta']:+.0f}%**"
    if kind == "S": core += f", **1 bid**" + (f", signed {money(r['signed'])}" if r.get("signed") else "")
    if kind == "B": core += f", budget **{money(r['exp_unit'])}**/unit vs benchmark {money(r['bench']['median'])} = **{r['bratio']:+.0f}%**"
    return f"  - {marks(r)} {core} — {links(r)}" + (f"\n    - {r['verdict']}" if r.get("verdict") else "")
L.append(f"- **⚠P price above benchmark ({len(flagged)}):**" + ("" if flagged else " none"))
for r in flagged: L.append(flagline(r, "P"))
L.append(f"- **⚠S single bidder in a competitive procedure — closed ({len(flag_single)}), open/in qualification ({len(open_single)}):**" + ("" if (flag_single or open_single) else " none"))
for r in flag_single: L.append(flagline(r, "S"))
for r in open_single: L.append(f"  - ⚠S {r['buyer'][:50]} ({r['region']}): {r['type']} ×{r['qty']:.0f}, {r['procedure']}, {r['status']}, 1 bid" + (f", budget {money(r['exp_unit'])}/unit" if r['exp_unit'] else "") + f" — {links(r)}")
L.append(f"- **⚠B budget > +{BUDGET_PCT} % above catalogue price — closed ({len(flag_budget)}), open ({len(open_budget)}):**" + ("" if (flag_budget or open_budget) else " none"))
for r in flag_budget: L.append(flagline(r, "B"))
for r in open_budget: L.append(f"  - ⚠B {r['buyer'][:50]} ({r['region']}): {r['type']} ×{r['qty']:.0f}, {r['procedure']}, budget **{money(r['exp_unit'])}**/unit vs benchmark {money(bench[r['ptype']]['median'])} = **{r['bratio']:+.0f}%** — {links(r)}")
L.append(f"- **Documents, top {TOP_N_DOCS} open by value** (machine-extracted facts; analyst paragraph when `data/notes/notes_{END.isoformat()}.md` has one):")
for r in top_open:
    L.append(f"  - {r['buyer'][:50]} — {money(r['value'])} UAH, {r['type']} ×{r['qty']:.0f} — {links(r)}\n    - {r['facts']}" + (f"\n    - **Note:** {r['note']}" if r.get("note") else ""))
L.append("- **Benchmarks since last run" + (f" ({earlier[-1]})" if earlier else "") + ":** " + ("; ".join(bench_changes) if bench_changes else ("no changes" if bench_last else "first run — no previous benchmarks to compare")))

L.append(f"\n## 1. Open now — {len(open_rows)} rows ({sum(r.get('n_tenders',1) for r in open_rows)} tenders; split purchases collapsed), sorted by deadline\n")
L.append("| deadline | status | buyer | region | product | qty | expected unit, UAH | vs benchmark | flags | bids | procedure | link |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
for r in open_rows:
    dl = (r["deadline"] + " (" + r["dl_kind"] + ")") if r["deadline"] != "9999" else r["dl_kind"]
    typ = r["type"] + ("" if r["precise"] else " ~")
    qty = f"{r['qty']:.0f}" + (f" (+{r['n_items']-1} items)" if r["n_items"] > 1 else "") + (f" in {r['n_tenders']} tenders" if r.get("n_tenders", 1) > 1 else "")
    L.append(f"| {dl} | {r['status']} | {r['buyer'][:45]} | {r['region']} | {typ} | {qty} | {money(r['exp_unit'])} | {r['ratio']} | {marks(r)} | {r['n_bids'] or '—'} | {r['procedure']} | {links(r)} |")

L.append(f"\n## 2. Closed last week — {len(closed_rows)} rows ({sum(r.get('n_tenders',1) for r in closed_rows)} contracts; split purchases collapsed). Flags: ⚠P price > +{FLAG_PCT} % vs benchmark ({len(flagged)}), ⚠S single bidder in a competitive procedure ({len(flag_single)}), ⚠B budget > +{BUDGET_PCT} % vs benchmark ({len(flag_budget)})\n")
L.append("| signed | buyer | region | product | qty | signed unit, UAH | benchmark median (n) | Δ | flags | doc verdict | expected unit | bids | supplier | procedure | link |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for r in closed_rows:
    typ = r["type"] + ("" if r["precise"] else " ~")
    qty = f"{r['qty']:.0f}" + (f" (+{r['n_items']-1} items)" if r["n_items"] > 1 else "") + (f" in {r['n_tenders']} tenders" if r.get("n_tenders", 1) > 1 else "")
    b = f"{money(r['bench']['median'])} ({r['bench']['n']})" if r["bench"] else "no benchmark"
    delta = f"{r['delta']:+.0f}%" if r["delta"] is not None else "—"
    L.append(f"| {r['signed_on']} | {r['buyer'][:45]} | {r['region']} | {typ} | {qty} | {money(r['signed'])} | {b} | {delta} | {marks(r)} | {r.get('verdict','')} | {money(r['exp_unit'])} | {r['n_bids'] or '—'} | {r['supplier']} | {r['procedure']} | {links(r)} |")

L.append("\n## 3. Benchmarks used (30-day window, net, collapsed)\n")
L.append("| type | n | median | IQR | min–max |")
L.append("|---|---|---|---|---|")
for k, b in sorted(bench.items()):
    L.append(f"| {label(k)} | {b['n']} | {money(b['median'])} | {money(b['q1'])}–{money(b['q3'])} | {money(b['min'])}–{money(b['max'])} |")

L.append(f"\n## Appendix A. Open defense tenders — {sum(r.get('n_tenders',1) for r in defense_rows)} tenders ({len(defense_rows)} rows), no price comparison\n")
L.append("| deadline | status | buyer | product | qty | expected value, UAH | procedure | link |")
L.append("|---|---|---|---|---|---|---|---|")
for r in defense_rows:
    dl = (r["deadline"] + " (" + r["dl_kind"] + ")") if r["deadline"] != "9999" else r["dl_kind"]
    qty = f"{r['qty']:.0f}" + (f" (+{r['n_items']-1} items)" if r["n_items"] > 1 else "") + (f" in {r['n_tenders']} tenders" if r.get("n_tenders", 1) > 1 else "")
    L.append(f"| {dl} | {r['status']} | {r['buyer'][:45]} | {r['type']} | {qty} | {money(r['value'])} | {r['procedure']} | {links(r)} |")
bench_hist[END.isoformat()] = bench
json.dump(bench_hist, open(bench_hist_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

L.append(f"\n## 4. State\n\n- `data/state/pending.json`: {len(pending)} tenders not yet terminal (all buyer kinds, product classes) — `refresh.py` re-fetches these next week.")
L.append(f"- `data/state/reported.json`: {len(reported)} tenders already listed in a closed section; they will not be listed again.")
L.append(f"- Flags are independent: ⚠P signed price > +{FLAG_PCT} % vs the type's benchmark median; ⚠S exactly one bid in aboveThreshold / belowThreshold / priceQuotation (bids are visible from qualification on, so open rows can carry it only in qualification); ⚠B buyer's expected unit price > +{BUDGET_PCT} % vs benchmark. Any flag triggers the document verdict.")
L.append("- Rows marked ~ were typed by regex only (no characteristics block; typical for `reporting` and `aboveThreshold`). Rows with 'no benchmark' are classes too heterogeneous to benchmark yet (EW jammers, generic quadcopters, fixed-wing).")

out = os.path.join(DIGEST_DIR, f"digest_{END.isoformat()}.md")
open(out, "w", encoding="utf-8").write("\n".join(L) + "\n")
json.dump(pending, open(os.path.join(STATE_DIR, "pending.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
json.dump(reported, open(reported_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"digest → {out}: {len(open_rows)} open, {len(closed_rows)} closed ({len(flagged)} flagged), pending {len(pending)}, reported {len(reported)}")
