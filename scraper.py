import sys
import os
import re
import time
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from supabase import create_client, Client

HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
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
    for del_tag in soup.find_all(["del", "s", "strike"]):
        del_tag.decompose()
    for tag in soup.find_all(style=re.compile(r"text-decoration:\s*line-through", re.I)):
        tag.decompose()
        
    for el in soup.find_all(class_=re.compile(r"price|amount|selling", re.I)):
        txt = el.get_text(separator=" ", strip=True).replace(",", "")
        nums = re.findall(r'\b\d+\b', txt)
        if nums and int(nums[0]) > 0:
            return int(nums[0])
            
    for tag in ["h6", "h5", "h4", "span"]:
        for el in soup.find_all(tag):
            txt = el.get_text(separator=" ", strip=True).replace(",", "")
            if "₹" in txt or "RS" in txt.upper():
                nums = re.findall(r'\b\d+\b', txt)
                if nums and int(nums[0]) > 0:
                    return int(nums[0])
    return 0

def run_sync():
    supabase_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    supabase_key = os.environ.get("SUPABASE_KEY", "").strip()
    supabase_url = re.sub(r'/rest/v1/?$', '', supabase_url)

    if not supabase_url or not supabase_key:
        print("Missing Supabase credentials. Ensure GitHub Secrets are set.")
        return

    supabase: Client = create_client(supabase_url, supabase_key)
    
    # FETCH DYNAMIC DEEP SYNC LIMIT FROM DATABASE
    settings_res = supabase.table("settings").select("sync_limit").eq("id", 1).execute()
    sync_limit = settings_res.data[0]["sync_limit"] if settings_res.data else 6
    print(f"--- Configuration Loaded | Scraper Depth Limit: {sync_limit} scrolls ---")

    vendor_list = supabase.table("vendors").select("*").eq("active", True).execute().data or []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=HEADERS["User-Agent"])
        page = context.new_page()
        page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["stylesheet", "font", "image"] else route.continue_())

        for store in vendor_list:
            store_name = store["name"]
            base_url = store["base_url"].rstrip("/")
            print(f"\n--- Scanning Store: {store_name} ---")

            try:
                page.goto(f"{base_url}/allcategory.html", timeout=30000)
                soup = BeautifulSoup(page.content(), "html.parser")
                categories = [a["href"] if a["href"].startswith("http") else f"{base_url}/{a['href'].lstrip('/')}" 
                              for a in soup.find_all("a", href=True) if ".html" in a["href"] and "login" not in a["href"]]
            except:
                categories = [base_url]

            seen_urls = set()
            for cat_url in categories:
                try:
                    page.goto(cat_url, timeout=20000)
                    # DYNAMIC SCROLLING APPLIED HERE
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

            for prod_url in seen_urls:
                try:
                    page.goto(prod_url, timeout=15000)
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
                        payload = {"vendor": store_name, "category": category, "title": title, "base_price": base_price, "in_stock": "OUT OF STOCK" not in p_soup.get_text().upper(), "images": list(set(images)), "video": video_url, "sizes": sizes, "url": prod_url}
                        supabase.table("products").upsert(payload, on_conflict="url").execute()
                except: continue
        browser.close()

if __name__ == "__main__":
    run_sync()
