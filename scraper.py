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
    cat_url = f"{base_url}/{category_path.lstrip('/')}" if category_path else base_url

    print(f"\nScanning: {store_name} -> {cat_url}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent=HEADERS["User-Agent"])
        page = context.new_page()

        page.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["stylesheet", "font", "image", "media"] 
            else route.continue_()
        )

        try:
            page.goto(cat_url, timeout=30000, wait_until="domcontentloaded")
            
            for _ in range(25):
                page.keyboard.press("End")
                time.sleep(1)
                try:
                    view_more = page.get_by_text("View More", exact=False)
                    if view_more.is_visible():
                        view_more.click()
                        time.sleep(1.5)
                    else:
                        break
                except:
                    break

            soup = BeautifulSoup(page.content(), "html.parser")
            prod_links = soup.find_all("a", href=re.compile(r"-npi\d+-"))

            for a in prod_links:
                href = a["href"]
                if href.startswith("/"): href = base_url + href
                if "whatsapp.com" not in href and href not in seen_urls:
                    seen_urls.add(href)

            print(f"Found {len(seen_urls)} products. Extracting details...")

            for prod_url in seen_urls:
                try:
                    page.goto(prod_url, timeout=15000, wait_until="domcontentloaded")
                    p_soup = BeautifulSoup(page.content(), "html.parser")

                    title_el = p_soup.find("h1")
                    title = title_el.get_text(strip=True) if title_el else "Unknown"

                    price_el = p_soup.find("h6")
                    price_num = re.sub(r"[^\d]", "", price_el.get_text(strip=True)) if price_el else ""
                    
                    category_hint = "footwear" if "shoe" in category_path.lower() else "bag"
                    
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
                except:
                    pass
        except Exception as e:
            print(f"Failed to load category: {e}")

        browser.close()

    # Push to Supabase Database
    if products:
        print("Pushing data to Supabase...")
        supabase_url = os.environ.get("SUPABASE_URL")
        supabase_key = os.environ.get("SUPABASE_KEY")
        
        if not supabase_url or not supabase_key:
            print("ERROR: Supabase credentials not found in environment variables.")
            return

        supabase: Client = create_client(supabase_url, supabase_key)
        
        success_count = 0
        for p in products:
            try:
                # Upsert automatically updates the price/stock if the URL already exists
                supabase.table("products").upsert(p, on_conflict="url").execute()
                success_count += 1
            except Exception as e:
                print(f"Failed to push {p['title'][:20]}: {e}")
                
        print(f"Successfully pushed {success_count} items to the cloud database.")
    else:
        print("No products found to push.")

if __name__ == "__main__":
    if len(sys.argv) >= 5:
        scrape_segment(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        scrape_segment("NM Official", "https://nmofficial.cartpe.in", "allcategory.html", "nm_official")
