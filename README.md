# outage-tracker
Collects incidents from Statuspage feeds (collector/sources.json) hourly via GitHub Actions into data/incidents.json.
Hand-log things without feeds (banks, gov) in data/manual.json.
News: `python collector/news.py` (Google News RSS + BleepingComputer; personal use only) writes data/news.json.
Run: `python collector/collect.py && python collector/summarize.py --days 90 --min-severity minor`
Known limits: each feed returns only its latest 50 incidents, so history for busy services starts recent and fills in over time. Datadog returns 403 to scripts.

Merge: `python collector/merge.py` -> data/events.json + events.csv (one row per outage; ai_link, ai_service_affected, cause). Corrections go in data/cause_overrides.json (cause and/or ai_link).

## Scope filters
- `data/excluded_ai.json`: outages of AI companies' own products, dropped unless coverage shows another industry (banks, airlines, etc.) was hit. `summarize.py --include-ai` counts them.
- `data/excluded_niche.json`: developer-only infrastructure outages with fewer than 3 articles.
- Added status feeds for everyday/work services (Reddit, Shopify, Coinbase, Box, Asana, Notion, Squarespace, Figma, HubSpot, 1Password).
- `data/filtered_commentary.json`: `dropped` = commentary removed (opinion, officials reacting, explainers); `evidence_only` = "Is X down?" pages kept as evidence but not counted as articles. An event needs 2+ real articles and 3+ including evidence pages.

## Dashboard
`index.html` is the dashboard (static, d3 from a CDN). It reads `data/dashboard_events.json`, which `collector/export_dashboard.py` rebuilds on every run. Preview locally with `python3 -m http.server` and open http://localhost:8000. Enable it under Settings → Pages → Deploy from branch → `main` / root.
