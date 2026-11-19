#!/usr/bin/env python3
"""Merge feed incidents, manual events and news into one list of outage events.

Output: data/events.json and data/events.csv  (one row per real-world outage).

News handling:
  * roundup/commentary headlines ("what to know", "outage after outage", "AI makes outages more
    likely") are dropped: they say nothing about when something broke;
  * articles are grouped by brand (Chase, United, Apple...) falling back to entity (Microsoft...);
  * a group's days are merged into one event when the gap is <= 1 day; events need >= 3 articles;
  * a news event that overlaps a manual event or a feed incident for the same company is folded in.

ai_link (how an outage is tied to AI):
  ai-service  the affected service is an AI product
  cited-cause AI/an AI tool is reported as the cause
  speculated  AI is raised as a possible factor (not confirmed)
  ruled-out   AI was explicitly said not to be the cause
  none        no AI link in the coverage we have
"""
import csv, json, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from causes import load_overrides

ROOT = Path(__file__).resolve().parent.parent

# Hard drops: opinion, politicians' reactions, explainers. Not reporting about the outage itself.
COMMENTARY = re.compile(r"\b(trump(?![\'’]s truth)|vance|senators?|lawmakers?|congress\w*|mullin)\b|^opinion\b|\(opinion\)|criticism mounts|cyberattack fears|what to know|how to |protect yourself|are you ready|is .{0,20} ready|outage after outage|string of|wave of|latest tech|everything be broken|more (tech )?outages likely|why (cloud|do|are)|causes behind|what would happen|file photo|what passengers can claim|seeks answers|fear the worst|trend", re.I)
# "Is X down?" pages: thin but they do show an outage was reported. Kept as evidence, not counted as articles.
SEO_STATUS = re.compile(r"is it down|is .{0,25} down\?|are .{0,25} down\?|check if|down or not|down today\?|outage today:", re.I)
BRANDS = {"Chase": r"\bchase\b", "Wells Fargo": r"wells fargo", "Bank of America": r"bank of america", "Capital One": r"capital one",
          "Citi": r"\bciti(bank)?\b", "PayPal": r"paypal", "Zelle": r"zelle", "United Airlines": r"united airlines|\bunited\b",
          "Delta": r"\bdelta\b", "American Airlines": r"american airlines", "Southwest": r"southwest", "NSA": r"\bnsa\b",
          "Apple": r"\bapple\b|icloud", "Microsoft": r"microsoft|outlook|\bazure\b|office 365", "AWS": r"\baws\b|amazon web services|us-east-1",
          "Google Cloud": r"google cloud", "Gmail": r"gmail", "Cloudflare": r"cloudflare", "Claude/Anthropic": r"claude|anthropic",
          "OpenAI/ChatGPT": r"openai|chatgpt", "PlayStation": r"playstation", "FAA": r"\bfaa\b"}
BRAND_ENTITY_CATEGORY = {"Chase": "bank", "Wells Fargo": "bank", "Bank of America": "bank", "Capital One": "bank", "Citi": "bank", "PayPal": "bank", "Zelle": "bank",
    "United Airlines": "transport", "Delta": "transport", "American Airlines": "transport", "Southwest": "transport", "FAA": "transport", "NSA": "government",
    "Apple": "consumer-app", "Microsoft": "saas", "AWS": "cloud", "Google Cloud": "cloud", "Gmail": "cloud", "Cloudflare": "cdn-network",
    "Claude/Anthropic": "ai", "OpenAI/ChatGPT": "ai", "PlayStation": "consumer-app"}
# which brand a feed/manual service name belongs to
SERVICE_BRAND = [("microsoft", "Microsoft"), ("chase", "Chase"), ("nsa", "NSA"), ("cloudflare", "Cloudflare"), ("anthropic", "Claude/Anthropic"), ("openai", "OpenAI/ChatGPT"), ("github", "GitHub")]

