#!/usr/bin/env python3
"""Collect incidents from Statuspage-style feeds and merge them into data/incidents.json.

Stdlib only. Safe to re-run: incidents are keyed by "<source>:<id>" and updated in place,
so an incident that was open on one run and resolved on the next ends up as one record.
Manually logged events (banks, government, anything without a feed) live in data/manual.json
and are merged in by summarize.py, never overwritten here.
"""
import json
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent))
from causes import classify_incident
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES = ROOT / "collector" / "sources.json"
OUT = ROOT / "data" / "incidents.json"
UA = "outage-tracker/0.1 (personal project)"

# Statuspage "impact" -> our severity
IMPACT = {"none": "none", "maintenance": "maintenance", "minor": "minor", "major": "major", "critical": "critical"}


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def parse_ts(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def normalize(src, inc):
    started = parse_ts(inc.get("started_at") or inc.get("created_at"))
    resolved = parse_ts(inc.get("resolved_at"))
    duration = int((resolved - started).total_seconds() / 60) if started and resolved else None
    impact = IMPACT.get(inc.get("impact", "none"), "none")
    is_maint = (inc.get("impact") == "maintenance") or inc.get("shortlink", "").endswith("maint")
    rec = {
        "key": f"{src['id']}:{inc['id']}",
        "source": src["id"],
        "service": src["name"],
        "category": src["category"],
        "kind": "feed",
        "title": inc.get("name"),
        "severity": "maintenance" if is_maint else impact,
        "status": inc.get("status"),
        "started_at": iso(started),
        "resolved_at": iso(resolved),
        "duration_min": duration,
        "components": [c.get("name") for c in inc.get("components", []) if c.get("name")],
        "updates": [
            {"at": iso(parse_ts(u.get("display_at") or u.get("created_at"))), "status": u.get("status"), "body": u.get("body")}
            for u in inc.get("incident_updates", [])
        ],
        "url": inc.get("shortlink") or f"{src['base']}/incidents/{inc['id']}",
    }
    rec["cause"], rec["cause_basis"], rec["cause_evidence"] = classify_incident(rec)
    return rec


def main():
    sources = json.loads(SOURCES.read_text())["statuspage"]
    existing = {}
    if OUT.exists():
        for rec in json.loads(OUT.read_text()).get("incidents", []):
            existing[rec["key"]] = rec

    added = updated = 0
    errors = []
    for src in sources:
        url = src["base"].rstrip("/") + "/api/v2/incidents.json"
        try:
            data = fetch_json(url)
        except Exception as e:  # keep going; one dead feed shouldn't stop the run
            errors.append(f"{src['id']}: {e}")
            continue
        for inc in data.get("incidents", []):
            rec = normalize(src, inc)
            if rec["key"] not in existing:
                added += 1
            elif existing[rec["key"]] != rec:
                updated += 1
            existing[rec["key"]] = rec

    incidents = sorted(existing.values(), key=lambda r: r["started_at"] or "", reverse=True)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "generated_at": iso(datetime.now(timezone.utc)),
        "count": len(incidents),
        "incidents": incidents,
    }, indent=1))
    print(f"added={added} updated={updated} total={len(incidents)} errors={len(errors)}")
    for e in errors:
        print("  ERROR", e, file=sys.stderr)
    # Only fail the job if every feed failed (likely a network problem).
    return 1 if len(errors) == len(sources) else 0


if __name__ == "__main__":
    sys.exit(main())
