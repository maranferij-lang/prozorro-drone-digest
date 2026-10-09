"""Guess a coarse product class for every candidate tender, then draw a STRATIFIED sample for hand labelling:
2–4 rows per guessed class, 40 rows total, fixed seed (reproducible).
python3 scripts/label_sample.py  → data/guessed_types_all.csv, data/label_sample_40.csv
"""
import sys, os, csv, random, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib

SEED, TOTAL = 20260920, 40
PRIORITY = ["matrice_4t", "fpv_drone", "ew_jammer", "ew_detector", "thermal_imager", "mavic", "quadcopter_other", "fixed_wing_uav"]  # get the 3rd/4th row

rows = []
for t in lib.all_cached_tenders():
    it = t["items"][0]; g, how = lib.guess(t, it)
    rows.append({"tenderID": t["tenderID"], "link": lib.link(t), "buyer": t["procuringEntity"]["name"].strip()[:60],
                 "buyer_kind": t["procuringEntity"].get("kind"), "procedure": t["procurementMethodType"], "status": t["status"],
                 "n_items": len(t["items"]), "cpv": it["classification"]["id"], "market_category": it.get("category", ""),
                 "title": t["title"].strip()[:100], "first_item_desc": it["description"].strip()[:140],
                 "qty": it["quantity"], "value": (t.get("value") or {}).get("amount"),
                 "guessed_type": g, "guess_how": how, "label": "", "comment": ""})
cols = list(rows[0].keys())
with open(os.path.join(lib.DATA, "guessed_types_all.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
counts = collections.Counter(r["guessed_type"] for r in rows)
print("guessed classes over", len(rows), "candidates:", counts.most_common())

by = collections.defaultdict(list)
for r in rows: by[r["guessed_type"]].append(r)
classes = sorted(by)
alloc = {c: min(2, len(by[c])) for c in classes}                      # 2 per class (or fewer if the class is tiny)
extra = TOTAL - sum(alloc.values())
for c in PRIORITY * 2:                                                # 3rd then 4th row for the classes we care about
    if extra <= 0: break
    if alloc[c] < min(4, len(by[c])): alloc[c] += 1; extra -= 1
rng = random.Random(SEED)
sample = []
for c in classes:
    pool = sorted(by[c], key=lambda r: r["tenderID"])                 # deterministic order before sampling
    sample += rng.sample(pool, alloc[c])
sample.sort(key=lambda r: (r["guessed_type"], r["tenderID"]))
with open(os.path.join(lib.DATA, "label_sample_40.csv"), "w", newline="", encoding="utf-8") as f:
    w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(sample)
print(f"stratified sample: {len(sample)} rows, seed {SEED}, per class:", dict(collections.Counter(r["guessed_type"] for r in sample)))
for r in sample: print(f"  {r['guessed_type']:18s} | {r['tenderID']} | {r['buyer_kind']:9s} | {r['first_item_desc'][:70]}")
