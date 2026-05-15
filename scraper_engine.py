import os
import json
import re
import hashlib
import asyncio
import requests
from playwright.async_api import async_playwright

# BASE_DIR should be the directory where the script is located
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# The standard bridge for dumb modules: /app/temp/leads/{id}/
BASE_TEMP_DIR = os.path.join(BASE_DIR, "temp", "leads")
TEMP_DIR = os.path.join(BASE_DIR, "temp")


# ---------------------------------------------------------------------------
# UTILITY: Business ID
# ---------------------------------------------------------------------------

def extract_business_id(url):
    """Stable hash of the URL used as the directory key for the data bridge."""
    return hashlib.md5(url.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# UTILITY: Place ID extractor
# ---------------------------------------------------------------------------

def extract_place_id(url):
    """
    Extracts the canonical Place ID (ChIJ...) from the !19s segment of a
    Google Maps URL.

    Example segment: !19sChIJ16H8bHUvAwER9OJ41xIye-g
    Returns:          ChIJ16H8bHUvAwER9OJ41xIye-g
    """
    match = re.search(r"!19s([A-Za-z0-9_\-]+)", url)
    if match:
        return match.group(1)
    return None


# ---------------------------------------------------------------------------
# STRATEGY A: Google Places API (fast, reliable, JSON)
# ---------------------------------------------------------------------------

def scrape_via_places_api(place_id, api_key, language="es-419"):
    """
    Fetches reviews using the Google Places Details API.

    Returns up to 5 most-recent reviews as a list of dicts.
    Requires GOOGLE_PLACES_API_KEY in the environment.

    API docs: https://developers.google.com/maps/documentation/places/web-service/details
    """
    print(f"[API] Fetching reviews for Place ID: {place_id}")
    endpoint = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields": "name,rating,reviews",
        "language": language,
        "key": api_key,
    }

    try:
        response = requests.get(endpoint, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[API] Request failed: {e}")
        return []

    status = data.get("status")
    if status != "OK":
        print(f"[API] API returned status: {status} — {data.get('error_message', '')}")
        return []

    raw_reviews = data.get("result", {}).get("reviews", [])
    print(f"[API] Received {len(raw_reviews)} reviews from Places API.")

    reviews = []
    for r in raw_reviews[:3]:  # We only need 3 for a video
        reviews.append({
            "reviewer_name": r.get("author_name", "Anonymous"),
            "review_text": r.get("text", ""),
            "rating": r.get("rating", 0),
            "avatar_url": r.get("profile_photo_url", ""),
        })
        print(f"[API] Review: '{r.get('author_name')}' ({r.get('rating')}★)")

    return reviews


# ---------------------------------------------------------------------------
# STRATEGY B: Playwright DOM scraping (fallback — no API key needed)
# ---------------------------------------------------------------------------

def build_reviews_url(url):
    """
    Transforms any Google Maps place URL into one that directly requests
    the reviews panel by appending the !9m1!1b1 data flag.
    Strips session-specific params (authuser, rclk) to reduce bot-detection.
    """
    if "?" in url:
        base, qs = url.split("?", 1)
    else:
        base, qs = url, ""

    qs_parts = [p for p in qs.split("&") if not re.match(r"(authuser|rclk)=", p) and p]
    clean_qs = "&".join(qs_parts)

    if "!9m1!1b1" in base:
        return f"{base}?{clean_qs}" if clean_qs else base

    reviews_base = f"{base}!9m1!1b1"
    return f"{reviews_base}?{clean_qs}" if clean_qs else reviews_base


async def scrape_via_playwright(url):
    """
    FALLBACK SCRAPER: Uses Playwright to load the Google Maps page in a
    headless browser and extracts reviews from the rendered DOM.

    Activated only when GOOGLE_PLACES_API_KEY is not set.
    """
    reviews_url = build_reviews_url(url)
    reviews_data = []
    os.makedirs(TEMP_DIR, exist_ok=True)
    debug_ss = os.path.join(TEMP_DIR, "debug_screenshot.png")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},
            locale="es-419",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()

        try:
            print(f"[PW] Navigating to: {reviews_url}")
            await page.goto(reviews_url, wait_until="load", timeout=60000)

            title = await page.title()
            print(f"[PW] Title: '{title}' | URL: {page.url}")

            await asyncio.sleep(4)

            # Checkpoint screenshot
            await page.screenshot(path=debug_ss, full_page=False)
            print(f"[PW] Checkpoint screenshot → {debug_ss}")

            # Cookie banner
            for sel in ['button:has-text("Aceptar todo")', 'button:has-text("Accept all")',
                        'form[action*="consent"] button']:
                try:
                    btn = await page.wait_for_selector(sel, timeout=2000)
                    if btn:
                        await btn.click()
                        print(f"[PW] Cookie dismissed: {sel}")
                        await asyncio.sleep(2)
                        break
                except Exception:
                    pass

            # Scroll the SIDEBAR (not the map)
            for i in range(4):
                result = await page.evaluate("""
                    () => {
                        const sels = [
                            'div[role="main"] .m6QErb[aria-label]',
                            'div[role="main"] .m6QErb',
                            '.TFQHme .m6QErb',
                            'div[role="main"]',
                        ];
                        for (const s of sels) {
                            const el = document.querySelector(s);
                            if (el && el.scrollHeight > el.clientHeight) {
                                el.scrollTop += 1200;
                                return s + ' @' + el.scrollTop;
                            }
                        }
                        return 'no-scroll';
                    }
                """)
                print(f"[PW] Scroll {i+1}: {result}")
                await asyncio.sleep(2)

            # Hover over sidebar and mouse-wheel it
            await page.mouse.move(200, 400)
            await page.mouse.wheel(0, 3000)
            await asyncio.sleep(2)

            # Dump sidebar HTML for debugging
            sidebar_html = await page.evaluate("""
                () => {
                    const el = document.querySelector('div[role="main"]');
                    return el ? el.innerHTML.substring(0, 3000) : 'no sidebar';
                }
            """)
            print(f"[PW] Sidebar HTML (3000): {sidebar_html}")

            # Try review selectors
            review_selectors = [
                "div[data-review-id]", "[data-review-id]",
                ".jftiEf", ".GHT2ce", ".lMbq3e", ".jJc9Ad",
                ".WMbnJf", ".wiI7pd", ".bwb7ce",
                '[jscontroller*="review"]',
                '[aria-label*="reseña de"]', '[aria-label*="review by"]',
            ]
            found = None
            for sel in review_selectors:
                try:
                    await page.wait_for_selector(sel, timeout=8000)
                    found = sel
                    print(f"[PW] ✓ Found reviews with: {sel}")
                    break
                except Exception:
                    print(f"[PW] ✗ {sel}")

            if not found:
                classes = await page.evaluate("""
                    () => {
                        const sb = document.querySelector('div[role="main"]');
                        if (!sb) return [];
                        const s = new Set();
                        sb.querySelectorAll('*').forEach(e => {
                            (e.className || '').toString().split(' ').forEach(c => {
                                if (c.length > 2 && c.length < 15) s.add(c);
                            });
                        });
                        return [...s].slice(0, 80);
                    }
                """)
                print(f"[PW] Sidebar classes: {classes}")
                raise TimeoutError("No review selector matched.")

            # Deep scroll to load avatars
            for _ in range(4):
                await page.mouse.wheel(0, 2000)
                await asyncio.sleep(2)

            review_elements = await page.query_selector_all(found)
            print(f"[PW] Parsing {len(review_elements)} review elements.")

            for i, el in enumerate(review_elements[:3]):
                text_el = await el.query_selector(".MyEned, .wiI7pd, .Jtu6Td, span[jsaction*='full-review']")
                text = (await text_el.inner_text()).strip() if text_el else ""

                rating_el = await el.query_selector('[aria-label*="star"], [aria-label*="estrella"]')
                rl = await rating_el.get_attribute("aria-label") if rating_el else "0"
                rm = re.search(r"(\d+)", rl)
                rating = int(rm.group(1)) if rm else 0

                name_el = await el.query_selector(".d4r55, .NfpymFe, .WNxzHc")
                name = (await name_el.inner_text()).strip() if name_el else "Anonymous"

                avatar_el = await el.query_selector('img[src*="googleusercontent.com"]')
                avatar_url = await avatar_el.get_attribute("src") if avatar_el else ""
                if avatar_url and "=s" in avatar_url:
                    avatar_url = re.sub(r"=s\d+.*", "=s256-c", avatar_url)

                reviews_data.append({
                    "reviewer_name": name,
                    "review_text": text,
                    "rating": rating,
                    "avatar_url": avatar_url,
                })
                print(f"[PW] Review {i+1}: '{name}' ({rating}★)")

        except Exception as e:
            print(f"[PW] Error: {e}")
            try:
                await page.screenshot(path=debug_ss.replace(".png", "_error.png"), full_page=False)
                print(f"[PW] Error screenshot saved.")
            except Exception:
                pass
        finally:
            await browser.close()

    return reviews_data


