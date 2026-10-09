"""Weekly refresh.
 1. Re-fetch every cached tender that is not in a terminal status (public API only, by cached hex id).
 2. Discover candidates created since --since (default: 8 days ago) and fetch the ones not cached yet.
    Discovery uses the site adapter by default; --discover feed uses the official feed walk instead.
python3 scripts/refresh.py [--since YYYY-MM-DD] [--discover site|feed] [--no-refresh]
"""
import sys, os, time, datetime, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib

args = sys.argv[1:]
since = args[args.index("--since") + 1] if "--since" in args else (datetime.date.today() - datetime.timedelta(days=8)).isoformat()
discover = args[args.index("--discover") + 1] if "--discover" in args else "site"
t0 = time.time(); log = []

if "--no-refresh" not in args:
    todo = [t for t in lib.all_cached_tenders() if t["status"] not in lib.TERMINAL]
    changed = 0; errors = 0
    for i, t in enumerate(todo):
        new = lib.public_tender(t["id"])
        if not new: errors += 1; continue
        if new["dateModified"] != t["dateModified"]: changed += 1; lib.save_tender(new)
        if i % 100 == 0: print(f"  refresh {i}/{len(todo)} changed {changed}", flush=True)
    msg = f"refresh: {len(todo)} non-terminal tenders re-fetched, {changed} changed, {errors} errors, {time.time()-t0:.0f}s"
    print(msg); log.append(msg)

t1 = time.time()
if discover == "site":
    cands = lib.find_candidates_site(since)
    new_ids = [tid for tid in cands if not lib.load_tender(tid)]
    msg = f"discover(site) since {since}: {len(cands)} candidates, {len(new_ids)} not cached, {time.time()-t1:.0f}s"
    print(msg); log.append(msg)
    got = 0
    for i, tid in enumerate(new_ids):
        if lib.fetch_tender_by_tender_id(tid): got += 1
        time.sleep(0.15)
        if i % 50 == 0: print(f"  fetch {i}/{len(new_ids)}", flush=True)
    msg = f"fetched {got}/{len(new_ids)} new tenders, {time.time()-t1:.0f}s"; print(msg); log.append(msg)
else:
    # feed fallback: hex ids straight from the official feed, no site API at all
    ids = lib.find_candidates_feed(f"{since}T00:00:00+03:00", kinds=("general", "authority", "special"))
    got = 0
    for i, hid in enumerate(ids):
        t = lib.public_tender(hid)
        if t and t["tenderID"][3:13] >= since and lib.guess(t)[0] != "not_relevant": lib.save_tender(t); got += 1
        if i % 500 == 0: print(f"  fetch {i}/{len(ids)} kept {got}", flush=True)
    msg = f"discover(feed) since {since}: {len(ids)} non-defense tenders in feed, {got} kept after classification, {time.time()-t1:.0f}s"
    print(msg); log.append(msg)

os.makedirs(os.path.join(lib.DATA, "state"), exist_ok=True)
with open(os.path.join(lib.DATA, "state", "refresh_log.txt"), "a") as f:
    f.write(datetime.datetime.now().isoformat(timespec="seconds") + "\n  " + "\n  ".join(log) + "\n")
