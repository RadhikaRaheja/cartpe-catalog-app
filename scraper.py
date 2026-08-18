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

def clean_video_url(url, base_url):
    if not url or url.strip() in ["#", "/#", "javascript:;", "javascript:void(0)"]:
        return None
    if url.startswith("/"):
        return base_url.rstrip("/") + url
    return url if url.startswith("http") else None

def extract_video_url(soup, base_url):
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True).upper()
        if (".mp4" in href.lower() or "VIDEO" in text) and not href.startswith("javascript") and href not in ["#", "/#"]:
            return clean_video_url(href, base_url)
            
    video_tag = soup.find("video")
    if video_tag:
        src = video_tag.get("src") or (video_tag.find("source") and video_tag.find("source").get("src"))
        if src:
            return clean_video_url(src, base_url)
    return None

def classify_product(title, url):
    text = f"{title} {url}".lower()
    if any(k in text for k in ["perfume", "parfum", "tester", "edp", "edt", "fragrance", "cologne"]):
        return "perfume"
    if any(k in text for k in ["belt", "buckle"]):
        return "belt"
    if any(k in text for k in ["glass", "frame", "wayfarer", "sunglass", "eyewear", "optical"]):
        return "eyewear"
    if any(k in text for k in ["watch", "chronograph", "dial"]):
        return "watch"
    if any(k in text for k in ["shoe", "sneaker", "heel", "sandal", "croc", "flipflop", "boot", "footwear", "slingback"]):
        return "footwear"
    if any(k in text for k in ["bag", "handbag", "tote", "crossbody", "saddle", "clutch", "purse", "backpack", "wallet"]):
        return "bag"
    return "accessories"

def extract_sizes(soup):
    sizes = []
    # Search for size pills or dropdown variants
    for el in soup.find_all(["button", "span", "div", "option"], class_=re.compile(r"size|variant|attribute", re.I)):
        txt = el.get_text(strip=True)
        if re.match(r"^(\d{2}|UK\s*\d+|US\s*\d+|[SMLXL]{1,3})$", txt, re.I):
            if txt not in sizes:
                sizes.append(txt)
    return sizes

def run_sync():
    supabase_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    supabase_key = os.environ.get("SUPABASE_KEY", "").strip()
    supabase_url = re.sub(r'/rest/v1/?$', '', supabase_url)

    if not supabase_url or not supabase_key:
        print("Missing Supabase credentials.")
        return

    supabase: Client = create_client(supabase_url, supabase_key)
    
    # Fetch dynamic vendors from database
    response = supabase.table("vendors").select("*").eq("active", True).execute()
    vendor_list = response.data or []
    print(f"Loaded {len(vendor_list)} active vendors from Supabase.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(user_agent=HEADERS["User-Agent"])
        page = context.new_page()

        page.route("**/*", lambda route: route.abort() 
            if route.request.resource_type in ["stylesheet", "font", "image"] 
            else route.continue_()
        )

        for store in vendor_list:
            store_name = store["name"]
            base_url = store["base_url"].rstrip("/")
            print(f"\n--- Scanning Store: {store_name} ({base_url}) ---")

            categories_to_scrape = []
            try:
                page.goto(f"{base_url}/allcategory.html", timeout=30000, wait_until="domcontentloaded")
                soup = BeautifulSoup(page.content(), "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"]
                    if href.endswith(".html") and not any(x in href for x in ["login", "cart", "account", "order", "allcategory"]):
                        full_url = href if href.startswith("http") else f"{base_url}/{href.lstrip('/')}"
                        if full_url not in categories_to_scrape:
                            categories_to_scrape.append(full_url)
            except:
                categories_to_scrape = [base_url]

            if not categories_to_scrape:
                categories_to_scrape = [base_url]

            seen_urls = set()
            for cat_url in categories_to_scrape:
                try:
                    page.goto(cat_url, timeout=20000, wait_until="domcontentloaded")
                    # Smooth scroll to collect initial articles
                    for _ in range(8):
                        page.keyboard.press("End")
                        time.sleep(0.5)
                        try:
                            btn = page.get_by_text("View More", exact=False)
                            if btn.is_visible():
                                btn.click()
                                time.sleep(0.8)
                            else:
                                break
                        except:
                            break

                    soup = BeautifulSoup(page.content(), "html.parser")
                    for a in soup.find_all("a", href=re.compile(r"-npi\d+-")):
                        href = a["href"]
                        if href.startswith("/"): href = base_url + href
                        if "whatsapp.com" not in href:
                            seen_urls.add(href)
                except:
                    pass

            print(f"Discovered {len(seen_urls)} product links for {store_name}. Extracting details...")

            for prod_url in seen_urls:
                try:
                    page.goto(prod_url, timeout=15000, wait_until="domcontentloaded")
                    p_soup = BeautifulSoup(page.content(), "html.parser")

                    title_el = p_soup.find("h1")
                    title = title_el.get_text(strip=True) if title_el else "Unknown"

                    price_el = p_soup.find("h6")
                    price_num = re.sub(r"[^\d]", "", price_el.get_text(strip=True)) if price_el else "0"

                    images = []
                    main_area = p_soup.find("div", {"role": "main"}) or p_soup
                    for img in main_area.find_all("img", src=re.compile(r"gallery_(md|lg)")):
                        # Upgrade directly to max resolution
                        hq_img = img["src"].replace("gallery_md", "gallery_lg").replace("gallery_sm", "gallery_lg")
                        if hq_img not in images:
                            images.append(hq_img)

                    video_url = extract_video_url(p_soup, base_url)
                    category = classify_product(title, prod_url)
                    sizes = extract_sizes(p_soup)

                    if images and title != "Unknown":
                        payload = {
                            "vendor": store_name,
                            "category": category,
                            "title": title,
                            "base_price": int(price_num) if price_num else 0,
                            "in_stock": "OUT OF STOCK" not in p_soup.get_text().upper(),
                            "images": images,
                            "video": video_url,
                            "sizes": sizes,
                            "url": prod_url
                        }
                        supabase.table("products").upsert(payload, on_conflict="url").execute()
                except Exception as e:
                    pass

        browser.close()
    print("\nCatalog sync completed.")

if __name__ == "__main__":
    run_sync()
