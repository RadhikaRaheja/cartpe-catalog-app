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
    if not text: return ""
    text = re.sub(r'(?i)\b(code|sku|art|item\s*no|ref)[:\s#-]*[a-z0-9_-]+', '', text)
    text = re.sub(r'#[a-zA-Z0-9_-]+', '', text)
    text = re.sub(r'-\s*[A-Z0-9]{3,}\s*$', '', text)
    return re.sub(r'\s{2,}', ' ', text).strip()

def clean_video_url(url, base_url):
    if not url or url.strip() in ["#", "/#", "javascript:;", "javascript:void(0)"]: return None
    if url.startswith("/"): return base_url.rstrip("/") + url
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
        if src: return clean_video_url(src, base_url)
    return None

def classify_product(title, url):
    text = f"{title} {url}".lower()
    if any(k in text for k in ["loafer", "shoe", "sneaker", "heel", "sandal", "croc", "flipflop", "boot", "footwear", "slingback", "slide", "mule", "birkenstock"]): return "footwear"
    if any(k in text for k in ["perfume", "parfum", "tester", "edp", "edt", "fragrance", "attar"]): return "perfume"
    if any(k in text for k in ["sunglass", "glasses", "optical", "frame", "wayfarer", "eyewear"]): return "eyewear"
    if any(k in text for k in ["watch", "chronograph", "dial", "quartz"]): return "watch"
    if any(k in text for k in ["belt", "reversible belt", "buckle set", "leather belt"]): return "belt"
    if any(k in text for k in ["bag", "handbag", "tote", "crossbody", "saddle", "clutch", "purse", "backpack", "wallet"]): return "bag"
    return "accessories"

def extract_sizes(soup, text_content):
    sizes = set()
    for el in soup.find_all(["button", "span", "div", "option", "label"]):
        txt = el.get_text(strip=True).upper()
        if re.match(r"^(3[5-9]|4[0-6])$", txt) or re.match(r"^(UK|US|EU)?\s*([5-9]|1[0-2])$", txt):
            sizes.add(txt.replace(" ", ""))

    if not sizes and text_content:
        size_str = re.search(r'(?i)(?:sizes?|uk|eu)[\s:-]+([0-9\s,\-/&]+)', text_content)
        if size_str:
            tokens = re.findall(r'\b(3[5-9]|4[0-6]|[5-9]|1[0-2])\b', size_str.group(1))
            for t in tokens:
                sizes.add(t)

    def sort_key(x):
        nums = re.findall(r'\d+', x)
        return int(nums[0]) if nums else 0
    
    return sorted(list(sizes), key=sort_key)

def extract_clean_price(soup):
    for tag in soup.find_all(["del", "s", "strike"]): tag.decompose()
    for tag in soup.find_all(class_=re.compile(r"old|cancel|strikethrough", re.I)): tag.decompose()
    
    for el in soup.find_all(class_=re.compile(r"price|amount|selling", re.I)):
        txt = el.get_text(separator=" ", strip=True).upper()
        txt = re.sub(r'[₹$€£]|RS\.?|INR', ' ', txt).replace(",", "")
        nums = [int(n) for n in re.findall(r'\b\d+\b', txt) if int(n) > 0]
        if nums:
            return min(nums) 
            
    for tag in ["h6", "h5", "h4", "h3", "span"]:
        for el in soup.find_all(tag):
            txt = el.get_text(separator=" ", strip=True).upper()
            if "₹" in txt or "RS" in txt:
                txt = re.sub(r'[₹$€£]|RS\.?|INR', ' ', txt).replace(",", "")
                nums = [int(n) for n in re.findall(r'\b\d+\b', txt) if int(n) > 0]
                if nums:
                    return min(nums)
    return 0

