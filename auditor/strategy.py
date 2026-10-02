"""
Turns findings into the 6-month plan from the Master Strategy (Section 14).
Two kinds of items, always labeled:
  * FINDING  - comes from a failed/warned check on this site, with evidence.
  * PLAYBOOK - standard work every roofing client gets (not a claim about this site).
"""
from . import config
from .checks import FAIL, WARN, slugify

MONTHS = {
    0: "Month 0 (weeks 1-2): audit, access and baseline",
    1: "Month 1: foundation and GBP",
    2: "Month 2: money spokes",
    3: "Month 3: top cities",
    4: "Month 4: expand",
    5: "Month 5: authority",
    6: "Month 6: optimize and case study",
}

PLAYBOOK = [
    (0, "Collect NAP, license, insurance, certifications, warranty terms, real services, target cities, 50+ job photos (S5 checklist)"),
    (0, "Get access: GBP manager, Search Console, GA4, website admin, call tracking"),
    (0, "Baseline: 7x7 rank grid for roofer, roofing contractor, roof repair, roof replacement, storm damage roof repair"),
    (0, "Keyword research and clustering; one cluster per URL in the mapping sheet (S8)"),
    (1, "GBP rebuild: categories, services with descriptions, attributes, hours, photos, booking link (S6)"),
    (1, "Start the review engine: same-day text with the review link after every job (S6)"),
    (1, "Core citations with exact NAP: Bing, Apple, Yelp, BBB, Facebook, Nextdoor (S11)"),
    (1, "Call tracking + UTM on the GBP link + GA4 events (S13)"),
    (2, "Trade citations: Angi, HomeAdvisor, Houzz, Thumbtack, manufacturer locators (S11)"),
    (2, "2 blog posts from the topical map, each linked to one money page (S10)"),
    (3, "Monthly spam check of the map pack and redressal reports (S6)"),
    (3, "First local links: sponsorship, supplier, partner pages (S11)"),
    (4, "3 blog posts; partner links from realtors, inspectors, insurance agents (S11)"),
    (5, "Local PR or sponsorship story; refresh Month 1 pages with new photos and reviews"),
    (6, "Rewrite pages ranking 4-15, add FAQs from real calls, AI answer test, before/after case study"),
]
WEEKLY = [
    "1-2 GBP posts (finished job with city + material + photo, storm alert, tip, offer)",
    "5-10 new real job photos on GBP",
    "Reply to every review within 48 hours",
    "Storm watch for the client's region; post and update the storm page within 48 hours of an event",
]


def build_plan(findings, silo_coverage, city_coverage, cities):
    roadmap = {m: [] for m in MONTHS}
    for f in findings:
        if f.status in (FAIL, WARN) and f.action:
            roadmap[f.month].append({"kind": "FINDING", "priority": f.priority or "P3", "text": f.action,
                                     "why": f.title, "ref": f.ref, "id": f.id})
    for m, text in PLAYBOOK:
        roadmap[m].append({"kind": "PLAYBOOK", "priority": "", "text": text, "why": "", "ref": "", "id": ""})
    order = {"P1": 0, "P2": 1, "P3": 2, "": 3}
    for m in roadmap:
        roadmap[m].sort(key=lambda x: (x["kind"] != "FINDING", order.get(x["priority"], 3)))

    pages = []
    hub_keys = {"repair_hub", "replacement_hub", "storm_hub", "free_inspection", "financing", "warranty", "reviews",
                "about", "contact", "service_areas"}
    for r in silo_coverage:
        if r["status"] == "missing_core":
            pages.append({"page": r["label"], "silo": r["silo"], "url": r["suggested_url"],
                          "month": 1 if r["key"] in hub_keys else 2, "type": "Core page (not found on site)"})
        elif r["status"] == "not_found_optional":
            pages.append({"page": r["label"], "silo": r["silo"], "url": r["suggested_url"],
                          "month": 4, "type": "Optional: only if client offers it"})
    for i, row in enumerate(city_coverage):
        city = row["city"]
        name = city.split(",")[0].strip()
        st = city.split(",")[1].strip().lower() if "," in city else ""
        suffix = f"{slugify(name)}{'-' + st if st else ''}"
        month = 3 if i < 5 else (4 if i < 10 else 5)
        if not row["pages"]:
            pages.append({"page": f"Roofer in {city}", "silo": "Service Areas", "url": f"/roofer-{suffix}/",
                          "month": month, "type": "City page (not found on site)"})
        if i < 5:
            for slug, label in config.COMBO_SERVICES:
                if not row["combos"].get(label):
                    pages.append({"page": f"{label} in {city}", "silo": "Combo", "url": f"/{slug}-{suffix}/",
                                  "month": 3 if i < 3 else 4, "type": "Combo page (not found on site)"})
    pages.sort(key=lambda p: p["month"])
    return {"months": MONTHS, "roadmap": roadmap, "weekly": WEEKLY, "page_plan": pages}
