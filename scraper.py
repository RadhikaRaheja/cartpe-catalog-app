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
        # Launching with arguments to prevent being blocked by the server
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
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
        except Exception as e:
            print(f"Automatic category scan failed: {e}")

        # Fallback Safety Net: If the category page fails to load, force the known ones
        if not categories:
            print("Using fallback category list...")
            categories = [
                f"{base_url}/flipflops-footwear.html",
                f"{base_url}/men-rsquo-s-shoe-footwear.html",
                f"{base_url}/ladies-shoes-footwear-women.html",
                f"{base_url}/premium-shoes-footwear.html",
                base_url
            ]

        # 2. Iterate Through Categories & Click "View More"
        for cat_url in categories:
            print(f"\nScanning Category: {cat_url}")
            try:
                page.goto(cat_url, timeout=45000)
                
                # Scroll and physically click "View More" up to 12 times to load older articles
                for _ in range(12): 
                    page.keyboard.press("End")
                    time.sleep(1.5)
                    try:
                        view_more = page.get_by_text("View More", exact=False)
                        if view_more.is_visible():
                            view_more.click()
                            time.sleep(2)
                        else:
                            break # Button is gone, everything is loaded
                    except:
                        break

                soup = BeautifulSoup(page.content(), "html.parser")
                prod_links = soup.find_all("a", href=re.compile(r"-npi\d+-"))

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

                        # Determine Category for your custom WhatsApp text formatting
                        category = "accessory"
                        cat_text = cat_url.lower()
                        if "shoe" in cat_text or "sneaker" in cat_text or "croc" in cat_text or "flipflop" in cat_text:
                            category = "footwear"
                        elif "bag" in cat_text or "clutch" in cat_text:
                            category = "bag"

                        in_stock = "OUT OF STOCK" not in p_soup.get_text().upper()

                        # Image Extraction - Priority 1: The main isolated product gallery
                        images = []
                        main_area = p_soup.find("div", {"role": "main"})
                        if main_area:
                            for img in main_area.find_all("img", src=re.compile(r"gallery_(md|lg)")):
                                if img["src"] not in images: images.append(img["src"])
                        
                        # Image Extraction - Priority 2: Fallback if standard layout is missing
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
                            print(f"✔ Scraped: {title[:30]}... | Category: {category}")

                    except Exception as err:
                        print(f"Skipping product due to error: {err}")
            except Exception as err:
                print(f"Skipping category due to error: {err}")

        browser.close()

    output_filename = f"{slug}.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(products)} products to {output_filename}")

if __name__ == "__main__":
    if len(sys.argv) >= 4:
        scrape_vendor(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        # Fallback if run manually without arguments
        scrape_vendor("Le Brouges Resell", "https://le-brouges-resell.cartpe.in", "le_brouges_resell")
