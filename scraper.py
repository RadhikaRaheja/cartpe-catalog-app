import json
import time
import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

STORES = [
    {"name": "Le Brouges Sneakers", "url": "https://le-brouges-resell.cartpe.in"},
    {"name": "Bagworld by Dolly", "url": "https://bagworld1.cartpe.in"},
    {"name": "Bag4u by Dolly", "url": "https://bag4u.cartpe.in"},
    {"name": "Muzammil Surat", "url": "https://mtcollection.cartpe.in"},
    {"name": "Le Brouges Bags", "url": "https://lebrouges-bags.cartpe.in"}
]

def auto_scroll(page):
    """Scrolls down the page to trigger infinite loading."""
    for _ in range(5):  # Adjust range for deeper scrolling
        page.keyboard.press("End")
        time.sleep(2)

def scrape_all():
    products = []
    seen_urls = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for store in STORES:
            store_name = store["name"]
            base_url = store["url"].rstrip("/")
            print(f"\n--- Scanning {store_name} ---")

            # 1. Get Categories
            categories = []
            try:
                page.goto(f"{base_url}/allcategory.html", timeout=60000)
                links = page.locator("a").all()
                for link in links:
                    href = link.get_attribute("href")
                    if href and href.endswith(".html") and "login" not in href and "cart" not in href:
                        full_url = href if href.startswith("http") else base_url + ("/" if not href.startswith("/") else "") + href
                        if full_url not in categories:
                            categories.append(full_url)
            except Exception as e:
                print(f"Error fetching categories: {e}")
                categories = [base_url]

            # 2. Scrape Category Pages
            for cat_url in categories:
                print(f"Checking category: {cat_url}")
                try:
                    page.goto(cat_url, timeout=60000)
                    auto_scroll(page) # Scroll to load items
                    
                    html = page.content()
                    soup = BeautifulSoup(html, "html.parser")
                    prod_links = soup.find_all("a", href=re.compile(r"-npi\d+-"))

                    for a in prod_links:
                        prod_url = a["href"]
                        if prod_url.startswith("/"):
                            prod_url = base_url + prod_url

                        if prod_url in seen_urls:
                            continue
                        seen_urls.add(prod_url)

                        # 3. Scrape Product Details
                        try:
                            page.goto(prod_url, timeout=60000)
                            p_html = page.content()
                            p_soup = BeautifulSoup(p_html, "html.parser")

                            # Title & Price
                            title = p_soup.find("h1").get_text(strip=True) if p_soup.find("h1") else "Unknown"
                            price = p_soup.find("h6").get_text(strip=True) if p_soup.find("h6") else "0"
                            
                            # Clean price (extract just numbers)
                            price_num = re.sub(r'[^\d.]', '', price)

                            # Category from Breadcrumbs (usually inside a nav tag near the title)
                            category = "General"
                            nav_tag = p_soup.find("nav")
                            if nav_tag:
                                breadcrumbs = nav_tag.find_all("a")
                                if len(breadcrumbs) > 1:
                                    category = breadcrumbs[-1].get_text(strip=True)

                            # Stock Status
                            in_stock = "Out Of Stock" not in p_soup.get_text()

                            # Images (Restrict to main product viewer, usually a slider or specific ul/div)
                            images = []
                            # Look specifically for the main gallery images, avoiding related products
                            main_area = p_soup.find("div", {"role": "main"}) or p_soup
                            for img in main_area.find_all("img", src=re.compile(r"gallery_(md|lg)")):
                                src = img["src"]
                                if src not in images:
                                    images.append(src)

                            # Videos (Look for "DOWNLOAD VIDEO" or "VIEW VIDEO" buttons)
                            video_url = None
                            vid_btn = p_soup.find("a", string=re.compile(r"VIDEO", re.IGNORECASE))
                            if vid_btn and vid_btn.get("href"):
                                video_url = vid_btn["href"]

                            if images and title != "Unknown":
                                products.append({
                                    "id": len(products) + 1,
                                    "vendor": store_name,
                                    "category": category,
                                    "title": title,
                                    "base_price": int(price_num) if price_num else 0,
                                    "in_stock": in_stock,
                                    "images": images,
                                    "video": video_url
                                })
                                print(f"Scraped: {title} | Video: {'Yes' if video_url else 'No'}")
                        except Exception as e:
                            print(f"Skipping product due to error: {e}")
                except Exception as e:
                     print(f"Skipping category due to error: {e}")

        browser.close()

    with open("catalog.json", "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(products)} total products.")

if __name__ == "__main__":
    scrape_all()
