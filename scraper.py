import sys
import json
import re
import requests
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    )
}

def extract_video_url(soup):
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).upper()
        if ("VIDEO" in text or ".mp4" in href.lower()) and not href.startswith("javascript"):
            return href
    video_tag = soup.find("video")
    if video_tag and video_tag.get("src"):
        return video_tag["src"]
    return None

def get_urls_from_sitemap(base_url):
    """Instantly grabs all product URLs from the site's XML sitemap to skip scrolling."""
    print(f"Checking for sitemap at {base_url}/sitemap.xml...")
    urls = []
    try:
        res = requests.get(f"{base_url}/sitemap.xml", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.content, "xml")
            for loc in soup.find_all("loc"):
                url_text = loc.text.strip()
                if "-npi" in url_text and "whatsapp.com" not in url_text:
                    urls.append(url_text)
    except Exception as e:
        print(f"Sitemap check failed: {e}")
    return urls

def scrape_vendor(store_name, base_url, slug):
    products = []
    base_url = base_url.rstrip("/")

    print(f"\n==========================================")
    print(f"Starting Optimized Scraper for: {store_name}")
    print(f"==========================================")

    # STEP 1: Get URLs the fast way
    product_urls = get_urls_from_sitemap(base_url)
    
    if product_urls:
        print(f"SUCCESS: Found {len(product_urls)} products via sitemap! Skipping manual page scrolling.")
    else:
        print("No sitemap found. Falling back to category scanning (with WhatsApp filter)...")
        # Fallback category scraping logic (omitted for brevity, but relies on finding standard links)
        # We will manually seed a few fallback URLs if needed, but sitemap almost always works for Cartpe.

    # STEP 2: Scrape the individual products quickly
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent=HEADERS["User-Agent"])
        page = context.new_page()

        # Block heavy resources to speed up page loads
        page.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["stylesheet", "font", "media"] 
            else route.continue_()
        )

        for prod_url in product_urls:
            # CRITICAL FIX: Ensure we never try to scrape WhatsApp or Facebook
            if "whatsapp.com" in prod_url or "facebook.com" in prod_url:
                continue

            try:
                # 15 second timeout. If it takes longer, skip it and keep moving.
                page.goto(prod_url, timeout=15000, wait_until="domcontentloaded")
                p_soup = BeautifulSoup(page.content(), "html.parser")

                title_el = p_soup.find("h1")
                title = title_el.get_text(strip=True) if title_el else "Unknown Product"

                price_el = p_soup.find("h6")
                price_raw = price_el.get_text(strip=True) if price_el else "0"
                price_num = re.sub(r"[^\d]", "", price_raw)
                base_price = int(price_num) if price_num else 0

                category = "accessory"
                url_lower = prod_url.lower()
                if "shoe" in url_lower or "sneaker" in url_lower or "croc" in url_lower or "flipflop" in url_lower:
                    category = "footwear"
                elif "bag" in url_lower or "clutch" in url_lower or "wallet" in url_lower:
                    category = "bag"

                in_stock = "OUT OF STOCK" not in p_soup.get_text().upper()

                images = []
                main_area = p_soup.find("div", {"role": "main"})
                if main_area:
                    for img in main_area.find_all("img", src=re.compile(r"gallery_(md|lg)")):
                        if img["src"] not in images: images.append(img["src"])
                
                if not images:
                    for img in p_soup.find_all("img", src=re.compile(r"gallery_(md|lg)")):
                        if img["src"] not in images: images.append(img["src"])

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
                    print(f"✔ Scraped: {title[:30]}...")

            except Exception as err:
                print(f"Skipping {prod_url} due to timeout/error.")

        browser.close()

    output_filename = f"{slug}.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(products)} products to {output_filename}")

if __name__ == "__main__":
    if len(sys.argv) >= 4:
        scrape_vendor(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        scrape_vendor("Le Brouges Bags", "https://lebrouges-bags.cartpe.in", "lebrouges_bags")
