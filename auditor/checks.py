"""
Every check here:
  * runs a fixed rule on data the tool actually fetched,
  * returns PASS / FAIL / WARN / INFO / NOT_CHECKED,
  * carries evidence (URLs and the exact text found),
  * points to the Master Strategy section and the action to take.
If the tool cannot see something, it says NOT_CHECKED. It never fills gaps with guesses.
"""
import re
import statistics
import urllib.robotparser
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse

from . import config
from .extract import PHONE_RE, norm_phone
from .places import same_site

PASS, FAIL, WARN, INFO, NOT_CHECKED = "pass", "fail", "warn", "info", "not_checked"
MAX_EVIDENCE = 25


@dataclass
class Finding:
    id: str
    area: str
    status: str
    title: str
    detail: str = ""
    evidence: list = field(default_factory=list)
    rule: str = ""
    ref: str = ""          # Master Strategy section
    action: str = ""
    priority: str = ""     # P1 (do first) / P2 / P3
    month: int = 1         # roadmap month (0-6)

    def to_dict(self):
        return asdict(self)


def _ev(items, limit=MAX_EVIDENCE):
    items = list(items)
    if len(items) > limit:
        return items[:limit] + [f"... and {len(items) - limit} more (see pages.csv)"]
    return items


def snippet(text, m, width=70):
    s, e = max(0, m.start() - width), min(len(text), m.end() + width)
    return ("..." if s else "") + text[s:e].strip() + ("..." if e < len(text) else "")


def path_of(u):
    return urlparse(u).path.lower() or "/"


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


