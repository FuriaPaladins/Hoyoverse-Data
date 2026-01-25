import asyncio
import json
import logging
import os
import re
from collections import defaultdict
from datetime import timezone, timedelta, datetime

import aiofiles
import aiohttp

logging.basicConfig(level=logging.INFO)


class GachaListURLS:
    GENSHIN = "https://operation-webstatic.mihoyo.com/gacha_info/hk4e/cn_gf01/gacha/list.json"
    HSR = "https://operation-webstatic.mihoyo.com/gacha_info/hkrpg/prod_gf_cn/gacha/list.json"
    ZZZ = "https://operation-webstatic.mihoyo.com/gacha_info/nap/prod_gf_cn/gacha/list.json"


class GachaBannerURLS:
    GENSHIN = "https://operation-webstatic.hoyoverse.com/gacha_info/hk4e/os_euro/{banner}/en-us.json"
    HSR = "https://operation-webstatic.hoyoverse.com/gacha_info/hkrpg/prod_official_eur/{banner}/en-us.json"
    ZZZ = "https://operation-webstatic.hoyoverse.com/gacha_info/nap/prod_gf_eu/{banner}/en-us.json"


class BannerParser:
    def __init__(self, session: aiohttp.ClientSession, game: str):
        self.session = session
        self.game = game

        self.short_game = {
            "genshin": "gi",
            "hsr": "hsr",
            "zzz": "zzz"
        }[game]

        self.file_path = f"banners/{self.game}.json"
        self.file_path_formatted = f"banners/{self.game}_formatted.json"

        self.character_data: dict = {}
        self.weapon_data: dict = {}

        self.formatted_banner_data: dict = defaultdict(list)
        self.data_to_add: dict = defaultdict(list)

        self.logger = logging.getLogger(f"BannerParser({self.short_game:<3}) ")

    async def parse(self):
        new_banner_ids = await self.load_banners()
        if not new_banner_ids:
            self.logger.info("No new banners found.")
            return
        self.logger.info(f"Found {len(new_banner_ids)} new banners for {self.game}.")

        ## Save raw banners
        task = [self.parse_raw_banner(banner) for banner in new_banner_ids]
        await asyncio.gather(*task)

        ## Save formatted banners
        # If there are new banners, we need to load the hakushin data to add them to the formatted file
        await self.load_data()

        async with aiofiles.open(self.file_path_formatted, "r") as f:
            formatted_data = await f.read()
            self.formatted_banner_data = json.loads(formatted_data)

        tasks = [self.parse_formatted_banner(banner) for banner in new_banner_ids]
        await asyncio.gather(*tasks)

        ## add each banner
        banner_count = 0
        for banner_type, banners in self.data_to_add.items():
            for add_banner in banners:

                exists = False
                for saved_banner in self.formatted_banner_data.get(banner_type, []):
                    if saved_banner["name"] == add_banner["name"] and str(saved_banner["start_time"]) == str(add_banner["start_time"]):
                        exists = True
                        break

                if not exists:
                    self.formatted_banner_data.setdefault(banner_type, [])
                    self.formatted_banner_data[banner_type].append(add_banner)
                    banner_count += 1

        self.logger.info(f"Added {banner_count} new parsed banners.")

        async with aiofiles.open(self.file_path_formatted, "w") as f:
            await f.write(json.dumps(self.formatted_banner_data, indent=4))
        self.logger.info(f"Saved formatted banner data to {self.file_path_formatted}")

    async def load_data(self):
        if not self.character_data:
            characters = await self.session.get(f"https://api.hakush.in/{self.short_game}/data/character.json")
            self.character_data = await characters.json()

        if not self.weapon_data:
            weapons = await self.session.get(f"https://api.hakush.in/{self.short_game}/data/{'lightcone' if self.game == 'hsr' else 'weapon'}.json")
            self.weapon_data = await weapons.json()

    async def load_banners(self) -> list[dict] | None:
        response = await self.session.get(getattr(GachaListURLS, self.game.upper()))
        data = await response.json()

        if data['retcode'] != 0:
            self.logger.error(f"Error: {data['message']}")
            return None

        banners = data["data"]['list']
        ## Delete banner name from each banner
        for banner in banners:
            del banner['gacha_name']

        # Check if the file exists, if not create it with an empty JSON structure
        if not os.path.exists(self.file_path):
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            async with aiofiles.open(self.file_path, "w") as f:
                await f.write(json.dumps({"banners": []}, indent=4))

        # Now proceed with opening the file to read and then update
        async with aiofiles.open(self.file_path, "r") as f:
            game_data = await f.read()
            game_data = json.loads(game_data)

        new_banners = []
        for banner in banners:
            if banner not in game_data['banners']:
                game_data['banners'].append(banner)
                new_banners.append(banner)

        # Write the updated data back to the file
        if new_banners:
            async with aiofiles.open(self.file_path, "w") as f:
                await f.write(json.dumps(game_data, indent=4))

        return new_banners

    async def parse_raw_banner(self, banner: dict):
        """ Parses the raw banner data, saves it as the request data looks. """
        file_path = f"banners/{self.game}/{banner['gacha_id']}.json"
        if os.path.exists(file_path):
            return

        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        response = await self.session.get(getattr(GachaBannerURLS, self.game.upper()).format(banner=banner['gacha_id']))
        data = await response.json()

        async with aiofiles.open(file_path, "w") as f:
            await f.write(json.dumps(data, indent=4))

    async def parse_formatted_banner(self, banner: dict):
        """ Formats the banner data from the URL request in a way that is easier to use in a wish tracker. """
        if self.game == "genshin":
            return await self._parse_banner_gi(banner)
        elif self.game == "hsr":
            return await self._parse_banner_hsr(banner)
        elif self.game == "zzz":
            return await self._parse_banner_zzz(banner)
        return False

    async def _parse_banner_gi(self, banner: dict):
        if banner["gacha_type"] in [100, 200]:
            return  # skip novice & standard banner

        start = banner["begin_time"]
        start_server_time = (True if "18:00:00" in start else False)
        start_dt = self.parse_time(start, start_server_time)

        end = banner["end_time"]
        end_server_time = (True if "14:59:59" in end or "17:59:00" in end else False)
        end_dt = self.parse_time(end, end_server_time)

        async with aiofiles.open(f"banners/genshin/{banner['gacha_id']}.json", "r") as f:
            banner_data = await f.read()
            banner_data = json.loads(banner_data)

        parsed_banner_name = self.parse_banner_name(banner_data["title"])
        if not parsed_banner_name:
            self.logger.error(f"Could not parse banner name for {banner['gacha_id']}")

        parsed_5 = [self.parse_drop_gi(i) for i in (banner_data["r5_up_items"] or [])]
        parsed_4 = [self.parse_drop_gi(i) for i in (banner_data["r4_up_items"] or [])]

        parsed_data = {
            "name": parsed_banner_name,
            "banner_type": banner["gacha_type"],
            "uprate_5": parsed_5,
            "uprate_4": parsed_4,
            "start_time": {
                "time": str(start_dt),
                "is_server_time": start_server_time,
            },
            "end_time": {
                "time": str(end_dt),
                "is_server_time": end_server_time,
            }
        }

        for saved_banner in self.data_to_add[str(banner["gacha_type"])]:
            if saved_banner["name"] == parsed_data["name"] and str(saved_banner["start_time"]) == str(parsed_data["start_time"]):
                return

        self.data_to_add[str(banner["gacha_type"])].append(parsed_data)

    async def _parse_banner_hsr(self, banner: dict):
        if banner["gacha_type"] in [1, 2]:
            return  # skip standard & beginner banner

        start = banner["begin_time"]
        start_server_time = (
            True if "12:00:00" in start else False
        )
        start_dt = self.parse_time(start, start_server_time)
        if "06:30:00" in start_dt.isoformat():
            start_dt -= timedelta(hours=3, minutes=30)

        end = banner["end_time"]
        end_server_time = True  # Always server time for Starrail
        end_dt = self.parse_time(end, end_server_time)

        async with aiofiles.open(f"banners/hsr/{banner['gacha_id']}.json", "r") as f:
            banner_data = await f.read()
            banner_data = json.loads(banner_data)

        parsed_5 = [self.parse_drop_hsr(i) for i in (banner_data["items_up_star_5"] or [])]
        parsed_4 = [self.parse_drop_hsr(i) for i in (banner_data["items_up_star_4"] or [])]

        parsed_data = {
            "name": banner_data["title"].split(":")[0],
            "banner_type": banner["gacha_type"],
            "uprate_5": parsed_5,
            "uprate_4": parsed_4,
            "start_time": {
                "time": str(start_dt),
                "is_server_time": start_server_time,
            },
            "end_time": {
                "time": str(end_dt),
                "is_server_time": end_server_time,
            }
        }

        found = False
        for saved_banner in self.data_to_add[str(banner["gacha_type"])]:
            if saved_banner["banner_type"] == parsed_data["banner_type"] and (str(saved_banner["start_time"]) == str(parsed_data["start_time"])) and (str(saved_banner["end_time"]) == str(parsed_data["end_time"])):

                for item in parsed_data["uprate_5"]:
                    if item not in saved_banner["uprate_5"]:
                        saved_banner["uprate_5"].append(item)

                for item in parsed_data["uprate_4"]:
                    if item not in saved_banner["uprate_4"]:
                        saved_banner["uprate_4"].append(item)

                saved_banner["names"] = list(set(saved_banner.get("names", [saved_banner["name"]]) + [parsed_data["name"]]))
                found = True

        if not found:
            self.data_to_add[str(banner["gacha_type"])].append(parsed_data)

    async def _parse_banner_zzz(self, banner: dict):
        banner_id = int(str(banner["gacha_type"])[0] if len(str(banner["gacha_type"])) == 4 else str(banner["gacha_type"])[:2])
        if banner_id in [1, 5]:
            return  # skip bangboo & standard banner

        start = banner["begin_time"]
        start_server_time = "12:00:00" in start
        start_dt = self.parse_time(start, start_server_time)
        if "06:00:00" in start_dt.isoformat():
            start_dt -= timedelta(hours=4)

        end = banner["end_time"]
        end_server_time = True  # Always server time for Starrail
        end_dt = self.parse_time(end, end_server_time)

        async with aiofiles.open(f"banners/zzz/{banner['gacha_id']}.json", "r") as f:
            banner_data = await f.read()
            banner_data = json.loads(banner_data)

        parsed_5 = [self.parse_drop_zzz(i) for i in (banner_data["items_up_star_5"] or [])]
        parsed_4 = [self.parse_drop_zzz(i) for i in (banner_data["items_up_star_4"] or [])]

        parsed_data = {
            "name": banner_data["title"].split(":")[0],
            "banner_type": banner_id,
            "uprate_5": parsed_5,
            "uprate_4": parsed_4,
            "start_time": {
                "time": str(start_dt),
                "is_server_time": start_server_time,
            },
            "end_time": {
                "time": str(end_dt),
                "is_server_time": end_server_time,
            }
        }

        found = False
        for saved_banner in self.data_to_add[str(banner_id)]:
            if saved_banner["banner_type"] == parsed_data["banner_type"] and (
                    str(saved_banner["start_time"]) == str(parsed_data["start_time"])) and (
                    str(saved_banner["end_time"]) == str(parsed_data["end_time"])):

                for item in parsed_data["uprate_5"]:
                    if item not in saved_banner["uprate_5"]:
                        saved_banner["uprate_5"].append(item)

                for item in parsed_data["uprate_4"]:
                    if item not in saved_banner["uprate_4"]:
                        saved_banner["uprate_4"].append(item)

                saved_banner["names"] = list(
                    set(saved_banner.get("names", [saved_banner["name"]]) + [parsed_data["name"]]))
                found = True

        if not found:
            self.data_to_add[str(banner_id)].append(parsed_data)

    @staticmethod
    def parse_time(time_str: str, is_server_time: bool) -> datetime:
        if is_server_time:
            dt = datetime.fromisoformat(time_str).replace(tzinfo=timezone(timedelta(hours=1)))
        else:
            dt = datetime.fromisoformat(time_str).replace(tzinfo=timezone(timedelta(hours=8)))
        return dt

    @staticmethod
    def parse_banner_name(title: str):
        """
        Remove <color...> tags then extract the quoted banner name.
        Falls back to stripping common prefixes if no quotes are present.
        """
        if not title:
            return None

        clean = re.sub(r'</?color[^>]*>', '', title)
        m = re.search(r'"(.*?)"', clean)
        if m:
            return m.group(1).strip()

        clean = re.sub(r'^(?:Event|Chronicled|Beginners\'|Wanderlust|Epitome)(?:\s+Wish)?\s*[:\-]?\s*', '', clean, flags=re.I).strip()
        return clean or None

    def parse_drop_gi(self, drop: dict) -> dict:
        if drop["item_type"] == "Character":
            rarity_map = {
                "QUALITY_ORANGE": 5,
                "QUALITY_PURPLE": 4
            }

            for character_id, character in self.character_data.items():
                if character["EN"] == drop["item_name"]:
                    return {"id": character_id, "name": character["EN"], "rank": rarity_map.get(character["rank"], character["rank"]), "colour": drop["item_color"], "item_type": "character"}

        elif drop["item_type"] == "Weapon":
            for weapon_id, weapon in self.weapon_data.items():
                if weapon["EN"] == drop["item_name"]:
                    return {"id": weapon_id, "name": weapon["EN"], "rank": weapon["rank"], "item_type": "weapon"}

        self.logger.error(f"Unknown drop: {drop}")
        return {}

    def parse_drop_hsr(self, drop: dict) -> dict:
        if drop["item_type"] == "avatar":
            rarity_map = {
                "CombatPowerAvatarRarityType4": 4,
                "CombatPowerAvatarRarityType5": 5
            }
            for character_id, character in self.character_data.items():
                if character["en"] == drop["item_name"]:
                    return {"id": character_id, "name": character["en"], "rank": rarity_map.get(character["rank"], character["rank"]), "item_type": "character"}

        elif drop["item_type"] == "equipment":
            rarity_map = {
                "CombatPowerLightconeRarity3": 3,
                "CombatPowerLightconeRarity4": 4,
                "CombatPowerLightconeRarity5": 5
            }
            for weapon_id, weapon in self.weapon_data.items():
                if weapon["en"] == drop["item_name"]:
                    return {"id": weapon_id, "name": weapon["en"], "rank": rarity_map.get(weapon["rank"], weapon["rank"]), "item_type": "lightcone"}

        self.logger.error(f"Unknown drop: {drop}")
        return {}

    def parse_drop_zzz(self, drop: dict) -> dict:
        if drop["item_type"] == "3":
            for character_id, character in self.character_data.items():
                if character["EN"] == drop["item_name"]:
                    return {"id": character_id, "name": character["EN"], "rank": drop["star"], "item_type": "character"}

        elif drop["item_type"] == "5":
            for weapon_id, weapon in self.weapon_data.items():
                if weapon["EN"] == drop["item_name"]:
                    return {"id": weapon_id, "name": weapon["EN"], "rank": drop["star"], "item_type": "lightcone"}

        self.logger.error(f"Unknown drop: {drop}")
        return {}


async def main():
    games = [
        "genshin", "hsr", "zzz",
    ]
    ## create tasks for each game
    async with aiohttp.ClientSession() as session:
        tasks = [BannerParser(session, game).parse() for game in games]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
