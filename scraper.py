import json
import re
import time
import requests
from bs4 import BeautifulSoup

# The updated list of Cartpe vendor websites
STORES = [
    {
        "name": "Le Brouges Sneakers",
        "url": "https://le-brouges-resell.cartpe.in"
    },
    {
        "name": "Bagworld by Dolly",
        "url": "https://bagworld1.cartpe.in"
    },
    {
        "name": "Bag4u by Dolly",
        "url": "https://bag4u.cartpe.in"
    },
    {
        "name": "Muzammil Surat",
        "url": "https://mtcollection.cartpe.in"
    },
    {
        "name": "Le Brouges Bags",
        "url": "https://lebrouges-bags.cartpe.in"
    }
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
}

def get_store_categories(base_url):
    categories = []
    try:
        res = requests.get(f"{base_url}/allcategory.html", headers=HEADERS, timeout=15)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            for a in soup.find_all("a", href=True):
                href = a["href"]
                if href.endswith(".html") and not any(x in href for x in ["login", "cart", "account", "order", "allcategory"]):
                    full_url = href if href.startswith("http") else base_url + ("/" if not href.startswith("/") else "") + href
                    if full_url not in categories:
                        categories.append(full_url)
    except Exception as e:
        print(f"Error fetching categories: {e}")
    return categories

def scrape_all():
    products = []
    seen_urls = set()

    for store in STORES:
        store_name = store["name"]
        base_url = store["url"].rstrip("/")
        
        categories = get_store_categories(base_url)
        if not categories:
            categories = [base_url]

        for cat_url in categories:
            for page in range(1, 6):
                paged_url = f"{cat_url}?page={page}"
                print(f"Checking: {paged_url}")
                
                try:
                    res = requests.get(paged_url, headers=HEADERS, timeout=15)
                    if res.status_code != 200:
                        break 
                    
                    soup = BeautifulSoup(res.text, "html.parser")
                    links = soup.find_all("a", href=re.compile(r"-npi\d+-"))
                    
                    if not links:
                        break 

                    for a in links:
                        prod_url = a["href"]
                        if prod_url.startswith("/"):
                            prod_url = base_url + prod_url

                        if prod_url in seen_urls:
                            continue
                        seen_urls.add(prod_url)

                        try:
                            p_res = requests.get(prod_url, headers=HEADERS, timeout=15)
                            if p_res.status_code != 200:
                                continue
                            p_soup = BeautifulSoup(p_res.text, "html.parser")

                            title_tag = p_soup.find("h1")
                            title = title_tag.get_text(strip=True) if title_tag else "Unknown"

                            page_text = p_soup.get_text()
                            in_stock = "Out Of Stock" not in page_text

                            price_tag = p_soup.find("h6")
                            price = price_tag.get_text(strip=True) if price_tag else "Contact for Price"

                            images = []
                            for img in p_soup.find_all("img", src=re.compile(r"gallery_(md|sm|lg)")):
                                src = img["src"]
                                if src not in images:
                                    images.append(src)

                            if images and title != "Unknown":
                                products.append({
                                    "id": len(products) + 1,
                                    "vendor": store_name,
                                    "title": title,
                                    "price": price,
                                    "in_stock": in_stock,
                                    "images": images
                                })
                                print(f"Scraped: {title}")
                            time.sleep(0.3)
                        except Exception as e:
                            print(f"Skipping a product due to error: {e}")
                            
                except Exception as e:
                    print(f"Skipping page due to error: {e}")

    with open("catalog.json", "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    print(f"\nSaved {len(products)} total products.")

if __name__ == "__main__":
    scrape_all()