class Auditor:
    def __init__(self, crawl, cities=None, psi=None, places_data=None, business_name=""):
        self.c = crawl
        self.cities = cities or []
        self.psi = psi or {}
        self.pl = places_data or {}
        self.business_name = business_name
        self.findings = []
        self.ok_pages = {u: p for u, p in crawl.pages.items()
                         if p.status == 200 and p.text and "noindex" not in p.meta_robots}
        self.all_html = {u: p for u, p in crawl.pages.items() if p.status == 200 and p.text}
        self.inbound = defaultdict(set)
        for u, p in crawl.pages.items():
            for l in p.internal_links:
                if l["url"] != u:
                    self.inbound[l["url"]].add(u)
        self.silo_coverage = []
        self.city_coverage = []
        self.phone_map = {}
        self.competitors = []
        self.site_facts = {}

    def add(self, **kw):
        self.findings.append(Finding(**kw))

    # ------------------------------------------------------------------ run
    def run(self):
        self.crawl_checks()
        self.onpage_checks()
        self.structure_checks()
        self.city_checks()
        self.local_checks()
        self.schema_checks()
        self.trust_checks()
        self.conversion_checks()
        self.speed_checks()
        self.gbp_checks()
        self.not_verified()
        return self.findings

    # --------------------------------------------------------- crawl/index
    def crawl_checks(self):
        c, home = self.c, self.c.home
        A = "Crawl & indexing"
        final = home.final_url or home.url
        if urlparse(final).scheme == "https":
            self.add(id="https", area=A, status=PASS, title="Homepage loads over HTTPS",
                     evidence=[final], rule="Final homepage URL uses https://", ref="S9")
        else:
            self.add(id="https", area=A, status=FAIL, title="Homepage is not served over HTTPS",
                     evidence=[final], rule="Final homepage URL uses https://", ref="S9",
                     action="Install SSL and 301 redirect all http:// URLs to https://.", priority="P1", month=1)

        home_host = urlparse(final).netloc
        bad = []
        for v, (st, fu, err) in c.http_variants.items():
            if err and not st:
                bad.append(f"{v} -> no response ({err[:80]})")
            elif urlparse(fu or "").netloc != home_host or urlparse(fu or "").scheme != urlparse(final).scheme:
                bad.append(f"{v} -> {st} {fu}")
        ev = [f"{v} -> {st} {fu}" for v, (st, fu, err) in c.http_variants.items()]
        self.add(id="host_variants", area=A, status=WARN if bad else PASS,
                 title="http / www versions redirect to one homepage" if not bad else "Some http / www versions do not end on the main homepage",
                 evidence=bad or ev, rule=f"Each variant should 301 to {urlparse(final).scheme}://{home_host}/",
                 ref="S7", action="301 redirect every http and www variant to the one main version." if bad else "",
                 priority="P2" if bad else "", month=1)

        if c.robots_status == 200:
            rp = urllib.robotparser.RobotFileParser()
            rp.parse(c.robots_text.splitlines())
            if not rp.can_fetch("Googlebot", final):
                self.add(id="robots", area=A, status=FAIL, title="robots.txt blocks Googlebot from the homepage",
                         evidence=[c.robots_text[:400]], rule="Googlebot must be allowed to crawl /", ref="S9",
                         action="Remove the Disallow rule that blocks Googlebot.", priority="P1", month=0)
            else:
                self.add(id="robots", area=A, status=PASS, title="robots.txt found and allows Googlebot",
                         evidence=[f"robots.txt status 200; sitemaps listed: {len(c.robots_sitemaps)}"], rule="robots.txt returns 200 and allows /")
        else:
            self.add(id="robots", area=A, status=WARN, title="No robots.txt found",
                     evidence=[f"robots.txt status {c.robots_status}"], rule="robots.txt should return 200",
                     ref="S9", action="Add a robots.txt that allows crawling and lists the sitemap.", priority="P3", month=1)

        found_maps = [s for s in c.sitemap_sources if s[1] == 200 and s[2]]
        if found_maps:
            self.add(id="sitemap", area=A, status=PASS, title=f"XML sitemap found ({len(c.sitemap_urls)} URLs on this domain)",
                     evidence=[f"{u} (status {st}, {n})" for u, st, n in found_maps][:10], rule="A valid sitemap.xml exists")
        else:
            self.add(id="sitemap", area=A, status=FAIL, title="No XML sitemap found",
                     evidence=[f"{u} -> status {st}" for u, st, n in c.sitemap_sources][:6],
                     rule="Checked robots.txt Sitemap lines, /sitemap.xml, /sitemap_index.xml, /wp-sitemap.xml",
                     ref="S9", action="Generate an XML sitemap, list it in robots.txt and submit it in Search Console.",
                     priority="P1", month=1)

        broken = [(u, p.status, p.error) for u, p in c.pages.items() if p.status >= 400 or (p.status == 0 and p.error)]
        if broken:
            ev = []
            for u, st, err in broken:
                src = sorted(self.inbound.get(u, []))[:3]
                ev.append(f"{u} -> {st or err[:60]} | linked from: {', '.join(src) or 'sitemap only'}")
            self.add(id="broken", area=A, status=FAIL, title=f"{len(broken)} broken internal URL(s)",
                     evidence=_ev(ev), rule="Internal URLs must return 200", ref="S7 / Checklist 7",
                     action="Fix or 301 redirect each broken URL and update the links pointing to it.",
                     priority="P1", month=1)
        else:
            self.add(id="broken", area=A, status=PASS, title="No broken internal URLs among crawled pages",
                     evidence=[f"{len(c.pages)} URLs fetched"], rule="Internal URLs must return 200")

        redirected = [f"{u} -> {p.final_url} ({', '.join(str(s) for s, _ in p.redirects)})"
                      for u, p in c.pages.items() if p.redirects and u != c.start_url]
        if redirected:
            self.add(id="redirects", area=A, status=WARN, title=f"{len(redirected)} internal link target(s) redirect",
                     evidence=_ev(redirected), rule="Internal links should point to the final URL (no redirect hops)",
                     ref="Checklist 7", action="Update internal links to point straight at the final URL.", priority="P3", month=2)

        noindex = [u for u, p in self.all_html.items() if "noindex" in p.meta_robots]
        if noindex:
            self.add(id="noindex", area=A, status=WARN, title=f"{len(noindex)} page(s) set to noindex",
                     evidence=_ev(noindex), rule="meta robots contains noindex",
                     detail="This can be intentional (thank-you pages, tags). Check that no money page is here.",
                     ref="S7", action="Remove noindex from any service, city or hub page in this list.", priority="P1", month=0)

        no_canon = [u for u, p in self.ok_pages.items() if not p.canonical]
        if no_canon:
            self.add(id="canonical_missing", area=A, status=WARN, title=f"{len(no_canon)} page(s) without a canonical tag",
                     evidence=_ev(no_canon), rule="Each indexable page has <link rel=canonical>",
                     ref="Checklist 2", action="Add a self-referencing canonical to every indexable page.", priority="P3", month=1)
        canon_else = [f"{u} -> canonical {p.canonical}" for u, p in self.ok_pages.items()
                      if p.canonical and p.canonical.rstrip("/") != (p.final_url or u).rstrip("/")]
        if canon_else:
            self.add(id="canonical_other", area=A, status=INFO, title=f"{len(canon_else)} page(s) canonicalise to another URL",
                     evidence=_ev(canon_else), rule="Canonical differs from the page URL",
                     detail="Fine for duplicates. A problem if a unique service or city page points elsewhere.")

        if self.c.sitemap_urls:
            orphans = [u for u in self.c.sitemap_urls if u in self.ok_pages and not self.inbound.get(u)
                       and u.rstrip("/") != (home.final_url or home.url).rstrip("/")]
            if orphans:
                self.add(id="orphans", area=A, status=WARN, title=f"{len(orphans)} sitemap page(s) with no internal links pointing to them",
                         evidence=_ev(orphans), rule="Page is in the sitemap but no crawled page links to it",
                         ref="S7 internal linking", action="Link each page from its hub, city page or a sibling.",
                         priority="P2", month=2)
        if c.hit_limit:
            self.add(id="crawl_limit", area=A, status=INFO, title=f"Crawl stopped at the page limit ({len(c.pages)} pages)",
                     rule="--max-pages", detail="Some checks only cover crawled pages. Re-run with a higher --max-pages for full coverage.")
        if c.skipped:
            blocked = [f"{u} ({r})" for u, r in c.skipped if "robots" in r]
            if blocked:
                self.add(id="robots_blocked", area=A, status=INFO, title=f"{len(blocked)} URL(s) skipped because robots.txt disallows them",
                         evidence=_ev(blocked), rule="robots.txt respected")

    # ------------------------------------------------------------ on-page
    def onpage_checks(self):
        A = "On-page"
        pages = self.ok_pages
        def offenders(fn):
            return [x for x in (fn(u, p) for u, p in pages.items()) if x]

        miss_t = offenders(lambda u, p: u if not p.title else None)
        long_t = offenders(lambda u, p: f"{u} | {len(p.title)} chars | {p.title}" if p.title and len(p.title) > config.TITLE_MAX else None)
        dup_t = self._dups({u: p.title for u, p in pages.items() if p.title})
        self._report(A, "title_missing", miss_t, "page(s) missing a title tag", "Every page has a <title>", "P1", 1,
                     "Write a unique title with the primary keyword + city.", "Checklist 3")
        self._report(A, "title_long", long_t, f"title(s) longer than {config.TITLE_MAX} characters",
                     f"Title under ~{config.TITLE_MAX} characters", "P3", 2, "Shorten so Google does not cut it.", "Checklist 3", fail_status=WARN)
        self._report(A, "title_dup", dup_t, "duplicate title(s)", "Titles are unique per page", "P2", 1,
                     "Give each page its own title matching its one keyword cluster.", "Checklist 3 / S8")

        miss_m = offenders(lambda u, p: u if not p.meta_description else None)
        bad_m = offenders(lambda u, p: f"{u} | {len(p.meta_description)} chars" if p.meta_description and not (config.META_MIN <= len(p.meta_description) <= config.META_MAX) else None)
        dup_m = self._dups({u: p.meta_description for u, p in pages.items() if p.meta_description})
        self._report(A, "meta_missing", miss_m, "page(s) missing a meta description", "Every page has a meta description",
                     "P2", 1, "Write 120-155 characters with the keyword, a benefit and a CTA.", "Checklist 3", fail_status=WARN)
        self._report(A, "meta_length", bad_m, f"meta description(s) outside {config.META_MIN}-{config.META_MAX} characters",
                     f"{config.META_MIN}-{config.META_MAX} characters", "P3", 2, "Rewrite to the target length.", "Checklist 3", fail_status=WARN)
        self._report(A, "meta_dup", dup_m, "duplicate meta description(s)", "Meta descriptions are unique", "P3", 2,
                     "Rewrite each to match its page.", "Checklist 3", fail_status=WARN)

        h1_bad = offenders(lambda u, p: f"{u} | {len(p.h1)} H1s {p.h1[:3]}" if len(p.h1) != 1 else None)
        dup_h1 = self._dups({u: p.h1[0] for u, p in pages.items() if len(p.h1) == 1})
        self._report(A, "h1", h1_bad, "page(s) without exactly one H1", "Exactly one H1 per page", "P2", 1,
                     "Use one H1 per page containing the service + city.", "Checklist 4")
        self._report(A, "h1_dup", dup_h1, "duplicate H1(s)", "H1s are unique", "P2", 2,
                     "Give each page a unique H1.", "Checklist 4", fail_status=WARN)

        long_u = offenders(lambda u, p: f"{u} ({len(u)} chars)" if len(u) > config.URL_MAX else None)
        ugly_u = offenders(lambda u, p: u if re.search(r"[A-Z_]", urlparse(u).path) else None)
        self._report(A, "url_length", long_u, f"URL(s) longer than {config.URL_MAX} characters", f"URL <= {config.URL_MAX} characters",
                     "P3", 3, "Use short keyword slugs for new pages. Only change live URLs with 301 redirects.", "Checklist 2", fail_status=WARN)
        self._report(A, "url_format", ugly_u, "URL(s) with uppercase letters or underscores", "lowercase, hyphens only",
                     "P3", 3, "Use lowercase hyphenated slugs for new pages.", "Checklist 2", fail_status=WARN)

        thin = offenders(lambda u, p: f"{u} | {p.word_count} words" if p.word_count < config.THIN_WORDS else None)
        self._report(A, "thin", thin, f"page(s) under {config.THIN_WORDS} words", f"Visible word count >= {config.THIN_WORDS} (includes menus and footer)",
                     "P2", 2, "Expand money pages using the service page template (Section 9). Contact/legal pages can stay short.",
                     "S9 / S10", fail_status=WARN)

        alt_pages = {u: p.images_missing_alt for u, p in pages.items() if p.images_missing_alt}
        total_imgs = sum(p.images_total for p in pages.values())
        total_missing = sum(len(v) for v in alt_pages.values())
        if total_missing:
            self.add(id="alt", area=A, status=WARN, title=f"{total_missing} of {total_imgs} images have no alt text",
                     evidence=_ev(f"{u} | {len(v)} missing, e.g. {v[0]}" for u, v in alt_pages.items()),
                     rule="Every meaningful <img> has alt text", ref="Checklist 9",
                     action="Add descriptive alt text (job + material + city where natural).", priority="P3", month=2)
        elif total_imgs:
            self.add(id="alt", area=A, status=PASS, title=f"All {total_imgs} images have alt text", rule="Every <img> has alt text")

        few = offenders(lambda u, p: f"{u} | {len(p.internal_links)} internal links" if len(p.internal_links) < config.MIN_INTERNAL_LINKS_OUT else None)
        self._report(A, "links_out", few, f"page(s) with fewer than {config.MIN_INTERNAL_LINKS_OUT} internal links",
                     f">= {config.MIN_INTERNAL_LINKS_OUT} internal links per page", "P3", 2,
                     "Add hub, sibling and city links (reverse silo).", "Checklist 7", fail_status=WARN)

        no_vp = offenders(lambda u, p: u if not p.viewport else None)
        self._report(A, "viewport", no_vp, "page(s) without a mobile viewport tag", "<meta name=viewport> present",
                     "P1", 1, "Add a responsive viewport tag; most roofing searches are on phones.", "S13")

    def _dups(self, mapping):
        cnt = Counter(v.strip().lower() for v in mapping.values())
        groups = defaultdict(list)
        for u, v in mapping.items():
            if cnt[v.strip().lower()] > 1:
                groups[v.strip()].append(u)
        return [f'"{k[:90]}" used on {len(us)} pages: {", ".join(us[:4])}' for k, us in groups.items()]

    def _report(self, area, fid, offenders, label, rule, prio, month, action, ref, fail_status=FAIL):
        if offenders:
            self.add(id=fid, area=area, status=fail_status, title=f"{len(offenders)} {label}",
                     evidence=_ev(offenders), rule=rule, ref=ref, action=action, priority=prio, month=month)
        else:
            self.add(id=fid, area=area, status=PASS, title=f"No {label.replace('page(s) ', 'pages ').replace('(s)', 's')}",
                     rule=rule, evidence=[f"{len(self.ok_pages)} indexable pages checked"])

    # ------------------------------------------------- structure / silos
    def _match(self, patterns):
        hits = []
        for u, p in self.ok_pages.items():
            path = path_of(u)
            for pat in patterns:
                if pat in path:
                    hits.append((u, f"URL contains '{pat}'"))
                    break
            else:
                h1 = (p.h1[0] if p.h1 else "").lower()
                for pat in patterns:
                    if len(pat) > 4 and pat.replace("-", " ") in h1:
                        hits.append((u, f"H1 contains '{pat.replace('-', ' ')}'"))
                        break
        return hits

    def structure_checks(self):
        A = "Site structure (silos)"
        missing_core, found_core = [], []
        for key, label, silo, core, pats, suggest in config.EXPECTED_PAGES:
            hits = self._match(pats)
            row = {"key": key, "label": label, "silo": silo, "core": core,
                   "found": [h[0] for h in hits[:5]], "matched_by": hits[0][1] if hits else "",
                   "suggested_url": suggest}
            row["status"] = "found" if hits else ("missing_core" if core else "not_found_optional")
            self.silo_coverage.append(row)
            (found_core if hits and core else missing_core if core else []).append(row)
        if missing_core:
            self.add(id="silo_missing", area=A, status=FAIL,
                     title=f"{len(missing_core)} core page(s) from the master plan not found",
                     evidence=[f"{r['label']} ({r['silo']}) -> build at {r['suggested_url']}" for r in missing_core],
                     rule=f"No crawled URL or H1 matched the page patterns (crawled {len(self.ok_pages)} indexable pages)",
                     detail="Check the list against the client's real services before building. Only build what they offer.",
                     ref="S7 / S14", action="Add these pages in the order of the roadmap (hubs Month 1, spokes Month 2).",
                     priority="P1", month=1)
        if found_core:
            self.add(id="silo_found", area=A, status=PASS, title=f"{len(found_core)} core page(s) already exist",
                     evidence=[f"{r['label']}: {r['found'][0]} ({r['matched_by']})" for r in found_core],
                     rule="URL or H1 pattern match", detail="Matches are pattern based. Open each URL to confirm it is a real, full page.")
        opt = [r for r in self.silo_coverage if r["status"] == "not_found_optional"]
        if opt:
            self.add(id="silo_optional", area=A, status=INFO, title=f"{len(opt)} optional service page(s) not found",
                     evidence=[f"{r['label']} -> {r['suggested_url']}" for r in opt],
                     rule="Optional in the master plan", detail="Build only if the client confirms they offer the service.")

    # ------------------------------------------------------------- cities
    def city_checks(self):
        A = "City & location pages"
        loc_re = re.compile(r"-(" + "|".join(s.lower() for s in config.US_STATES) + r")(?:/|$)|/(?:service-areas?|locations?|areas?-we-serve|areas?)/[^/]+")
        auto = [u for u in self.ok_pages if loc_re.search(path_of(u))]
        self.site_facts["location_like_urls"] = auto
        if not self.cities:
            self.add(id="cities", area=A, status=NOT_CHECKED, title="Target cities not given, so city coverage was not checked",
                     evidence=_ev(auto) if auto else ["No location-style URLs detected"],
                     detail="Evidence lists URLs that look like location pages by URL pattern only.",
                     rule='Run with --cities "Frisco, TX; Plano, TX"', ref="S7")
            return
        missing, combos_missing = [], []
        for city in self.cities:
            name = city.split(",")[0].strip()
            cslug = slugify(name)
            pages = [u for u, p in self.ok_pages.items()
                     if cslug in path_of(u) or any(name.lower() in h.lower() for h in p.h1)]
            mentions = [u for u, p in self.ok_pages.items() if re.search(r"\b" + re.escape(name) + r"\b", p.text, re.I)]
            combos = {}
            for sslug, slabel in config.COMBO_SERVICES:
                key = sslug.split("-")[1] if sslug.startswith("roof-") else "storm"
                hit = [u for u in pages if key in path_of(u)]
                combos[slabel] = hit[0] if hit else ""
                if not hit:
                    st = city.split(",")[1].strip().lower() if "," in city else ""
                    combos_missing.append(f"{slabel} in {city} -> /{sslug}-{cslug}{'-' + st if st else ''}/")
            row = {"city": city, "pages": pages[:5], "mention_pages": len(mentions), "combos": combos}
            self.city_coverage.append(row)
            if not pages:
                st = city.split(",")[1].strip().lower() if "," in city else ""
                missing.append(f"{city}: no dedicated page (mentioned on {len(mentions)} page(s)) -> build /roofer-{cslug}{'-' + st if st else ''}/")
        if missing:
            self.add(id="city_pages", area=A, status=FAIL, title=f"{len(missing)} of {len(self.cities)} target cities have no dedicated page",
                     evidence=missing, rule="A page whose URL or H1 contains the city name",
                     ref="S7 / S9 city template", action="Write one fresh city page per city using the city template. No copy-paste pages.",
                     priority="P1", month=3)
        else:
            self.add(id="city_pages", area=A, status=PASS, title=f"All {len(self.cities)} target cities have a page",
                     evidence=[f"{r['city']}: {r['pages'][0]}" for r in self.city_coverage],
                     rule="A page whose URL or H1 contains the city name")
        if combos_missing:
            self.add(id="combo_pages", area=A, status=WARN, title=f"{len(combos_missing)} Service x City combo page(s) not found",
                     evidence=_ev(combos_missing), rule="URL or H1 has both the city and the service",
                     detail="Build combos only for the top cities and top 2-3 services, and only with genuinely local content.",
                     ref="S7 combo rule", action="Add combos for the top cities during Months 3-4.", priority="P2", month=3)

    # ----------------------------------------------------- local / NAP
    def local_checks(self):
        A = "Local signals & NAP"
        home = self.c.home
        phone_pages = defaultdict(set)
        for u, p in self.all_html.items():
            for n in p.phones_in_text:
                phone_pages[n].add(u)
            for t in p.tel_links:
                d = re.sub(r"\D", "", t)[-10:]
                if len(d) == 10:
                    phone_pages[norm_phone(d[:3], d[3:6], d[6:])].add(u)
        self.phone_map = {k: sorted(v) for k, v in sorted(phone_pages.items(), key=lambda kv: -len(kv[1]))}
        n_pages = len(self.all_html) or 1
        if not phone_pages:
            self.add(id="phone", area=A, status=FAIL, title="No US phone number found on the site",
                     rule="Phone in text or tel: link", ref="S6 / S16", action="Show one consistent phone number in the header and footer of every page.",
                     priority="P1", month=1)
        elif len(phone_pages) == 1:
            n, us = next(iter(self.phone_map.items()))
            self.add(id="phone", area=A, status=PASS, title=f"One phone number used across the site: {n}",
                     evidence=[f"{n} on {len(us)} of {n_pages} pages"], rule="Single consistent phone number")
        else:
            self.add(id="phone", area=A, status=WARN, title=f"{len(phone_pages)} different phone numbers found",
                     evidence=[f"{n} on {len(us)} page(s), e.g. {us[0]}" for n, us in self.phone_map.items()][:15],
                     detail="Some may be call tracking numbers or unrelated numbers in text. Confirm which one matches GBP.",
                     rule="One primary phone number site-wide (NAP)", ref="S6 / S13",
                     action="Keep one primary number (the GBP number) in header, footer and schema.", priority="P2", month=1)

        if home.tel_links:
            self.add(id="click_to_call", area=A, status=PASS, title="Homepage has a click-to-call link",
                     evidence=home.tel_links[:3], rule='<a href="tel:..."> on homepage')
        else:
            self.add(id="click_to_call", area=A, status=FAIL, title="Homepage has no click-to-call link",
                     rule='<a href="tel:..."> on homepage', ref="S13",
                     action="Add a tap-to-call button in the header, sticky on mobile.", priority="P1", month=1)
        tel_cov = sum(1 for p in self.all_html.values() if p.tel_links)
        self.site_facts["tel_coverage"] = f"{tel_cov} of {len(self.all_html)} pages"

        addr_ev = []
        for u, p in self.all_html.items():
            for b in p.schema_blocks:
                a = b.get("address")
                if isinstance(a, dict) and a.get("streetAddress"):
                    addr_ev.append(f"schema on {u}: {a.get('streetAddress')}, {a.get('addressLocality','')} {a.get('addressRegion','')} {a.get('postalCode','')}")
                    break
            if addr_ev:
                break
        if home.state_zip_mentions:
            addr_ev.append(f"homepage text mentions: {', '.join(home.state_zip_mentions[:3])}")
        self.add(id="address", area=A, status=PASS if addr_ev else WARN,
                 title="Business address / ZIP visible" if addr_ev else "No street address or STATE+ZIP found on the homepage or in schema",
                 evidence=addr_ev, rule="Street address in LocalBusiness schema or STATE ZIP in homepage text",
                 detail="" if addr_ev else "Correct if the client is a hidden service area business. If they have a real office, show it.",
                 ref="S6 setup step 4", action="" if addr_ev else "Confirm office status with the client, then show the address in the footer and schema if real.",
                 priority="" if addr_ev else "P2", month=1)

        maps = [u for u, p in self.all_html.items() if p.map_embed]
        self.add(id="map_embed", area=A, status=PASS if maps else WARN,
                 title=f"Google Map embedded on {len(maps)} page(s)" if maps else "No embedded Google Map found",
                 evidence=_ev(maps), rule="iframe with google.com/maps", ref="Checklist 10",
                 action="" if maps else "Embed the GBP map on the contact page and city hub.", priority="" if maps else "P3", month=2)

        gbp_links, social = set(), defaultdict(set)
        patterns = {"Google Business Profile": r"(google\.[a-z.]+/maps|maps\.app\.goo\.gl|g\.page|goo\.gl/maps|business\.google|search\.google\.com/local)",
                    "Facebook": r"facebook\.com", "Instagram": r"instagram\.com", "YouTube": r"youtube\.com|youtu\.be",
                    "LinkedIn": r"linkedin\.com", "Yelp": r"yelp\.com", "BBB": r"bbb\.org", "Angi": r"angi\.com|angieslist",
                    "HomeAdvisor": r"homeadvisor\.com", "Houzz": r"houzz\.com", "Nextdoor": r"nextdoor\.com",
                    "X / Twitter": r"twitter\.com|//x\.com", "Pinterest": r"pinterest\.", "TikTok": r"tiktok\.com"}
        for p in self.all_html.values():
            for l in p.external_links:
                for name, pat in patterns.items():
                    if re.search(pat, l["url"], re.I):
                        social[name].add(l["url"])
        gbp = social.pop("Google Business Profile", set())
        self.add(id="gbp_link", area=A, status=PASS if gbp else WARN,
                 title="Website links to the Google Business Profile" if gbp else "No link to a Google Business Profile found",
                 evidence=sorted(gbp)[:5], rule="External link to google maps / g.page / maps.app.goo.gl",
                 ref="Checklist 10", action="" if gbp else "Link to the GBP (reviews link) from the footer and reviews page.",
                 priority="" if gbp else "P3", month=1)
        self.site_facts["profiles_linked"] = {k: sorted(v)[:3] for k, v in social.items()}
        self.add(id="profiles", area=A, status=PASS if social else WARN,
                 title=f"Links to {len(social)} social / directory profile(s)" if social else "No social or directory profile links found",
                 evidence=[f"{k}: {sorted(v)[0]}" for k, v in social.items()], rule="External links to known profiles",
                 ref="S11", action="" if social else "Link the real profiles (Facebook, BBB, Yelp, Nextdoor) and add them to schema sameAs.",
                 priority="" if social else "P3", month=2)

    # ------------------------------------------------------------- schema
    def schema_checks(self):
        A = "Schema"
        home = self.c.home
        lb_pages, lb_block = [], None
        for u, p in self.all_html.items():
            for b in p.schema_blocks:
                types = b.get("@type") if isinstance(b.get("@type"), list) else [b.get("@type")]
                if any(t in config.LOCAL_BUSINESS_TYPES for t in types if t):
                    lb_pages.append(u)
                    if lb_block is None or u == (home.url):
                        lb_block = (u, b, types)
                    break
        if not lb_block:
            self.add(id="lb_schema", area=A, status=FAIL, title="No LocalBusiness / RoofingContractor schema found",
                     evidence=[f"Schema types on homepage: {', '.join(home.schema_types) or 'none'}"],
                     rule=f"JSON-LD @type in {sorted(config.LOCAL_BUSINESS_TYPES)}", ref="S9",
                     action="Add RoofingContractor JSON-LD sitewide with name, address, telephone, url, areaServed, geo, hours, sameAs.",
                     priority="P1", month=1)
        else:
            u, b, types = lb_block
            missing = [label for key, label in config.LOCAL_BUSINESS_FIELDS
                       if not b.get(key) and not (key == "openingHoursSpecification" and b.get("openingHours"))]
            self.add(id="lb_schema", area=A, status=PASS if not missing else WARN,
                     title=f"{'/'.join(t for t in types if t)} schema found on {len(lb_pages)} page(s)" + (f", missing {len(missing)} field(s)" if missing else ""),
                     evidence=[f"Example: {u}"] + ([f"Missing: {', '.join(missing)}"] if missing else []),
                     rule="LocalBusiness fields: " + ", ".join(l for _, l in config.LOCAL_BUSINESS_FIELDS), ref="S9",
                     action=f"Add the missing fields: {', '.join(missing)}." if missing else "", priority="P2" if missing else "", month=1)
            if "RoofingContractor" not in types:
                self.add(id="lb_type", area=A, status=INFO, title=f"Schema type is {'/'.join(t for t in types if t)}, not RoofingContractor",
                         rule="Most specific schema.org type", action="Use @type RoofingContractor (a LocalBusiness subtype).", ref="S9")
            if b.get("aggregateRating"):
                self.add(id="self_reviews", area=A, status=WARN, title="aggregateRating is marked up on the business's own LocalBusiness schema",
                         evidence=[u], rule="Google policy: self-serving reviews on LocalBusiness/Organization are not eligible for review rich results",
                         ref="S16", action="Remove it or make sure it is not relied on for stars in search.", priority="P3", month=2)
            tel = b.get("telephone")
            if tel and self.phone_map:
                d = re.sub(r"\D", "", str(tel))[-10:]
                if len(d) == 10 and norm_phone(d[:3], d[3:6], d[6:]) not in self.phone_map:
                    self.add(id="schema_phone", area=A, status=WARN, title="Schema telephone does not appear in the page text",
                             evidence=[f"schema: {tel}", f"site numbers: {', '.join(list(self.phone_map)[:4])}"],
                             rule="Schema telephone = visible phone (NAP)", ref="S6", action="Make schema and visible phone identical.",
                             priority="P2", month=1)
            self.site_facts["schema_name"] = b.get("name", "")
        errs = [f"{u}: {e}" for u, p in self.all_html.items() for e in p.schema_errors]
        if errs:
            self.add(id="schema_errors", area=A, status=FAIL, title=f"{len(errs)} invalid JSON-LD block(s)", evidence=_ev(errs),
                     rule="JSON-LD must parse", ref="S9", action="Fix the JSON syntax; Google ignores broken blocks.", priority="P2", month=1)
        all_types = Counter(t for p in self.all_html.values() for t in p.schema_types)
        self.site_facts["schema_types"] = dict(all_types.most_common())
        faq = [u for u, p in self.all_html.items() if "FAQPage" in p.schema_types]
        self.add(id="faq_schema", area=A, status=PASS if faq else WARN,
                 title=f"FAQPage schema on {len(faq)} page(s)" if faq else "No FAQPage schema found",
                 evidence=_ev(faq), rule="JSON-LD @type FAQPage",
                 detail="Since Aug 2023 Google shows FAQ rich results mainly for authoritative government and health sites; the markup still helps machines read Q&A.",
                 ref="S9 / S12", action="" if faq else "Add FAQ blocks with FAQPage schema to service and city pages.",
                 priority="" if faq else "P3", month=2)
        bc = [u for u, p in self.all_html.items() if "BreadcrumbList" in p.schema_types]
        self.add(id="breadcrumbs", area=A, status=PASS if bc else WARN,
                 title=f"BreadcrumbList schema on {len(bc)} page(s)" if bc else "No BreadcrumbList schema found",
                 rule="JSON-LD @type BreadcrumbList", ref="S9",
                 action="" if bc else "Add breadcrumbs (Home > Silo > Page) with schema.", priority="" if bc else "P3", month=2)
        svc = [u for u, p in self.all_html.items() if "Service" in p.schema_types]
        self.add(id="service_schema", area=A, status=PASS if svc else INFO,
                 title=f"Service schema on {len(svc)} page(s)" if svc else "No Service schema found",
                 rule="JSON-LD @type Service", ref="S9", action="" if svc else "Add Service schema to each service page.",
                 month=2)

    # ------------------------------------------------------- trust / EEAT
    def trust_checks(self):
        A = "Trust & E-E-A-T"
        ordered = sorted(self.all_html.items(), key=lambda kv: (kv[0].rstrip("/") != (self.c.home.final_url or self.c.home.url).rstrip("/"), kv[0]))
        def find(pattern, flags=re.I):
            rx = re.compile(pattern, flags)
            ev, pages = [], 0
            for u, p in ordered:
                m = rx.search(p.text)
                if m:
                    pages += 1
                    if len(ev) < 3:
                        ev.append(f"{u}: \"{snippet(p.text, m)}\"")
            return pages, ev
        for key, label, pat in config.TRUST_SIGNALS:
            n, ev = find(pat)
            self.add(id=f"trust_{key}", area=A, status=PASS if n else WARN,
                     title=f"{label} (on {n} page(s))" if n else f"Not found: {label}",
                     evidence=ev, rule=f"regex: {pat}", ref="S9 trust strip / S10",
                     detail="Shows what the site itself claims. Verify each claim is true." if n else "Add only if true. CONFIRM with the client first.",
                     action="" if n else f"If the client can prove it, add it to the trust strip and relevant pages.",
                     priority="" if n else "P2", month=1)
        brands = []
        for name, pat in config.MANUFACTURERS:
            n, ev = find(pat, 0)
            if n:
                brands.append(f"{name} on {n} page(s) | {ev[0]}")
        certs = []
        for pat in config.CERT_PHRASES:
            n, ev = find(pat)
            if n:
                certs.append(ev[0])
        self.site_facts["manufacturers"] = brands
        self.add(id="manufacturers", area=A, status=PASS if brands else WARN,
                 title=f"{len(brands)} roofing manufacturer brand(s) mentioned" if brands else "No roofing manufacturer brands mentioned",
                 evidence=brands + certs[:5], rule="Brand names: " + ", ".join(n for n, _ in config.MANUFACTURERS), ref="S10 entity bank",
                 detail="Entity signal. Only name brands they install and certifications they can prove.",
                 action="" if brands else "Name the shingle and metal systems they install (entities) on service pages.",
                 priority="" if brands else "P2", month=2)

    # --------------------------------------------------------- conversion
    def conversion_checks(self):
        A = "Conversion"
        home = self.c.home
        self.add(id="home_form", area=A, status=PASS if home.forms else WARN,
                 title="Homepage has a form" if home.forms else "No form on the homepage",
                 rule="<form> on homepage", ref="S9 block 3 / S13",
                 detail="" if home.forms else "Some form builders load by JavaScript and are not visible to this crawler. Check in a browser.",
                 action="" if home.forms else "Add a short quote bar near the top (name, phone, ZIP, service).", priority="" if home.forms else "P2", month=1)
        svc_pages = set(u for r in self.silo_coverage if r["status"] == "found" and r["silo"] not in ("About", "Foundation", "Content") for u in r["found"])
        no_form = [u for u in svc_pages if u in self.all_html and not self.all_html[u].forms]
        no_tel = [u for u in svc_pages if u in self.all_html and not self.all_html[u].tel_links]
        if svc_pages:
            self.add(id="svc_cta", area=A, status=WARN if (no_form or no_tel) else PASS,
                     title=f"Service pages: {len(no_form)} without a form, {len(no_tel)} without click-to-call (of {len(svc_pages)})",
                     evidence=_ev([f"no form: {u}" for u in no_form] + [f"no tel link: {u}" for u in no_tel]),
                     rule="Each service page has a form and a tel: link", ref="S9 / S13",
                     action="Add the quote form and call button to every service page." if (no_form or no_tel) else "",
                     priority="P2" if (no_form or no_tel) else "", month=2)

    # -------------------------------------------------------------- speed
    def speed_checks(self):
        A = "Speed (PageSpeed Insights)"
        if not self.psi:
            self.add(id="psi", area=A, status=NOT_CHECKED, title="PageSpeed not run", rule="Run without --no-psi")
            return
        for strat, d in self.psi.items():
            if not d.get("ok"):
                self.add(id=f"psi_{strat}", area=A, status=NOT_CHECKED, title=f"PageSpeed ({strat}) failed",
                         evidence=[d.get("error", "")], rule="PageSpeed Insights API v5")
                continue
            perf = d["scores"].get("performance")
            st = PASS if perf is not None and perf >= 90 else WARN if perf is not None and perf >= 50 else FAIL
            ev = [f"Scores: " + ", ".join(f"{k} {v}" for k, v in d["scores"].items())]
            ev += [f"{k}: {v}" for k, v in d["lab"].items() if v]
            if d.get("field"):
                ev += [f"{k}: {v['value']} ({v['category']}, {d.get('field_scope','')})" for k, v in d["field"].items()]
            else:
                ev.append("No real-user (CrUX) data from Google for this site")
            self.add(id=f"psi_{strat}", area=A, status=st, title=f"{strat.title()} performance score {perf}",
                     evidence=ev, rule="Lighthouse bands: 90+ good, 50-89 needs work, <50 poor", ref="S9 / S13",
                     action="" if st == PASS else "Compress images, lazy-load below the fold, cut unused scripts and plugins.",
                     priority="" if st == PASS else ("P1" if st == FAIL and strat == "mobile" else "P2"), month=1)

    # ---------------------------------------------------------------- GBP
    def gbp_checks(self):
        A = "Google Business Profile (Places API)"
        if not self.pl:
            self.add(id="gbp", area=A, status=NOT_CHECKED, title="GBP not checked (no Places API key)",
                     rule="Set GOOGLE_PLACES_API_KEY in .env", ref="S6",
                     detail="Use the GBP Audit sheet manually, or add a key to pull categories, rating, reviews and NAP automatically.")
            return
        client = self.pl.get("client")
        if not client:
            self.add(id="gbp", area=A, status=WARN, title="No Google place found that links to this website",
                     evidence=self.pl.get("client_notes", []),
                     rule="A Places result whose website = this domain (or --place-id)", ref="S6",
                     detail="The GBP may link to another URL, be unverified, or not exist. Re-run with --place-id to be sure.",
                     action="Find the client's GBP, confirm ownership and link it to the website.", priority="P1", month=0)
        else:
            ev = [f"Name: {client['name']}", f"Primary type: {client['primary_category']} ({client['primary_type']})",
                  f"Rating: {client['rating']} from {client['reviews']} reviews", f"Phone: {client['phone']}",
                  f"Address: {client['address']}", f"Website: {client['website']}", f"Status: {client['status']}",
                  f"Maps: {client['maps_url']}"] + [f"Matched by: {self.pl.get('client_match', '')}"]
            self.add(id="gbp", area=A, status=INFO, title=f"GBP found: {client['name']}", evidence=ev,
                     rule="Google Places API (New) data")
            pt = client["primary_type"]
            self.add(id="gbp_category", area=A, status=PASS if pt == "roofing_contractor" else WARN,
                     title=f"Primary type is {client['primary_category'] or pt or 'not returned'}",
                     evidence=[f"primaryType = {pt}", f"types = {', '.join(client['types'])}"],
                     rule="Primary type should be roofing_contractor",
                     detail="Places API types are close to, but not identical to, GBP category names. Confirm in the GBP editor.",
                     ref="S6 setup step 1", action="" if pt == "roofing_contractor" else "Set the primary GBP category to Roofing contractor.",
                     priority="" if pt == "roofing_contractor" else "P1", month=1)
            if client["website"]:
                ok = same_site(client["website"], self.c.home.final_url or self.c.home.url)
                self.add(id="gbp_website", area=A, status=PASS if ok else FAIL,
                         title="GBP website link points to this site" if ok else "GBP website link points to a different domain",
                         evidence=[client["website"]], rule="GBP website domain = audited domain", ref="S6 step 7",
                         action="" if ok else "Update the GBP website link.", priority="" if ok else "P1", month=0)
            if client["phone"]:
                d = re.sub(r"\D", "", client["phone"])[-10:]
                pn = norm_phone(d[:3], d[3:6], d[6:]) if len(d) == 10 else client["phone"]
                on_site = pn in self.phone_map
                self.add(id="gbp_phone", area=A, status=PASS if on_site else FAIL,
                         title=f"GBP phone {pn} {'is' if on_site else 'is NOT'} shown on the website",
                         evidence=[f"Pages with it: {len(self.phone_map.get(pn, []))}"] + [f"Site numbers: {', '.join(list(self.phone_map)[:5])}"],
                         rule="GBP phone appears on the website (NAP)", ref="S6 / S13",
                         action="" if on_site else "Show the GBP phone (or set the tracking number as primary on GBP).",
                         priority="" if on_site else "P1", month=0)
            site_name = self.site_facts.get("schema_name") or self.c.home.og_site_name
            if site_name:
                same = site_name.strip().lower() == client["name"].strip().lower()
                self.add(id="gbp_name", area=A, status=PASS if same else WARN,
                         title="GBP name matches the website name" if same else "GBP name and website name differ",
                         evidence=[f"GBP: {client['name']}", f"Website (schema / og:site_name): {site_name}"],
                         rule="Exact same business name everywhere", ref="S6 step 3 / GBP audit sheet",
                         action="" if same else "Use the exact GBP name in the logo text, footer and schema (unless GBP is keyword-stuffed: then fix GBP).",
                         priority="" if same else "P2", month=1)
            if not client["hours"]:
                self.add(id="gbp_hours", area=A, status=WARN, title="No regular hours returned for the GBP",
                         rule="regularOpeningHours present", ref="S6 step 7", action="Add business hours in GBP.", priority="P2", month=1)
            if client["status"] and client["status"] != "OPERATIONAL":
                self.add(id="gbp_status", area=A, status=FAIL, title=f"GBP status is {client['status']}", rule="businessStatus = OPERATIONAL",
                         ref="S6", action="Fix the profile status in GBP.", priority="P1", month=0)

        for comp in self.pl.get("competitors", []):
            city, res = comp["city"], comp["data"]
            if not res.get("ok"):
                self.add(id=f"comp_{slugify(city)}", area="Competitors (Places API)", status=NOT_CHECKED,
                         title=f"Competitor search failed for {city}", evidence=[res.get("error", "")], rule=res.get("query", ""))
                continue
            rows = res["results"]
            pos = None
            for i, r in enumerate(rows, 1):
                if (client and r["place_id"] == client["place_id"]) or same_site(r["website"], self.c.home.final_url or self.c.home.url):
                    pos = i
                    break
            others = [r for i, r in enumerate(rows, 1) if i != pos]
            for i, r in enumerate(rows, 1):
                r["is_client"] = (i == pos)
            top3 = [r for r in others[:3] if r.get("reviews") is not None]
            counts = [r["reviews"] for r in others if r.get("reviews") is not None]
            row = {"city": city, "query": res["query"], "client_position": pos, "results": rows,
                   "top3_avg_reviews": round(sum(r["reviews"] for r in top3) / len(top3)) if top3 else None,
                   "median_reviews": round(statistics.median(counts)) if counts else None}
            self.competitors.append(row)
            ev = [f"#{i} {r['name']} | {r['rating']}* | {r['reviews']} reviews | {r['primary_category']}" for i, r in enumerate(rows[:5], 1)]
            mine = client["reviews"] if client else None
            gap = (row["top3_avg_reviews"] - mine) if (mine is not None and row["top3_avg_reviews"] is not None) else None
            st = INFO if pos is None else (PASS if pos <= 3 else WARN)
            self.add(id=f"comp_{slugify(city)}", area="Competitors (Places API)", status=st,
                     title=f"{city}: client is #{pos} in Places results" if pos else f"{city}: client not in the top {len(rows)} Places results",
                     evidence=ev + ([f"Top-3 competitors' average reviews: {row['top3_avg_reviews']} | client: {mine} | gap: {gap}"] if gap is not None else []),
                     rule=f'Places Text Search "{res["query"]}". NOT the live map pack from a location; confirm with a rank grid.',
                     ref="S6 reviews / S11", action=(f"Close the review gap of {gap} with a weekly review engine." if gap and gap > 0 else ""),
                     priority="P2" if gap and gap > 0 else "", month=1)

    # ------------------------------------------------------- not verified
    def not_verified(self):
        A = "Needs manual check"
        items = [
            ("rank_grid", "True map pack positions across the city", "Rank grid tool (Local Falcon / BrightLocal), 7x7 grid, 5 core terms", "S5"),
            ("keywords", "Keyword volumes and difficulty", "Semrush Keyword Magic + Keyword Gap vs top 3 map competitors", "S8"),
            ("backlinks", "Backlinks and referring domains", "Semrush / Ahrefs backlink report", "S11"),
            ("citations", "Citation consistency on directories (Yelp, BBB, Angi, Apple, Bing...)", "Citation scan tool or manual search of the exact NAP", "S11"),
            ("gbp_detail", "GBP secondary categories, services list, posts, photo freshness", "GBP manager access + your GBP Audit sheet (not exposed by the Places API)", "S6"),
            ("review_velocity", "Review velocity over time (client vs competitors)", "Monthly snapshots of review counts (re-run this tool each month)", "S6 / S11"),
            ("spam", "Fake or keyword-stuffed listings in the map pack", "Manual check of the map pack, then Redressal Complaint Form", "S6"),
            ("ai_answers", "Whether AI tools name the client", "Ask ChatGPT, Gemini, AI Mode 'best roofer in [city]' and log results", "S12"),
            ("tracking", "Call tracking, GA4 and Search Console setup", "Account access during onboarding", "S13"),
            ("claims", "Truth of license, insurance, warranty and certification claims", "Proof from the client (CONFIRM system)", "S5 / S16"),
        ]
        for fid, what, how, ref in items:
            self.add(id=f"nv_{fid}", area=A, status=NOT_CHECKED, title=what, rule=how, ref=ref,
                     detail="This tool does not have access to this data, so it reports nothing here instead of guessing.")
