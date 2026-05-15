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
# We use os.path.join to maintain compatibility, but targeting /app/temp/leads
BASE_TEMP_DIR = os.path.join(BASE_DIR, "temp", "leads")

def extract_business_id(url):
    """
    Extracts a unique business ID from the Google Maps URL.
    Used to create the directory structure for the data bridge.
    """
    return hashlib.md5(url.encode('utf-8')).hexdigest()

async def scrape_reviews_with_playwright(url):
    """
    DUMB SCRAPER: Focuses solely on materializing review data and avatar URLs.
    Does not know about video rendering or cloud uploads.

    RESILIENCE LAYERS:
      1. wait_until='load'  — Google Maps never reaches networkidle; use 'load' instead.
      2. Viewport 1280x720  — ensures all elements are within visible bounds.
      3. Cookie banner      — dismisses Google's consent wall before interacting.
      4. Reviews tab click  — URL lands on Overview; must click the Reviews tab.
      5. Pre-scroll         — wakes up lazy-loaded review cards before the wait.
      6. Debug screenshot   — saved to /app/temp/debug_screenshot.png on any failure.
    """
    reviews_data = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 720},   # RESILIENCE #2
            locale="es-419",
        )
        page = await context.new_page()
        debug_screenshot_path = os.path.join(BASE_DIR, "temp", "debug_screenshot.png")

        try:
            print(f"[NAV] Navigating to: {url}")
            # RESILIENCE #1: 'load' fires as soon as the HTML is parsed + resources
            # fetched. 'networkidle' never fires on Google Maps (continuous requests).
            await page.goto(url, wait_until="load", timeout=60000)
            print("[NAV] Page 'load' event fired.")
            print(f"[NAV] Page title: '{await page.title()}'")
            print(f"[NAV] Current URL: {page.url}")

            # Give JS a moment to hydrate the SPA shell.
            await asyncio.sleep(3)

            # CHECKPOINT SCREENSHOT: Capture what the headless browser sees right
            # after load, before any interaction. Critical for diagnosing consent
            # walls, CAPTCHAs, or unexpected redirects.
            os.makedirs(os.path.dirname(debug_screenshot_path), exist_ok=True)
            await page.screenshot(path=debug_screenshot_path, full_page=False)
            print(f"[CHECKPOINT] Screenshot saved → {debug_screenshot_path}")

            # RESILIENCE #3: Dismiss Google's cookie/consent banner if present.
            cookie_selectors = [
                'button:has-text("Aceptar todo")',
                'button:has-text("Accept all")',
                'button:has-text("Tout accepter")',
                'button[aria-label*="Accept"]',
                'form[action*="consent"] button',
            ]
            for sel in cookie_selectors:
                try:
                    btn = await page.wait_for_selector(sel, timeout=1500)
                    if btn:
                        await btn.click()
                        print(f"[COOKIE] Banner dismissed: '{sel}'")
                        await asyncio.sleep(2)
                        # Save post-cookie screenshot.
                        await page.screenshot(path=debug_screenshot_path.replace(".png", "_postcookie.png"), full_page=False)
                        break
                except Exception:
                    pass
            else:
                print("[COOKIE] No banner found — page is clean.")

            # RESILIENCE #4: Click the "Reseñas" / "Reviews" tab.
            # The URL lands on the Overview panel; reviews live in a separate tab.
            reviews_tab_selectors = [
                'button[aria-label*="eseña"]',           # Reseñas (es)
                'button[aria-label*="eview"]',           # Reviews (en)
                '[role="tab"]:has-text("Reseñas")',
                '[role="tab"]:has-text("Reviews")',
                'button[jsaction*="reviews"]',
            ]
            tab_clicked = False
            for sel in reviews_tab_selectors:
                try:
                    tab = await page.wait_for_selector(sel, timeout=2000)
                    if tab:
                        await tab.click()
                        print(f"[TAB] Reviews tab clicked: '{sel}'")
                        await asyncio.sleep(3)
                        tab_clicked = True
                        break
                except Exception:
                    pass

            if not tab_clicked:
                # Dump all visible buttons/tabs to help identify the correct selector.
                buttons = await page.query_selector_all('button, [role="tab"]')
                labels = []
                for b in buttons[:20]:
                    lbl = await b.get_attribute("aria-label") or await b.inner_text() or ""
                    if lbl.strip():
                        labels.append(lbl.strip()[:60])
                print(f"[TAB] WARNING: Reviews tab not found. Visible buttons/tabs: {labels}")
                # Save a screenshot at this point to see current page state.
                await page.screenshot(path=debug_screenshot_path.replace(".png", "_notab.png"), full_page=False)

            # RESILIENCE #5: Gentle scroll to wake up lazy-loaded review cards.
            await page.mouse.wheel(0, 500)
            await asyncio.sleep(1.5)

            # Wait for the review cards with a generous budget.
            print("[WAIT] Waiting for div[data-review-id]...")
            await page.wait_for_selector("div[data-review-id]", timeout=30000)
            print("[WAIT] Review cards detected.")

            # Deep scroll to load more cards / avatar images.
            for _ in range(4):
                await page.mouse.wheel(0, 2000)
                await asyncio.sleep(2)

            review_elements = await page.query_selector_all("div[data-review-id]")
            print(f"[PARSE] Found {len(review_elements)} review cards.")

            for i, review_elem in enumerate(review_elements[:3]):
                # --- Text ---
                text_elem = await review_elem.query_selector(
                    '.MyEned, span[jsaction*="full-review"], .wiI7pd'
                )
                text = await text_elem.inner_text() if text_elem else ""

                # --- Rating ---
                # aria-label can be "4 stars" or "4 estrellas"
                rating_elem = await review_elem.query_selector(
                    '[aria-label*="star"], [aria-label*="estrella"]'
                )
                rating_label = await rating_elem.get_attribute("aria-label") if rating_elem else "0"
                rating_match = re.search(r"(\d+)", rating_label)
                rating = int(rating_match.group(1)) if rating_match else 0

                # --- Name ---
                name_elem = await review_elem.query_selector(".d4r55, .NfpymFe")
                name = await name_elem.inner_text() if name_elem else "Anonymous"

                # --- Avatar ---
                avatar_img = await review_elem.query_selector('img[src*="googleusercontent.com"]')
                avatar_url = await avatar_img.get_attribute("src") if avatar_img else ""
                if avatar_url and "=s" in avatar_url:
                    avatar_url = re.sub(r"=s\d+.*", "=s256-c", avatar_url)

                reviews_data.append({
                    "reviewer_name": name,
                    "review_text": text,
                    "rating": rating,
                    "avatar_url": avatar_url,
                })
                print(f"[PARSE] Review {i+1}: {name} ({rating}★)")

        except Exception as e:
            print(f"[ERROR] Scraping failed: {e}")
            # RESILIENCE #6: Save a screenshot for post-mortem debugging.
            try:
                os.makedirs(os.path.dirname(debug_screenshot_path), exist_ok=True)
                await page.screenshot(path=debug_screenshot_path, full_page=False)
                print(f"[DEBUG] Screenshot saved → {debug_screenshot_path}")
            except Exception as ss_err:
                print(f"[DEBUG] Could not save screenshot: {ss_err}")
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
        with open(local_path, 'wb') as f:
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
    
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump({
            "business_id": business_id,
            "status": "ready_for_render",
            "reviews": reviews_data
        }, f, ensure_ascii=False, indent=4)
    
    return metadata_path

