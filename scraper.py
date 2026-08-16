import sys
import json
import re
import time
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    )
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)

def extract_video_url(soup):
    """Detects .mp4 video links from product HTML."""
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(strip=True).upper()
        if ("VIDEO" in text or ".mp4" in href.lower()) and not href.startswith("javascript"):
            return href
    video_tag = soup.find("video")
    if video_tag and video_tag.get("src"):
        return video_tag["src"]
    for btn in soup.find_all(["button", "a", "div"], onclick=True):
        match = re.search(r"'(https?://[^']+\.mp4[^']*)'", btn["onclick"])
        if match:
            return match.group(1)
    return None

def get_product_links_from_category(cat_url, base_url):
    """Scrapes product links across pagination pages rapidly."""
    links = set()
    for page in range(1, 15):
        paged_url = f"{cat_url}?page={page}" if "?" not in cat_url else f"{cat_url}&page={page}"
        try:
            res = SESSION.get(paged_url, timeout=10)
            if res.status_code != 200:
                break
            soup = BeautifulSoup(res.text, "html.parser")
            found_on_page = False
            for a in soup.find_all("a", href=re.compile(r"-npi\d+-")):
                href = a["href"]
                if "whatsapp.com" in href or "facebook.com" in href:
                    continue
                full_url = href if href.startswith("http") else f"{base_url}/{href.lstrip('/')}"
                links.add(full_url)
                found_on_page = True
            
            if not found_on_page:
                break
        except Exception:
            break
    return list(links)

def parse_product_page(prod_url, store_name, category_hint):
    """Direct HTTP request to extract isolated media and details."""
    try:
        res = SESSION.get(prod_url, timeout=8)
        if res.status_code != 200:
            return None

        soup = BeautifulSoup(res.text, "html.parser")

        title_el = soup.find("h1")
        title = title_el.get_text(strip=True) if title_el else "Unknown Product"

        price_el = soup.find("h6")
        price_num = re.sub(r"[^\d]", "", price_el.get_text(strip=True)) if price_el else ""
        base_price = int(price_num) if price_num else 0

        # Category segregation
        category = category_hint
        url_lower = prod_url.lower()
        if any(w in url_lower for w in ["shoe", "sneaker", "croc", "flipflop"]):
            category = "footwear"
        elif any(w in url_lower for w in ["bag", "clutch", "wallet"]):
            category = "bag"

        in_stock = "OUT OF STOCK" not in soup.get_text().upper()

        # Strict image gallery extraction (ignoring related items)
        images = []
        main_area = soup.find("div", {"role": "main"}) or soup
        for img in main_area.find_all("img", src=re.compile(r"gallery_(md|lg)")):
            src = img["src"]
            if src not in images:
                images.append(src)

        video_url = extract_video_url(soup)

        if images and title != "Unknown Product":
            return {
                "vendor": store_name,
                "category": category,
                "title": title,
                "base_price": base_price,
                "in_stock": in_stock,
                "images": images,
                "video": video_url,
                "url": prod_url
            }
    except Exception:
        pass
    return None

def scrape_segment(store_name, base_url, category_path, slug):
    base_url = base_url.rstrip("/")
    cat_url = f"{base_url}/{category_path.lstrip('/')}" if category_path else base_url
    print(f"\nScanning {store_name} -> {cat_url}")

    product_urls = get_product_links_from_category(cat_url, base_url)
    print(f"Found {len(product_urls)} links. Parsing products...")

    products = []
    category_hint = "bag" if "bag" in category_path.lower() else "footwear"

    for idx, url in enumerate(product_urls, start=1):
        item = parse_product_page(url, store_name, category_hint)
        if item:
            products.append(item)
            if idx % 10 == 0:
                print(f"Processed {idx}/{len(product_urls)} items...")

    output_filename = f"{slug}.json"
    with open(output_filename, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(products)} products to {output_filename}")

if __name__ == "__main__":
    if len(sys.argv) >= 5:
        scrape_segment(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        # Default test segment
        scrape_segment("Le Brouges Bags", "https://lebrouges-bags.cartpe.in", "allcategory.html", "lebrouges_bags")
