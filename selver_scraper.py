# -*- coding: utf-8 -*-

import argparse
import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from time import sleep
import traceback

from config import selver_config as conf
import db_util


BASE_URL = "https://www.selver.ee"

PAGE_LOAD_DELAY = 10
PAGE_SWITCH_SLEEP = 1
NETWORK_ERROR_SLEEP = 60

params = {
    "limit": 96,
    "page": 1
}
driver = None


def has_next_products_page(soup):
    return soup.select_one("div.sf-pagination__item--next a") is not None

def get_product_price(product_card):
    price_label_span = product_card.find("span", {"class": "ProductBadge__badge--label"})

    if price_label_span and price_label_span.text.strip() != "":
        price_text = price_label_span.text.strip().split(" ")[0]
        return float(price_text.replace(",", ".").strip())

    prices_div = product_card.find("div", {"class": "ProductPrices"})

    if prices_div.find("div", {"class": "ProductPrice--special"}):
        price_text = prices_div.find("div", {"class": "ProductPrice--special"}).text.strip().split(" ")[0]
        return float(price_text.replace(",", ".").strip())

    price_text = prices_div.find("div", {"class": "ProductPrice"}).text.strip().split(" ")[0]
    return float(price_text.replace(",", ".").strip())

def get_product_links_with_prices(soup):
    result = {}

    for item in soup.select("div.ProductCard"):
        link = item.find("a", {"class": "ProductCard__link"}).get("href")
        price = get_product_price(item)
        result[link] = price

    return result

def has_product_with_url(url):
    return db_util.get_product_by_url(url) is not None

def get_product_title(soup):
    return soup.find("h1").text.strip()

def get_barcode(soup):
    attributes_table = soup.find("table", {"class": "ProductAttributes__table"})
    for row in attributes_table.find_all("tr"):
        if row.find("th").text.strip() == "Ribakood":
            return row.find("td").text.strip()

def get_image(soup):
    image_div = soup.find("div", {"class": "image"})
    if image_div:
        return image_div.find("img").get("src")

def get_contents(soup):
    for item in soup.select("div.ProductInfoBox div.AttributeAccordion"):
        if item.find("div", {"class": "AttributeAccordion__heading"}).text.strip() == "Koostisosad":
            content = item.find("div", {"class": "AttributeAccordion__content"}).text
            return content.replace("* Toote koostisosade loetelu võib muutuda. Kontrollige enne toote tarbimist pakendil esitatud koostisosi.", "").strip()

def get_page_soup(url, element, params=None):
    global driver
    full_url = BASE_URL + url
    driver.get(full_url)
    time.sleep(3)
    
    # Nõustume küpsistega
    try:
        cookie_btn = driver.find_element(By.CSS_SELECTOR, '#cookie-accept, button:has-text("Nõustun")')
        if cookie_btn: cookie_btn.click()
    except Exception:
        pass

    driver.execute_script("window.scrollBy(0, 1000);")
    time.sleep(1)
    return BeautifulSoup(driver.page_source, "html.parser")

def insert_product_to_database(url, title, barcode, image, contents, price):
    db_util.insert_product(url, title, barcode, image, contents, price, "SELVER")

def handle_error(error, url):
    # network errors
    if isinstance(error, requests.exceptions.ConnectionError):
        print("NETWORK ERROR")
        sleep(NETWORK_ERROR_SLEEP)

    # page parsing errors
    elif isinstance(error, TypeError):
        print(f"TYPE ERROR: {url}")
        traceback.print_exc()

    # page parsing errors
    elif isinstance(error, AttributeError):
        print(f"ATTRIBUTE ERROR: {url}")
        traceback.print_exc()

    # other errors
    elif isinstance(error, Exception):
        print(f"OTHER ERROR: {url}")
        traceback.print_exc()

def handle_product_page(url, price):
    try:
        soup = get_page_soup(url, "h1")

        title = get_product_title(soup)
        barcode = get_barcode(soup)
        image = get_image(soup)
        contents = get_contents(soup)

        insert_product_to_database(url, title, barcode, image, contents, price)

    except Exception as e:
        handle_error(e, url)

def handle_products_page(url, no_details=False):
    try:
        soup = get_page_soup(url, ".ProductCard", params)

        has_next_page = has_next_products_page(soup)
        links_with_prices = get_product_links_with_prices(soup)

        link_index = 0

        for product_url, price in links_with_prices.items():
            if not no_details:
                print(f"Page {params['page']}: {link_index + 1}/{len(links_with_prices)}", end="\r")
            full_url = f"{BASE_URL}{product_url}"

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

def open_browser():
    global driver
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)

def close_browser():
    driver.quit()

def scrape(no_details=False):
    open_browser()

    for category in conf.CATEGORIES:
        print(category, end="\t\t\t\t\n")

        for subcategory in conf.CATEGORIES[category]:
            print(subcategory, end="\t\t\t\t\n")
            params["page"] = 1
            has_next_page = True

            while has_next_page:
                if not no_details:
                    print(f"Page {params['page']}", end="\t\t\t\t\r")
                url = f"{BASE_URL}/{category}/{subcategory}"
                
                has_next_page = handle_products_page(url, no_details=no_details)

    close_browser()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-details', action='store_true', help='Disable detailed logging for CI logs')
    args = parser.parse_args()
    scrape(no_details=args.no_details)