# ---------------------------------------------------------------------------
# PUBLIC ENTRYPOINT: scrape_reviews (chooses strategy automatically)
# ---------------------------------------------------------------------------

async def scrape_reviews(url):
    """
    Chooses the scraping strategy based on available credentials:

    1. GOOGLE_PLACES_API_KEY set → Places API (fast, reliable, JSON)
    2. No API key              → Playwright DOM scraping (fallback)
    """
    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()

    if api_key:
        place_id = extract_place_id(url)
        if place_id:
            print(f"[STRATEGY] Using Google Places API (Place ID: {place_id})")
            reviews = scrape_via_places_api(place_id, api_key)
            if reviews:
                return reviews
            print("[STRATEGY] Places API returned 0 results — falling back to Playwright.")
        else:
            print("[STRATEGY] Could not extract Place ID from URL — falling back to Playwright.")
    else:
        print("[STRATEGY] No GOOGLE_PLACES_API_KEY — using Playwright fallback.")

    return await scrape_via_playwright(url)


# ---------------------------------------------------------------------------
# MATERIALIZER: Download avatar locally
# ---------------------------------------------------------------------------

def download_avatar(avatar_url, business_id, review_index):
    """
    Downloads the reviewer avatar to the local lead folder.
    Ensures the Renderer doesn't need internet access at render time.
    """
    if not avatar_url:
        return None

    lead_dir = os.path.join(BASE_TEMP_DIR, business_id)
    os.makedirs(lead_dir, exist_ok=True)
    local_path = os.path.join(lead_dir, f"avatar_{review_index}.jpg")

    try:
        response = requests.get(avatar_url, stream=True, timeout=15)
        response.raise_for_status()
        with open(local_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"[AVATAR] Saved: {local_path}")
        return local_path
    except Exception as e:
        print(f"[AVATAR] Error downloading avatar {review_index}: {e}")
        return None


