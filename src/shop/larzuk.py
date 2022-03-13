from datetime import datetime, timedelta
from multiprocessing.sharedctypes import Value
from operator import attrgetter, itemgetter
import os
from re import I, T
import time
import math
from tkinter import W

from PIL import Image, ImageDraw, ImageFont, ImageChops
from pathlib import Path
from typing import Tuple
from cv2 import threshold
import keyboard
import numpy as np
from char.basic import Basic
from char.i_char import IChar
from char.sorceress.light_sorc import LightSorc
from game_stats import GameStats
from item.item_finder import ItemFinder, Template
from pather import Location, Pather

from town import TownManager, A1, A2, A3, A4, A5
from screen import Screen
from config import Config
from logger import Logger
from npc_manager import NpcManager, Npc
from template_finder import TemplateFinder, TemplateMatch
from ui.ui_manager import UiManager
from utils.custom_mouse import mouse
from utils.misc import wait, load_template
import cv2

from messenger import Messenger

class LarzukShopper:
    """
    Shop at Larzuk for sutff
    """

    def __init__(self, config: Config):
        self._config = config

        self._running_start = datetime.now()
        self._running_for = 0
        # self._max_run_length = timedelta(0, 28800) 8 hours
        self._max_run_length = timedelta(0, 43200)
        self._run_count = 0
        self._font_size = 19
        # 19 is the default size in 720p
        self._font = ImageFont.truetype("assets/fonts/exocetblizzardot-medium.otf", 19)
        self._templates_initialized = False

        # As we find many matches for items, we skip some points that are too close from each other
        # this is the parameter used in the min distance points need to be
        # math.hypot(x0 - x1, y0, y1) < self._min_distance_between_points:
        self._min_distance_between_points = 20

        self._item_finder = ItemFinder()
        self._screen = Screen(config.general["monitor"])
        self._template_finder = TemplateFinder(self._screen,  ["assets\\templates", "assets\\npc", "assets\\shop"], save_last_res=True)
        self._pather = Pather(self._screen, self._template_finder)
        self._messenger = Messenger()
        self._npc_manager = NpcManager(
            screen=self._screen, template_finder=self._template_finder
        )

        self._ui_manager = UiManager(self._screen, self._template_finder, GameStats())
        self._char: IChar = Basic(self._config.basic, self._screen, self._template_finder, self._ui_manager, self._pather)

        # Create Town Manager
        a5 = A5(self._screen, self._template_finder, self._pather, self._char, self._npc_manager)
        a4 = A4(self._screen, self._template_finder, self._pather, self._char, self._npc_manager)
        a3 = A3(self._screen, self._template_finder, self._pather, self._char, self._npc_manager)
        a2 = A2(self._screen, self._template_finder, self._pather, self._char, self._npc_manager)
        a1 = A1(self._screen, self._template_finder, self._pather, self._char, self._npc_manager)
        self._a5 = a5
        self._town_manager = TownManager(self._template_finder, self._ui_manager, self._item_finder, a1, a2, a3, a4, a5)
        self._route_config = self._config.routes
        self._route_order = self._config.routes_order

        # Claws config
        self.roi_vendor = config.ui_roi["vendor_stash"]
        self.char_location = Location.A5_TOWN_START
        self.articles_bought = 0

        self.armors = [
            'ancient',
            'full_plate',
            'gothic_plate',
            'plate'
        ]

        self.helms = [
            'great_helm',
            'crown'
        ]

        self.weapons = [
            'bastard_sword',
            'great_sword',
            'crystal_sword',
            'war_sword',
            'flamberge'
        ]

        # Color suffixes
        self.weapon_suffixes = [
            'Burning',
            'Thunder',
            'Storms',
            'Carnage',
            'Slaughter',
            'Butchery',
            'Evisceration',
            'Performance',
            'Transcendence',
            'Pestilence',
            'Anthrax',
            # 'Swiftness',
            'Quickness',
            'Glacier',
            'Winter',
            'Locust',
            'Lamprey',
            'Incineration',
            'Wraith',
            'Vampire',
            'Enchantment',
            'Giant',
            'Ox',
            'Charges' # always take charges just in case we have something cool
        ]

        # Store images refs in memory to avoid loading them every time (see initTemplates)
        self.asset_folder = "assets/shop/larzuk/"
        self.templates = {}
        self.paused = True

    def pause(self):
        Logger.info("Pausing...")
        self.paused = True

    def restart(self):
        self._ui_manager.save_and_exit()
        wait(2, 5)
        self._ui_manager.start_game()
        wait(10, 15)
        self.char_location = Location.A5_TOWN_START
        self.start()

    def start(self):
        if not self._templates_initialized:
            self.init_templates()
            Logger.debug("Loaded templates!")

        Logger.info("Personal Larzuk Shopper at your service! Hang on, running some errands...")
        self.paused = False
        while not self.paused: 
            if datetime.now() - self._running_start > self._max_run_length:
                Logger.info("Tired of shopping.")
                Logger.info(f"Bought {self.articles_bought}")
                self.paused = True
                self._ui_manager.save_and_exit()
                break

            if not self.reset_shop():
                Logger.info("Something went wrong, pausing.")
                self.restart()
                break

            if not self.shop():
                Logger.info("Something went wrong, pausing.")
                self.restart()
                break

            self._running_for = datetime.now() - self._running_start 
            self._run_count += 1
            Logger.info(f"Done shopping, let's reset the shop. Shopping for {self._running_for}")

    def stop(self):
        Logger.info(f"Leaving, shopped {self._run_count} times for {self._running_for}. Bought {self.articles_bought} articles.")
        os._exit(1)

    def shop(self):
        """
        This assumes we are next to Larzuk, opens its shop and looks for stuff
        """
        self._npc_manager.open_npc_menu(Npc.LARZUK)
        self._npc_manager.press_npc_btn(Npc.LARZUK, "trade_repair")
        time.sleep(0.1) 

        # Go to Armors
        x, y = self._screen.convert_screen_to_monitor((self._config.ui_pos["vendor_tab_1_x"], self._config.ui_pos["vendor_tab_1_y"]))
        mouse.move(x, y)
        mouse.click(button="left")
        wait(0.3, 1.5)
        should_stash = self.look_for_armor()

        # Go to Weapons 1
        x, y = self._screen.convert_screen_to_monitor((self._config.ui_pos["vendor_tab_2_x"], self._config.ui_pos["vendor_tab_2_y"]))
        mouse.move(x, y)
        mouse.click(button="left")
        wait(0.3, 2)
        bought_weapon = self.look_for_weapon()

        if not should_stash:
            should_stash = bought_weapon

        # Go to Weapons 2
        x, y = self._screen.convert_screen_to_monitor((self._config.ui_pos["vendor_tab_3_x"], self._config.ui_pos["vendor_tab_3_y"]))
        mouse.move(x, y)
        mouse.click(button="left")
        wait(0.3, 2)
        bought_weapon = self.look_for_weapon()

        if not should_stash:
            should_stash = bought_weapon

        # self._ui_manager.close_vendor_screen()
        keyboard.send("esc")

        def stash_is_open_func():
            img = self._screen.grab()
            found = self._template_finder.search("INVENTORY_GOLD_BTN", img, roi=self._config.ui_roi["gold_btn"]).valid
            found |= self._template_finder.search("INVENTORY_GOLD_BTN", img, roi=self._config.ui_roi["gold_btn_stash"]).valid
            return found

        # Move away from larzuk, path traverser has issue with 
        # if not self._pather.traverse_nodes((self.char_location, Location.A5_WP), self._char, force_move=True):
        #     Logger.error('Could not go to WP')

        # self.char_location = Location.A5_WP
        x, y = self._screen.convert_screen_to_monitor((37, 328))
        self._char.move((x, y), force_move=True)

        if should_stash:
            Logger.debug("Should stash")
            if self._char.select_by_template(["A5_STASH", "A5_STASH_2"], stash_is_open_func):
                self._ui_manager.stash_all_items(self._config.char["num_loot_columns"], self._item_finder, True)

        return True

    def open_nihla_wp(self) -> bool: 
        for x in range(0, 5):
            wait(0.7, 1.3)

            wp = self._template_finder.search(
                ref=self.templates["wp_nihla"],
                inp_img=self._screen.grab(),
                threshold=0.70,
                best_match=True
            )

            if not wp.valid:
                Logger.error(f'Could not find nihla wp? lets try again {x}')
                continue

            mouse._move_to(wp.rec[0] + wp.rec[3] / 2, wp.rec[1] + wp.rec[2] / 2)
            wait(0.8, 1.3)
            mouse.click(button="left")
            wait(0.3, 0.8)

            has_wp = self._template_finder.search(self.templates["waypoint_menu"], self._screen.grab())
            if has_wp.valid:
                return True

            Logger.error(f'Could not open nihla wp? lets try again {x}')

        return False

    def reset_shop(self) -> bool:
        if not self._town_manager.open_wp(self.char_location):
            Logger.error("Could not find WP.")
            return False

        if not self._ui_manager.use_wp(5, 5):
            Logger.error("Could not use WP from town to nihla")
            return False

        self.char_location = Location.A5_NIHLATAK_START

        if not self.open_nihla_wp():
            Logger.error("Could not find nihla WP.")
            return False

        if not self._ui_manager.use_wp(5, 0):
            Logger.error("Could not use WP to go back to town attempt again.")
            return False

        self.char_location = Location.A5_WP
        if not self._pather.traverse_nodes((self.char_location, Location.A5_LARZUK), self._char, force_move=True):
            return False

        self.char_location = Location.A5_LARZUK
        return True

    def look_for_armor(self) -> bool:
        bought_something = False
        vendor_screen = self._screen.grab()
        armors = []

        for armor_template in self.armors:
            armors = armors + self.template_matches(armor_template, vendor_screen, 0.80)

        armors.sort(key=lambda obj: obj.position[0], reverse=True)
        armors.sort(key=lambda obj: obj.position[1])

        for armor in armors:
            mouse.move(*armor.position)
            wait(0.1, 0.8)
            img = self._screen.grab()

            has_4_socket = self.has_text(img, "Socketed (4)")
            # is_titan = self.has_text(img, "of the Titan")
            is_whale = self.has_text(img, "of the Whale")
            # is_stability = self.has_text(img, "of Stability")
            # is_simplicity = self.has_text(img, "of Simplicity") #req
            is_amicae = self.has_text(img, "Amicae") # DR
            is_centaur = self.has_text(img, "of the Centaur") # dexterity
            is_nirvana = self.has_text(img, "Nirvana") # dexterity

            if has_4_socket and (is_whale or is_amicae or is_centaur or is_nirvana):
                mouse.click(button="right")
                Logger.info(f"Bought Jeweler's {armor}!")
                self.articles_bought += 1
                bought_something = True

        helms = []

        for helm_template in self.helms:
            helms = helms + self.template_matches(helm_template, vendor_screen, 0.80)

        for helm in helms:
            mouse.move(helm.position[0], helm.position[1] + 10)
            wait(0.3, 0.8)
            img = self._screen.grab()

            has_3_socket = self.has_text(img, "Socketed (3)")
            is_titan = self.has_text(img, "of the Titan")
            is_whale = self.has_text(img, "of the Whale")
            is_stability = self.has_text(img, "of Stability")

            if has_3_socket and (is_titan or is_whale or is_stability):
                mouse.click(button="right")
                Logger.info(f"Bought Jeweler's {helm}!")
                self.articles_bought += 1
                bought_something = True
            
        return bought_something

    def look_for_weapon(self) -> bool:
        bought_something = False
        vendor_screen = self._screen.grab()
        weapons = []

        for weapon_template in self.weapons:
            weapons = weapons + self.template_matches(weapon_template, vendor_screen, 0.75)

        weapons.sort(key=lambda obj: obj.position[0], reverse=True)
        weapons.sort(key=lambda obj: obj.position[1])

        for weapon in weapons:
            mouse.move(*weapon.position)
            wait(0.1, 0.8)
            img = self._screen.grab()
            has_bo = self.has_text(img, "+3 to Warcries", 0.93)

            # Let's look for colored ones only
            if has_bo and self.has_suffix(img):
                mouse.click(button="right")
                Logger.info(f"Bought Berserker's {weapon}!")
                self.articles_bought += 1
                bought_something = True
            
        return bought_something

    def has_suffix(self, img) -> bool:
        for suffix in self.weapon_suffixes:
            if self.has_text(img, suffix, 0.89):
                return True
        return False
    
    def init_templates(self): 
        directory = os.fsencode(self.asset_folder)
        for file in os.listdir(directory):
            filename = os.fsdecode(file)
            if filename.endswith(".png"):
                template = Path(filename).stem
                Logger.info(f"Load template {template}")
                self.templates[template] = load_template(self.asset_folder + filename, 1.0)
        self._templates_initialized = True

    def template_matches(self, name: str, img: np.ndarray, threshold: float) -> list[TemplateMatch]:
        if not name in self.templates:
            raise ValueError(f'Template {name} is not loaded')

        temp_matches = self._template_finder.search(
            ref=self.templates[name],
            inp_img=img,
            threshold=threshold,
            roi=self.roi_vendor,
            normalize_monitor=True,
            every_matches=True
        )

        # Note that this would be probably faster with np.array(np.where) but I'm not yet familiarize enough with the api
        def pointIsCloseToTemplateInList(point: Tuple[int], list: list[TemplateMatch]) -> bool:
            for p in list:
                if math.hypot(p.position[0] - point[0], p.position[1] - point[1]) < self._min_distance_between_points:
                    return True
            return False

        # Filter out values that are too close
        matches = []
        for template in temp_matches:
            if pointIsCloseToTemplateInList(template.position, matches):
                continue

            matches.append(template)

        return matches

    def template_match(self, name: str, img: np.ndarray, threshold: float) -> TemplateMatch:
        return self._template_finder.search(
            ref=self.templates[name],
            inp_img=img,
            threshold=threshold,
            roi=self.roi_vendor,
            normalize_monitor=True
        )

    def create_text_template(self, text: str, size: int = 19) -> Image:
        """
        Creates a template with diablo 2 font
        :param text: The text that will be printed
        :param size: The size of the text in points (19 is default)
        :return: Returns an Image
        """
        if 'str_' + text in self.templates:
            return self.templates['str_'+text]

        sizePx = size * (1 + 1/3)
        height = math.floor(sizePx)
        # finds an approximate width 
        widthCharPx = sizePx * 0.5 
        width = math.floor(len(text) * widthCharPx)
        image = Image.new('L', (width, height), 255)
        draw = ImageDraw.Draw(image)
        # use a bitmap font
        draw.text((0, 0), text, font=self._font, fill=0)
        # Fix approximate width and crop to content
        arr = np.asarray(image)
        coords = np.column_stack(np.where(arr < 255))
        max = np.amax(coords, 0)
        # Adds a px right + bottom
        self.templates['str_' + text] = np.asarray(image.crop((0, 0, max[1] + 1, max[0] + 1)))
        return self.templates['str_' + text]

    # TODO: implement ROI but vendor roi is too small
    def has_text(self, img, text: str, threshold: float = 0.85, font_size: int = 0) -> bool:
        if font_size == 0:
            font_size = self._font_size

        img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Do some threshold
        img[img > 70] = 255
        img = (255-img)

        template = self.create_text_template(text, font_size)
        res = cv2.matchTemplate(img, template, cv2.TM_CCOEFF_NORMED)
        return np.amax(res) >= threshold

    def select_by_template(self, template_type: str) -> bool:
        Logger.debug(f"Select {template_type}")
        template_match = self._template_finder.search_and_wait(template_type, time_out=10)
        if template_match.valid:
            x_m, y_m = self._screen.convert_screen_to_monitor(template_match.position)
            mouse.move(x_m, y_m)
            wait(0.1, 0.2)
            mouse.click(button="left")
            return True
        return False