"""Unit-price table per ITEM for the precise price types (Matrice 4T, FPV 10" day/thermal/fiber).
Split purchases (same buyer ЄДРПОУ + same created date + same type) get one group_id; stats are computed on
collapsed groups (one observation = median of the group) but every raw row stays in the CSV.
python3 scripts/price_table.py [--since YYYY-MM-DD]   → data/price_table.csv, data/benchmarks.json
"""
import sys, csv, json, os, statistics, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib

since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else "2026-08-21"
rows, skipped = [], collections.Counter()
for t in lib.all_cached_tenders():
    if t["tenderID"][3:13] < since: continue
    bids_all = lib.active_bids(t)
    award = next((a for a in t.get("awards", []) if a["status"] == "active"), None)
    cdoc = None
    for c in t.get("contracts", []):
        if c["status"] in ("active", "pending"): cdoc = lib.contract(c["id"]); break
    for it in t["items"]:
        exp = lib.req_expected(t, it["id"]); rids = lib.req_ids_for_item(t, it["id"])
        answers = [lib.resp_map(b, rids) for b in bids_all]
        ptype, how = lib.classify_item(t, it, answers, exp)
        if not ptype:
            if how: skipped[how] += 1
            continue
        qty = it["quantity"]; v = t.get("value") or {}; n_items = len(t["items"])
        bids, implausible = lib.bid_unit_prices(t, it)
        signed, src, sdate = lib.signed_unit_price(t, it, cdoc)
        vat = v.get("valueAddedTaxIncluded")          # signed price is already net (contract-level flag inside lib)
        bids = [lib.net(b, vat)[0] for b in bids]
        wans = lib.resp_map(next((b for b in bids_all if award and b["id"] == award.get("bid_id")), {}), rids) if award else {}
        rows.append({
            "type": ptype, "group_id": "", "group_size": 1,
            "tenderID": t["tenderID"], "link": lib.link(t),
            "buyer": t["procuringEntity"]["name"].strip(), "buyer_edrpou": t["procuringEntity"]["identifier"]["id"],
            "buyer_kind": t["procuringEntity"].get("kind"), "region": lib.buyer_region(t),
            "procedure": t["procurementMethodType"], "status": t["status"], "created": t["dateCreated"][:10],
            "n_items_in_tender": n_items, "qty": qty, "unit": it["unit"]["name"],
            "expected_unit": lib.net(round(v["amount"] / qty, 2), vat)[0] if (v.get("amount") and n_items == 1 and qty) else None,
            "vat_included": v.get("valueAddedTaxIncluded"),
            "n_bids": len(bids), "bid_unit_prices": " | ".join(f"{x:,.0f}" for x in bids),
            "bid_min": bids[0] if bids else None, "bid_max": bids[-1] if bids else None,
            "bids_implausible": " | ".join(f"{x:,.0f}" for x in implausible),
            "signed_unit": signed, "signed_src": src, "signed_date": sdate,
            "brand": wans.get("Бренд", ""), "model": wans.get("Модель", ""),
            "thermal": wans.get("Тепловізор", exp.get("Тепловізор", "")), "size_inch": exp.get("Розмір", ""),
            "payload_kg": exp.get("Корисне навантаження", ""), "protocol": wans.get("Протокол прийому сигналу", ""),
            "video": wans.get("Відеозв'язок", exp.get("Відеозв'язок", "")),
            "market_category": it.get("category", ""), "how": how, "item_desc": it["description"].strip()[:120],
        })

# split-purchase groups
groups = collections.defaultdict(list)
for r in rows: groups[(r["type"], r["buyer_edrpou"], r["created"])].append(r)
for k, rs in groups.items():
    gid = f"{k[0]}|{k[1]}|{k[2]}"
    for r in rs: r["group_id"] = gid; r["group_size"] = len(rs)
rows.sort(key=lambda r: (r["type"], r["created"], r["tenderID"]))
with open(os.path.join(lib.DATA, "price_table.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
print("rows:", len(rows), "| groups:", len(groups), "| multi-tender groups:", sum(1 for g in groups.values() if len(g) > 1), "| skipped items:", dict(skipped))

def q(xs):
    xs = sorted(x for x in xs if x)
    if not xs: return None
    if len(xs) < 4: return {"n": len(xs), "median": statistics.median(xs), "q1": xs[0], "q3": xs[-1], "min": xs[0], "max": xs[-1]}
    qq = statistics.quantiles(xs, n=4); return {"n": len(xs), "median": statistics.median(xs), "q1": qq[0], "q3": qq[2], "min": xs[0], "max": xs[-1]}
def fmt(label, st):
    if not st: print(f"  {label:46s} n=0"); return
    print(f"  {label:46s} n={st['n']:3d} median={st['median']:>9,.0f}  IQR={st['q1']:>9,.0f}–{st['q3']:<9,.0f} min={st['min']:>9,.0f} max={st['max']:>9,.0f}")

bench = {}
for ptype in sorted(set(r["type"] for r in rows)):
    rs = [r for r in rows if r["type"] == ptype]
    # collapse: one observation per group = median of the group's values
    def collapsed(key, filt=lambda r: True):
        by = collections.defaultdict(list)
        for r in rs:
            if filt(r) and r[key]: by[r["group_id"]].append(r[key])
        return [statistics.median(v) for v in by.values()]
    print(f"\n== {ptype}: {len(rs)} items, {len(set(r['group_id'] for r in rs))} groups | buyer kind:",
          dict(collections.Counter(r["buyer_kind"] for r in rs)))
    fmt("signed unit, raw rows", q([r["signed_unit"] for r in rs]))
    fmt("signed unit, collapsed groups", q(collapsed("signed_unit")))
    fmt("signed unit, collapsed, kind ≠ defense", q(collapsed("signed_unit", lambda r: r["buyer_kind"] != "defense")))
    fmt("expected unit, collapsed groups", q(collapsed("expected_unit")))
    fmt("lowest bid, collapsed groups", q(collapsed("bid_min")))
    st = q(collapsed("signed_unit"))
    if st: bench[ptype] = {"basis": "signed unit price, net of VAT, split purchases collapsed, 30-day window from " + since, **st}
json.dump(bench, open(os.path.join(lib.DATA, "benchmarks.json"), "w"), ensure_ascii=False, indent=1)
print("\nbenchmarks →", {k: (v["n"], round(v["median"])) for k, v in bench.items()})