# ---------------------------------------------------------------------------
# BRIDGE: Save metadata.json contract
# ---------------------------------------------------------------------------

def save_metadata(business_id, reviews_data):
    """
    THE BRIDGE: Writes metadata.json so the Renderer knows what to process.
    Status 'ready_for_render' signals the Renderer to pick it up.
    """
    lead_dir = os.path.join(BASE_TEMP_DIR, business_id)
    os.makedirs(lead_dir, exist_ok=True)
    metadata_path = os.path.join(lead_dir, "metadata.json")

    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "business_id": business_id,
                "status": "ready_for_render",
                "reviews": reviews_data,
            },
            f,
            ensure_ascii=False,
            indent=4,
        )
    return metadata_path


# ---------------------------------------------------------------------------
# POC RUNNER: test_single_url
# ---------------------------------------------------------------------------

async def test_single_url(url):
    """
    Validates the full Scraper → Bridge pipeline for a single URL.
    Run manually to inspect metadata.json before launching the Renderer.
    """
    print("--- SCRAPER ENGINE START ---")
    business_id = extract_business_id(url)
    print(f"Lead ID: {business_id}")

    # 1. Scrape (auto-selects strategy)
    reviews_data = await scrape_reviews(url)

    if not reviews_data:
        print("No reviews found. Stopping.")
        return

    # 2. Materialize avatars
    for i, review in enumerate(reviews_data):
        print(f"Processing review {i + 1}...")
        local_path = download_avatar(review["avatar_url"], business_id, i)
        review["avatar_local_path"] = local_path  # Renderer reads this field

    # 3. Write bridge contract
    metadata_path = save_metadata(business_id, reviews_data)

    print("--- SUCCESS ---")
    print(f"Folder : {os.path.join(BASE_TEMP_DIR, business_id)}")
    print(f"Contract: {metadata_path}")


if __name__ == "__main__":
    import sys

    example_url = (
        "https://www.google.com/maps/place/Telocuido+Petsitter/"
        "data=!4m7!3m6!1s0x1032f756cfca1d7:0xe87b3212d778e2f4"
        "!8m2!3d-32.9979487!4d-71.4582527"
        "!16s%2Fg%2F11ts4gs3dr"
        "!19sChIJ16H8bHUvAwER9OJ41xIye-g"
        "?authuser=0&hl=es-419&rclk=1"
    )

    test_url = example_url
    if len(sys.argv) > 1:
        test_url = sys.argv[1]

    asyncio.run(test_single_url(test_url))
