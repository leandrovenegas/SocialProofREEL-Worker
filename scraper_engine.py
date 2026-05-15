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


def extract_business_id(url):
    """
    Extracts a unique business ID from the Google Maps URL.
    Used to create the directory structure for the data bridge.
    """
    return hashlib.md5(url.encode("utf-8")).hexdigest()


def build_reviews_url(url):
    """
    Transforms any Google Maps place URL into one that directly opens
    the reviews panel by injecting the '!9m1!1b1' data flag.

    This eliminates the need to detect and click a Reviews tab.
    If the URL already contains the flag, it is returned unchanged.

    Also strips session-specific params (authuser, rclk) that may
    trigger bot-detection redirects.
    """
    # Parse into base path and query string first.
    if "?" in url:
        base, qs = url.split("?", 1)
    else:
        base, qs = url, ""

    # Remove session-specific params that may cause bot-detection redirects.
    qs_parts = [p for p in qs.split("&") if not re.match(r"(authuser|rclk)=", p) and p]
    clean_qs = "&".join(qs_parts)

    # If !9m1!1b1 already present, return with cleaned query string only.
    if "!9m1!1b1" in base:
        return f"{base}?{clean_qs}" if clean_qs else base

    # Append the reviews-direct flag to the path.
    reviews_base = f"{base}!9m1!1b1"
    return f"{reviews_base}?{clean_qs}" if clean_qs else reviews_base


