#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
メルカリから販売履歴や購入履歴を収集します．

Usage:
  crawler.py [-c CONFIG]

Options:
  -c CONFIG     : CONFIG を設定ファイルとして読み込んで実行します．[default: config.yaml]
"""

import logging
import random
import math
import re
import datetime
import time
import traceback

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

import store_yahoo.const
import store_yahoo.handle

import local_lib.captcha
import local_lib.selenium_util

STATUS_ORDER_COUNT = "[collect] Count of year"
STATUS_ORDER_ITEM_ALL = "[collect] All orders"
STATUS_ORDER_ITEM_BY_YEAR = "[collect] Year {year} orders"

LOGIN_RETRY_COUNT = 2
FETCH_RETRY_COUNT = 3

YAHOO_NORMAL = "yahoo.com"
YAHOO_SHOP = "yahoo-shops.com"


def wait_for_loading(handle, xpath='//div[@class="front-delivery-display"]', sec=1):
    driver, wait = store_yahoo.handle.get_selenium_driver(handle)

    wait.until(EC.visibility_of_all_elements_located((By.XPATH, xpath)))
    time.sleep(sec)


def parse_date(date_text):
    return datetime.datetime.strptime(date_text, "%Y年%m月%d日")


def parse_datetime(datetime_text):
    return datetime.datetime.strptime(datetime_text, "%Y年%m月%d日 %H:%M")


def gen_hist_url(year, page):
    return store_yahoo.const.HIST_URL_BY_YEAR.format(
        year=year, first_order=store_yahoo.const.ORDER_COUNT_PER_PAGE * (page - 1) + 1
    )


def gen_item_id_from_url(url):
    m = re.match(r"https://store.shopping.yahoo.co.jp/([^/]+)/([^.]+).html", url)

    return "{store_id}_{item_id}".format(store_id=m.group(1), item_id=m.group(2))


def gen_order_url_from_no(no):
    m = re.match(r"(.*)-(\d+)$", no)
    store_id = m.group(1)

    return store_yahoo.const.ORDER_URL_BY_NO.format(store_id=store_id, no=no)


def gen_status_label_by_year(year):
    return STATUS_ORDER_ITEM_BY_YEAR.format(year=year)


def visit_url(handle, url, xpath='//div[@class="front-delivery-display"]'):
    driver, wait = store_yahoo.handle.get_selenium_driver(handle)
    driver.get(url)

    wait_for_loading(handle, xpath)


def save_thumbnail(handle, item, thumb_url):
    driver, wait = store_yahoo.handle.get_selenium_driver(handle)

    with local_lib.selenium_util.browser_tab(driver, thumb_url):
        png_data = driver.find_element(By.XPATH, "//img").screenshot_as_png

        with open(store_yahoo.handle.get_thumb_path(handle, item), "wb") as f:
            f.write(png_data)


def fetch_item_detail(handle, item):
    driver, wait = store_yahoo.handle.get_selenium_driver(handle)

    with local_lib.selenium_util.browser_tab(driver, item["url"]):
        wait_for_loading(handle, '//div[contains(@class, "Masthead")]')

        breadcrumb_list = driver.find_elements(By.XPATH, '//div[contains(@id, "bclst")]/ol/li')
        category = list(map(lambda x: x.text, breadcrumb_list))

        if len(category) >= 2:
            category.pop(0)
            category.pop(-1)

        item["category"] = category


def parse_item(handle, item_xpath):
    driver, wait = store_yahoo.handle.get_selenium_driver(handle)

    name = driver.find_element(
        By.XPATH,
        item_xpath + '//dl[contains(@class, "elDetail")]/dd[contains(@class, "elName")]/a/span',
    ).text

    url = driver.find_element(
        By.XPATH,
        item_xpath + '//dl[contains(@class, "elDetail")]/dd[contains(@class, "elName")]/a',
    ).get_attribute("href")

    item_id = gen_item_id_from_url(url)

    price_text = driver.find_element(
        By.XPATH, item_xpath + '//dd[contains(@class, "elInfo")]/span[@class="elPrice"]'
    ).text
    price = int(re.match(r".*?(\d{1,3}(?:,\d{3})*)", price_text).group(1).replace(",", ""))

    count_text = driver.find_element(
        By.XPATH, item_xpath + '//dd[contains(@class, "elInfo")]/span[@class="elNum"]'
    ).text
    count = int(re.match(r"\D+(\d+)", count_text).group(1))

    item = {"name": name, "price": price, "count": count, "url": url, "id": item_id}

    fetch_item_detail(handle, item)

    thumb_url = driver.find_element(
        By.XPATH,
        item_xpath + '//dl[contains(@class, "elDetail")]/dt[contains(@class, "elImage")]/a/img',
    ).get_attribute("src")
    save_thumbnail(handle, item, thumb_url)

    return item


def parse_order(handle, order_info):
    ITEM_XPATH = '//div[contains(@class, "mdOrderItem")]/div[contains(@class, "elItem")]/ul[contains(@class, "elList")]/li'

    driver, wait = store_yahoo.handle.get_selenium_driver(handle)

    logging.info(
        "Parse order: {date} - {seller} - {no}".format(
            date=order_info["date"].strftime("%Y-%m-%d"),
            seller=order_info["seller"],
            no=order_info["no"],
        )
    )

    datetime_label = driver.find_element(
        By.XPATH, '//div[contains(@class, "elOrderInfo")]/p[@class="elOrderDate"]'
    ).text
    datetime_text = re.match(r".*日時：(.*)", datetime_label).group(1)
    date = parse_datetime(datetime_text)

    item_base = {
        "date": date,
        "no": order_info["no"],
        "seller": order_info["seller"],
        "kind": order_info["kind"],
    }

    is_unempty = False
    for i in range(len(driver.find_elements(By.XPATH, ITEM_XPATH))):
        item_xpath = "(" + ITEM_XPATH + ")[{index}]".format(index=i + 1)

        item = parse_item(handle, item_xpath)
        item |= item_base

        logging.info("{name} {price:,}円".format(name=item["name"], price=item["price"]))

        store_yahoo.handle.record_item(handle, item)
        is_unempty = True

    return is_unempty


def fetch_order_item_list_by_order_info(handle, order_info):
    wait_for_loading(handle)

    if not parse_order(handle, order_info):
        logging.warning("Failed to parse order of {no}".format(no=order_info["no"]))

    time.sleep(1)


def skip_order_item_list_by_year_page(handle, year, page):
    logging.info("Skip check order of {year} page {page} [cached]".format(year=year, page=page))
    incr_order = min(
        store_yahoo.handle.get_order_count(handle, year)
        - store_yahoo.handle.get_progress_bar(handle, gen_status_label_by_year(year)).count,
        store_yahoo.const.ORDER_COUNT_PER_PAGE,
    )
    store_yahoo.handle.get_progress_bar(handle, gen_status_label_by_year(year)).update(incr_order)
    store_yahoo.handle.get_progress_bar(handle, STATUS_ORDER_ITEM_ALL).update(incr_order)

    # NOTE: これ，状況によっては最終ページで成り立たないので，良くない
    return incr_order != store_yahoo.const.ORDER_COUNT_PER_PAGE


def fetch_order_item_list_by_year_page(handle, year, page, retry=0):
    ORDER_DATE_XPATH = '//li[contains(@class, "elOrderItem")]'

    driver, wait = store_yahoo.handle.get_selenium_driver(handle)

    total_page = math.ceil(
        store_yahoo.handle.get_order_count(handle, year) / store_yahoo.const.ORDER_COUNT_PER_PAGE
    )

    store_yahoo.handle.set_status(
        handle,
        "注文履歴を解析しています... {year}年 {page}/{total_page} ページ".format(year=year, page=page, total_page=total_page),
    )

    visit_url(handle, gen_hist_url(year, page))
    keep_logged_on(handle)

    logging.info(
        "Check order of {year} page {page}/{total_page}".format(year=year, page=page, total_page=total_page)
    )
    logging.info("URL: {url}".format(url=driver.current_url))

    order_list = []
    for i in range(len(driver.find_elements(By.XPATH, ORDER_DATE_XPATH))):
        order_date_xpath = "(" + ORDER_DATE_XPATH + "[{index}])".format(index=i + 1)

        date_text = driver.find_element(
            By.XPATH, order_date_xpath + '//p[contains(@class, "elDate")]/span'
        ).text
        date = parse_date(date_text)

        order_xpath_base = order_date_xpath + '//li[contains(@class, "elItemList")]'
        for j in range(len(driver.find_elements(By.XPATH, order_xpath_base))):
            order_xpath = "(" + order_xpath_base + "[{index}])".format(index=j + 1)

            onclick = driver.find_element(
                By.XPATH,
                order_xpath + '//div[contains(@class, "elControl")]/p[contains(@class,"elButton")]/a',
            ).get_attribute("onclick")

            kind_text = driver.find_element(
                By.XPATH,
                order_xpath + '//div[contains(@class, "elControl")]/p[contains(@class,"elButton")]/a/span',
            ).text
            if re.match(r"寄付詳細", kind_text):
                kind = "tax"
            else:
                kind = "normal"

            no = driver.find_element(By.XPATH, order_xpath + '//dd[contains(@class, "elOrderData")]').text

            seller = driver.find_element(
                By.XPATH,
                order_xpath + '//div[contains(@class, "elStoreInfo")]/p[contains(@class, "elName")]/a/span',
            ).text

            order_list.append({"date": date, "seller": seller, "no": no, "kind": kind, "onclick": onclick})

    for order_info in order_list:
        if not store_yahoo.handle.get_order_stat(handle, order_info["no"]):
            driver.execute_script(order_info["onclick"])
            fetch_order_item_list_by_order_info(handle, order_info)
            driver.back()
        else:
            logging.info(
                "Done order: {date} - {no} [cached]".format(
                    date=order_info["date"].strftime("%Y-%m-%d"), no=order_info["no"]
                )
            )

        store_yahoo.handle.get_progress_bar(handle, gen_status_label_by_year(year)).update()
        store_yahoo.handle.get_progress_bar(handle, STATUS_ORDER_ITEM_ALL).update()

        if year == datetime.datetime.now().year:
            last_item = store_yahoo.handle.get_last_item(handle, year)
            if (
                store_yahoo.handle.get_year_checked(handle, year)
                and (last_item != None)
                and (last_item["no"] == order_info["no"])
            ):
                logging.info("Latest order found, skipping analysis of subsequent pages")
                for i in range(total_page):
                    store_yahoo.handle.set_page_checked(handle, year, i + 1)

    return page >= total_page


def fetch_order_item_list_by_year(handle, year, start_page=1):
    visit_url(handle, gen_hist_url(year, start_page))

    keep_logged_on(handle)

    year_list = store_yahoo.handle.get_year_list(handle)

    logging.info(
        "Check order of {year} ({year_index}/{total_year})".format(
            year=year, year_index=year_list.index(year) + 1, total_year=len(year_list)
        )
    )

    store_yahoo.handle.set_progress_bar(
        handle,
        gen_status_label_by_year(year),
        store_yahoo.handle.get_order_count(handle, year),
    )

    page = start_page
    while True:
        if not store_yahoo.handle.get_page_checked(handle, year, page):
            is_last = fetch_order_item_list_by_year_page(handle, year, page)
            store_yahoo.handle.set_page_checked(handle, year, page)
        else:
            is_last = skip_order_item_list_by_year_page(handle, year, page)

        store_yahoo.handle.store_order_info(handle)

        if is_last:
            break

        page += 1

    store_yahoo.handle.get_progress_bar(handle, gen_status_label_by_year(year)).update()

    store_yahoo.handle.set_year_checked(handle, year)


def fetch_year_list(handle):
    driver, wait = store_yahoo.handle.get_selenium_driver(handle)

    visit_url(handle, gen_hist_url("", 1))

    keep_logged_on(handle)

    year_list = list(
        sorted(
            map(
                lambda elem: int(elem.get_attribute("value")),
                driver.find_elements(By.XPATH, '//select[@id="year"]/option[contains(@value, "20")]'),
            )
        )
    )

    store_yahoo.handle.set_year_list(handle, year_list)

    return year_list


def fetch_order_count_by_year(handle, year):
    driver, wait = store_yahoo.handle.get_selenium_driver(handle)

    store_yahoo.handle.set_status(handle, "注文件数を調べています... {year}年".format(year=year))

    visit_url(handle, gen_hist_url(year, 1))

    return int(
        driver.find_element(
            By.XPATH, '//h2[contains(@class, "elResultCount")]/span[contains(@class, "elCount")]'
        ).text
    )


def fetch_order_count(handle):
    year_list = store_yahoo.handle.get_year_list(handle)

    logging.info("Collect order count")

    store_yahoo.handle.set_progress_bar(handle, STATUS_ORDER_COUNT, len(year_list))

    total_count = 0
    for year in year_list:
        if year >= store_yahoo.handle.get_cache_last_modified(handle).year:
            count = fetch_order_count_by_year(handle, year)
            store_yahoo.handle.set_order_count(handle, year, count)
            logging.info("Year {year}: {count:4,} orders".format(year=year, count=count))
        else:
            count = store_yahoo.handle.get_order_count(handle, year)
            logging.info("Year {year}: {count:4,} orders [cached]".format(year=year, count=count))

        total_count += count
        store_yahoo.handle.get_progress_bar(handle, STATUS_ORDER_COUNT).update()

    logging.info("Total order is {total_count:,}".format(total_count=total_count))

    store_yahoo.handle.get_progress_bar(handle, STATUS_ORDER_COUNT).update()
    store_yahoo.handle.store_order_info(handle)


def fetch_order_item_list_all_year(handle):
    driver, wait = store_yahoo.handle.get_selenium_driver(handle)

    year_list = fetch_year_list(handle)
    fetch_order_count(handle)

    store_yahoo.handle.set_progress_bar(
        handle, STATUS_ORDER_ITEM_ALL, store_yahoo.handle.get_total_order_count(handle)
    )

    for year in year_list:
        if (
            (year == datetime.datetime.now().year)
            or (year == store_yahoo.handle.get_cache_last_modified(handle).year)
            or (not store_yahoo.handle.get_year_checked(handle, year))
        ):
            fetch_order_item_list_by_year(handle, year)
        else:
            logging.info(
                "Done order of {year} ({year_index}/{total_year}) [cached]".format(
                    year=year, year_index=year_list.index(year) + 1, total_year=len(year_list)
                )
            )
            store_yahoo.handle.get_progress_bar(handle, STATUS_ORDER_ITEM_ALL).update(
                store_yahoo.handle.get_order_count(handle, year)
            )

    store_yahoo.handle.get_progress_bar(handle, STATUS_ORDER_ITEM_ALL).update()


def fetch_order_item_list(handle):
    store_yahoo.handle.set_status(handle, "巡回ロボットの準備をします...")
    driver, wait = store_yahoo.handle.get_selenium_driver(handle)

    store_yahoo.handle.set_status(handle, "注文履歴の収集を開始します...")

    try:
        fetch_order_item_list_all_year(handle)
    except:
        local_lib.selenium_util.dump_page(
            driver, int(random.random() * 100), store_yahoo.handle.get_debug_dir_path(handle)
        )
        raise

    store_yahoo.handle.set_status(handle, "注文履歴の収集が完了しました．")


def execute_login(handle):
    driver, wait = store_yahoo.handle.get_selenium_driver(handle)

    local_lib.selenium_util.click_xpath(
        driver, '//p[contains(@class, "elButton")]/a/span[contains(text(), "ログイン")]'
    )

    wait_for_loading(handle, xpath='//div[@class="loginAreaBox"]')
    driver.find_element(By.XPATH, '//input[@id="login_handle"]').send_keys(
        store_yahoo.handle.get_login_user(handle)
    )
    local_lib.selenium_util.click_xpath(
        driver, '//button[contains(@type, "button") and contains(text(), "次へ")]'
    )

    wait_for_loading(handle, xpath='//div[@class="loginAreaBox"]')
    local_lib.selenium_util.click_xpath(
        driver, '//button[contains(@type, "submit") and contains(text(), "確認コードを送信")]'
    )

    wait_for_loading(handle, xpath='//div[@class="loginAreaBox"]')

    if local_lib.selenium_util.xpath_exists(
        driver, '//div[contains(@class, "errorMessage")]/span[contains(text(), "時間をおいてから再度")]'
    ):
        logging.error("It is necessary to leave extra time because of the continuous failures...")
        raise "ログインの失敗が続いたので，30分空ける必要があります．"

    logging.info("確認コードの対応を行います．")
    code = input("SMS で送られてきた確認コードを入力してください: ")

    driver.find_element(By.XPATH, '//input[@id="code"]').send_keys(code)
    local_lib.selenium_util.click_xpath(
        driver, '//button[contains(@type, "submit") and contains(text(), "ログイン")]'
    )

    time.sleep(2)

    if local_lib.selenium_util.xpath_exists(driver, '//div[@class="loginAreaBox"]'):
        local_lib.selenium_util.click_xpath(
            driver,
            '//span[contains(@class, "ar-radio_label") and contains(text(), "メールアドレス")]/following-sibling::div[contains(@class, "ar-radio_focus")]',
        )
        driver.find_element(By.XPATH, '//input[@name="aq_answer"]').send_keys(
            store_yahoo.handle.get_login_mail(handle)
        )
        local_lib.selenium_util.click_xpath(
            driver, '//button[contains(@type, "submit") and contains(text(), "入力する")]'
        )

        time.sleep(2)


def keep_logged_on(handle):
    driver, wait = store_yahoo.handle.get_selenium_driver(handle)

    wait_for_loading(handle)

    if not local_lib.selenium_util.xpath_exists(
        driver, '//p[contains(@class, "elButton")]/a/span[contains(text(), "ログイン")]'
    ):
        return

    logging.info("Try to login")

    for i in range(LOGIN_RETRY_COUNT):
        if i != 0:
            logging.info("Retry to login")

        execute_login(handle)

        wait_for_loading(handle)

        if not local_lib.selenium_util.xpath_exists(driver, '//div[@class="loginAreaBox"]'):
            return

        logging.warning("Failed to login")

        local_lib.selenium_util.dump_page(
            driver,
            int(random.random() * 100),
            store_yahoo.handle.get_debug_dir_path(handle),
        )

    logging.error("Give up to login")
    raise Exception("ログインに失敗しました．")


if __name__ == "__main__":
    from docopt import docopt

    import local_lib.logger
    import local_lib.config

    args = docopt(__doc__)

    local_lib.logger.init("test", level=logging.INFO)

    config = local_lib.config.load(args["-c"])
    handle = store_yahoo.handle.create(config)

    driver, wait = store_yahoo.handle.get_selenium_driver(handle)

    try:
        fetch_order_item_list(handle)
    except:
        driver, wait = store_yahoo.handle.get_selenium_driver(handle)
        logging.error(traceback.format_exc())

        local_lib.selenium_util.dump_page(
            driver,
            int(random.random() * 100),
            store_yahoo.handle.get_debug_dir_path(handle),
        )
