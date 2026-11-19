#!/usr/bin/env python3
"""Write data/review_queue.md: records whose cause is unknown or inferred, with the evidence
the classifier used, so you can correct them in data/cause_overrides.json.
Usage: review.py [--days 7] [--include-unknown]
"""
import argparse, json, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from causes import load_overrides

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--include-unknown", action="store_true")
    a = ap.parse_args()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=a.days)).strftime("%Y-%m-%d")
    ov = load_overrides(ROOT)
    rows = []
    for r in json.loads((ROOT / "data/incidents.json").read_text())["incidents"] + json.loads((ROOT / "data/manual.json").read_text())["events"]:
        if (r.get("started_at") or "") >= cutoff and r.get("severity") in ("major", "critical"):
            rows.append((r["key"], r["started_at"][:10], r["service"], r["title"], r.get("cause", "unknown"), r.get("cause_basis"), r.get("cause_evidence")))
    for e in json.loads((ROOT / "data/news.json").read_text())["events"]:
        if e["date"] >= cutoff:
            rows.append((e["key"], e["date"], e["entity"], e["headline"], e["cause"], e.get("cause_basis"), e.get("cause_evidence")))
    out = [f"# Cause review queue (last {a.days}d)", "", "Fix a label by adding `\"<key>\": {\"cause\": \"...\", \"note\": \"...\"}` to data/cause_overrides.json.", ""]
    n = 0
    for key, d, svc, title, cause, basis, ev in sorted(rows, key=lambda x: x[1], reverse=True):
        if key in ov:
            continue
        if cause == "unknown" and not a.include_unknown:
            continue
        n += 1
        out += [f"- **{key}** ({d}, {svc}) → `{cause}` [{basis}]", f"  - {title[:100]}", f"  - evidence: {ev}"]
    (ROOT / "data/review_queue.md").write_text("\n".join(out) + "\n")
    print(f"{n} records to review -> data/review_queue.md")


if __name__ == "__main__":
    main()
