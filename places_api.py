"""
scraper_engine.py — SocialProofREEL Worker
==========================================
DUMB SCRAPER: Materializes review data from Google Places API into /app/temp/leads/{id}/.
Does NOT know about video rendering or cloud uploads.

INPUT:  A business name/search query  (e.g. "Telocuido Petsitter Quilpué Chile")
        OR a Google Maps URL           (e.g. "https://www.google.com/maps/place/...")

OUTPUT: /app/temp/leads/{business_id}/
            metadata.json           ← the data bridge contract for the Renderer
            avatar_0.jpg            ← reviewer profile photo
            avatar_1.jpg
            avatar_2.jpg

STRATEGY:
  1. Find Place  → Places Text Search API  → stable Place ID + business name
  2. Get Details → Places Details API      → reviews (text, rating, author, avatar URL)
  3. Materialize → download avatars locally, write metadata.json

REQUIRES:
  GOOGLE_PLACES_API_KEY in environment (set in .env, mounted via --env-file)
"""

import os
import re
import json
import hashlib
import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DIR     = os.path.dirname(os.path.abspath(__file__))
BASE_TEMP_DIR = os.path.join(BASE_DIR, "videos_locales")
PLACES_BASE  = "https://maps.googleapis.com/maps/api/place"


# ---------------------------------------------------------------------------
# STEP 1 — Find Place
# Accepts either a free-text business name or a Google Maps URL.
# Returns (place_id, display_name, rating) or raises on failure.
# ---------------------------------------------------------------------------

def _extract_place_id_from_url(url: str) -> str | None:
    """Pull the ChIJ... Place ID embedded in the !19s segment of a Maps URL."""
    m = re.search(r"!19s([A-Za-z0-9_\-]+)", url)
    return m.group(1) if m else None


