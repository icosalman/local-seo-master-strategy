import argparse
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from . import config, pagespeed, places
from .checks import Auditor
from .crawler import crawl
from .report import write_all
from .strategy import build_plan

ROOT = Path(__file__).resolve().parent.parent


def load_env():
    """Tiny .env reader (KEY=value lines). Real environment variables win."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def parse_cities(s):
    if not s:
        return []
    return [c.strip() for c in re.split(r"[;\n|]", s) if c.strip()]


def detect_cms(html):
    found = []
    for name, pats in config.CMS_MARKERS:
        if any(re.search(p, html or "", re.I) for p in pats):
            found.append(name)
    return found


def interactive(args):
    print("\nSQ Local Auditor: roofing local SEO audit\n")
    args.url = input("Client website URL: ").strip()
    if not args.cities:
        args.cities = input('Target cities (e.g. "Frisco, TX; Plano, TX"), Enter to skip: ').strip()
    if not args.name:
        args.name = input("Business name as on Google (Enter to skip): ").strip()
    return args


def main(argv=None):
    load_env()
    ap = argparse.ArgumentParser(prog="python -m auditor",
                                 description="Audit a roofing website against the Roofing Local SEO Master Strategy.")
    ap.add_argument("url", nargs="?", help="client website, e.g. https://example-roofing.com")
    ap.add_argument("--cities", default="", help='target cities, separated by ; e.g. "Frisco, TX; Plano, TX"')
    ap.add_argument("--name", default="", help="business name as shown on Google (helps find the GBP)")
    ap.add_argument("--place-id", default="", help="Google place ID of the client's GBP (most exact)")
    ap.add_argument("--comp-keyword", default="roofing contractor", help='competitor search phrase (default "roofing contractor")')
    ap.add_argument("--max-pages", type=int, default=config.DEFAULT_MAX_PAGES)
    ap.add_argument("--no-psi", action="store_true", help="skip PageSpeed Insights")
    ap.add_argument("--no-places", action="store_true", help="skip Google Places even if a key is set")
    ap.add_argument("--ignore-robots", action="store_true", help="crawl pages robots.txt disallows (only with client permission)")
    ap.add_argument("--out", default=str(ROOT / "reports"), help="output folder")
    args = ap.parse_args(argv)
    if not args.url:
        args = interactive(args)
        if not args.url:
            sys.exit("No URL given.")

    url = args.url if "://" in args.url else "https://" + args.url
    cities = parse_cities(args.cities)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    print(f"\n[1/5] Crawling {url} (max {args.max_pages} pages)...")
    res = crawl(url, max_pages=args.max_pages, respect_robots=not args.ignore_robots)
    print(f"      {len(res.pages)} pages fetched, {len(res.sitemap_urls)} sitemap URLs, {res.requests} requests")
    home_url = res.home.final_url or res.home.url
    if res.home.status != 200 or not res.home.text:
        sys.exit(f"\nStopped: the homepage returned status {res.home.status or res.home.error} "
                 f"({res.home.content_type or 'no content'}) to the crawler.\n"
                 "Running the checks on a blocked or empty page would produce wrong results, so no report was written.\n"
                 "Common cause: a firewall (e.g. Cloudflare) blocking bots. Ask the client to allow the user agent "
                 f'"{config.USER_AGENT}", or try the exact final URL.')

    psi = {}
    if not args.no_psi:
        key = os.environ.get("PAGESPEED_API_KEY", "")
        print("[2/5] PageSpeed Insights (mobile + desktop)... this can take a minute")
        for strat in ("mobile", "desktop"):
            psi[strat] = pagespeed.run(home_url, strat, key)
            print(f"      {strat}: " + (f"performance {psi[strat]['scores'].get('performance')}" if psi[strat].get("ok") else psi[strat].get("error", "")))
    else:
        print("[2/5] PageSpeed skipped")

    pl = {}
    pkey = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if pkey and not args.no_places:
        print("[3/5] Google Places: client profile and competitors...")
        notes, client, match = [], None, ""
        if args.place_id:
            d = places.details(args.place_id, pkey)
            if d.get("ok"):
                client, match = d["place"], f"--place-id {args.place_id}"
            else:
                notes.append(f"place-id lookup failed: {d.get('error')}")
        if not client:
            domain = urlparse(home_url).netloc.replace("www.", "")
            name = args.name or res.home.og_site_name
            queries = []
            if name:
                queries.append(f"{name} {cities[0]}" if cities else name)
            queries.append(domain)
            for q in queries:
                r = places.text_search(q, pkey, 10)
                if not r.get("ok"):
                    notes.append(f'"{q}": {r.get("error")}')
                    continue
                hit = next((p for p in r["results"] if places.same_site(p["website"], home_url)), None)
                notes.append(f'"{q}": {len(r["results"])} results, website match: {"yes" if hit else "no"}')
                if hit:
                    client, match = hit, f'search "{q}" + website domain match'
                    break
        pl = {"client": client, "client_match": match, "client_notes": notes, "competitors": []}
        for city in cities[:10]:
            q = f"{args.comp_keyword} in {city}"
            pl["competitors"].append({"city": city, "data": places.text_search(q, pkey, 20)})
        print(f"      client GBP: {client['name'] if client else 'not matched'}; competitor searches: {len(pl['competitors'])}")
    else:
        print("[3/5] Google Places skipped (no GOOGLE_PLACES_API_KEY)" if not pkey else "[3/5] Google Places skipped")

    print("[4/5] Running checks against the master strategy...")
    aud = Auditor(res, cities=cities, psi=psi, places_data=pl, business_name=args.name)
    findings = aud.run()
    plan = build_plan(findings, aud.silo_coverage, aud.city_coverage, cities)

    print("[5/5] Writing report...")
    out_dir = Path(args.out) / f"{res.site_host}_{stamp}"
    pages = sorted(res.pages.values(), key=lambda p: p.url)
    ctx = {
        "site_host": res.site_host, "start_url": res.start_url, "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "business_name": args.name, "cities": cities, "cms": detect_cms(res.home.html_sample),
        "pages": pages, "indexable_count": len(aud.ok_pages), "sitemap_count": len(res.sitemap_urls),
        "findings": findings, "plan": plan, "silo_coverage": aud.silo_coverage, "city_coverage": aud.city_coverage,
        "combo_labels": [l for _, l in config.COMBO_SERVICES], "competitors": aud.competitors,
        "phone_map": aud.phone_map, "site_facts": aud.site_facts, "robots_status": res.robots_status,
        "inbound_counts": {u: len(v) for u, v in aud.inbound.items()}, "requests": res.requests,
        "psi": psi, "places_client": pl.get("client") if pl else None,
    }
    report = write_all(out_dir, ctx)
    c = {s: sum(1 for f in findings if f.status == s) for s in ("fail", "warn", "pass", "info", "not_checked")}
    print(f"\nDone. {c['fail']} fail, {c['warn']} warn, {c['pass']} pass, {c['info']} info, {c['not_checked']} not checked")
    print(f"Report: {report}")
    return report


if __name__ == "__main__":
    main()
