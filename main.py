import asyncio
import json
import os

import aiofiles
import aiohttp


class GachaListURLS:
    GENSHIN = "https://operation-webstatic.mihoyo.com/gacha_info/hk4e/cn_gf01/gacha/list.json"
    HSR = "https://operation-webstatic.mihoyo.com/gacha_info/hkrpg/prod_gf_cn/gacha/list.json"
    ZZZ = "https://operation-webstatic.mihoyo.com/gacha_info/nap/prod_gf_cn/gacha/list.json"


class GachaBannerURLS:
    GENSHIN = "https://operation-webstatic.hoyoverse.com/gacha_info/hk4e/os_euro/{banner}/en-us.json"
    HSR = "https://operation-webstatic.hoyoverse.com/gacha_info/hkrpg/prod_official_eur/{banner}/en-us.json"
    ZZZ = "https://operation-webstatic.hoyoverse.com/gacha_info/nap/prod_gf_eu/{banner}/en-us.json"


async def parse_game(session: aiohttp.ClientSession, game: str):
    async with session.get(getattr(GachaListURLS, game.upper())) as response:
        data = await response.json()
    if data['retcode'] != 0:
        print(f"Error: {data['message']}")
        return

    banners = data['data']['list']
    ## Delete banner name from each banner
    for banner in banners:
        del banner['gacha_name']
    file_path = f"banners/{game}.json"

    # Check if the file exists, if not create it with an empty JSON structure
    if not os.path.exists(file_path):
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        async with aiofiles.open(file_path, "w") as f:
            await f.write(json.dumps({"banners": []}, indent=4))

    # Now proceed with opening the file to read and then update
    banner_counts = 0
    async with aiofiles.open(file_path, "r") as f:
        game_data = await f.read()
        game_data = json.loads(game_data)
        for banner in banners:
            if banner not in game_data['banners']:
                game_data['banners'].append(banner)
                banner_counts += 1
    print(f"Added {banner_counts} new banners for {game}")

    # Write the updated data back to the file
    async with aiofiles.open(file_path, "w") as f:
        await f.write(json.dumps(game_data, indent=4))

    ## Next: Get the details for each banner
    tasks = [parse_banner(session, game, banner['gacha_id']) for banner in banners]
    await asyncio.gather(*tasks)


async def parse_banner(session: aiohttp.ClientSession, game: str, banner: str):
    # first check if the banner already exists
    file_path = f"banners/{game}/{banner}.json"
    if os.path.exists(file_path):
        return
    else:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

    async with session.get(getattr(GachaBannerURLS, game.upper()).format(banner=banner)) as response:
        data = await response.json()

    async with aiofiles.open(file_path, "w") as f:
        await f.write(json.dumps(data, indent=4))
    print(f"Saved {game}/{banner}.json")


async def main():
    games = [
        "hsr", "genshin", "zzz"
    ]
    ## create tasks for each game
    async with aiohttp.ClientSession() as session:
        tasks = [parse_game(session, game) for game in games]
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
