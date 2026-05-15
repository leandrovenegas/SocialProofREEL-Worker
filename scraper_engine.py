import os
import json
import re
import hashlib
import asyncio
import requests
from playwright.async_api import async_playwright

# Define the base temporary directory relative to the script\'s location
BASE_TEMP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp", "leads")

def extract_business_id(url):
    """
    Extracts a unique business ID from the Google Maps URL.
    For POC, we\'ll hash the URL. In a real scenario, this might parse a place ID.
    """
    return hashlib.md5(url.encode(\'utf-8\')).hexdigest()

async def scrape_reviews_with_playwright(url):
    """
    Scrapes the top 3 reviews (text, rating, avatar URL) from a Google Maps URL using Playwright.
    Focuses on waiting for dynamic content to load reliably.
    """
    reviews_data = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until=\'domcontentloaded\')

            # Give it some time for initial content to load
            await page.wait_for_timeout(3000)

            # Scroll the review section to load more reviews
            # Identify the scrollable container for reviews. This selector is a common pattern for Google Maps review sections.
            # It might need adjustment based on specific Google Maps UI variations.
            scrollable_selector = 'div[aria-label*="Reviews for"]' 
            
            # Wait for the scrollable element to be present
            await page.wait_for_selector(scrollable_selector, timeout=10000)

            # Scroll multiple times to ensure enough reviews are loaded
            for _ in range(5):
                await page.evaluate(f"document.querySelector('{scrollable_selector}').scrollTop += 500;")
                await page.wait_for_timeout(1000) # Give time for new content to load

            # Wait for review elements to appear after scrolling
            await page.wait_for_selector('div[data-review-id]', timeout=10000)

            review_elements = await page.query_selector_all('div[data-review-id]')
            
            for i, review_elem in enumerate(review_elements[:3]): # Take top 3 reviews
                review_text_element = await review_elem.query_selector('span[jsaction*="full-review"]')
                if not review_text_element:
                    # Fallback to a more general text selector if 'full-review' isn't present initially
                    review_text_element = await review_elem.query_selector('span.MyEned') 
                
                review_text_content = await review_text_element.inner_text() if review_text_element else ''

                rating_element = await review_elem.query_selector('[aria-label*="stars"]')
                rating_aria_label = await rating_element.get_attribute('aria-label') if rating_element else '0 stars'
                rating_match = re.search(r'(\d+\.?\d*)', rating_aria_label)
                rating = float(rating_match.group(1)) if rating_match else 0.0

                # Avatar image selector. Google often uses data-url or src attributes.
                avatar_img = await review_elem.query_selector('img[src*="googleusercontent.com"], img.WEBjEd') 
                avatar_url = await avatar_img.get_attribute('src') if avatar_img else ''
                
                reviews_data.append({
                    "text": review_text_content,
                    "rating": rating,
                    "avatar_url": avatar_url
                })
        except Exception as e:
            print(f"Playwright scraping error: {e}")
        finally:
            await browser.close()
    return reviews_data

def download_avatar(avatar_url, business_id, review_index):
    """
    Downloads an avatar image and saves it locally.
    """
    if not avatar_url:
        print(f"No avatar URL provided for review {review_index}.")
        return None

    lead_dir = os.path.join(BASE_TEMP_DIR, business_id)
    os.makedirs(lead_dir, exist_ok=True)
    
    local_path = os.path.join(lead_dir, f"avatar_{review_index}.jpg")
    
    try:
        # Playwright should give a direct image URL, so requests is fine here
        response = requests.get(avatar_url, stream=True)
        response.raise_for_status()
        with open(local_path, \'wb\') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return local_path
    except requests.exceptions.RequestException as e:
        print(f"Error downloading avatar from {avatar_url}: {e}")
        return None

def save_metadata(business_id, reviews_data):
    """
    Saves the scraped review data and local avatar paths to a metadata.json file.
    """
    lead_dir = os.path.join(BASE_TEMP_DIR, business_id)
    os.makedirs(lead_dir, exist_ok=True)
    
    metadata_path = os.path.join(lead_dir, "metadata.json")
    
    with open(metadata_path, \'w\', encoding=\'utf-8\') as f:
        json.dump({
            "business_id": business_id,
            "reviews": reviews_data
        }, f, ensure_ascii=False, indent=4)
    
    return metadata_path

async def test_single_url(url):
    """
    Tests the scraping process for a single Google Maps URL using Playwright.
    """
    print(f"Starting Playwright scraping process for URL: {url}")
    try:
        business_id = extract_business_id(url)
        print(f"Extracted Business ID: {business_id}")

        reviews_data = await scrape_reviews_with_playwright(url)
        print(f"Scraped {len(reviews_data)} reviews.")

        for i, review in enumerate(reviews_data):
            if review["avatar_url"]:
                local_avatar_path = download_avatar(review["avatar_url"], business_id, i)
                review["avatar_local_path"] = local_avatar_path
            else:
                review["avatar_local_path"] = None # No avatar downloaded

        metadata_path = save_metadata(business_id, reviews_data)
        print(f"Metadata saved to: {metadata_path}")
        print("Playwright scraping process completed successfully!")
        return metadata_path
    except Exception as e:
        print(f"An error occurred during Playwright scraping: {e}")
        return None

if __name__ == "__main__":
    # Example Usage: Replace with a real Google Maps URL for testing
    example_url = "https://www.google.com/maps/place/The+British+Museum/@51.5194467,-0.1270026,17z/data=!4m8!1m2!2m1!1sBritish+Museum+reviews!3m4!1s0x48761b4742467d1b:0x5e0892040685601d!8m2!3d51.5194467!4d-0.1269986?hl=en"
    asyncio.run(test_single_url(example_url))
