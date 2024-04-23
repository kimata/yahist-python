#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Yahoo!ストアの購入履歴情報を収集して，Excel ファイルとして出力します．

Usage:
  yahist.py [-c CONFIG] [-e] [-N]

Options:
  -c CONFIG    : CONFIG を設定ファイルとして読み込んで実行します．[default: config.yaml]
  -e           : データ収集は行わず，Excel ファイルの出力のみ行います．
  -N            : サムネイル画像を含めないようにします．
"""

import logging
import random

import store_yahoo.handle
import store_yahoo.crawler
import store_yahoo.order_history
import local_lib.selenium_util

NAME = "yahist"
VERSION = "0.1.0"


def execute_fetch(handle):
    try:
        store_yahoo.crawler.fetch_order_item_list(handle)
    except:
        driver, wait = store_yahoo.handle.get_selenium_driver(handle)
        local_lib.selenium_util.dump_page(
            driver, int(random.random() * 100), store_yahoo.handle.get_debug_dir_path(handle)
        )
        raise


def execute(config, is_export_mode=False, is_need_thumb=True):
    handle = store_yahoo.handle.create(config)

    try:
        if not is_export_mode:
            execute_fetch(handle)
        store_yahoo.order_history.generate_table_excel(
            handle, store_yahoo.handle.get_excel_file_path(handle), is_need_thumb
        )

        store_yahoo.handle.finish(handle)
    except:
        store_yahoo.handle.set_status(handle, "エラーが発生しました", is_error=True)
        logging.error(traceback.format_exc())

    input("完了しました．エンターを押すと終了します．")


######################################################################
if __name__ == "__main__":
    from docopt import docopt
    import traceback

    import local_lib.logger
    import local_lib.config

    args = docopt(__doc__)

    local_lib.logger.init("yahist", level=logging.INFO)

    config_file = args["-c"]
    is_export_mode = args["-e"]
    is_need_thumb = not args["-N"]

    config = local_lib.config.load(args["-c"])

    try:
        execute(config, is_export_mode, is_need_thumb)
    except:
        logging.error(traceback.format_exc())
