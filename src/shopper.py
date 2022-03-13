from beautifultable import BeautifulTable
import logging
import traceback
import keyboard
import time
import os
from shop.anya import AnyaShopper
from shop.drognan import DrognanShopper
from config import Config
from logger import Logger
from shop.larzuk import LarzukShopper
from version import __version__


def main():
    config = Config()
    if config.general["logg_lvl"] == "info":
        Logger.init(logging.INFO)
    elif config.general["logg_lvl"] == "debug":
        Logger.init(logging.DEBUG)
    else:
        print(f"ERROR: Unkown logg_lvl {config.general['logg_lvl']}. Must be one of [info, debug]")

    print(f"============ Shop {__version__} [name: {config.general['name']}] ============")
    table = BeautifulTable()
    table.rows.append(["f9", "Shop"])
    table.rows.append(["f10", "Pause"])
    table.rows.append([config.general['exit_key'], "Stop shop"])
    table.columns.header = ["hotkey", "action"]
    print(table)
    print("\n")

    merchant = LarzukShopper(config)
    keyboard.add_hotkey(config.general["exit_key"], lambda: merchant.stop())
    keyboard.add_hotkey("f10", lambda: merchant.pause())

    while 1:
        if keyboard.is_pressed("f9"):
            merchant.start()
            break
        time.sleep(0.02)

if __name__ == "__main__":
    # To avoid cmd just closing down, except any errors and add a input() to the end
    try:
        main()
    except:
        traceback.print_exc()
    print("Press Enter to exit ...")
    input()