def find_place(query_or_url: str, api_key: str) -> dict:
    """
    Resolves a business to a canonical Place ID using the Places API.

    If the input is a Google Maps URL, we first try to extract the Place ID
    directly from the URL (instant, no API call). If that fails or returns
    NOT_FOUND, we fall through to a Text Search using the URL itself as the
    query (Google is good at understanding Maps URLs as text).

    If the input is a plain text query, we go straight to Text Search.

    Returns:
        {
            "place_id":   "ChIJ...",
            "name":       "Telocuido Petsitter",
            "rating":     5.0,
            "address":    "...",
        }
    """
    is_url = query_or_url.startswith("http")

    # --- Try direct URL extraction first (no API quota used) ---
    if is_url:
        place_id = _extract_place_id_from_url(query_or_url)
        if place_id:
            print(f"[FIND] Place ID extracted from URL: {place_id}")
            # Validate it's still alive by fetching basic fields.
            detail = _call_place_details(place_id, "name,rating,formatted_address", api_key)
            if detail:
                return {
                    "place_id": place_id,
                    "name":     detail.get("name", ""),
                    "rating":   detail.get("rating", 0),
                    "address":  detail.get("formatted_address", ""),
                }
            print("[FIND] URL Place ID not found in API — falling back to Text Search.")

    # --- Text Search (works for names, addresses, or partial URLs) ---
    # For URLs we extract the business name from the path as the search query.
    if is_url:
        # Extract readable name from URL path segment
        m = re.search(r"/maps/place/([^/]+)/", query_or_url)
        search_query = m.group(1).replace("+", " ") if m else query_or_url
    else:
        search_query = query_or_url

    print(f"[FIND] Text Search: '{search_query}'")
    resp = requests.get(
        f"{PLACES_BASE}/textsearch/json",
        params={"query": search_query, "language": "es-419", "key": api_key},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") != "OK" or not data.get("results"):
        raise RuntimeError(
            f"Text Search failed — status: {data.get('status')} "
            f"({data.get('error_message', 'no results')})"
        )

    result = data["results"][0]
    place_id = result["place_id"]
    print(f"[FIND] [OK] Found: '{result['name']}' | Place ID: {place_id}")
    return {
        "place_id": place_id,
        "name":     result.get("name", ""),
        "rating":   result.get("rating", 0),
        "address":  result.get("formatted_address", ""),
    }


# ---------------------------------------------------------------------------
# STEP 2 — Get Reviews
# Calls Place Details API with the reviews + photos fields.
# ---------------------------------------------------------------------------

def _call_place_details(place_id: str, fields: str, api_key: str) -> dict | None:
    """Low-level Place Details call. Returns the result dict or None."""
    resp = requests.get(
        f"{PLACES_BASE}/details/json",
        params={
            "place_id": place_id,
            "fields":   fields,
            "language": "es-419",
            "key":      api_key,
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "OK":
        print(f"[DETAILS] API status: {data.get('status')} — {data.get('error_message', '')}")
        return None
    return data.get("result", {})


def get_reviews(place_id: str, api_key: str, max_reviews: int = 3) -> tuple[list[dict], list[dict]]:
    """
    Fetches up to `max_reviews` reviews for the given Place ID and its photos.
    Sorts reviews by rating descending (prioritizes 5 stars).
    """
    print(f"[REVIEWS] Fetching reviews for Place ID: {place_id}")
    result = _call_place_details(
        place_id,
        "name,rating,reviews,photos",
        api_key,
    )
    if not result:
        return [], []

    raw_reviews = result.get("reviews", [])
    # Sort reviews prioritizing higher ratings (5 stars first)
    raw_reviews.sort(key=lambda x: x.get("rating", 0), reverse=True)
    
    reviews = []
    for r in raw_reviews:
        text = r.get("text", "").strip()
        if not text:
            continue
            
        reviews.append({
            "reviewer_name": r.get("author_name", "Anonymous"),
            "review_text":   text,
            "rating":        r.get("rating", 0),
            "avatar_url":    r.get("profile_photo_url", ""),
        })
        print(f"[REVIEWS] - {r.get('author_name')} ({r.get('rating')} stars) - {text[:60]}...")
        
        if len(reviews) >= max_reviews:
            break

    print(f"[REVIEWS] API returned {len(raw_reviews)} raw reviews. Found {len(reviews)} with text. Using top {len(reviews)}.")

    photos = result.get("photos", [])
    return reviews, photos


# ---------------------------------------------------------------------------
# STEP 3 — Materialize assets
# ---------------------------------------------------------------------------

def download_avatar(avatar_url: str, business_id: str, index: int) -> str | None:
    """
    Downloads a reviewer profile photo to /videos_locales/{business_id}/avatar_{index}.jpg.
    Returns the local path or None on failure.
    Forces high-resolution download by modifying the URL size parameter.
    """
    if not avatar_url:
        print(f"[AVATAR] Review {index}: no avatar URL provided.")
        return None

    # Force high-res (e.g. change =s128-c0x00000000-cc-rp-mo to =s1080-c0x00000000-cc-rp-mo)
    avatar_url = re.sub(r'=s\d+', '=s1080', avatar_url)

    lead_dir = os.path.join(BASE_TEMP_DIR, business_id)
    os.makedirs(lead_dir, exist_ok=True)
    local_path = os.path.join(lead_dir, f"avatar_{index}.jpg")

    try:
        resp = requests.get(avatar_url, stream=True, timeout=15)
        resp.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"[AVATAR] [OK] Saved high-res: {local_path}")
        return local_path
    except Exception as e:
        print(f"[AVATAR] [ERROR] Failed to download avatar {index}: {e}")
        return None


def download_place_photo(photo_reference: str, business_id: str, api_key: str) -> str | None:
    """
    Downloads a background photo of the place using the Google Places Photo API.
    """
    if not photo_reference:
        return None

    lead_dir = os.path.join(BASE_TEMP_DIR, business_id)
    os.makedirs(lead_dir, exist_ok=True)
    local_path = os.path.join(lead_dir, "background.jpg")

    url = f"{PLACES_BASE}/photo"
    params = {
        "maxwidth": 1080,
        "photo_reference": photo_reference,
        "key": api_key
    }

    try:
        print(f"[PHOTO] Downloading background photo for {business_id}...")
        resp = requests.get(url, params=params, stream=True, timeout=20)
        resp.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"[PHOTO] [OK] Saved background: {local_path}")
        return local_path
    except Exception as e:
        print(f"[PHOTO] [ERROR] Failed to download background photo: {e}")
        return None


def save_metadata(business_id: str, place_info: dict, reviews: list[dict], bg_path: str | None) -> str:
    """
    THE BRIDGE: Writes metadata.json — the data contract between Places API and Renderer.
    Status 'ready_for_render' signals the Renderer to pick up this lead.
    """
    lead_dir = os.path.join(BASE_TEMP_DIR, business_id)
    os.makedirs(lead_dir, exist_ok=True)
    metadata_path = os.path.join(lead_dir, "metadata.json")

    payload = {
        "business_id":   business_id,
        "business_name": place_info.get("name", ""),
        "overall_rating": place_info.get("rating", 0),
        "address":        place_info.get("address", ""),
        "place_id":       place_info.get("place_id", ""),
        "status":         "ready_for_render",
        "background_local_path": bg_path,
        "reviews":        reviews,
    }

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)

    print(f"[BRIDGE] metadata.json written: {metadata_path}")
    return metadata_path


