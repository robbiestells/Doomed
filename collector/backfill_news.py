#!/usr/bin/env python3
"""Backfill data/news.json from Google News RSS using dated queries (after:/before:).
Each query-month returns only ~10-20 items, so this samples big outages; it does not count every one.
Personal, non-commercial use only. Usage: backfill_news.py [YYYY-MM start] [YYYY-MM end exclusive]
"""
import json, sys, time, urllib.parse, urllib.error
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import news
from causes import classify_ev

QUERIES = ["outage", "Microsoft outage", "AWS outage OR Azure outage", "Google Cloud outage OR Gmail outage",
           "Cloudflare outage", "bank outage", "airline outage OR airport outage", "Apple OR iCloud outage",
           "government network outage", "ChatGPT OR Claude outage"]


def months(a, b):
    y, m = map(int, a.split("-")); ey, em = map(int, b.split("-"))
    while (y, m) < (ey, em):
        ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
        yield f"{y}-{m:02d}-01", f"{ny}-{nm:02d}-01"
        y, m = ny, nm


def fetch(q, a, b):
    u = "https://news.google.com/rss/search?q=" + urllib.parse.quote(f"{q} after:{a} before:{b}") + "&hl=en-US&gl=US&ceid=US:en"
    for wait in (0, 25, 60):
        time.sleep(wait)
        try:
            return news.get(u)
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
    raise RuntimeError("rate limited")


def main():
    a = sys.argv[1] if len(sys.argv) > 1 else "2025-11"
    b = sys.argv[2] if len(sys.argv) > 2 else "2026-11"
    seen = {x["url"]: x for x in json.loads(news.OUT.read_text()).get("articles", [])} if news.OUT.exists() else {}
    new = fails = 0
    for s, e in months(a, b):
        for q in QUERIES:
            try:
                for title, link, outlet, dt in news.parse_feed(fetch(q, s, e)):
                    if not news.OUTAGE.search(title) or news.NOISE.search(title) or link in seen:
                        continue
                    ent, cat = news.classify(title)
                    cause, ev = classify_ev(title, press=True)
                    seen[link] = {"url": link, "title": title, "outlet": outlet, "published_at": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                  "entity": ent, "category": cat, "cause": cause, "cause_evidence": ev}
                    new += 1
            except Exception as ex:
                fails += 1
                print("FAIL", s, q, str(ex)[:40], file=sys.stderr)
            time.sleep(2)
        print(s, "total", len(seen), flush=True)
    arts = sorted(seen.values(), key=lambda x: x["published_at"], reverse=True)
    old = json.loads(news.OUT.read_text()) if news.OUT.exists() else {}
    old["articles"] = arts
    news.OUT.write_text(json.dumps(old, indent=1))
    print(f"new={new} failed_queries={fails} total={len(arts)}")


if __name__ == "__main__":
    main()
