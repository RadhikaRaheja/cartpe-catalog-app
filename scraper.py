import sys
import json
import re
import time
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    )
}

def extract_video_url(soup):
    """Detects .mp4 video links from the main product page."""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).upper()
        if ("VIDEO" in text or ".mp4" in href.lower()) and not href.startswith("javascript"):
            return href
    video_tag = soup.find("video")
    if video_tag and video_tag.get("src"):
        return video_tag["src"]
    return None

def scrape_vendor(store_name, base_url, slug):
    products = []
    seen_urls = set()
    base_url = base_url.rstrip("/")

    print(f"\n==========================================")
    print(f"Starting Scraper for: {store_name}")
    print(f"==========================================")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=HEADERS["User-Agent"])
        page = context.new_page()

        # 1. Gather Categories
        categories = []
        try:
            page.goto(f"{base_url}/allcategory.html", timeout=45000)
            soup = BeautifulSoup(page.content(), "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.endswith(".html") and not any(x in href for x in ["login", "cart", "account", "order", "allcategory"]):
                    full_url = href if href.startswith("http") else f"{base_url}/{href.lstrip('/')}"
                    if full_url not in categories:
                        categories.append(full_url)
        except Exception:
            categories = [base_url]

        # 2. Iterate Through Categories and Pagination
        for cat_url in categories:
            print(f"\nScanning Category: {cat_url}")
            for page_num in range(1, 10): # Checks up to 9 pages per category
                paged_url = f"{cat_url}?page={page_num}" if "?" not in cat_url else f"{cat_url}&page={page_num}"
                try:
                    page.goto(paged_url, timeout=30000)
                    soup = BeautifulSoup(page.content(), "html.parser")
                    prod_links = soup.find_all("a", href=re.compile(r"-npi\d+-"))
                    
                    if not prod_links:
                        break # No more products on this page, move to next category

                    for a in prod_links:
                        prod_url = a["href"]
                        if prod_url.startswith("/"):
                            prod_url = base_url + prod_url

                        if prod_url in seen_urls:
                            continue
                        seen_urls.add(prod_url)

                        # 3. Scrape Individual Product Page
                        try:
                            page.goto(prod_url, timeout=45000)
                            p_soup = BeautifulSoup(page.content(), "html.parser")

                            title_el = p_soup.find("h1")
                            title = title_el.get_text(strip=True) if title_el else "Unknown Product"

                            price_el = p_soup.find("h6")
                            price_raw = price_el.get_text(strip=True) if price_el else "0"
                            price_num = re.sub(r"[^\d]", "", price_raw)
                            base_price = int(price_num) if price_num else 0

                            # Determine Category for Formatting
                            category = "accessory"
                            cat_text = cat_url.lower()
                            if "shoe" in cat_text or "sneaker" in cat_text or "croc" in cat_text or "flipflop" in cat_text:
                                category = "footwear"
                            elif "bag" in cat_text or "clutch" in cat_text:
                                category = "bag"

                            in_stock = "OUT OF STOCK" not in p_soup.get_text().upper()

                            # STRICT IMAGE SELECTION: Only target the main carousel container
                            images = []
                            # Cartpe usually wraps the main product images in a section directly under the title container
                            # By targeting the ul/li elements that hold the main images, we avoid related products
                            main_gallery = p_soup.find("ul") or p_soup.find("div", {"role": "main"}) 
                            if main_gallery:
                                for img in main_gallery.find_all("img", src=re.compile(r"gallery_(md|lg)")):
                                    src = img["src"]
                                    if src not in images:
                                        images.append(src)

                            video_url = extract_video_url(p_soup)

                            if images and title != "Unknown Product":
                                products.append({
                                    "vendor": store_name,
                                    "category": category,
                                    "title": title,
                                    "base_price": base_price,
                                    "in_stock": in_stock,
                                    "images": images,
                                    "video": video_url,
                                    "url": prod_url
                                })
                                print(f"✔ Scraped: {title[:30]}... | Category: {category}")

                        except Exception as err:
                            pass # Skip item on error
                except Exception as err:
                    break # Stop pagination loop on error

        browser.close()

    output_filename = f"{slug}.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(products)} products to {output_filename}")

if __name__ == "__main__":
    if len(sys.argv) >= 4:
        scrape_vendor(sys.argv[1], sys.argv[2], sys.argv[3])
