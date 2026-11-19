#!/usr/bin/env python3
"""Merge feed incidents + manual events and print/write frequency stats to data/summary.json.

Usage: summarize.py [--days N] [--min-severity minor|major|critical]
"Outage" here means severity >= min-severity (default: major) and not maintenance.
"""
import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RANK = {"none": 0, "maintenance": 0, "minor": 1, "major": 2, "critical": 3}


def load():
    import sys; sys.path.insert(0, str(Path(__file__).resolve().parent))
    from causes import load_overrides
    ov = load_overrides(ROOT)
    recs = []
    inc = ROOT / "data" / "incidents.json"
    if inc.exists():
        recs += json.loads(inc.read_text())["incidents"]
    man = ROOT / "data" / "manual.json"
    if man.exists():
        recs += json.loads(man.read_text())["events"]
    for r in recs:
        if r["key"] in ov:
            r["cause"], r["cause_basis"] = ov[r["key"]]["cause"], "override"
    return recs


def parse(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--include-ai", action="store_true", help="count outages of AI services (excluded by default)")
    ap.add_argument("--min-severity", default="major", choices=["minor", "major", "critical"])
    a = ap.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=a.days)
    floor = RANK[a.min_severity]
    recs = [r for r in load()
            if r.get("started_at") and parse(r["started_at"]) >= cutoff
            and RANK.get(r.get("severity"), 0) >= floor
            and (a.include_ai or r.get("category") != "ai")]

    by_service = Counter(r["service"] for r in recs)
    by_category = Counter(r["category"] for r in recs)
    by_week = Counter(parse(r["started_at"]).strftime("%G-W%V") for r in recs)
    by_cause = Counter(r.get("cause", "unknown") for r in recs)
    known = [r for r in recs if r.get("cause", "unknown") != "unknown"]
    by_dow = Counter(parse(r["started_at"]).strftime("%a") for r in recs)
    durations = defaultdict(list)
    for r in recs:
        if r.get("duration_min") is not None:
            durations[r["service"]].append(r["duration_min"])
        elif r.get("resolved_at"):
            durations[r["service"]].append(int((parse(r["resolved_at"]) - parse(r["started_at"])).total_seconds() / 60))

    summary = {
        "window_days": a.days,
        "min_severity": a.min_severity,
        "total": len(recs),
        "per_week_avg": round(len(recs) / (a.days / 7), 2),
        "by_service": by_service.most_common(),
        "by_category": by_category.most_common(),
        "by_week": sorted(by_week.items()),
        "by_cause": by_cause.most_common(),
        "cause_known_pct": round(100 * len(known) / len(recs), 1) if recs else 0,
        "by_weekday": by_dow.most_common(),
        "median_duration_min": {s: sorted(d)[len(d) // 2] for s, d in durations.items()},
    }
    (ROOT / "data" / "summary.json").write_text(json.dumps(summary, indent=1))

    print(f"{summary['total']} incidents >= {a.min_severity} in last {a.days}d ({summary['per_week_avg']}/week)")
    print("\nBy service:")
    for s, n in summary["by_service"]:
        med = summary["median_duration_min"].get(s)
        print(f"  {n:3d}  {s}" + (f"  (median {med} min)" if med is not None else ""))
    print("\nBy cause:", ", ".join(f"{c}={n}" for c, n in summary["by_cause"]), f"({summary['cause_known_pct']}% known)")
    print("\nBy category:", ", ".join(f"{c}={n}" for c, n in summary["by_category"]))
    print("By week:    ", ", ".join(f"{w}={n}" for w, n in summary["by_week"]))


if __name__ == "__main__":
    main()
