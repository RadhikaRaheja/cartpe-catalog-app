import sys
import json
import time
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    )
}

def auto_scroll(page):
    """Simulates scrolling to load dynamically rendered products."""
    for _ in range(4):
        page.keyboard.press("PageDown")
        time.sleep(1.5)

def extract_video_url(page, soup):
    """Detects .mp4 video links from buttons, modals, or page source."""
    # 1. Check direct download / view video buttons
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).upper()
        if ("VIDEO" in text or ".mp4" in href.lower()) and not href.startswith("javascript"):
            if "cartpe.in" in href or href.startswith("http"):
                return href

    # 2. Check <video> or <source> tags
    video_tag = soup.find("video")
    if video_tag:
        if video_tag.get("src"):
            return video_tag["src"]
        source_tag = video_tag.find("source")
        if source_tag and source_tag.get("src"):
            return source_tag["src"]

    # 3. Check for onclick scripts containing video URLs
    for btn in soup.find_all(["button", "a", "div"], onclick=True):
        onclick = btn["onclick"]
        match = re.search(r"'(https?://[^']+\.mp4[^']*)'", onclick)
        if match:
            return match.group(1)

    return None

def scrape_vendor(store_name, base_url, slug):
    products = []
    seen_urls = set()
    base_url = base_url.rstrip("/")

    print(f"\n==========================================")
    print(f"Starting Scraper for: {store_name} ({base_url})")
    print(f"==========================================")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=HEADERS["User-Agent"])
        page = context.new_page()

        # Gather Categories
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
            print(f"Category scan fallback to base URL: {e}")
            categories = [base_url]

        for cat_url in categories:
            print(f"\nScanning Category: {cat_url}")
            try:
                page.goto(cat_url, timeout=45000)
                auto_scroll(page)

                soup = BeautifulSoup(page.content(), "html.parser")
                prod_links = soup.find_all("a", href=re.compile(r"-npi\d+-"))

                for a in prod_links:
                    prod_url = a["href"]
                    if prod_url.startswith("/"):
                        prod_url = base_url + prod_url

                    if prod_url in seen_urls:
                        continue
                    seen_urls.add(prod_url)

                    try:
                        page.goto(prod_url, timeout=45000)
                        p_soup = BeautifulSoup(page.content(), "html.parser")

                        # Title
                        title_el = p_soup.find("h1")
                        title = title_el.get_text(strip=True) if title_el else "Unknown Product"

                        # Price
                        price_el = p_soup.find("h6")
                        price_raw = price_el.get_text(strip=True) if price_el else "0"
                        price_num = re.sub(r"[^\d]", "", price_raw)
                        base_price = int(price_num) if price_num else 0

                        # Breadcrumb Category
                        category = "General"
                        nav = p_soup.find("nav")
                        if nav:
                            crumbs = [c.get_text(strip=True) for c in nav.find_all("a")]
                            if len(crumbs) > 1:
                                category = crumbs[-1]

                        # Stock Availability
                        in_stock = "OUT OF STOCK" not in p_soup.get_text().upper()

                        # Isolated Product Gallery (Prevents picking up related products)
                        images = []
                        main_box = p_soup.find("div", {"role": "main"}) or p_soup
                        for img in main_box.find_all("img", src=re.compile(r"gallery_(md|lg)")):
                            src = img["src"]
                            if src not in images:
                                images.append(src)

                        # Video Detection
                        video_url = extract_video_url(page, p_soup)

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
                            print(f"✔ [{store_name}] {title[:35]}... | Video: {'YES' if video_url else 'NO'}")

                    except Exception as err:
                        print(f"Error scraping product {prod_url}: {err}")

            except Exception as err:
                print(f"Error scraping category {cat_url}: {err}")

        browser.close()

    output_filename = f"{slug}.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(products)} products to {output_filename}")

if __name__ == "__main__":
    if len(sys.argv) >= 4:
        scrape_vendor(sys.argv[1], sys.argv[2], sys.argv[3])
    else:
        # Local fallback test
        scrape_vendor("Le Brouges Sneakers", "https://le-brouges-resell.cartpe.in", "le_brouges_sneakers")
