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

from config import barbora_config as conf
import db_util


BASE_URL = "https://barbora.ee"

PAGE_LOAD_DELAY = 20
PAGE_SWITCH_SLEEP = 1
NETWORK_ERROR_SLEEP = 60

params = {
    "page": 1
}
driver = None


def has_next_products_page(soup):
    pagination = soup.find("ul", {"class": "pagination"})
    active_link = pagination.find("li", {"class": "active"}).find("a").get("href")
    last_link = pagination.find_all("li")[-1].find("a").get("href")
    return active_link != last_link

def get_product_links_with_prices():
    script = """
    const getLinksWithPrices = () => {
        const result = {};

        const shadowRootElSelector = 'div#category-page-results-placeholder > div > ul > li > div > div';
        document.querySelectorAll(shadowRootElSelector).forEach((el) => {
            const root = el.shadowRoot;
            const linkEl = root.querySelector('a');
            const priceEl = root.querySelector('meta[itemprop="price"]');
            result[linkEl.href] = priceEl ? parseFloat(priceEl.content) : null;
        });

        return result;
    };
    return getLinksWithPrices();
    """

    return driver.execute_script(script)

def has_product_with_url(url):
    return db_util.get_product_by_url(url) is not None

def get_product_title(soup):
    return soup.find("h1", {"class": "b-product-info--title"}).text.strip()

def get_image(soup):
    pictures_div = soup.find("div", {"class": "b-product-info--pictures"})
    if pictures_div:
        return pictures_div.find("img").get("src")

def get_contents(soup):
    list_index = -1
    has_contents = False

    product_info = soup.find("dl", {"class": "b-product-info--info-2"})
    for term in product_info.find_all("dt"):
        list_index += 1
        if term.text.strip() == "Koostisosad":
            has_contents = True
            break
        
    if has_contents:
        return product_info.find_all("dd")[list_index].text.strip()

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
    db_util.insert_product(url, title, None, image, contents, price, "BARBORA")

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
        soup = get_page_soup(url, "h1.b-product-info--title")

        title = get_product_title(soup)
        image = get_image(soup)
        contents = get_contents(soup)

        insert_product_to_database(url, title, image, contents, price)

    except Exception as e:
        handle_error(e, url)

def handle_products_page(url, no_details=False):
    try:
        selector = "div#category-page-results-placeholder > div > ul > li > div > div"
        soup = get_page_soup(url, selector, params)

        has_next_page = has_next_products_page(soup)
        links_with_prices = get_product_links_with_prices()

        link_index = 0

        for product_url, price in links_with_prices.items():
            if not no_details:
                print(f"Page {params['page']}: {link_index + 1}/{len(links_with_prices)}", end="\r")

            if has_product_with_url(product_url):
                if price is not None:
                    db_util.update_product_price(product_url, price)
            else:
                handle_product_page(product_url, price)

            link_index += 1

        if has_next_page:
            params["page"] += 1
            return True

    except Exception as e:
        handle_error(e, url)

# -*- coding: utf-8 -*-

import argparse
import requests
from bs4 import BeautifulSoup
from time import sleep
import traceback

from config import prisma_config as conf
import db_util


BASE_URL = "https://www.prismamarket.ee"

PAGE_SWITCH_SLEEP = 1
NETWORK_ERROR_SLEEP = 60

params = {
    "page": 1
}


def has_next_products_page(soup):
    return soup.find("a", string="Järgmine leht") is not None

def get_product_links_with_prices(soup):
    result = {}

    for item in soup.select("div[data-test-id='product-list-item']"):
        link = item.find("a").get("href")
        price = item.find("span", {"data-test-id": "display-price"}).text.strip()
        result[link] = float(price.replace("€", "").replace(",", ".").strip())

    return result

def has_product_with_url(url):
    return db_util.get_product_by_url(url) is not None

def get_product_title(soup):
    return soup.find("h1").text.strip()

def get_barcode(soup):
    ean_element = soup.find("h3", string="EAN")
    return ean_element.find_next("div").find("span").text.strip()

def get_image(soup):
    product_div = soup.select("div[data-test-id='product-page-container']")
    return product_div[0].find("img").get("src")

def get_contents(soup):
    contents_element = soup.find("h3", string="Koostisosad")
    if contents_element:
        return contents_element.find_next("div").text.strip()

def get_page_soup(url, query_params=None):
    page = requests.get(url, params=query_params)
    sleep(PAGE_SWITCH_SLEEP)
    return BeautifulSoup(page.text, "html.parser")

def insert_product_to_database(url, title, barcode, image, contents, price):
    db_util.insert_product(url, title, barcode, image, contents, price, "PRISMA")

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

def scrape(no_details=False):
    for category in conf.CATEGORIES:
        print(category)
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


def close_browser():
    driver.quit()

def scrape(no_details=False):
    open_browser()

    for category in conf.CATEGORIES:
        print(category)
        path = conf.CATEGORIES[category]

        params["page"] = 1
        has_next_page = True

        while has_next_page:
            if not no_details:
                print(f"Page {params['page']}", end="\r")
            url = f"{BASE_URL}{path}"

            has_next_page = handle_products_page(url, no_details=no_details)

    close_browser()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-details', action='store_true', help='Disable detailed logging for CI logs')
    args = parser.parse_args()
    scrape(no_details=args.no_details)
