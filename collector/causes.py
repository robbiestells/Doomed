"""Cause classification shared by collect.py, news.py and summarize.py.

Returns (category, basis). Category is "unknown" unless wording clearly supports one.
basis: "provider" (text from the company's own incident updates) or "press" (news headline).
Keyword rules, so treat as a first pass; the `cause_override` field on any record wins.
"""
import re

# Order matters: more specific / attack-like first. "cyberattack" only matches when the
# text asserts it, and a negation ("not the result of a cyberattack") is stripped first.
CAUSES = [
    ("cyberattack", r"ddos|cyber-?attack|ransomware|hack(ed|ers?)|malicious|breach|attack(ed)? (on|against)"),
    ("software-change", r"software (update|patch)|\bpatch\b|deploy(ment|ed)?|rollout|rolled out|release|code change|bad update|faulty update|defect|\bbug\b|regression|\brollback\b|rolled back|migration"),
    ("config-change", r"configuration|misconfigur|config change|certificate|expired|\bdns\b|routing|\bbgp\b|firewall rule|policy change"),
    ("capacity-overload", r"overload|overwhelm|capacity|traffic spike|surge|high load|resource exhaustion|rate limit|queue backlog|thundering"),
    ("network", r"network (issue|upgrade|problem|connectivity|degradation)|connectivity|fiber|\bisp\b|peering|packet loss|latency"),
    ("hardware-datacenter", r"data ?cent(er|re)|power (loss|failure|outage)|cooling|hardware|disk|storage (failure|array)|fire\b|overheat|region (failure|outage)"),
    ("third-party", r"third[- ]party|upstream|vendor|dependency|provider (issue|outage)|cloud provider|due to (aws|azure|cloudflare|google)|caused by (aws|azure|cloudflare)"),
    ("human-error", r"human error|operator error|accidental(ly)?|mistake|inadvertent"),
]
# Remediation wording ("a fix has been deployed") describes the cure, not the cause.
REMEDIATION = re.compile(r"(a |the |our )?(fix|fixes|mitigation|workaround|patch|rollback|change|update)[^.]{0,40}(deployed|rolled out|applied|implemented|released|in place|completed)|(deployed|applied|implemented|rolled out) (a |the )?(fix|mitigation|workaround)|rolled back", re.I)
NEGATION = re.compile(r"(not|no evidence of|ruled out|wasn'?t|was not|isn'?t)[^.]{0,60}(cyber-?attack|hack|malicious|attack|ddos)", re.I)


# Headlines that raise a possibility rather than state a cause.
SPECULATIVE = re.compile(r"\?|\b(could|may|might|whether|was it|is it|proof|fear|suspect|speculat|rumou?r|claims?|why|what to know|how to|protect|ready|would)\b", re.I)
# For press text, a cause is only taken from wording that asserts it.
PRESS_BLOCK = {"cyberattack"}  # never inferred from a headline alone; needs provider/official wording


def classify_ev(text, press=False):
    """Returns (category, evidence). Evidence is the matched phrase plus nearby words."""
    if not text:
        return "unknown", None
    if press and SPECULATIVE.search(text):
        return "unknown", None
    t = REMEDIATION.sub(" ", NEGATION.sub(" ", text))
    for name, rx in CAUSES:
        if press and name in PRESS_BLOCK:
            continue
        m = re.search(rx, t, re.I)
        if m:
            a, b = max(0, m.start() - 50), min(len(t), m.end() + 50)
            return name, ("..." + t[a:b].replace("\n", " ").strip() + "...")
    return "unknown", None


def classify(text, press=False):
    return classify_ev(text, press)[0]


def load_overrides(root):
    """data/cause_overrides.json: {"overrides": {"<record key>": {"cause": "...", "note": "..."}}}"""
    import json
    p = root / "data" / "cause_overrides.json"
    return json.loads(p.read_text()).get("overrides", {}) if p.exists() else {}


def classify_incident(rec):
    """Feed incident: prefer the resolution/postmortem wording over early 'investigating' updates."""
    ups = rec.get("updates") or []
    # later statuses first: postmortem > resolved > monitoring > identified > investigating
    order = {"postmortem": 0, "resolved": 1, "monitoring": 2, "identified": 3, "update": 4, "investigating": 5}
    for u in sorted(ups, key=lambda u: order.get(u.get("status"), 6)):
        c, ev = classify_ev(u.get("body"))
        if c != "unknown":
            return c, "provider", ev
    return "unknown", None, None
