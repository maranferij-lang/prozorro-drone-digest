"""Re-fetch the 3 sample tenders live and print buyer / value / qty / unit price / link.
python3 scripts/sample3.py
"""
import requests
B = "https://public-api.prozorro.gov.ua/api/2.5"
SITE = "https://prozorro.gov.ua/api"
S = requests.Session(); S.headers.update({"User-Agent": "Mozilla/5.0 (research script)"})
for tid in ["UA-2026-08-25-003833-a", "UA-2026-09-08-013028-a", "UA-2026-09-03-008514-a"]:
    hid = S.get(f"{SITE}/tenders/{tid}/summary", timeout=30).json()["id"]
    t = S.get(f"{B}/tenders/{hid}", timeout=30).json()["data"]
    it = t["items"][0]
    print(f"\n{tid}  https://prozorro.gov.ua/tender/{tid}")
    print("  buyer   :", t["procuringEntity"]["name"], "| kind", t["procuringEntity"]["kind"])
    print("  status  :", t["status"], "|", t["procurementMethodType"])
    print("  item    :", it["description"][:90].strip(), "| cpv", it["classification"]["id"], "| qty", it["quantity"], it["unit"]["name"])
    v = t["value"]; print("  expected:", v["amount"], v["currency"], "| VAT incl:", v.get("valueAddedTaxIncluded"), "| per unit:", round(v["amount"] / it["quantity"], 2))
    for a in t.get("awards", []):
        print("  award   :", a["status"], a["value"]["amount"], a["suppliers"][0]["name"][:50])
    for c in t.get("contracts", []):
        cc = S.get(f"{B}/contracts/{c['id']}", timeout=30).json()["data"]
        uv = (cc["items"][0]["unit"].get("value") or {}).get("amount") if cc.get("items") else None
        print("  contract:", cc["status"], cc["value"]["amount"], "| signed", (cc.get("dateSigned") or "")[:10], "| item unit.value:", uv, "| derived per unit:", round(cc["value"]["amount"] / cc["items"][0]["quantity"], 2) if cc.get("items") else None)
