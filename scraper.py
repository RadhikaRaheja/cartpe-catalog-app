import json
import re
import time
import requests
from bs4 import BeautifulSoup

# Base URL of the Cartpe store
BASE_URL = "https://le-brouges-resell.cartpe.in"

# List of category pages to scrape
CATEGORIES = [
    f"{BASE_URL}/men-rsquo-s-shoe-footwear.html",
    f"{BASE_URL}/flipflops-footwear.html",
    f"{BASE_URL}/premium-shoes-footwear.html",
    f"{BASE_URL}/ladies-shoes-footwear-women.html",
]

# Headers to mimic a real web browser and prevent the scraper from being blocked
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    )
}

def get_products():
    products = []
    seen_urls = set()

    for cat_url in CATEGORIES:
        print(f"Fetching category: {cat_url}")
        try:
            res = requests.get(cat_url, headers=HEADERS)
            if res.status_code != 200:
                print(f"Failed to fetch {cat_url}. Status code: {res.status_code}")
                continue

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
