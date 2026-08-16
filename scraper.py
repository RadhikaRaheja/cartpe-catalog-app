import sys
import json
import re
import time
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
    """Detects .mp4 video links from the main product page."""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if ("VIDEO" in a.get_text(strip=True).upper() or ".mp4" in href.lower()) and not href.startswith("javascript"):
            return href
    video_tag = soup.find("video")
    if video_tag and video_tag.get("src"):
        return video_tag["src"]
    return None

def get_urls_from_sitemap(base_url):
    """Checks if the site has a sitemap to instantly grab URLs."""
    urls = []
    try:
        res = requests.get(f"{base_url}/sitemap.xml", headers=HEADERS, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.content, "xml")
            for loc in soup.find_all("loc"):
                url_text = loc.text.strip()
                if "-npi" in url_text and "whatsapp.com" not in url_text:
                    urls.append(url_text)
    except Exception:
        pass
    return urls

def scrape_vendor(store_name, base_url, slug):
    products = []
    base_url = base_url.rstrip("/")

    print(f"\n==========================================")
    print(f"Starting Deep Scraper for: {store_name}")
    print(f"==========================================")

    product_urls = get_urls_from_sitemap(base_url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent=HEADERS["User-Agent"])
        page = context.new_page()

        page.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["stylesheet", "font", "media", "image"] 
            else route.continue_()
        )

        # AGGRESSIVE FALLBACK SCROLLING: Captures deep/older inventory
        if not product_urls:
            categories = []
            try:
                page.goto(f"{base_url}/allcategory.html", timeout=15000, wait_until="domcontentloaded")
                soup = BeautifulSoup(page.content(), "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if href.endswith(".html") and not any(x in href for x in ["login", "cart", "account", "order"]):
                        full_url = href if href.startswith("http") else f"{base_url}/{href.lstrip('/')}"
                        if full_url not in categories:
                            categories.append(full_url)
            except Exception:
                pass

            if not categories:
                categories = [
                    f"{base_url}/flipflops-footwear.html",
                    f"{base_url}/men-rsquo-s-shoe-footwear.html",
                    f"{base_url}/ladies-shoes-footwear-women.html",
                    f"{base_url}/premium-shoes-footwear.html",
                    base_url
                ]

            seen_links = set()
            for cat_url in categories:
                print(f"Extracting links from: {cat_url}")
                try:
                    page.goto(cat_url, timeout=15000, wait_until="domcontentloaded")
                    # DEEP SCROLL: Click "View More" up to 30 times
                    for _ in range(30):
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
                        if href.startswith("/"):
                            href = base_url + href
                        
                        if href not in seen_links and "whatsapp.com" not in href:
                            seen_links.add(href)
                            product_urls.append(href)
                except Exception:
                    pass

        product_urls = list(set(product_urls))
        print(f"\nTotal product URLs found: {len(product_urls)}")

        for prod_url in product_urls:
            if "whatsapp.com" in prod_url or "facebook.com" in prod_url:
                continue

            try:
                page.goto(prod_url, timeout=15000, wait_until="domcontentloaded")
                p_soup = BeautifulSoup(page.content(), "html.parser")

                title_el = p_soup.find("h1")
                title = title_el.get_text(strip=True) if title_el else "Unknown Product"

                price_el = p_soup.find("h6")
                price_num = re.sub(r"[^\d]", "", price_el.get_text(strip=True)) if price_el else ""
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
                    print(f"✔ Scraped: {title[:35]}...")

            except Exception:
                pass

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
