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

from config import rimi_config as conf
import db_util


BASE_URL = "https://www.rimi.ee"

PAGE_LOAD_DELAY = 10
PAGE_SWITCH_SLEEP = 1
NETWORK_ERROR_SLEEP = 60

params = {
    "currentPage": 1,
    "pageSize": 80
}
driver = None


def has_next_products_page(soup):
    return soup.find("a", {"aria-label": "Next &raquo;"}) is not None

def get_price(euros, cents):
    return float(f"{euros}.{cents}")

def get_product_links_with_prices(soup):
    result = {}

    for item in soup.select("div.card"):
        price = None
        link = item.find("a", {"class": "card__url"}).get("href")
        price_label_div = item.find("div", {"class": "price-label__price"})
        price_div = item.find("div", {"class": "card__price"})

        if price_label_div:
            euros = price_label_div.find("span", {"class": "major"}).text.strip()
            cents = price_label_div.find("span", {"class": "cents"}).text.strip()
            price = get_price(euros, cents)
        elif price_div:
            euros = price_div.find("span").text.strip()
            cents = price_div.find("sup").text.strip()
            price = get_price(euros, cents)

        result[link] = price

    return result

def has_product_with_url(url):
    return db_util.get_product_by_url(url) is not None

def get_product_title(soup):
    return soup.find("h1", {"class": "name"}).text.strip()

def get_image(soup):
    image_div = soup.find("div", {"class": "product__main-image"})
    if image_div:
        return image_div.find("img").get("src")

def get_contents(soup):
    for div in soup.find_all("div", {"class": "product__list-wrapper"}):
        heading = div.find("p", {"class": "heading"})
        if heading and heading.text.strip() == "Koostisosad":
            return div.find("ul").text.strip()

def get_page_soup(url, wait_for_selector, query_params=None):
    full_url = None

    if query_params:
        param_string = "&".join([f"{k}={v}" for k, v in query_params.items()])
        full_url = f"{url}?{param_string}"
    else:
        full_url = url

    driver.get(full_url)

    try:
        element = EC.presence_of_element_located((By.CSS_SELECTOR, wait_for_selector))
        WebDriverWait(driver, PAGE_LOAD_DELAY).until(element)
        sleep(PAGE_SWITCH_SLEEP)
        return BeautifulSoup(driver.page_source, "html.parser")
    except TimeoutException as e:
        raise e

def insert_product_to_database(url, title, image, contents, price):
    db_util.insert_product(url, title, None, image, contents, price, "RIMI")

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
        image = get_image(soup)
        contents = get_contents(soup)

        insert_product_to_database(url, title, image, contents, price)

    except Exception as e:
        handle_error(e, url)

def handle_products_page(url, no_details=False):
    try:
        soup = get_page_soup(url, "a.card__url", params)

        has_next_page = has_next_products_page(soup)
        links_with_prices = get_product_links_with_prices(soup)

        link_index = 0

        for product_url, price in links_with_prices.items():
            if not no_details:
                print(f"Page {params['currentPage']}: {link_index + 1}/{len(links_with_prices)}", end="\r")
            full_url = f"{BASE_URL}{product_url}"

            if has_product_with_url(full_url):
                if price is not None:
                    db_util.update_product_price(full_url, price)
            else:
                handle_product_page(full_url, price)

            link_index += 1

        if has_next_page:
            params["currentPage"] += 1
            return True
    
    except Exception as e:
        handle_error(e, url)

def open_browser():
    global driver
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--log-level=OFF")
    driver = webdriver.Chrome(options=options)

def close_browser():
    driver.quit()

def scrape(no_details=False):
    open_browser()

    for category in conf.CATEGORIES:
        print(category)
        path = conf.CATEGORIES[category]

        params["currentPage"] = 1
        has_next_page = True

        while has_next_page:
            if not no_details:
                print(f"Page {params['currentPage']}", end="\r")
            url = f"{BASE_URL}{path}"
            
            has_next_page = handle_products_page(url, no_details=no_details)

    close_browser()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-details', action='store_true', help='Disable detailed logging for CI logs')
    args = parser.parse_args()
    scrape(no_details=args.no_details)
