# -*- coding: utf-8 -*-

import argparse
import requests
from bs4 import BeautifulSoup
from time import sleep
import traceback
import re

from config import prisma_config as conf
import db_util

BASE_URL = "https://www.prismamarket.ee"

PAGE_SWITCH_SLEEP = 1
NETWORK_ERROR_SLEEP = 60

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'et-EE,et;q=0.9,en-US;q=0.8,en;q=0.7'
}

params = {
    "page": 1
}

def has_next_products_page(soup):
    # Otsib kas järgmise lehe link eksisteerib
    next_link = soup.find("a", string=re.compile(r"Järgmine", re.I)) or soup.select_one("a[rel='next'], [class*='next-page']")
    return next_link is not None

def get_product_links_with_prices(soup):
    result = {}
    
    # Otsime tootekaste (nii uued kui vanad Prisma klassid)
    items = soup.select("article, div[class*='ProductCard'], div[class*='product-card'], div[data-test-id='product-list-item'], li.product-item")

    for item in items:
        try:
            link_tag = item.find("a", href=True)
            if not link_tag:
                continue
            link = link_tag.get("href")

            # Kontrollime, et link oleks toote link
            if not any(k in link for k in ['/toode/', '/entry/', '/products/', '/p/']):
                sub_a = item.select_one("a[href*='/toode/'], a[href*='/entry/'], a[href*='/products/']")
                if sub_a:
                    link = sub_a.get("href")
                else:
                    continue

            # Hinna leidmine
            price_text = item.get_text()
            match = re.search(r'(\d+[\.,]\d{2})\s*€', price_text)
            if match:
                price = float(match.group(1).replace(",", "."))
                result[link] = price
        except Exception:
            continue

    return result

def has_product_with_url(url):
    return db_util.get_product_by_url(url) is not None

def get_product_title(soup):
    h1 = soup.find("h1")
    return h1.text.strip() if h1 else "Nimetu toode"

def get_barcode(soup):
    try:
        ean_element = soup.find(string=re.compile(r'EAN', re.I))
        if ean_element:
            parent = ean_element.find_parent()
            match = re.search(r'\b(\d{8,14})\b', parent.get_text() if parent else '')
            if match:
                return match.group(1)
            next_el = parent.find_next()
            if next_el:
                match = re.search(r'\b(\d{8,14})\b', next_el.get_text())
                if match:
                    return match.group(1)
    except Exception:
        pass
    return ""

def get_image(soup):
    try:
        img = soup.select_one("div[data-test-id='product-page-container'] img, img[class*='product'], img.pic, .product-image img, img")
        if img:
            src = img.get("src") or img.get("data-src") or ""
            return src
    except Exception:
        pass
    return ""

def get_contents(soup):
    try:
        contents_element = soup.find(string=re.compile(r'Koostisosad|Toitumisalane teave', re.I))
        if contents_element:
            parent = contents_element.find_parent()
            if parent:
                next_div = parent.find_next()
                if next_div:
                    return next_div.get_text().strip()
    except Exception:
        pass
    return ""

def get_page_soup(url, query_params=None):
    page = requests.get(url, params=query_params, headers=HEADERS, timeout=15)
    sleep(PAGE_SWITCH_SLEEP)
    return BeautifulSoup(page.text, "html.parser")

def insert_product_to_database(url, title, barcode, image, contents, price):
    db_util.insert_product(url, title, barcode, image, contents, price, "PRISMA")

def handle_error(error, url):
    if isinstance(error, requests.exceptions.ConnectionError):
        print("NETWORK ERROR")
        sleep(NETWORK_ERROR_SLEEP)
    else:
        print(f"ERROR: {url} -> {error}")

def handle_product_page(url, price):
    try:
        soup = get_page_soup(url)

        title = get_product_title(soup)
        barcode = get_barcode(soup)
        image = get_image(soup)
        contents = get_contents(soup)

        insert_product_to_database(url, title, barcode, image, contents, price)

    except Exception as e:
        handle_error(e, url)

def handle_products_page(url, no_details=False):
    try:
        soup = get_page_soup(url, params)

        has_next_page = has_next_products_page(soup)
        links_with_prices = get_product_links_with_prices(soup)

        if len(links_with_prices) == 0:
            return False

        link_index = 0
        for product_url, price in links_with_prices.items():
            if not no_details:
                print(f"Page {params['page']}: {link_index + 1}/{len(links_with_prices)} ({product_url[:30]}...)")
            
            full_url = f"{BASE_URL}{product_url}" if product_url.startswith("/") else product_url

            if has_product_with_url(full_url):
                if price is not None:
                    db_util.update_product_price(full_url, price)
            else:
                handle_product_page(full_url, price)

            link_index += 1

        if has_next_page:
            params["page"] += 1
            return True
    
    except Exception as e:
        handle_error(e, url)
    return False

def scrape(no_details=False):
    for category in conf.CATEGORIES:
        print(f"\n📂 Prisma kategooria: {category}")
        path = conf.CATEGORIES[category]

        params["page"] = 1
        has_next_page = True

        while has_next_page:
            if not no_details:
                print(f"Page {params['page']}", end="\r")
            url = f"{BASE_URL}{path}"
            has_next_page = handle_products_page(url, no_details=no_details)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-details', action='store_true', help='Disable detailed logging for CI logs')
    args = parser.parse_args()
    scrape(no_details=args.no_details)
