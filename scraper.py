import sys
import os
import re
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

def extract_video_url(soup):
    for a in soup.find_all("a", href=True):
        if "VIDEO" in a.get_text(strip=True).upper() or ".mp4" in a["href"].lower():
            if not a["href"].startswith("javascript"):
                return a["href"]
    video_tag = soup.find("video")
    if video_tag and video_tag.get("src"):
        return video_tag["src"]
    return None

def scrape_segment(store_name, base_url, category_path, slug):
    products = []
    seen_urls = set()
    base_url = base_url.rstrip("/")
    
    print(f"\n==========================================")
    print(f"Scanning: {store_name}")
    print(f"==========================================")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent=HEADERS["User-Agent"])
        page = context.new_page()

        page.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["stylesheet", "font", "image", "media"] 
            else route.continue_()
        )

        categories_to_scrape = []
        
        # INTELLIGENT ROUTING: Expand allcategory.html into actual product categories
        if "allcategory" in category_path.lower():
            cat_url = f"{base_url}/allcategory.html"
            print(f"Fetching categories from {cat_url}...")
            try:
                page.goto(cat_url, timeout=30000, wait_until="domcontentloaded")
                soup = BeautifulSoup(page.content(), "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if href.endswith(".html") and not any(x in href for x in ["login", "cart", "account", "order", "allcategory"]):
                        full_url = href if href.startswith("http") else f"{base_url}/{href.lstrip('/')}"
                        if full_url not in categories_to_scrape:
                            categories_to_scrape.append(full_url)
            except Exception as e:
                print(f"Could not load allcategory page: {e}")
                
            if not categories_to_scrape:
                categories_to_scrape = [base_url]
        else:
            categories_to_scrape = [f"{base_url}/{category_path.lstrip('/')}"]

        print(f"Found {len(categories_to_scrape)} category pages to scan.")

        # Step 1: Gather Product URLs from Categories
        for cat_link in categories_to_scrape:
            print(f"Scanning category: {cat_link}")
            try:
                page.goto(cat_link, timeout=15000, wait_until="domcontentloaded")
                # Scroll 10 times per category to gather older inventory safely
                for _ in range(10):
                    page.keyboard.press("End")
                    time.sleep(0.8)
                    try:
                        view_more = page.get_by_text("View More", exact=False)
                        if view_more.is_visible():
                            view_more.click()
                            time.sleep(1)
                        else:
                            break
                    except:
                        break

                soup = BeautifulSoup(page.content(), "html.parser")
                for a in soup.find_all("a", href=re.compile(r"-npi\d+-")):
                    href = a["href"]
                    if href.startswith("/"): href = base_url + href
                    if "whatsapp.com" not in href and href not in seen_urls:
                        seen_urls.add(href)
            except Exception as e:
                pass

        print(f"\nFound {len(seen_urls)} unique product URLs. Extracting details...")

        # Step 2: Extract Product Data
        for idx, prod_url in enumerate(seen_urls, 1):
            try:
                page.goto(prod_url, timeout=15000, wait_until="domcontentloaded")
                p_soup = BeautifulSoup(page.content(), "html.parser")

                title_el = p_soup.find("h1")
                title = title_el.get_text(strip=True) if title_el else "Unknown"

                price_el = p_soup.find("h6")
                price_num = re.sub(r"[^\d]", "", price_el.get_text(strip=True)) if price_el else ""
                
                category_hint = "footwear" if any(w in prod_url.lower() for w in ["shoe","sneaker","croc", "flipflop"]) else "bag"
                
                images = []
                main_area = p_soup.find("div", {"role": "main"}) or p_soup
                for img in main_area.find_all("img", src=re.compile(r"gallery_(md|lg)")):
                    if img["src"] not in images: images.append(img["src"])

                video_url = extract_video_url(p_soup)

                if images and title != "Unknown":
                    products.append({
                        "vendor": store_name,
                        "category": category_hint,
                        "title": title,
                        "base_price": int(price_num) if price_num else 0,
                        "in_stock": "OUT OF STOCK" not in p_soup.get_text().upper(),
                        "images": images,
                        "video": video_url,
                        "url": prod_url
                    })
                if idx % 10 == 0:
                    print(f"Processed {idx}/{len(seen_urls)} products...")
            except:
                pass

        browser.close()

    # Step 3: Push to Supabase Database
    if products:
        print(f"\nPushing {len(products)} products to Supabase...")
        
        supabase_url = os.environ.get("SUPABASE_URL", "").strip()
        supabase_key = os.environ.get("SUPABASE_KEY", "").strip()
        
        # Auto-clean the URL to prevent PGRST125 errors if the secret has extra paths
        supabase_url = re.sub(r'/rest/v1/?$', '', supabase_url)
        supabase_url = supabase_url.rstrip("/")
        
        if not supabase_url or not supabase_key:
            print("ERROR: Supabase credentials not found in environment variables.")
            return

        supabase: Client = create_client(supabase_url, supabase_key)
        
        success_count = 0
        for p in products:
            try:
                # Upsert updates the price/stock if the item already exists in your DB
                supabase.table("products").upsert(p, on_conflict="url").execute()
                success_count += 1
            except Exception as e:
                print(f"Failed to push {p['title'][:20]}: {e}")
                
        print(f"Successfully synced {success_count} items to the cloud database.")
    else:
        print("No products found to push.")

if __name__ == "__main__":
    if len(sys.argv) >= 5:
        scrape_segment(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        scrape_segment("NM Official", "https://nmofficial.cartpe.in", "allcategory.html", "nm_official")