AI_ANY = re.compile(r"\bA\.?I\.?\b|artificial intelligence|chatgpt|copilot|claude|openai|anthropic|\bllm\b|ai-generated|ai agent|vibe cod", re.I)
AI_RULED_OUT = re.compile(r"(not|no|neither|isn'?t|wasn'?t|nor)[^.]{0,40}\b(A\.?I\.?|artificial intelligence)\b|\bA\.?I\.?\b[^.]{0,30}(not to blame|ruled out|wasn'?t (to blame|the cause))|rules? out[^.]{0,30}\bA\.?I\b", re.I)
AI_CITED = re.compile(r"(caused|triggered|blamed|due) (by|on|to)[^.]{0,25}(\bA\.?I\.?\b|ai-generated|ai agent|ai tool|automated agent)|ai-(generated|driven|written|assisted) (code|change|config|patch(es)?|update(s)?)[^.]{0,30}(behind|cause|blamed|linked)|(behind|blamed|linked)[^.]{0,30}ai-(driven|generated|written|assisted) (code|change|config|patch(es)?|update(s)?)|ai-generated (code|change|config)|ai (agent|tool|assistant)[^.]{0,30}(deleted|pushed|caused|broke|misconfigured)", re.I)
AI_SPEC = re.compile(r"\bA\.?I\.?\b", re.I)


def brand_of(title):
    for b, rx in BRANDS.items():
        if re.search(rx, title, re.I):
            return b
    return None


UNRELATED = re.compile(r"no outage link|\$\d+m deal|smart ai", re.I)


def ai_link(texts, category=None):
    """Returns (ai_link, evidence). Priority: cited > ruled-out > speculated > ai-service."""
    hit = {}
    for t in texts:
        if UNRELATED.search(t):
            continue
        if AI_RULED_OUT.search(t): hit.setdefault("ruled-out", t)
        elif AI_CITED.search(t): hit.setdefault("cited-cause", t)
        elif AI_ANY.search(t): hit.setdefault("speculated", t)
    for k in ("cited-cause", "ruled-out", "speculated"):
        if k in hit:
            return k, hit[k][:120]
    if category == "ai":
        return "ai-service", "affected service is an AI product"
    return "none", None


_IND = r"banks?|banking|payments?|payment (systems?|apps?)|trading|brokerages?|airlines?|flights?|airports?|hospitals?|clinics?|retailers?|stores?|insurers?|supermarkets?|e-?commerce|travel"
_VERB = r"hit|hits|affect(s|ed)?|disrupt(s|ed)?|down|outages?|delays?|delayed|halt(s|ed)?|ground(s|ed)?|knock(s|ed)?|impact(s|ed)?|struggl\w+|cripple[sd]?|stall(s|ed)?|freez\w+"
# Another industry counts only when it is named as the thing that was hit.
OTHER_INDUSTRY = re.compile(r"\b(" + _IND + r")\b[^.]{0,50}\b(" + _VERB + r")\b|\b(" + _VERB + r")\b[^.]{0,50}\b(" + _IND + r")\b", re.I)
AI_PRODUCTS = re.compile(r"copilot|chatgpt|claude|gemini|openai|anthropic|\bai services\b", re.I)


# How much an outage touches daily or work life. Developer and API infrastructure is "niche"
# and is kept only when the press covered it (3+ articles).
LIFE_DAILY = {"bank", "transport", "government", "telecom", "consumer-app", "commerce"}
LIFE_WORK = {"saas", "cloud", "cdn-network"}
LIFE_OVERRIDE = {"GitHub": "work", "Vercel": "niche"}


def life_tier(e):
    t = LIFE_OVERRIDE.get(e.get("service"))
    if t:
        return t
    c = e.get("category")
    return "daily" if c in LIFE_DAILY else "work" if c in LIFE_WORK else "niche"


def d(s): return datetime.strptime(s[:10], "%Y-%m-%d")
def load(p): return json.loads((ROOT / p).read_text())


