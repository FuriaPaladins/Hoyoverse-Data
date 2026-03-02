import asyncio
import logging
import os
import re
import time
from collections import defaultdict
from datetime import timezone, timedelta, datetime

import aiofiles
import aiohttp
import orjson

logging.basicConfig(level=logging.INFO)

# Pre-compile regex for performance
BANNER_NAME_RE = re.compile(r'"(.*?)"')
CLEAN_TAGS_RE = re.compile(r'</?color[^>]*>')


class GachaListURLS:
    GENSHIN = "https://operation-webstatic.mihoyo.com/gacha_info/hk4e/cn_gf01/gacha/list.json"
    HSR = "https://operation-webstatic.mihoyo.com/gacha_info/hkrpg/prod_gf_cn/gacha/list.json"
    ZZZ = "https://operation-webstatic.mihoyo.com/gacha_info/nap/prod_gf_cn/gacha/list.json"


class GachaBannerURLS:
    GENSHIN = "https://operation-webstatic.mihoyo.com/gacha_info/hk4e/cn_gf01/{banner}/en-us.json"
    HSR = "https://operation-webstatic.hoyoverse.com/gacha_info/hkrpg/prod_official_eur/{banner}/en-us.json"
    ZZZ = "https://operation-webstatic.hoyoverse.com/gacha_info/nap/prod_gf_eu/{banner}/en-us.json"


VALUES = {
    "gi": {"name": "NameTextMapHash", "rarity": "Rarity"},
    "hsr": {"name": "EquipmentName", "rarity": "Rarity"},
    "zzz": {"name": "Name", "rarity": "Rarity"}
}

RARITY_MAP = {
    "QUALITY_ORANGE": 5,
    "QUALITY_PURPLE": 4,
    "QUALITY_ORANGE_SP": 5
}


