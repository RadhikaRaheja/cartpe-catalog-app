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

def clean_vendor_codes(text):
    """Removes vendor codes, SKUs, and trailing tags to prevent Google reverse-search."""
    if not text:
        return ""
    # Strip SKU patterns, item codes, and trailing hashes/numbers
    text = re.sub(r'(?i)\b(code|sku|art|item\s*no|ref)[:\s#-]*[a-z0-9_-]+', '', text)
    text = re.sub(r'#[a-zA-Z0-9_-]+', '', text)
    text = re.sub(r'-\s*[A-Z0-9]{3,}\s*$', '', text)
    text = re.sub(r'\s{2,}', ' ', text).strip()
    return text

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
    """Strict hierarchical classifier to eliminate mistagged items."""
    text = f"{title} {url}".lower()
    
    # 1. Footwear (highest priority)
    if any(k in text for k in [
        "loafer", "shoe", "sneaker", "heel", "sandal", "croc", "flipflop", 
        "flip flop", "boot", "footwear", "slingback", "slide", "mule", 
        "birkenstock", "derby", "oxford", "yeezy", "dunk", "jordan", "airforce"
    ]):
        return "footwear"
    
    # 2. Perfumes
    if any(k in text for k in ["perfume", "parfum", "tester", "edp", "edt", "fragrance", "cologne", "attar"]):
        return "perfume"
        
    # 3. Eyewear
    if any(k in text for k in ["sunglass", "glasses", "optical", "frame", "wayfarer", "eyewear", "aviator"]):
        return "eyewear"
        
    # 4. Watches
    if any(k in text for k in ["watch", "chronograph", "dial", "quartz", "automatic"]):
        return "watch"
        
    # 5. Belts
    if any(k in text for k in ["belt", "reversible belt", "buckle set", "leather belt"]):
        return "belt"
        
    # 6. Bags
    if any(k in text for k in ["bag", "handbag", "tote", "crossbody", "saddle", "clutch", "purse", "backpack", "wallet", "sling"]):
        return "bag"
        
    return "accessories"

def extract_sizes(soup, text_content):
    """Extracts sizes from interactive pills, select menus, and description text."""
    sizes = []
    
    # Check interactive DOM elements
    for el in soup.find_all(["button", "span", "div", "option", "li"], class_=re.compile(r"size|variant|attribute|pill", re.I)):
        txt = el.get_text(strip=True)
        if re.match(r"^(\d{1,2}|UK\s*\d+|US\s*\d+|EU\s*\d+|[SMLXL]{1,3})$", txt, re.I):
            if txt not in sizes:
                sizes.append(txt)

    # Check text patterns like 'Sizes :- 36-37-38-39-40' or 'UK 6 to 10'
    if not sizes and text_content:
        size_match = re.search(r'(?i)(?:sizes?|uk)\s*[:-]?\s*([0-9\s\-,/toUKUS]+)', text_content)
        if size_match:
            raw_sizes = size_match.group(1).strip()
            # Clean up into readable tokens
            tokens = re.findall(r'\b\d{1,2}\b', raw_sizes)
            if tokens and len(tokens) >= 2:
                sizes = tokens[:8]
                
    return sizes

def extract_clean_price(soup):
    """Safely extracts the active listing price, discarding strikethrough/MRP tags."""
    # Remove all strikethrough elements
    for del_tag in soup.find_all(["del", "s", "strike"]):
        del_tag.decompose()
        
    # Find price in standard Cartpe tags
    price_candidates = []
    for el in soup.find_all(["h6", "span", "div", "p"], class_=re.compile(r"price|selling|offer", re.I)):
        txt = el.get_text(strip=True)
        nums = re.findall(r'\d+', txt.replace(",", ""))
        if nums:
            price_candidates.append(int(nums[0]))
            
    # Fallback to general h6
    if not price_candidates:
        h6 = soup.find("h6")
        if h6:
            nums = re.findall(r'\d+', h6.get_text(strip=True).replace(",", ""))
            if nums:
                price_candidates.append(int(nums[0]))
                
    return price_candidates[0] if price_candidates else 0

def run_sync():
    supabase_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    supabase_key = os.environ.get("SUPABASE_KEY", "").strip()
    supabase_url = re.sub(r'/rest/v1/?$', '', supabase_url)

    if not supabase_url or not supabase_key:
        print("Missing Supabase credentials.")
        return

    supabase: Client = create_client(supabase_url, supabase_key)
    
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
            print(f"\nScanning Store: {store_name} ({base_url})")

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

            print(f"Found {len(seen_urls)} product links for {store_name}.")

            for prod_url in seen_urls:
                try:
                    page.goto(prod_url, timeout=15000, wait_until="domcontentloaded")
                    page_html = page.content()
                    p_soup = BeautifulSoup(page_html, "html.parser")

                    raw_title = p_soup.find("h1").get_text(strip=True) if p_soup.find("h1") else "Unknown"
                    title = clean_vendor_codes(raw_title)

                    base_price = extract_clean_price(p_soup)
                    category = classify_product(title, prod_url)
                    sizes = extract_sizes(p_soup, p_soup.get_text())

                    images = []
                    main_area = p_soup.find("div", {"role": "main"}) or p_soup
                    for img in main_area.find_all("img", src=re.compile(r"gallery_(md|lg)")):
                        hq_img = img["src"].replace("gallery_md", "gallery_lg").replace("gallery_sm", "gallery_lg")
                        if hq_img not in images:
                            images.append(hq_img)

                    video_url = extract_video_url(p_soup, base_url)

                    if images and title != "Unknown":
                        payload = {
                            "vendor": store_name,
                            "category": category,
                            "title": title,
                            "base_price": base_price,
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
    print("Sync completed successfully.")

if __name__ == "__main__":
    run_sync()
