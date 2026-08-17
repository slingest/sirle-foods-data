# -*- coding: utf-8 -*-

import argparse
import requests
from bs4 import BeautifulSoup
from time import sleep
import traceback
import re
from selenium import webdriver
from selenium.webdriver.common.by import By

from config import rimi_config as conf
import db_util

BASE_URL = "https://www.rimi.ee"

PAGE_SWITCH_SLEEP = 1
NETWORK_ERROR_SLEEP = 60

params = {
    "page": 1
}

driver = None

def open_browser():
    global driver
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=OFF")
    driver = webdriver.Chrome(options=options)

def close_browser():
    global driver
    if driver:
        driver.quit()

# PUHASTAB HINNA JA HOIAB ÄRA 'per tk' VEA
def get_price(euros, cents):
    try:
        full_text = f"{euros}.{cents}"
        match = re.search(r'(\d+)[\.,](\d{2})', full_text)
        if match:
            return float(f"{match.group(1)}.{match.group(2)}")
        nums = re.findall(r'\d+', full_text)
        if len(nums) >= 2:
            return float(f"{nums[0]}.{nums[1]}")
        elif len(nums) == 1:
            return float(nums[0])
    except Exception:
        pass
    return 0.0

def has_next_products_page(soup):
    next_link = soup.select_one("a.pagination__item--next, a[rel='next']")
    return next_link is not None

def get_product_links_with_prices(soup):
    result = {}
    for item in soup.select("div.product-grid__item, li.product-grid__item, div.card"):
        try:
            link_tag = item.select_one("a.product-card__full-link, a.card__url, a")
            if not link_tag or 'href' not in link_tag.attrs:
                continue
            link = link_tag.get("href")

            euros_el = item.select_one("span.price-tag > span, .price-tag span, .price span")
            cents_el = item.select_one("span.price-tag > div > sup, .price-tag sup, .price sup")
            
            euros = euros_el.text.strip() if euros_el else item.text
            cents = cents_el.text.strip() if cents_el else "00"

            price = get_price(euros, cents)
            if price > 0:
                result[link] = price
        except Exception:
            continue

    return result

def has_product_with_url(url):
    return db_util.get_product_by_url(url) is not None

def get_product_title(soup):
    h1 = soup.select_one("h1.product__title, h1")
    return h1.text.strip() if h1 else "Nimetu toode"

def get_barcode(soup):
    try:
        ean_match = re.search(r'EAN:\s*(\d+)', soup.text)
        if ean_match:
            return ean_match.group(1)
        el = soup.select_one("[data-product-code], [itemprop='gtin13']")
        if el:
            return el.get('data-product-code') or el.get('content') or ""
    except Exception:
        pass
    return ""

def get_image(soup):
    try:
        img = soup.select_one(".product__image img, .gallery img, img")
        if img:
            src = img.get("src") or img.get("data-src") or ""
            if src and not src.startswith("http"):
                src = "https://www.rimi.ee" + src
            return src
    except Exception:
        pass
    return ""

def get_contents(soup):
    try:
        cont = soup.select_one(".product__details, .details, #product-details, div.info")
        if cont:
            return cont.text.strip()
    except Exception:
        pass
    return ""

# LOLLI-KINDEL LEHE LUGEMINE (EI JÄÄ KINNI!)
def get_page_soup(url, element=None, params=None):
    global driver
    full_url = url
    if params and "page" in params:
        sep = "&" if "?" in url else "?"
        full_url = f"{url}{sep}page={params['page']}"
        
    try:
        driver.get(full_url)
        sleep(PAGE_SWITCH_SLEEP)
        return BeautifulSoup(driver.page_source, "html.parser")
    except Exception:
        return BeautifulSoup("", "html.parser")

def insert_product_to_database(url, title, barcode, image, contents, price):
    db_util.insert_product(url, title, barcode, image, contents, price, "RIMI")

def handle_product_page(url, price):
    try:
        soup = get_page_soup(url)
        title = get_product_title(soup)
        barcode = get_barcode(soup)
        image = get_image(soup)
        contents = get_contents(soup)
        insert_product_to_database(url, title, barcode, image, contents, price)
    except Exception as e:
        print(f"Tootelehe viga: {url} -> {e}")

def handle_products_page(url, no_details=False):
    try:
        soup = get_page_soup(url, params=params)
        has_next_page = has_next_products_page(soup)
        links_with_prices = get_product_links_with_prices(soup)

        if len(links_with_prices) == 0:
            return False

        link_index = 0
        for product_url, price in links_with_prices.items():
            if not no_details:
                print(f"Page {params['page']}: {link_index + 1}/{len(links_with_prices)}", end="\r")
            
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
        print(f"Viga lehel: {url} -> {e}")
    return False

def scrape(no_details=False):
    open_browser()
    try:
        for category in conf.CATEGORIES:
            print(f"\n📂 Rimi kategooria: {category}")
            path = conf.CATEGORIES[category]

            params["page"] = 1
            has_next_page = True

            while has_next_page:
                if not no_details:
                    print(f"Page {params['page']}", end="\r")
                url = f"{BASE_URL}{path}"
                has_next_page = handle_products_page(url, no_details=no_details)
    finally:
        close_browser()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-details', action='store_true', help='Disable detailed logging for CI logs')
    args = parser.parse_args()
    scrape(no_details=args.no_details)