async def test_single_url(url):
    """
    POC: Validates that the Scraper creates the local bridge folder correctly.
    """
    print(f"--- SCRAPER ENGINE START ---")
    business_id = extract_business_id(url)
    print(f"Lead ID: {business_id}")

    # 1. Scrape
    reviews_data = await scrape_reviews_with_playwright(url)
    
    if not reviews_data:
        print("No reviews found. Stopping.")
        return

    # 2. Materialize Assets
    for i, review in enumerate(reviews_data):
        print(f"Processing review {i+1}...")
        local_path = download_avatar(review["avatar_url"], business_id, i)
        review["avatar_local_path"] = local_path # The Renderer will use this field

    # 3. Create Bridge Contract
    metadata_path = save_metadata(business_id, reviews_data)
    
    print(f"--- SUCCESS ---")
    print(f"Folder Materialized: {os.path.join(BASE_TEMP_DIR, business_id)}")
    print(f"Metadata Contract: {metadata_path}")

if __name__ == "__main__":
    import sys
    example_url = "https://www.google.com/maps/place/Telocuido+Petsitter/data=!4m7!3m6!1s0x1032f756cfca1d7:0xe87b3212d778e2f4!8m2!3d-32.9979487!4d-71.4582527!16s%2Fg%2F11ts4gs3dr!19sChIJ16H8bHUvAwER9OJ41xIye-g?authuser=0&hl=es-419&rclk=1" # Updated URL
    
    # Default test URL if none provided
    test_url = example_url # Initialize test_url with example_url

    if len(sys.argv) > 1:
        test_url = sys.argv[1]

    asyncio.run(test_single_url(test_url))
