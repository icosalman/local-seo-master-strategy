"""Google PageSpeed Insights v5. Works without a key at low volume; a free key raises the quota."""
import requests

API = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
CATEGORIES = ["performance", "seo", "accessibility", "best-practices"]
LAB_AUDITS = [
    ("largest-contentful-paint", "LCP (lab)"),
    ("cumulative-layout-shift", "CLS (lab)"),
    ("total-blocking-time", "TBT (lab)"),
    ("first-contentful-paint", "FCP (lab)"),
    ("speed-index", "Speed Index (lab)"),
]
FIELD_METRICS = [
    ("LARGEST_CONTENTFUL_PAINT_MS", "LCP (real users, p75)", "ms"),
    ("INTERACTION_TO_NEXT_PAINT", "INP (real users, p75)", "ms"),
    ("CUMULATIVE_LAYOUT_SHIFT_SCORE", "CLS (real users, p75)", "x100"),
]


def run(url: str, strategy: str = "mobile", api_key: str = "", timeout: int = 150) -> dict:
    params = [("url", url), ("strategy", strategy)] + [("category", c) for c in CATEGORIES]
    if api_key:
        params.append(("key", api_key))
    out = {"url": url, "strategy": strategy, "ok": False}
    try:
        r = requests.get(API, params=params, timeout=timeout)
    except requests.RequestException as e:
        out["error"] = f"{type(e).__name__}: {e}"[:300]
        return out
    if r.status_code != 200:
        try:
            msg = r.json().get("error", {}).get("message", r.text[:200])
        except ValueError:
            msg = r.text[:200]
        out["error"] = f"HTTP {r.status_code}: {msg}"
        return out
    data = r.json()
    lh = data.get("lighthouseResult", {})
    out["ok"] = True
    out["fetched_at"] = lh.get("fetchTime", "")
    out["scores"] = {k: (round(v["score"] * 100) if v.get("score") is not None else None)
                     for k, v in lh.get("categories", {}).items()}
    audits = lh.get("audits", {})
    out["lab"] = {label: audits.get(key, {}).get("displayValue", "") for key, label in LAB_AUDITS}
    le = data.get("loadingExperience", {}) or {}
    fm = {}
    if le.get("metrics") and le.get("id"):
        for key, label, unit in FIELD_METRICS:
            m = le["metrics"].get(key)
            if m:
                val = m.get("percentile")
                if unit == "x100" and val is not None:
                    val = round(val / 100, 2)
                    disp = str(val)
                else:
                    disp = f"{val} ms"
                fm[label] = {"value": disp, "category": m.get("category", "")}
        out["field_scope"] = "whole origin" if le.get("origin_fallback") else "this URL"
    out["field"] = fm   # empty = Google has no real-user (CrUX) data for this site
    return out