class BannerParser:
    def __init__(self, session: aiohttp.ClientSession, game: str):
        self.session = session
        self.game = game
        self.short_game = {"genshin": "gi", "hsr": "hsr", "zzz": "zzz"}[game]
        self.file_path = f"banners/{self.game}.json"
        self.file_path_formatted = f"banners/{self.game}_formatted.json"

        self.item_lookup: dict[str, dict] = {}

        self.formatted_banner_data: dict = defaultdict(list)
        self.data_to_add: dict = defaultdict(list)
        self.logger = logging.getLogger(f"BannerParser({self.short_game:<3})")

    async def parse(self):
        new_banner_ids = await self.load_banners()
        if not new_banner_ids:
            self.logger.info("No new banners found.")
            return

        self.logger.info(f"Found {len(new_banner_ids)} new banners.")

        # 1. Fetch raw data for new banners in parallel
        await asyncio.gather(*(self.parse_raw_banner(b) for b in new_banner_ids))

        # 2. Load Item Data once
        await self.load_item_data()

        # 3. Load existing formatted data
        if os.path.exists(self.file_path_formatted):
            async with aiofiles.open(self.file_path_formatted, "rb") as f:
                content = await f.read()
                if content:
                    self.formatted_banner_data = orjson.loads(content)

        # 4. Process new banners
        await asyncio.gather(*(self.parse_formatted_banner(b) for b in new_banner_ids))

        # 5. Merge logic
        new_count = 0
        for b_type, banners in self.data_to_add.items():
            existing_list = self.formatted_banner_data.setdefault(b_type, [])
            for new_b in banners:
                # Optimized check: using get() and direct object comparison
                if not any(ex["name"] == new_b["name"] and ex["start_time"] == new_b["start_time"] for ex in existing_list):
                    existing_list.append(new_b)
                    new_count += 1

        if new_count > 0:
            async with aiofiles.open(self.file_path_formatted, "wb") as f:
                await f.write(orjson.dumps(self.formatted_banner_data))
            self.logger.info(f"Added {new_count} new parsed banners.")

    async def load_item_data(self):
        """Fetches and builds a high-speed lookup table for items."""
        base_url = f"https://raw.githubusercontent.com/EnkaNetwork/API-docs/refs/heads/master/store/{self.short_game}"
        loc_file = "hsr.json" if self.short_game == "hsr" else "locs.json"

        # Parallel fetch character/weapon/text data
        res_loc, res_char, res_weap = await asyncio.gather(
            self.session.get(f"{base_url}/{loc_file}"),
            self.session.get(f"{base_url}/avatars.json"),
            self.session.get(f"{base_url}/weapons.json")
        )

        text_map = (orjson.loads(await res_loc.read()))["en"]
        characters = orjson.loads(await res_char.read())
        weapons = orjson.loads(await res_weap.read())

        # Build lookup table: item_name -> parsed_info
        for itype, dataset in [("character", characters), ("weapon", weapons)]:
            for item_id, item_data in dataset.items():
                # Logic to resolve name from hash
                if self.short_game == "hsr":
                    key = "AvatarName" if itype == "character" else "EquipmentName"
                    name_hash = item_data[key]["Hash"]
                elif self.short_game == "zzz" and itype == "weapon":
                    name_hash = str(item_data.get("ItemName"))
                else:
                    name_hash = str(item_data.get(VALUES[self.short_game]["name"]))

                name = text_map.get(name_hash, "Unknown")

                # Rarity logic
                raw_rarity = item_data.get("QualityType") or item_data.get("Rarity")
                fin_rarity = RARITY_MAP.get(raw_rarity, raw_rarity)
                if self.short_game == "zzz": fin_rarity += 1

                self.item_lookup[name] = {
                    "id": int(str(item_id).split("-")[0]),
                    "name": name,
                    "rarity": fin_rarity,
                    "item_type": itype
                }

    async def load_banners(self) -> list:
        async with self.session.get(getattr(GachaListURLS, self.game.upper())) as resp:
            data = orjson.loads(await resp.read())

        if data['retcode'] != 0:
            self.logger.error(f"Error: {data['message']}")
            return []

        banners = data["data"]['list']
        ## Delete banner name from each banner
        for b in banners:
            b.pop('gacha_name', None)

        game_data = {"banners": []}
        if os.path.exists(self.file_path):
            async with aiofiles.open(self.file_path, "rb") as f:
                if content := await f.read():
                    game_data = orjson.loads(content)

        new_banners = [b for b in banners if b not in game_data['banners']]

        if new_banners:
            game_data['banners'].extend(new_banners)
            os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
            async with aiofiles.open(self.file_path, "wb") as f:
                await f.write(orjson.dumps(game_data, option=orjson.OPT_INDENT_2))

        return new_banners

    async def parse_raw_banner(self, banner: dict):
        """ Parses the raw banner data, saves it as the request data looks. """
        path = f"banners/{self.game}/{banner['gacha_id']}.json"
        if os.path.exists(path):
            return

        os.makedirs(os.path.dirname(path), exist_ok=True)
        async with self.session.get(getattr(GachaBannerURLS, self.game.upper()).format(banner=banner['gacha_id'])) as resp:
            data = await resp.read()
            async with aiofiles.open(path, "wb") as f:
                await f.write(data)

    def parse_drop(self, drop: dict) -> dict:
        # O(1) lookup instead of O(N) loop
        return self.item_lookup.get(drop["item_name"], {})

    async def parse_formatted_banner(self, banner: dict):
        # Dispatch table for cleaner routing
        parsers = {
            "genshin": self._parse_banner_gi,
            "hsr": self._parse_banner_hsr,
            "zzz": self._parse_banner_zzz
        }
        await parsers[self.game](banner)

    # Simplified common logic for the internal parsers
    async def _get_banner_json(self, gacha_id):
        async with aiofiles.open(f"banners/{self.game}/{gacha_id}.json", "rb") as f:
            return orjson.loads(await f.read())

    async def _parse_banner_gi(self, banner: dict):
        if banner["gacha_type"] in [100, 200]:
            return

        banner_data = await self._get_banner_json(banner['gacha_id'])
        start_server = "18:00:00" in banner["begin_time"]
        end_server = any(x in banner["end_time"] for x in ["14:59:59", "17:59:00"])

        parsed_data = {
            "name": self.parse_banner_name(banner_data["title"]),
            "banner_type": banner["gacha_type"],
            "uprate_5": [self.parse_drop(i) for i in (banner_data["r5_up_items"] or [])],
            "uprate_4": [self.parse_drop(i) for i in (banner_data["r4_up_items"] or [])],
            "start_time": {
                "time": str(self.parse_time(banner["begin_time"], start_server)),
                "is_server_time": start_server
            },
            "end_time": {
                "time": str(self.parse_time(banner["end_time"], end_server)),
                "is_server_time": end_server
            }
        }
        self.data_to_add[str(banner["gacha_type"])].append(parsed_data)

    async def _parse_banner_hsr(self, banner: dict):
        if banner["gacha_type"] in [1, 2]:
            return  # skip standard & beginner banner

        banner_data = await self._get_banner_json(banner['gacha_id'])

        start = banner["begin_time"]
        start_server_time = ("12:00:00" in start)
        start_dt = self.parse_time(start, start_server_time)

        # Specific HSR timezone correction logic
        if start_dt.hour == 6 and start_dt.minute == 30:
            start_dt -= timedelta(hours=3, minutes=30)

        end = banner["end_time"]
        end_dt = self.parse_time(end, True)  # Always server time for HSR

        parsed_data = {
            "name": banner_data["title"].split(":")[0],
            "banner_type": banner["gacha_type"],
            "uprate_5": [self.parse_drop(i) for i in (banner_data["items_up_star_5"] or [])],
            "uprate_4": [self.parse_drop(i) for i in (banner_data["items_up_star_4"] or [])],
            "start_time": {"time": str(start_dt), "is_server_time": start_server_time},
            "end_time": {"time": str(end_dt), "is_server_time": True}
        }

        # Check if we already have this banner period (for dual banners)
        found = False
        for saved in self.data_to_add[str(banner["gacha_type"])]:
            if saved["start_time"] == parsed_data["start_time"] and saved["end_time"] == parsed_data["end_time"]:
                # Merge unique items only
                saved["uprate_5"] = list(
                    {item['id']: item for item in (saved["uprate_5"] + parsed_data["uprate_5"])}.values())
                saved["uprate_4"] = list(
                    {item['id']: item for item in (saved["uprate_4"] + parsed_data["uprate_4"])}.values())

                # Handle names list
                names = saved.get("names", [saved["name"]])
                if parsed_data["name"] not in names:
                    names.append(parsed_data["name"])
                saved["names"] = names
                found = True
                break

        if not found:
            self.data_to_add[str(banner["gacha_type"])].append(parsed_data)

    async def _parse_banner_zzz(self, banner: dict):
        g_type = str(banner["gacha_type"])
        banner_id = int(g_type[0] if len(g_type) == 4 else g_type[:2])

        if banner_id in [1, 5]:
            return  # skip bangboo & standard banner

        banner_data = await self._get_banner_json(banner['gacha_id'])

        start = banner["begin_time"]
        start_server_time = "12:00:00" in start
        start_dt = self.parse_time(start, start_server_time)

        # ZZZ timezone correction logic
        if start_dt.hour == 6:
            start_dt -= timedelta(hours=4)

        end = banner["end_time"]
        end_dt = self.parse_time(end, True)

        parsed_data = {
            "name": banner_data["title"].split(":")[0],
            "banner_type": banner_id,
            "uprate_5": [self.parse_drop(i) for i in (banner_data["items_up_star_5"] or [])],
            "uprate_4": [self.parse_drop(i) for i in (banner_data["items_up_star_4"] or [])],
            "start_time": {"time": str(start_dt), "is_server_time": start_server_time},
            "end_time": {"time": str(end_dt), "is_server_time": True}
        }

        # Merge logic for ZZZ (Similar to HSR dual-banner logic)
        found = False
        for saved in self.data_to_add[str(banner_id)]:
            if saved["start_time"] == parsed_data["start_time"] and saved["end_time"] == parsed_data["end_time"]:
                saved["uprate_5"] = list({item['id']: item for item in (saved["uprate_5"] + parsed_data["uprate_5"])}.values())
                saved["uprate_4"] = list({item['id']: item for item in (saved["uprate_4"] + parsed_data["uprate_4"])}.values())

                names = saved.get("names", [saved["name"]])
                if parsed_data["name"] not in names:
                    names.append(parsed_data["name"])
                saved["names"] = names
                found = True
                break

        if not found:
            self.data_to_add[str(banner_id)].append(parsed_data)

    @staticmethod
    def parse_time(time_str: str, is_server_time: bool) -> datetime:
        offset = 1 if is_server_time else 8
        return datetime.fromisoformat(time_str).replace(tzinfo=timezone(timedelta(hours=offset)))

    @staticmethod
    def parse_banner_name(title: str):
        if not title:
            return None

        clean = CLEAN_TAGS_RE.sub('', title)
        m = BANNER_NAME_RE.search(clean)
        return m.group(1).strip() if m else clean.strip()


async def main():
    async with aiohttp.ClientSession() as session:
        await asyncio.gather(*(BannerParser(session, g).parse() for g in ["genshin", "hsr", "zzz"]))


if __name__ == "__main__":
    asyncio.run(main())