async def scrape_reviews_with_playwright(url):
    """
    DUMB SCRAPER: Focuses solely on materializing review data and avatar URLs.
    Does not know about video rendering or cloud uploads.

    STRATEGY:
      - Navigate directly to the reviews URL (!9m1!1b1 flag) — no tab clicking.
      - Use wait_until='load' — Google Maps never reaches 'networkidle'.
      - Dump page title, URL, and visible text after load for diagnosis.
      - Save checkpoint screenshots at every critical stage.
      - Cookie banner handling before waiting for review elements.
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

        # Hide the webdriver flag that signals automation.
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = await context.new_page()

        try:
            print(f"[NAV] Reviews URL: {reviews_url}")
            await page.goto(reviews_url, wait_until="load", timeout=60000)

            # Print immediate diagnostics.
            title = await page.title()
            current_url = page.url
            print(f"[NAV] Page title : '{title}'")
            print(f"[NAV] Current URL: {current_url}")

            # Wait for SPA hydration.
            await asyncio.sleep(4)

            # --- CHECKPOINT SCREENSHOT (stage 1) ---
            await page.screenshot(path=debug_ss, full_page=False)
            print(f"[SS1] Checkpoint screenshot → {debug_ss}")

            # --- Dump visible text for remote diagnosis ---
            body_text = await page.evaluate("() => document.body.innerText")
            excerpt = " | ".join(body_text.split("\n")[:15])
            print(f"[TEXT] Visible text excerpt: {excerpt[:500]}")

            # --- Cookie / consent banner ---
            cookie_selectors = [
                'button:has-text("Aceptar todo")',
                'button:has-text("Accept all")',
                'button:has-text("Tout accepter")',
                'button[aria-label*="Accept"]',
                'form[action*="consent"] button',
            ]
            cookie_dismissed = False
            for sel in cookie_selectors:
                try:
                    btn = await page.wait_for_selector(sel, timeout=2000)
                    if btn:
                        await btn.click()
                        print(f"[COOKIE] Banner dismissed: '{sel}'")
                        await asyncio.sleep(2)
                        cookie_dismissed = True
                        await page.screenshot(
                            path=debug_ss.replace(".png", "_post_cookie.png"),
                            full_page=False,
                        )
                        break
                except Exception:
                    pass
            if not cookie_dismissed:
                print("[COOKIE] No banner detected — continuing.")

            # --- Navigate to Reviews panel ---
            # STRATEGY A: Click the overall star-rating widget.
            # Confirmed visible in debug screenshot (5.0 ★★★★★ at top of sidebar).
            # This is the most reliable CTA to open the reviews list.
            nav_to_reviews = False
            star_selectors = [
                'button[jsaction*="rating"]',
                'span.F7nice',
                '.DkEaL',                             # rating row container
                '[aria-label*="estrella"][role]',
                '[aria-label*="star"][role]',
                'span[role="img"][aria-label*="5"]',
            ]
            for sel in star_selectors:
                try:
                    el = await page.wait_for_selector(sel, timeout=3000)
                    if el:
                        await el.click()
                        print(f"[REVIEWS] Opened via star click: '{sel}'")
                        await asyncio.sleep(3)
                        nav_to_reviews = True
                        break
                except Exception:
                    pass

            # STRATEGY B: Tab selectors fallback.
            if not nav_to_reviews:
                tab_selectors = [
                    'button[aria-label*="eseña"]',
                    'button[aria-label*="eview"]',
                    '[role="tab"]:has-text("Reseñas")',
                    '[role="tab"]:has-text("Reviews")',
                    'button:has-text("Reseñas")',
                    'button:has-text("Reviews")',
                ]
                for sel in tab_selectors:
                    try:
                        tab = await page.wait_for_selector(sel, timeout=2000)
                        if tab:
                            await tab.click()
                            print(f"[REVIEWS] Opened via tab click: '{sel}'")
                            await asyncio.sleep(3)
                            nav_to_reviews = True
                            break
                    except Exception:
                        pass

            if not nav_to_reviews:
                print("[REVIEWS] WARNING: Could not click into reviews — trying !9m1!1b1 URL directly.")

            # --- Pre-scroll to trigger lazy-load ---
            await page.mouse.wheel(0, 500)
            await asyncio.sleep(1.5)

            # --- Wait for review cards ---
            # Primary selector: standard Google Maps review card.
            # Fallback selectors added for DOM variations.
            review_selectors = [
                "div[data-review-id]",
                '[data-review-id]',
                '.jftiEf',          # alternate review container class
                '[class*="review"]',
            ]

            found_selector = None
            for sel in review_selectors:
                try:
                    print(f"[WAIT] Trying selector: {sel}")
                    await page.wait_for_selector(sel, timeout=15000)
                    found_selector = sel
                    print(f"[WAIT] ✓ Review cards detected with: {sel}")
                    break
                except Exception:
                    print(f"[WAIT] ✗ Not found: {sel}")

            if not found_selector:
                # Dump all data-* attributes to help find the real selector.
                data_attrs = await page.evaluate("""
                    () => {
                        const els = document.querySelectorAll('[data-review-id],[data-hveid],[data-local-attribute]');
                        return Array.from(els).slice(0, 10).map(e => ({
                            tag: e.tagName,
                            id: e.id,
                            cls: e.className.substring(0,80),
                            attrs: Array.from(e.attributes).map(a => a.name + '=' + a.value).join(' ').substring(0,120)
                        }));
                    }
                """)
                print(f"[DOM] data-review-id elements found: {data_attrs}")
                raise TimeoutError("No review card selector matched after all fallbacks.")

            # --- Screenshot after reviews loaded ---
            await page.screenshot(
                path=debug_ss.replace(".png", "_reviews_loaded.png"), full_page=False
            )
            print(f"[SS2] Reviews-loaded screenshot saved.")

            # Deep scroll to materialize avatars.
            for _ in range(4):
                await page.mouse.wheel(0, 2000)
                await asyncio.sleep(2)

            review_elements = await page.query_selector_all(found_selector)
            print(f"[PARSE] Found {len(review_elements)} review elements.")

            for i, review_elem in enumerate(review_elements[:3]):
                # --- Text ---
                text_elem = await review_elem.query_selector(
                    ".MyEned, span[jsaction*='full-review'], .wiI7pd, .Jtu6Td"
                )
                text = (await text_elem.inner_text()).strip() if text_elem else ""

                # --- Rating (bilingual aria-label) ---
                rating_elem = await review_elem.query_selector(
                    '[aria-label*="star"], [aria-label*="estrella"]'
                )
                rating_label = (
                    await rating_elem.get_attribute("aria-label") if rating_elem else "0"
                )
                rating_match = re.search(r"(\d+)", rating_label)
                rating = int(rating_match.group(1)) if rating_match else 0

                # --- Name ---
                name_elem = await review_elem.query_selector(".d4r55, .NfpymFe, .WNxzHc")
                name = (await name_elem.inner_text()).strip() if name_elem else "Anonymous"

                # --- Avatar ---
                avatar_img = await review_elem.query_selector(
                    'img[src*="googleusercontent.com"]'
                )
                avatar_url = await avatar_img.get_attribute("src") if avatar_img else ""
                if avatar_url and "=s" in avatar_url:
                    avatar_url = re.sub(r"=s\d+.*", "=s256-c", avatar_url)

                reviews_data.append(
                    {
                        "reviewer_name": name,
                        "review_text": text,
                        "rating": rating,
                        "avatar_url": avatar_url,
                    }
                )
                print(f"[PARSE] Review {i + 1}: '{name}' ({rating}★) — {text[:60]}...")

        except Exception as e:
            print(f"[ERROR] Scraping failed: {e}")
            try:
                await page.screenshot(path=debug_ss.replace(".png", "_error.png"), full_page=False)
                print(f"[SS_ERR] Error screenshot saved → {debug_ss.replace('.png', '_error.png')}")
            except Exception as ss_err:
                print(f"[SS_ERR] Could not save screenshot: {ss_err}")
        finally:
            await browser.close()

    return reviews_data


def download_avatar(avatar_url, business_id, review_index):
    """
    MATERIALIZER: Downloads the avatar to the local lead folder.
    This ensures the Renderer doesn't need internet access.
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
        return local_path
    except Exception as e:
        print(f"Error downloading avatar {review_index}: {e}")
        return None


def save_metadata(business_id, reviews_data):
    """
    THE BRIDGE: Generates the metadata.json contract.
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


async def test_single_url(url):
    """
    POC: Validates that the Scraper creates the local bridge folder correctly.
    """
    print("--- SCRAPER ENGINE START ---")
    business_id = extract_business_id(url)
    print(f"Lead ID: {business_id}")

    # 1. Scrape
    reviews_data = await scrape_reviews_with_playwright(url)

    if not reviews_data:
        print("No reviews found. Stopping.")
        return

    # 2. Materialize Assets
    for i, review in enumerate(reviews_data):
        print(f"Processing review {i + 1}...")
        local_path = download_avatar(review["avatar_url"], business_id, i)
        review["avatar_local_path"] = local_path  # The Renderer will use this field

    # 3. Create Bridge Contract
    metadata_path = save_metadata(business_id, reviews_data)

    print("--- SUCCESS ---")
    print(f"Folder Materialized: {os.path.join(BASE_TEMP_DIR, business_id)}")
    print(f"Metadata Contract: {metadata_path}")


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
