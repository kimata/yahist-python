#!/usr/bin/env python3
# -*- coding: utf-8 -*-

HIST_URL_BY_YEAR = (
    "https://odhistory.shopping.yahoo.co.jp/order-history/list" + "?year={year}&firstorder={first_order}"
)

ORDER_URL_BY_NO = (
    "https://odhistory.shopping.yahoo.co.jp/order-history/details?"
    + "list-catalog={store_id}&catalog={store_id}&oid={no}"
)


ORDER_COUNT_PER_PAGE = 20
