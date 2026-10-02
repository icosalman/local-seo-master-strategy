import re
from collections import deque
from dataclasses import dataclass, field
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import config
from .extract import parse_page, Page
from .fetcher import Fetcher, normalize_url, bare_host


@dataclass
class CrawlResult:
    start_url: str
    site_host: str
    home: Page = None
    pages: dict = field(default_factory=dict)          # url -> Page (HTML pages fetched)
    robots_status: int = 0
    robots_text: str = ""
    robots_sitemaps: list = field(default_factory=list)
    sitemap_sources: list = field(default_factory=list)  # [(url, status, count)]
    sitemap_urls: list = field(default_factory=list)
    skipped: list = field(default_factory=list)        # [(url, reason)]
    http_variants: dict = field(default_factory=dict)  # variant -> (status, final_url)
    hit_limit: bool = False
    requests: int = 0


def _parse_sitemap(xml_text):
    soup = BeautifulSoup(xml_text, "xml")
    if soup.find("sitemapindex"):
        return "index", [l.get_text(strip=True) for l in soup.find_all("loc")]
    return "urlset", [l.get_text(strip=True) for l in soup.find_all("loc")]


def _is_html_candidate(url):
    path = urlparse(url).path.lower()
    return not path.endswith(config.SKIP_EXTENSIONS)


def crawl(start_url: str, max_pages: int = config.DEFAULT_MAX_PAGES,
          respect_robots: bool = True, log=print) -> CrawlResult:
    f = Fetcher(respect_robots=respect_robots)
    start_url = normalize_url(start_url if "://" in start_url else "https://" + start_url)
    first = f.get(start_url, check_robots=False)
    if first.error and not first.status:
        raise SystemExit(f"Could not reach {start_url}: {first.error}")
    home_url = normalize_url(first.final_url or start_url)
    site_host = bare_host(urlparse(home_url).netloc)
    res = CrawlResult(start_url=start_url, site_host=site_host)
    origin = f"{urlparse(home_url).scheme}://{urlparse(home_url).netloc}"

    # robots.txt
    rp, raw = f.robots_for(home_url)
    res.robots_status = raw.status
    res.robots_text = raw.text[:5000] if raw.status == 200 else ""
    if raw.status == 200:
        res.robots_sitemaps = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", raw.text)

    # http / https / www variants (only checks where they end up)
    host = urlparse(home_url).netloc
    alt_host = host[4:] if host.startswith("www.") else "www." + host
    for v in (f"http://{host}/", f"https://{alt_host}/", f"http://{alt_host}/"):
        r = f.get(v, check_robots=False)
        res.http_variants[v] = (r.status, r.final_url, r.error)

    # sitemaps
    candidates = list(dict.fromkeys(res.robots_sitemaps + [
        origin + "/sitemap.xml", origin + "/sitemap_index.xml", origin + "/wp-sitemap.xml"]))
    seen_maps = set()
    queue = deque(candidates)
    while queue and len(res.sitemap_urls) < config.MAX_SITEMAP_URLS and len(seen_maps) < 60:
        sm = queue.popleft()
        if sm in seen_maps:
            continue
        seen_maps.add(sm)
        r = f.get(sm, check_robots=False)
        if r.status != 200 or "<" not in (r.text or ""):
            res.sitemap_sources.append((sm, r.status, 0))
            continue
        kind, locs = _parse_sitemap(r.text)
        if kind == "index":
            res.sitemap_sources.append((sm, r.status, f"index of {len(locs)} sitemaps"))
            queue.extend(locs)
        else:
            res.sitemap_sources.append((sm, r.status, len(locs)))
            for loc in locs:
                u = normalize_url(loc)
                if bare_host(urlparse(u).netloc) == site_host and u not in res.sitemap_urls:
                    res.sitemap_urls.append(u)

    # BFS crawl: homepage first, then links, then sitemap URLs not reached by links
    home = parse_page(first, site_host)
    res.home = home
    res.pages[home_url] = home
    seen = {home_url, start_url}
    frontier = deque()

    def enqueue(u):
        if u in seen:
            return
        if bare_host(urlparse(u).netloc) != site_host or not _is_html_candidate(u):
            return
        seen.add(u)
        frontier.append(u)

    for l in home.internal_links:
        enqueue(l["url"])
    for u in res.sitemap_urls:
        enqueue(u)

    while frontier:
        if len(res.pages) >= max_pages:
            res.hit_limit = True
            break
        u = frontier.popleft()
        r = f.get(u)
        if r.error == "blocked by robots.txt":
            res.skipped.append((u, "blocked by robots.txt"))
            continue
        if r.status and "html" not in (r.content_type or ""):
            res.skipped.append((u, f"not HTML ({r.content_type or 'unknown'})"))
            continue
        page = parse_page(r, site_host)
        res.pages[u] = page
        if len(res.pages) % 10 == 0:
            log(f"  crawled {len(res.pages)} pages...")
        if page.status == 200:
            for l in page.internal_links:
                enqueue(l["url"])
    res.requests = f.request_count
    return res