def news_events(articles, overrides):
    groups = {}
    dropped, weak = [], []
    def rec(a, m):
        return {"published": (a.get("published_at") or "")[:10], "title": a["title"], "outlet": a.get("outlet") or a.get("source"), "url": a.get("url"), "matched": m.group(0)}
    for a in articles:
        m = COMMENTARY.search(a["title"])
        if m:
            if brand_of(a["title"]):
                dropped.append(rec(a, m))
            continue
        b = brand_of(a["title"])
        if not b:
            continue  # unattributable
        w = SEO_STATUS.search(a["title"])
        if w:
            weak.append(dict(rec(a, w), brand=b))
            a = dict(a, weak=True)
        groups.setdefault(b, []).append(a)
    dropped.sort(key=lambda x: x["published"], reverse=True)
    weak.sort(key=lambda x: x["published"], reverse=True)
    (ROOT / "data/filtered_commentary.json").write_text(json.dumps({"dropped_count": len(dropped), "dropped": dropped, "evidence_only_count": len(weak), "evidence_only": weak}, indent=1))
    events = []
    for b, arts in groups.items():
        days = {}
        for a in arts:
            days.setdefault(a["published_at"][:10], []).append(a)
        cur = None
        for day in sorted(days):
            if cur and (d(day) - d(cur["end"])).days <= 1:
                cur["end"] = day; cur["arts"] += days[day]
            else:
                if cur: events.append(cur)
                cur = {"brand": b, "start": day, "end": day, "arts": list(days[day])}
        if cur: events.append(cur)
    out = []
    for e in events:
        strong = [a for a in e["arts"] if not a.get("weak")]
        # needs 2+ real articles, and 3+ counting "Is X down?" pages as evidence
        if len(strong) < 2 or len(e["arts"]) < 3:
            continue
        weak_n = len(e["arts"]) - len(strong)
        e["arts"] = strong
        titles = [a["title"] for a in e["arts"]]
        causes = {}
        for a in e["arts"]:
            if a.get("cause", "unknown") != "unknown":
                causes.setdefault(a["cause"], []).append(a)
        cause = max(causes, key=lambda c: len(causes[c])) if causes else "unknown"
        ev = causes[cause][0].get("cause_evidence") if causes else None
        link, ai_ev = ai_link(titles, BRAND_ENTITY_CATEGORY.get(e["brand"]))
        other_ind = any(OTHER_INDUSTRY.search(t) for t in titles)
        out.append({"key": f"news:{e['brand']}:{e['start']}", "brand": e["brand"], "category": BRAND_ENTITY_CATEGORY.get(e["brand"], "other"),
                    "title": max(e["arts"], key=lambda a: a["published_at"])["title"] if False else sorted(titles, key=len)[len(titles)//2],
                    "first_reported": e["start"], "last_reported": e["end"], "articles": len(e["arts"]), "evidence_pages": weak_n,
                    "outlets": len({a.get("outlet") for a in e["arts"] if a.get("outlet")}), "cause": cause, "cause_basis": "press" if causes else None,
                    "cause_evidence": ev, "other_industry": other_ind, "ai_link": link, "ai_evidence": ai_ev, "urls": [a["url"] for a in e["arts"]][:5]})
    return out


def main():
    ov = load_overrides(ROOT)
    news = news_events(load("data/news.json")["articles"], ov)
    events = []
    # manual events
    manual = load("data/manual.json")["events"]
    for m in manual:
        brand = next((b for s, b in SERVICE_BRAND if s in m["service"].lower()), None)
        if "chase" in m["service"].lower(): brand = "Chase"
        events.append({**m, "brand": brand, "sources": ["manual"], "articles": 0, "first_reported": m["started_at"][:10],
                       "last_reported": (m.get("resolved_at") or m["started_at"])[:10], "title": m["title"], "cause_basis": m.get("cause_basis")})
    # feed incidents (major+)
    for r in load("data/incidents.json")["incidents"]:
        if r["severity"] in ("major", "critical"):
            brand = next((b for s, b in SERVICE_BRAND if s in r["service"].lower()), None)
            events.append({**r, "brand": brand, "sources": ["status-page"], "articles": 0, "first_reported": r["started_at"][:10],
                           "last_reported": (r.get("resolved_at") or r["started_at"])[:10]})
    # fold news into events that share a brand and overlap (+/-1 day); else add as news-only
    used = set()
    for e in events:
        txts = []
        for n in news:
            if n["brand"] and n["brand"] == e.get("brand") and d(n["first_reported"]) <= d(e["last_reported"]) + timedelta(days=1) and d(n["last_reported"]) >= d(e["first_reported"]) - timedelta(days=1):
                used.add(n["key"]); e["other_industry"] = e.get("other_industry") or n.get("other_industry", False); e["articles"] += n["articles"]; e["sources"].append("news"); e.setdefault("urls", []).extend(n["urls"])
                txts.append(n["title"])
                if e.get("cause", "unknown") == "unknown" and n["cause"] != "unknown":
                    e["cause"], e["cause_basis"], e["cause_evidence"] = n["cause"], "press", n["cause_evidence"]
                if n["ai_link"] != "none" and e.get("ai_link", "none") in (None, "none", "ai-service"):
                    e["ai_link"], e["ai_evidence"] = n["ai_link"], n["ai_evidence"]
        if "ai_link" not in e:
            e["ai_link"], e["ai_evidence"] = ai_link(txts, e.get("category"))
        elif e["ai_link"] == "none" and e.get("category") == "ai":
            e["ai_link"], e["ai_evidence"] = "ai-service", "affected service is an AI product"
    for n in news:
        if n["key"] not in used:
            events.append({**n, "service": n["brand"], "kind": "news", "severity": "reported", "sources": ["news"], "started_at": n["first_reported"] + "T00:00:00Z",
                           "resolved_at": None, "time_precision": "day"})
    for e in events:
        blob = " ".join([e.get("service", ""), e.get("title", ""), " ".join(e.get("components") or [])])
        e["ai_service_affected"] = bool(e.get("category") == "ai" or AI_PRODUCTS.search(blob))
        o = ov.get(e["key"], {})
        if "cause" in o:
            e["cause"], e["cause_basis"] = o["cause"], "override"
        if "ai_link" in o:
            e["ai_link"], e["ai_evidence"] = o["ai_link"], "override: " + o.get("note", "")
    for e in events:
        e.setdefault("cause", "unknown")
    # AI companies' own outages are out of scope unless coverage shows another industry was hit.
    def feed_text(e):
        return " ".join([e.get("title") or ""] + [u.get("body") or "" for u in (e.get("updates") or [])])
    kept, excluded = [], []
    for e in events:
        if e.get("category") == "ai":
            hit = e.get("other_industry") or (e["sources"] == ["status-page"] and OTHER_INDUSTRY.search(feed_text(e)))
            if not hit:
                excluded.append({"key": e["key"], "service": e["service"], "title": e.get("title"), "first_reported": e["first_reported"]})
                continue
        kept.append(e)
    events = kept
    kept, niche = [], []
    for e in events:
        e["life_impact"] = life_tier(e)
        if e["life_impact"] == "niche" and e.get("articles", 0) < 3:
            niche.append({"key": e["key"], "service": e["service"], "title": e.get("title"), "first_reported": e["first_reported"]})
        else:
            kept.append(e)
    events = kept
    (ROOT / "data/excluded_niche.json").write_text(json.dumps({"count": len(niche), "events": niche}, indent=1))
    (ROOT / "data/excluded_ai.json").write_text(json.dumps({"count": len(excluded), "events": excluded}, indent=1))
    events.sort(key=lambda e: e["first_reported"], reverse=True)
    (ROOT / "data/events.json").write_text(json.dumps({"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "count": len(events), "events": events}, indent=1))
    cols = ["first_reported", "last_reported", "service", "category", "title", "severity", "cause", "cause_basis", "ai_link", "ai_service_affected", "ai_evidence", "articles", "sources", "key"]
    with open(ROOT / "data/events.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols)
        for e in events:
            w.writerow([("|".join(e[c]) if c == "sources" else e.get(c)) for c in cols])
    print(f"excluded_niche={len(niche)}  excluded_ai={len(excluded)}  events={len(events)}  (news-only={sum(1 for e in events if e['sources']==['news'])})")


if __name__ == "__main__":
    main()
