import requests, json, time, sys
H={"User-Agent":"Mozilla/5.0 (research script)","Accept":"application/json"}
U="https://prozorro.gov.ua/api/search/tenders"
CUTOFF="2026-08-21"   # 30 days before 2026-09-20
KW=["FPV","дрон","дрони","БПЛА","безпілотн","квадрокоптер","Mavic","РЕБ","радіоелектронн","тепловізор","тепловізійн","антидрон","БпАК","Autel"]
out={}; stats={}
for kw in KW:
    page=1; n=0; t0=time.time()
    while True:
        r=requests.post(U,params={"text":kw,"page":page,"sort_by":"dateCreated","order":"desc"},headers=H,timeout=60)
        if r.status_code!=200: print(kw,"page",page,"HTTP",r.status_code); break
        d=r.json(); data=d.get("data",[])
        if not data: break
        stop=False
        for x in data:
            created=x["tenderID"][3:13]
            if created<CUTOFF: stop=True; break
            n+=1
            rec=out.setdefault(x["tenderID"],{**x,"kw":[]}); rec["kw"].append(kw)
        if stop or page>=500: break
        page+=1
    stats[kw]={"hits_30d":n,"pages":page,"total_alltime":d.get("total"),"secs":round(time.time()-t0,1)}
    print(kw,stats[kw],flush=True)
json.dump(out,open("data/search_hits.json","w"),ensure_ascii=False,indent=1)
json.dump(stats,open("data/search_stats.json","w"),ensure_ascii=False,indent=1)
print("unique tenders:",len(out))
