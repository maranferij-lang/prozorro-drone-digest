import requests, json, time, os
H={"User-Agent":"Mozilla/5.0 (research script)","Accept":"application/json"}
hits=json.load(open("data/search_hits.json"))
S=requests.Session(); S.headers.update(H)
todo=[t for t in hits if not os.path.exists(f"data/tenders/{t}.json")]
print("todo",len(todo)); t0=time.time(); ok=0; r429=0; other=[]
for i,tid in enumerate(todo):
    for attempt in range(6):
        s=S.get(f"https://prozorro.gov.ua/api/tenders/{tid}/summary",timeout=60)
        if s.status_code==429:
            r429+=1; ra=s.headers.get("Retry-After"); time.sleep(float(ra) if ra else 2*(attempt+1)); continue
        break
    if s.status_code!=200: other.append((tid,"summary",s.status_code)); continue
    hid=s.json()["id"]
    r=S.get(f"https://public-api.prozorro.gov.ua/api/2.5/tenders/{hid}",timeout=60)
    if r.status_code!=200: other.append((tid,"public",r.status_code)); continue
    json.dump(r.json()["data"],open(f"data/tenders/{tid}.json","w"),ensure_ascii=False); ok+=1
    time.sleep(0.15)
    if i%200==0: print(i,"ok",ok,"429s",r429,"secs",round(time.time()-t0),flush=True)
print("done ok",ok,"429s",r429,"other errors",other[:10],"secs",round(time.time()-t0))
print("Retry-After header seen:",s.headers.get("Retry-After"))
