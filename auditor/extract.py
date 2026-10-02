import json
import re
from dataclasses import dataclass, field, asdict
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from . import config
from .fetcher import absolute, bare_host

PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?([2-9]\d{2})\)?[\s.-]?([2-9]\d{2})[\s.-]?(\d{4})(?!\d)")
STATE_ZIP_RE = re.compile(r"\b(" + "|".join(config.US_STATES) + r")\.?\s+(\d{5})(?:-\d{4})?\b")


def norm_phone(a, b, c):
    return f"({a}) {b}-{c}"


@dataclass
class Page:
    url: str
    final_url: str = ""
    status: int = 0
    error: str = ""
    redirects: list = field(default_factory=list)
    elapsed_ms: int = 0
    content_type: str = ""
    title: str = ""
    meta_description: str = ""
    meta_robots: str = ""
    canonical: str = ""
    viewport: bool = False
    h1: list = field(default_factory=list)
    h2: list = field(default_factory=list)
    h3: list = field(default_factory=list)
    word_count: int = 0
    images_total: int = 0
    images_missing_alt: list = field(default_factory=list)
    internal_links: list = field(default_factory=list)
    external_links: list = field(default_factory=list)
    tel_links: list = field(default_factory=list)
    phones_in_text: list = field(default_factory=list)
    state_zip_mentions: list = field(default_factory=list)
    forms: int = 0
    map_embed: bool = False
    iframes: list = field(default_factory=list)
    schema_types: list = field(default_factory=list)
    schema_blocks: list = field(default_factory=list)   # parsed JSON-LD objects (flattened)
    schema_errors: list = field(default_factory=list)
    microdata_types: list = field(default_factory=list)
    og_site_name: str = ""
    lang: str = ""
    generator: str = ""
    text: str = ""          # visible text (kept for signal search; dropped from JSON export)
    html_sample: str = ""   # first 200k chars of raw HTML for CMS detection

    def to_dict(self, keep_text=False):
        d = asdict(self)
        if not keep_text:
            d.pop("text", None)
            d.pop("html_sample", None)
            d.pop("schema_blocks", None)
        return d


def _flatten_jsonld(obj, out):
    if isinstance(obj, list):
        for o in obj:
            _flatten_jsonld(o, out)
    elif isinstance(obj, dict):
        if "@graph" in obj:
            _flatten_jsonld(obj["@graph"], out)
        if "@type" in obj:
            out.append(obj)
        for k, v in obj.items():
            if k != "@graph" and isinstance(v, (dict, list)):
                # nested entities (e.g. provider inside Service) also count
                nested = []
                _flatten_jsonld(v, nested)
                out.extend(n for n in nested if n not in out)


def _types_of(obj):
    t = obj.get("@type")
    if isinstance(t, list):
        return [str(x) for x in t]
    return [str(t)] if t else []


def parse_page(resp, site_host: str) -> Page:
    p = Page(url=resp.url, final_url=resp.final_url, status=resp.status, error=resp.error,
             redirects=resp.redirects, elapsed_ms=resp.elapsed_ms, content_type=resp.content_type)
    if not resp.text or "html" not in (resp.content_type or "html"):
        return p
    html = resp.text
    p.html_sample = html[:200000]
    soup = BeautifulSoup(html, "lxml")
    base = resp.final_url or resp.url

    if soup.html and soup.html.get("lang"):
        p.lang = soup.html.get("lang")
    if soup.title and soup.title.string:
        p.title = " ".join(soup.title.string.split())
    for m in soup.find_all("meta"):
        name = (m.get("name") or m.get("property") or "").lower()
        content = " ".join((m.get("content") or "").split())
        if name == "description" and not p.meta_description:
            p.meta_description = content
        elif name == "robots":
            p.meta_robots = content.lower()
        elif name == "viewport":
            p.viewport = True
        elif name == "og:site_name":
            p.og_site_name = content
        elif name == "generator":
            p.generator = content
    link = soup.find("link", rel=lambda v: v and "canonical" in (v if isinstance(v, list) else [v]))
    if link and link.get("href"):
        p.canonical = absolute(base, link["href"])

    # JSON-LD
    for s in soup.find_all("script", type=lambda t: t and "ld+json" in t.lower()):
        raw = s.string or s.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            p.schema_errors.append(f"Invalid JSON-LD: {e.msg} (line {e.lineno})")
            continue
        found = []
        _flatten_jsonld(data, found)
        for obj in found:
            p.schema_blocks.append(obj)
            for t in _types_of(obj):
                if t not in p.schema_types:
                    p.schema_types.append(t)
    for el in soup.find_all(attrs={"itemtype": True}):
        t = el["itemtype"].rstrip("/").split("/")[-1]
        if t not in p.microdata_types:
            p.microdata_types.append(t)

    # iframes / maps (before removing tags)
    for f in soup.find_all("iframe"):
        src = f.get("src") or f.get("data-src") or ""
        if src:
            p.iframes.append(src[:300])
            if "google.com/maps" in src or "maps.google" in src:
                p.map_embed = True
    p.forms = len(soup.find_all("form"))

    # links
    seen_int, seen_ext = set(), set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.startswith("tel:"):
            num = re.sub(r"[^\d+]", "", href[4:])
            if num and num not in p.tel_links:
                p.tel_links.append(num)
            continue
        if href.startswith(("mailto:", "javascript:", "#", "sms:")):
            continue
        u = absolute(base, href)
        pu = urlparse(u)
        if pu.scheme not in ("http", "https"):
            continue
        anchor = " ".join(a.get_text(" ").split())[:120]
        if bare_host(pu.netloc) == site_host:
            if u not in seen_int:
                seen_int.add(u)
                p.internal_links.append({"url": u, "anchor": anchor})
        else:
            if u not in seen_ext:
                seen_ext.add(u)
                p.external_links.append({"url": u, "anchor": anchor})

    # images
    for img in soup.find_all("img"):
        p.images_total += 1
        alt = img.get("alt")
        if alt is None or not alt.strip():
            src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
            p.images_missing_alt.append(absolute(base, src) if src and not src.startswith("data:") else "(inline image)")

    # headings
    p.h1 = [" ".join(h.get_text(" ").split()) for h in soup.find_all("h1")]
    p.h2 = [" ".join(h.get_text(" ").split()) for h in soup.find_all("h2")][:40]
    p.h3 = [" ".join(h.get_text(" ").split()) for h in soup.find_all("h3")][:60]

    # visible text
    for tag in soup(["script", "style", "noscript", "template", "svg"]):
        tag.decompose()
    text = " ".join(soup.get_text(" ").split())
    p.text = text
    p.word_count = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'\-]*", text))

    phones = []
    for m in PHONE_RE.finditer(text):
        n = norm_phone(*m.groups())
        if n not in phones:
            phones.append(n)
    p.phones_in_text = phones[:10]
    sz = []
    for m in STATE_ZIP_RE.finditer(text):
        v = f"{m.group(1)} {m.group(2)}"
        if v not in sz:
            sz.append(v)
    p.state_zip_mentions = sz[:10]
    return p
