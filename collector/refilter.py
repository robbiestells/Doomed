#!/usr/bin/env python3
"""Re-apply the current outage filter and cause rules to every stored article in data/news.json.
Run after changing OUTAGE / NOISE in news.py. Prints what was removed."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import news
from causes import classify_ev

d = json.loads(news.OUT.read_text())
keep, gone = [], []
for a in d["articles"]:
    ok = bool(news.OUTAGE.search(a["title"])) and not news.NOISE.search(a["title"])
    (keep if ok else gone).append(a)
for a in keep:
    a["cause"], a["cause_evidence"] = classify_ev(a["title"], press=True)
d["articles"] = keep
news.OUT.write_text(json.dumps(d, indent=1))
print(f"kept {len(keep)}, removed {len(gone)}")
if "-v" in sys.argv:
    for a in gone:
        print("  -", a["title"][:100])
