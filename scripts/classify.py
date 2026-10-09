import json, re, glob, collections
PAT={
 "fpv":     r"\bfpv\b|фпв",
 "drone":   r"дрон|квадрокоптер|безпілотн|бпла|бпак|\buav\b|\bmavic\b|\bautel\b|\bmatrice\b|\bdji\b|мультикоптер|гексакоптер|октокоптер|літальн(ий|их|ого|і) апарат",
 "ew":      r"\bреб\b|радіоелектронн(ої|а|ий|ого|их|у|і) (боротьб|захист|подавл|протиді)|антидрон|глушил|подавлюва|детектор (дрон|бпла)|постановник|станці[яї] завад|засіб реб",
 "thermal": r"тепловіз",
 "nightvision": r"нічного бачення|\bпнб\b",
}
def text_of(t):
    parts=[t.get("title",""),t.get("description","") or ""]+[it.get("description","") or "" for it in t.get("items",[])]
    return " ".join(parts).lower()
rows=[]
for p in glob.glob("data/tenders/*.json"):
    t=json.load(open(p)); tags=[k for k,rx in PAT.items() if re.search(rx,text_of(t))]
    # title-only tags for precision comparison
    ttags=[k for k,rx in PAT.items() if re.search(rx,(t.get("title") or "").lower())]
    rows.append((t,tags,ttags))
print("full set:",len(rows),"| tagged (title+desc+items):",sum(1 for r in rows if r[1]),"| tagged title-only:",sum(1 for r in rows if r[2]))
print("tag counts (title+items):",collections.Counter(tag for _,tags,_ in rows for tag in tags))
print("tag counts (title only):  ",collections.Counter(tag for _,_,tt in rows for tag in tt))
print("search noise (no tag):",sum(1 for r in rows if not r[1]))
res={}
for tag in PAT:
    c=collections.Counter(); names={}; nt=0
    for t,tags,_ in rows:
        if tag in tags:
            nt+=1
            for it in t.get("items",[]):
                cl=it.get("classification",{}); c[cl.get("id")]+=1; names[cl.get("id")]=cl.get("description")
    res[tag]={"tenders":nt,"cpv":[(code,n,names[code]) for code,n in c.most_common(15)]}
    print(f"\n== {tag}: {nt} tenders; item CPV codes:")
    for code,n,nm in res[tag]["cpv"]: print(f"  {code}  {n:4d}  {nm}")
# thermal sample titles
print("\nthermal titles:",[t["title"][:70] for t,tags,_ in rows if "thermal" in tags][:12])
print("\new titles:",[t["title"][:70] for t,tags,_ in rows if "ew" in tags][:25])
# buyer kinds among tagged
print("\nbuyer kind (tagged):",collections.Counter(t["procuringEntity"]["kind"] for t,tags,_ in rows if tags).most_common())
print("procurementMethodType (tagged):",collections.Counter(t["procurementMethodType"] for t,tags,_ in rows if tags).most_common())
print("status (tagged):",collections.Counter(t["status"] for t,tags,_ in rows if tags).most_common())
# CPV coverage: what share of drone-tagged tenders would a CPV-only filter catch?
DRONE_CPV={"34710000-7","34711200-6","34740000-6","34741000-3","34730000-3","35613000-4","35740000-3"}
dt=[t for t,tags,_ in rows if "drone" in tags or "fpv" in tags]
caught=sum(1 for t in dt if any(it["classification"]["id"] in DRONE_CPV for it in t["items"]))
print(f"\ndrone/fpv tenders: {len(dt)}; with at least one item in drone CPV set: {caught} ({caught*100//len(dt)}%)")
# what tenders sit in 34710000-7 but are NOT drones? (precision of CPV)
allcpv=collections.Counter(it["classification"]["id"] for t,_,_ in rows for it in t["items"])
json.dump({"tags":{k:v for k,v in res.items()},"n":len(rows)},open("data/classify_result.json","w"),ensure_ascii=False,indent=1)
# non-defense drone buyers (municipal-ish) examples
print("\nnon-defense drone buyers sample:")
for t,tags,_ in rows:
    if ("drone" in tags or "fpv" in tags) and t["procuringEntity"]["kind"]!="defense":
        print("  ",t["tenderID"],t["procuringEntity"]["kind"],"|",t["procuringEntity"]["name"][:45],"|",t["title"][:50],"|",t.get("value",{}).get("amount"))
