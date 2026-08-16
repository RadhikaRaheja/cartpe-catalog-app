import json
import re
import time
import requests
from bs4 import BeautifulSoup

# Add as many Cartpe vendor websites as you like:
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
     },

    {
        "name": "Noman Bags, Sunglasses, Watches",
         "url": "https://nmofficial.cartpe.in"
     }
    
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    )
}

def get_store_categories(base_url):
    """Find all category URLs for a given Cartpe store."""
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
        print(f"Error fetching categories for {base_url}: {e}")
    return categories

def scrape_all():
    products = []
    seen_urls = set()

    for store in STORES:
        store_name = store["name"]
        base_url = store["url"].rstrip("/")
        print(f"\n--- Scanning Store: {store_name} ({base_url}) ---")

        categories = get_store_categories(base_url)
        if not categories:
            categories = [base_url]

        for cat_url in categories:
            print(f"Checking category: {cat_url}")
            try:
                res = requests.get(cat_url, headers=HEADERS, timeout=15)
                if res.status_code != 200:
                    continue

                soup = BeautifulSoup(res.text, "html.parser")
                links = soup.find_all("a", href=re.compile(r"-npi\d+-"))

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

                        # Title
                        title_tag = p_soup.find("h1")
                        title = title_tag.get_text(strip=True) if title_tag else "Unknown"

                        # Stock Check
                        page_text = p_soup.get_text()
                        in_stock = "Out Of Stock" not in page_text

                        # Price
                        price_tag = p_soup.find("h6")
                        price = price_tag.get_text(strip=True) if price_tag else "N/A"

                        # Images
                        images = []
                        for img in p_soup.find_all("img", src=re.compile(r"gallery_(md|sm|lg)")):
                            src = img["src"]
                            if src not in images:
                                images.append(src)

                        products.append({
                            "id": len(products) + 1,
                            "vendor": store_name,
                            "title": title,
                            "price": price,
                            "url": prod_url,
                            "in_stock": in_stock,
                            "images": images
                        })
                        print(f"[{store_name}] Scraped: {title} | In Stock: {in_stock}")
                        time.sleep(0.3)
                    except Exception as err:
                        print(f"Error on product {prod_url}: {err}")
            except Exception as err:
                print(f"Error on category {cat_url}: {err}")

    with open("catalog.json", "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    print(f"\nDone! Scraped {len(products)} total products across all stores.")

if __name__ == "__main__":
    scrape_all()
            soup = BeautifulSoup(res.text, "html.parser")
            
            # Find all product links. Cartpe product URLs typically contain '-npi' followed by numbers
            links = soup.find_all("a", href=re.compile(r"-npi\d+-"))

            for a in links:
                prod_url = a["href"]
                
                # Ensure the URL is absolute
                if prod_url.startswith("/"):
                    prod_url = BASE_URL + prod_url
                
                # Skip duplicate products
                if prod_url in seen_urls:
                    continue
                seen_urls.add(prod_url)

                try:
                    # Fetch individual product page
                    p_res = requests.get(prod_url, headers=HEADERS)
                    p_soup = BeautifulSoup(p_res.text, "html.parser")

                    # Extract the Title
                    title_tag = p_soup.find("h1")
                    title = title_tag.get_text(strip=True) if title_tag else "Unknown Product"

                    # Extract Stock Status based on the presence of "Out Of Stock" text
                    page_text = p_soup.get_text()
                    in_stock = "Out Of Stock" not in page_text

                    # Extract Price (Cartpe usually places this in <h6> tags)
                    price_tag = p_soup.find("h6") 
                    price = price_tag.get_text(strip=True) if price_tag else "Price not found"

                    # Extract Images (Looking for gallery classes/identifiers)
                    images = []
                    for img in p_soup.find_all("img", src=re.compile(r"gallery_(md|sm|lg)")):
                        src = img["src"]
                        if src not in images:
                            images.append(src)

                    # Append to our product list
                    products.append({
                        "id": len(products) + 1,
                        "title": title,
                        "price": price,
                        "url": prod_url,
                        "in_stock": in_stock,
                        "images": images,
                    })
                    print(f"Scraped: {title} | In Stock: {in_stock}")
                    
                    # Be polite to the server, pause briefly between requests
                    time.sleep(0.5) 
                except Exception as e:
                    print(f"Error scraping product {prod_url}: {e}")
        except Exception as e:
             print(f"Error accessing category {cat_url}: {e}")

    # Save all scraped data to a JSON file
    with open("catalog.json", "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    print(f"\nDone! Successfully saved {len(products)} products to catalog.json")

if __name__ == "__main__":
    get_products()