# ---------------------------------------------------------------------------
# PUBLIC ENTRYPOINT — process_lead
# ---------------------------------------------------------------------------

def process_lead(query_or_url: str) -> str | None:
    """
    Full pipeline: Find → Reviews → Materialize → Bridge.

    Args:
        query_or_url: Business name + location (e.g. "Telocuido Petsitter Quilpué Chile")
                      OR a Google Maps place URL.

    Returns:
        Path to metadata.json, or None if the pipeline failed.
    """
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        raise EnvironmentError(
            "GOOGLE_PLACES_API_KEY is not set. "
            "Add it to your .env file and run with --env-file .env"
        )

    print("--- SCRAPER ENGINE START ---")
    business_id = hashlib.md5(query_or_url.encode("utf-8")).hexdigest()
    print(f"Lead ID: {business_id}")

    # Step 1 — Find Place
    try:
        place_info = find_place(query_or_url, api_key)
    except Exception as e:
        print(f"[ERROR] Could not find business: {e}")
        return None

    # Step 2 — Get Reviews and Photos
    reviews, photos = get_reviews(place_info["place_id"], api_key)
    if not reviews:
        print("[ERROR] No reviews returned by the API. Stopping.")
        return None

    # Step 3 — Download avatars
    for i, review in enumerate(reviews):
        local_path = download_avatar(review["avatar_url"], business_id, i)
        review["avatar_local_path"] = local_path  # Renderer reads this field

    # Step 4 — Download background photo
    bg_path = None
    if photos:
        # Get the photo_reference of the first photo
        photo_ref = photos[0].get("photo_reference")
        if photo_ref:
            bg_path = download_place_photo(photo_ref, business_id, api_key)

    # Step 5 — Write bridge contract
    metadata_path = save_metadata(business_id, place_info, reviews, bg_path)

    print("--- SUCCESS ---")
    print(f"Business : {place_info['name']} ({place_info['rating']} stars)")
    print(f"Reviews  : {len(reviews)}")
    print(f"Folder   : {os.path.join(BASE_TEMP_DIR, business_id)}")
    print(f"Contract : {metadata_path}")
    return metadata_path


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    # Accept a plain text search query OR a Google Maps URL.
    # Default to the test business if no argument given.
    default_query = "Telocuido Petsitter Quilpué Chile"

    query = sys.argv[1] if len(sys.argv) > 1 else default_query
    print(f"Input: {query}\n")

    result = process_lead(query)
    if not result:
        sys.exit(1)
