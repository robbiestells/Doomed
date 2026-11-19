"""Flatten data/events.json into the rows the dashboard page reads (data/dashboard_events.json)."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
events = json.loads((ROOT / "data/events.json").read_text())["events"]
rows = []
for e in events:
    src = "status-page" if "status-page" in e["sources"] else ("manual" if "manual" in e["sources"] else "news")
    rows.append({
        "id": e["key"], "first": e["first_reported"], "last": e["last_reported"], "service": e["service"],
        "category": e["category"], "life_impact": e.get("life_impact"), "severity": e.get("severity"),
        "cause": e.get("cause", "unknown"), "cause_basis": e.get("cause_basis"), "ai_link": e["ai_link"],
        "articles": e.get("articles", 0), "source": src,
        "sampled": bool(e.get("articles", 0) > 0 and e["first_reported"] < "2026-11-12"),
        "title": (e.get("title") or "")[:140],
        "url": e.get("url") or (e.get("urls") or [None])[0],
    })
(ROOT / "data/dashboard_events.json").write_text(json.dumps(rows, separators=(",", ":")))
print(f"dashboard rows={len(rows)}")
