import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urlparse, urlunparse, urljoin, urldefrag

import requests

from . import config


def normalize_url(url: str) -> str:
    """Drop fragments, lowercase scheme/host, keep path and query as-is."""
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    path = p.path or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, "", p.query, ""))


def bare_host(netloc: str) -> str:
    host = netloc.lower().split(":")[0] if "@" not in netloc else netloc.split("@")[-1]
    return host[4:] if host.startswith("www.") else host


@dataclass
class Response:
    url: str                      # requested URL
    final_url: str = ""
    status: int = 0
    content_type: str = ""
    text: str = ""
    elapsed_ms: int = 0
    redirects: list = field(default_factory=list)   # [(status, url), ...]
    error: str = ""


class Fetcher:
    def __init__(self, respect_robots: bool = True, delay: float = config.CRAWL_DELAY):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        self.respect_robots = respect_robots
        self.delay = delay
        self._robots = {}
        self._last = 0.0
        self.request_count = 0

    def _wait(self):
        gap = time.time() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        self._last = time.time()

    def robots_for(self, base: str):
        p = urlparse(base)
        key = f"{p.scheme}://{p.netloc}"
        if key not in self._robots:
            rp = urllib.robotparser.RobotFileParser()
            raw = self.get(key + "/robots.txt", check_robots=False)
            if raw.status == 200 and raw.text:
                rp.parse(raw.text.splitlines())
                self._robots[key] = (rp, raw)
            else:
                self._robots[key] = (None, raw)
        return self._robots[key]

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        rp, _ = self.robots_for(url)
        if rp is None:
            return True
        # Falls back to the "*" group when no rule names our user agent
        return rp.can_fetch(config.USER_AGENT, url)

    def get(self, url: str, check_robots: bool = True) -> Response:
        r = Response(url=url)
        if check_robots and not self.allowed(url):
            r.error = "blocked by robots.txt"
            return r
        self._wait()
        self.request_count += 1
        t0 = time.time()
        try:
            resp = self.session.get(url, timeout=config.REQUEST_TIMEOUT, allow_redirects=True)
        except requests.RequestException as e:
            r.error = f"{type(e).__name__}: {e}"[:300]
            return r
        r.elapsed_ms = int((time.time() - t0) * 1000)
        r.final_url = resp.url
        r.status = resp.status_code
        r.content_type = resp.headers.get("Content-Type", "")
        r.redirects = [(h.status_code, h.url) for h in resp.history]
        if "html" in r.content_type or "xml" in r.content_type or "text" in r.content_type:
            resp.encoding = resp.encoding or resp.apparent_encoding
            r.text = resp.text
        return r


def absolute(base: str, href: str) -> str:
    return normalize_url(urljoin(base, href))
