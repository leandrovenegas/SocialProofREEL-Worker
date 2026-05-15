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
    """
    reviews_data = []
    async with async_playwright() as p:
        # Launching Chromium as pre-installed in the Docker container
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        try:
            print(f"Navigating to: {url}")
            await page.goto(url, wait_until='networkidle', timeout=60000)

            # Wait for the main reviews container to load
            # This selector is common for the reviews tab or section
            await page.wait_for_selector('div[data-review-id]', timeout=20000)

            # Scroll to ensure images/reviews are loaded
            for _ in range(3):
                await page.mouse.wheel(0, 2000)
                await asyncio.sleep(2)

            review_elements = await page.query_selector_all('div[data-review-id]')
            print(f"Found {len(review_elements)} potential reviews.")
            
            for i, review_elem in enumerate(review_elements[:3]):
                # Extract text
                # Google often uses different classes, so we try a few common ones
                text_elem = await review_elem.query_selector('.MyEned, span[jsaction*="full-review"]')
                text = await text_elem.inner_text() if text_elem else ""

                # Extract rating
                rating_elem = await review_elem.query_selector('[aria-label*="stars"]')
                rating_label = await rating_elem.get_attribute('aria-label') if rating_elem else "0"
                rating_match = re.search(r'(\d+)', rating_label)
                rating = int(rating_match.group(1)) if rating_match else 0

                # Extract reviewer name
                name_elem = await review_elem.query_selector('.d4r55') # Common name class
                name = await name_elem.inner_text() if name_elem else "Anonymous"

                # Extract avatar URL - Prioritizing real images
                # Look for img tags within the review element
                avatar_img = await review_elem.query_selector('img[src*="googleusercontent.com"]')
                avatar_url = await avatar_img.get_attribute('src') if avatar_img else ""
                
                # If we have a URL, let's try to get a higher resolution version if possible
                if avatar_url and "=s" in avatar_url:
                    avatar_url = re.sub(r'=s\d+.*', '=s256-c', avatar_url)

                reviews_data.append({
                    "reviewer_name": name,
                    "review_text": text,
                    "rating": rating,
                    "avatar_url": avatar_url
                })
                
        except Exception as e:
            print(f"Scraping error: {e}")
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
