#!/usr/bin/env python3
"""Collect outage news from Google News RSS (+ BleepingComputer) into data/news.json.

Google News RSS is for personal, non-commercial use only. Articles are stored as
headline + link + outlet + time (no article text). Events are clustered by
(entity, day) so one outage covered by 30 outlets counts once.
"""
import json, re, sys, pathlib, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from causes import classify_ev
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "news.json"
UA = "outage-tracker/0.1 (personal project)"

QUERIES = [
    "outage", "services down outage", "bank outage customers unable", "Microsoft outage",
    "AWS OR Azure OR \"Google Cloud\" outage", "Cloudflare outage", "airline system outage",
    "government network outage", "cyberattack outage", "data center outage",
]
FEEDS = ["https://www.bleepingcomputer.com/feed/"]

# entity -> (regex, category). First match wins; order matters.
ENTITIES = [
    ("Microsoft", r"microsoft|outlook|azure|teams\b|office 365|microsoft 365", "saas"),
    ("AWS", r"\baws\b|amazon web services", "cloud"),
    ("Google", r"google|gmail|youtube", "cloud"),
    ("Cloudflare", r"cloudflare", "cdn-network"),
    ("Meta", r"facebook|instagram|whatsapp|\bmeta\b", "consumer-app"),
    ("X", r"\bx\b outage|twitter", "consumer-app"),
    ("Apple", r"\bapple\b|icloud", "consumer-app"),
    ("OpenAI/Anthropic", r"openai|chatgpt|anthropic|claude", "ai"),
    ("Banks", r"\bbank|chase|wells fargo|citi|capital one|zelle|paypal|venmo|visa|mastercard", "bank"),
    ("Airlines", r"airline|airport|united|delta|american airlines|southwest|faa\b", "transport"),
    ("Government", r"\bnsa\b|government|federal|pentagon|dhs|irs|\bcia\b|agency|ministry|\bnhs\b", "government"),
    ("Telecom/ISP", r"verizon|at&t|t-mobile|comcast|xfinity|spectrum|telecom|\bisp\b|broadband", "telecom"),
    ("Retail/Payments", r"square|stripe|shopify|point-of-sale|checkout", "commerce"),
]
# A headline must state a technical failure and must not be about money, sports or utilities.
OUTAGE = re.compile(r"\boutages?\b|went down|goes down|going down|\b(is|are|was|were|currently|still|now)\s+down\b|\bdown for\b|\b(systems?|services?|sites?|websites?|apps?|servers?|networks?|logins?) down\b|\bdisruptions?\b|not working|\bglitch(es)?\b|locked out|knocked (offline|out)|\boffline\b|unable to (access|log ?in|sign in|connect)|can.?t (log ?in|access|sign in)|\b(500|503) errors?\b|ground stop", re.I)
FINANCE = re.compile(r"\bstocks?\b|\bshares\b(?!\s+(what|some|details|how|why|its|a|an|the|new|more|that|update))|\bstake\b|\bbuy(ing)?\b|\bsell(ing)?\b|price target|earnings|\binvestors?\b|\betfs?\b|dividend|\bdow\b|s&p|market cap|valuation|\bdown \$?\d+(\.\d+)?\s?%|\bup \$?\d+(\.\d+)?\s?%|\bdown \$\d|\bup \$\d|wall street|portfolio|\bwhy i.?m\b|\bmotley\b|bearish|bullish|\bcat bond|parametric", re.I)
SPORTS_TV = re.compile(r"\bnfl\b|\bnba\b|\bnhl\b|fantasy|season \d|episode|box office|\bplayoffs?\b", re.I)
UTILITY = re.compile(r"power outage|electric|utility|storm|hurricane|snow|blackout|water outage|wildfire|\bpge\b|pg&e|duke energy|con ?ed", re.I)
NOISE = re.compile(FINANCE.pattern + "|" + SPORTS_TV.pattern + "|" + UTILITY.pattern, re.I)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def classify(title):
    for name, rx, cat in ENTITIES:
        if re.search(rx, title, re.I):
            return name, cat
    return "Other", "other"


def parse_feed(xml):
    root = ET.fromstring(xml)
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        link = it.findtext("link")
        pub = it.findtext("pubDate")
        src = it.find("source")
        outlet = src.text if src is not None else None
        if outlet and title.endswith(" - " + outlet):
            title = title[: -len(outlet) - 3]
        try:
            dt = parsedate_to_datetime(pub).astimezone(timezone.utc)
        except Exception:
            continue
        yield title, link, outlet, dt


def main():
    seen = {}
    if OUT.exists():
        for a in json.loads(OUT.read_text()).get("articles", []):
            seen[a["url"]] = a
    urls = [("https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:7d") + "&hl=en-US&gl=US&ceid=US:en") for q in QUERIES] + FEEDS
    errs, new = 0, 0
    for u in urls:
        try:
            for title, link, outlet, dt in parse_feed(get(u)):
                if not OUTAGE.search(title) or NOISE.search(title) or link in seen:
                    continue
                ent, cat = classify(title)
                seen[link] = {"url": link, "title": title, "outlet": outlet or "BleepingComputer" if "bleeping" in u else outlet,
                              "published_at": dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "entity": ent, "category": cat, }
                new += 1
        except Exception as e:
            errs += 1
            print("ERROR", u[:70], e, file=sys.stderr)
    for a in seen.values():
        a["cause"], a["cause_evidence"] = classify_ev(a["title"], press=True)
    arts = sorted(seen.values(), key=lambda a: a["published_at"], reverse=True)

    clusters = {}
    for a in arts:
        k = (a["entity"], a["published_at"][:10])
        c = clusters.setdefault(k, {"entity": a["entity"], "category": a["category"], "date": a["published_at"][:10], "articles": 0, "outlets": set(), "headline": a["title"], "url": a["url"], "causes": {}})
        c["articles"] += 1
        if a["outlet"]: c["outlets"].add(a["outlet"])
        if a["cause"] != "unknown": c["causes"][a["cause"]] = c["causes"].get(a["cause"], 0) + 1; c.setdefault("ev", {}).setdefault(a["cause"], a["cause_evidence"])
    events = sorted(({**{k: v for k, v in c.items() if k != "causes"}, "outlets": len(c["outlets"]), "cause": (max(c["causes"], key=c["causes"].get) if c["causes"] else "unknown"), "cause_basis": "press" if c["causes"] else None, "cause_evidence": (c.get("ev", {}).get(max(c["causes"], key=c["causes"].get)) if c["causes"] else None), "key": "news:" + c["entity"] + ":" + c["date"]} for c in clusters.values()), key=lambda c: (c["date"], c["articles"]), reverse=True)
    OUT.write_text(json.dumps({"articles": arts, "events": events}, indent=1))
    print(f"new_articles={new} total={len(arts)} events={len(events)} feed_errors={errs}")


if __name__ == "__main__":
    main()
