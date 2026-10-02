"""
Google Places API (New). Needs GOOGLE_PLACES_API_KEY with "Places API (New)" enabled.
Returns exactly what Google's API returns. Important limit, shown in the report too:
Text Search order is NOT the live map pack seen from a searcher's location.
Use a rank grid tool (Local Falcon, BrightLocal) for true map positions.
"""
from urllib.parse import urlparse

import requests

SEARCH = "https://places.googleapis.com/v1/places:searchText"
DETAILS = "https://places.googleapis.com/v1/places/{}"
FIELDS = [
    "id", "displayName", "formattedAddress", "nationalPhoneNumber", "websiteUri",
    "rating", "userRatingCount", "primaryType", "primaryTypeDisplayName", "types",
    "businessStatus", "googleMapsUri", "regularOpeningHours",
]


def _clean(p: dict) -> dict:
    return {
        "place_id": p.get("id", ""),
        "name": (p.get("displayName") or {}).get("text", ""),
        "address": p.get("formattedAddress", ""),
        "phone": p.get("nationalPhoneNumber", ""),
        "website": p.get("websiteUri", ""),
        "rating": p.get("rating"),
        "reviews": p.get("userRatingCount"),
        "primary_type": p.get("primaryType", ""),
        "primary_category": (p.get("primaryTypeDisplayName") or {}).get("text", ""),
        "types": p.get("types", []),
        "status": p.get("businessStatus", ""),
        "maps_url": p.get("googleMapsUri", ""),
        "hours": (p.get("regularOpeningHours") or {}).get("weekdayDescriptions", []),
    }


def _err(r):
    try:
        return f"HTTP {r.status_code}: {r.json().get('error', {}).get('message', '')}"
    except ValueError:
        return f"HTTP {r.status_code}: {r.text[:200]}"


def text_search(query: str, api_key: str, max_results: int = 20) -> dict:
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": ",".join("places." + f for f in FIELDS),
        "Content-Type": "application/json",
    }
    body = {"textQuery": query, "pageSize": min(max_results, 20), "languageCode": "en", "regionCode": "US"}
    try:
        r = requests.post(SEARCH, json=body, headers=headers, timeout=30)
    except requests.RequestException as e:
        return {"ok": False, "query": query, "error": str(e)[:300], "results": []}
    if r.status_code != 200:
        return {"ok": False, "query": query, "error": _err(r), "results": []}
    return {"ok": True, "query": query, "results": [_clean(p) for p in r.json().get("places", [])]}


def details(place_id: str, api_key: str) -> dict:
    headers = {"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": ",".join(FIELDS)}
    try:
        r = requests.get(DETAILS.format(place_id), headers=headers, timeout=30)
    except requests.RequestException as e:
        return {"ok": False, "error": str(e)[:300]}
    if r.status_code != 200:
        return {"ok": False, "error": _err(r)}
    return {"ok": True, "place": _clean(r.json())}


def same_site(a: str, b: str) -> bool:
    def h(u):
        n = urlparse(u if "://" in u else "https://" + u).netloc.lower()
        return n[4:] if n.startswith("www.") else n
    return bool(a and b) and h(a) == h(b)