def run_sync():
    supabase_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    supabase_key = os.environ.get("SUPABASE_KEY", "").strip()
    target_vendor = os.environ.get("TARGET_VENDOR", "").strip() # MATRIX LISTENER ADDED
    
    supabase_url = re.sub(r'/rest/v1/?$', '', supabase_url)

    if not supabase_url or not supabase_key:
        print("Missing Supabase credentials. Ensure GitHub Secrets are set.")
        return

    supabase: Client = create_client(supabase_url, supabase_key)
    
    settings_res = supabase.table("settings").select("sync_limit").eq("id", 1).execute()
    sync_limit = settings_res.data[0]["sync_limit"] if settings_res.data else 6
    print(f"--- Configuration Loaded | Scraper Depth Limit: {sync_limit} scrolls ---")

    vendor_list = supabase.table("vendors").select("*").eq("active", True).order("sort_order").execute().data or []
    
    # ISOLATE VENDOR IF RUNNING IN MATRIX MODE
    if target_vendor:
        vendor_list = [v for v in vendor_list if v["name"].strip().lower() == target_vendor.lower()]
        print(f"--- Matrix Cloud Mode: Isolated Server specifically for [{target_vendor}] ---")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=HEADERS["User-Agent"])
        page = context.new_page()
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["stylesheet", "font", "image", "media"] else route.continue_())

        for store in vendor_list:
            store_name = store["name"]
            base_url = store["base_url"].rstrip("/")
            print(f"\n--- Scanning Store: {store_name} ---")

            try:
                page.goto(f"{base_url}/allcategory.html", timeout=30000, wait_until="domcontentloaded")
                soup = BeautifulSoup(page.content(), "html.parser")
                categories = [a["href"] if a["href"].startswith("http") else f"{base_url}/{a['href'].lstrip('/')}" 
                              for a in soup.find_all("a", href=True) if ".html" in a["href"] and "login" not in a["href"]]
            except:
                categories = [base_url]

            seen_urls = set()
            for cat_url in categories:
                try:
                    page.goto(cat_url, timeout=20000, wait_until="domcontentloaded")
                    for _ in range(sync_limit):
                        page.keyboard.press("End")
                        time.sleep(0.5)
                        try:
                            btn = page.get_by_text("View More", exact=False)
                            if btn.is_visible():
                                btn.click()
                                time.sleep(0.8)
                            else: break
                        except: break
                    
                    for a in BeautifulSoup(page.content(), "html.parser").find_all("a", href=re.compile(r"-npi\d+-")):
                        seen_urls.add(a["href"] if a["href"].startswith("http") else base_url + a["href"])
                except: continue

            print(f"Discovered {len(seen_urls)} products for {store_name}. Extracting details...")

            for prod_url in seen_urls:
                try:
                    page.goto(prod_url, timeout=12000, wait_until="domcontentloaded")
                    p_soup = BeautifulSoup(page.content(), "html.parser")

                    title = clean_vendor_codes(p_soup.find("h1").get_text(strip=True) if p_soup.find("h1") else "Unknown")
                    base_price = extract_clean_price(p_soup)
                    category = classify_product(title, prod_url)
                    sizes = extract_sizes(p_soup, p_soup.get_text())

                    images = []
                    for img in (p_soup.find("div", {"role": "main"}) or p_soup).find_all("img", src=re.compile(r"gallery_(md|lg)")):
                        images.append(img["src"].replace("gallery_md", "gallery_lg").replace("gallery_sm", "gallery_lg"))

                    video_url = extract_video_url(p_soup, base_url)

                    if images and base_price > 0:
                        print(f"✅ Extracted: ₹{base_price} | {title[:40]}...") 
                        payload = {"vendor": store_name, "category": category, "title": title, "base_price": base_price, "in_stock": "OUT OF STOCK" not in p_soup.get_text().upper(), "images": list(set(images)), "video": video_url, "sizes": sizes, "url": prod_url}
                        supabase.table("products").upsert(payload, on_conflict="url").execute()
                except: continue
        browser.close()

if __name__ == "__main__":
    run_sync()
