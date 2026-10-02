import csv
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).parent / "templates"
STATUS_ORDER = {"fail": 0, "warn": 1, "info": 2, "pass": 3, "not_checked": 4}
PRIO_ORDER = {"P1": 0, "P2": 1, "P3": 2, "": 3}


def write_all(out_dir: Path, ctx: dict):
    out_dir.mkdir(parents=True, exist_ok=True)
    findings = ctx["findings"]

    # data.json (everything, machine readable)
    data = dict(ctx)
    data["findings"] = [f.to_dict() for f in findings]
    data["pages"] = [p.to_dict() for p in ctx["pages"]]
    (out_dir / "data.json").write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # pages.csv
    with open(out_dir / "pages.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["url", "status", "final_url", "title", "title_len", "meta_description_len", "h1_count", "h1",
                    "words", "internal_links_out", "inbound_internal_links", "images", "images_missing_alt",
                    "tel_links", "forms", "map_embed", "canonical", "meta_robots", "schema_types", "load_ms"])
        for p in ctx["pages"]:
            w.writerow([p.url, p.status or p.error, p.final_url, p.title, len(p.title), len(p.meta_description),
                        len(p.h1), " | ".join(p.h1), p.word_count, len(p.internal_links),
                        ctx["inbound_counts"].get(p.url, 0), p.images_total, len(p.images_missing_alt),
                        " ".join(p.tel_links), p.forms, p.map_embed, p.canonical, p.meta_robots,
                        " ".join(p.schema_types), p.elapsed_ms])

    # action_plan.csv (paste into your tracker sheet)
    with open(out_dir / "action_plan.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["month", "kind", "priority", "action", "because", "strategy_ref", "done"])
        for m, items in ctx["plan"]["roadmap"].items():
            for it in items:
                w.writerow([m, it["kind"], it["priority"], it["text"], it["why"], it["ref"], ""])
        w.writerow([])
        w.writerow(["month", "page_to_build", "silo", "suggested_url", "type", "", ""])
        for pg in ctx["plan"]["page_plan"]:
            w.writerow([pg["month"], pg["page"], pg["silo"], pg["url"], pg["type"], "", ""])

    # findings.csv
    with open(out_dir / "findings.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["area", "status", "priority", "title", "rule", "evidence", "action", "month", "strategy_ref"])
        for f in sorted(findings, key=lambda f: (STATUS_ORDER[f.status], PRIO_ORDER.get(f.priority, 3))):
            w.writerow([f.area, f.status, f.priority, f.title, f.rule, " || ".join(map(str, f.evidence)),
                        f.action, f.month, f.ref])

    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    tpl = env.get_template("report.html.j2")
    weak = sorted([f for f in findings if f.status in ("fail", "warn")],
                  key=lambda f: (PRIO_ORDER.get(f.priority, 3), STATUS_ORDER[f.status]))
    strong = [f for f in findings if f.status == "pass"]
    info = [f for f in findings if f.status == "info"]
    manual = [f for f in findings if f.status == "not_checked"]
    counts = {s: sum(1 for f in findings if f.status == s) for s in STATUS_ORDER}
    html = tpl.render(**ctx, weak=weak, strong=strong, info=info, manual=manual, counts=counts,
                      total=len(findings))
    (out_dir / "report.html").write_text(html, encoding="utf-8")
    return out_dir / "report.html"
