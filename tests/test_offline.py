"""
Offline end-to-end test. Serves tests/fixture_site on localhost and fakes the
PageSpeed and Places API responses (shape copied from Google's documented format),
so the whole pipeline runs without internet or keys.
Run:  python tests/test_offline.py
"""
import csv
import functools
import http.server
import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from auditor import cli, pagespeed, places  # noqa: E402

PORT = 8765


def serve():
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "tests" / "fixture_site"))
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("localhost", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def fake_psi(url, strategy="mobile", api_key="", timeout=0):
    return {"url": url, "strategy": strategy, "ok": True, "fetched_at": "test",
            "scores": {"performance": 42 if strategy == "mobile" else 91, "seo": 92, "accessibility": 80, "best-practices": 96},
            "lab": {"LCP (lab)": "5.1 s", "CLS (lab)": "0.02"}, "field": {}}


def place(name, site, rating, reviews, pid, ptype="roofing_contractor"):
    return {"place_id": pid, "name": name, "address": "1 Main St, Frisco, TX 75034, USA", "phone": "(214) 555-0101",
            "website": site, "rating": rating, "reviews": reviews, "primary_type": ptype,
            "primary_category": "Roofing Contractor" if ptype == "roofing_contractor" else ptype, "types": [ptype],
            "status": "OPERATIONAL", "maps_url": "https://maps.google.com/?cid=1", "hours": ["Monday: 8AM-6PM"]}


def fake_search(query, api_key, max_results=20):
    me = place("Acme Roofing LLC", f"http://localhost:{PORT}/", 4.8, 37, "me", "general_contractor")
    comps = [place("Big Roof Co", "https://bigroof.example", 4.9, 412, "c1"),
             place("Storm Pros", "https://stormpros.example", 4.7, 230, "c2"),
             place("Lone Star Roofing", "https://lsr.example", 4.8, 180, "c3")]
    return {"ok": True, "query": query, "results": comps[:2] + [me] + comps[2:] if " in " in query else [me]}


def main():
    serve()
    pagespeed.run = fake_psi
    places.text_search = fake_search
    os.environ["GOOGLE_PLACES_API_KEY"] = "test-key"
    out = ROOT / "tests" / "_out"
    report = cli.main([f"http://localhost:{PORT}/", "--cities", "Frisco, TX; Plano, TX", "--name", "Acme Roofing", "--out", str(out)])
    rows = list(csv.DictReader(open(report.parent / "findings.csv", encoding="utf-8")))
    ids = {r["title"]: r["status"] for r in rows}
    checks = {
        "broken link found": any("broken internal" in t and s == "fail" for t, s in ids.items()),
        "two phones found": any("2 different phone numbers" in t for t in ids),
        "mobile PSI fail": any("Mobile performance score 42" in t and s == "fail" for t, s in ids.items()),
        "category warn": any("Primary type is general_contractor" in t and s == "warn" for t, s in ids.items()),
        "competitor position": any("client is #3" in t for t in ids),
        "plano missing": any("1 of 2 target cities" in t for t in ids),
        "orphan found": any("no internal links pointing" in t for t in ids),
        "gbp name differs": any("GBP name and website name differ" in t for t in ids),
    }
    for k, v in checks.items():
        print(("PASS " if v else "FAIL ") + k)
    if not all(checks.values()):
        sys.exit(1)
    print("All offline checks passed. Report:", report)


if __name__ == "__main__":
    main()
