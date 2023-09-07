# Hoyoverse Data
This repository includes semi auto-updating data scraped from the [genshin wiki](https://genshin-impact.fandom.com/wiki/Wish/History#Wishes_by_Type) and [starrail wiki](https://honkai-star-rail.fandom.com/wiki/Warp/List).  
Data is also gathered from [ambr.top](https://ambr.top/) and [yatta.top](https://hsr.yatta.top/en) to sort Characters and Weapons between 4* and 5* for the json file.  

Currently, includes banner data and banner assets.  

This project is maintained primarily for personal use for my Discord Bot, [Itto](https://bit.ly/itto_bot)  


## Usage - Genshin
You should be requesting the json [from this page](https://raw.githubusercontent.com/FuriaPaladins/Hoyoverse-Data/master/genshin_banners.json)  

## Usage - Star Rail
You should be requesting json [from this page](https://raw.githubusercontent.com/FuriaPaladins/Hoyoverse-Data/master/starrail_banners.json)

This repo has a python file called `cast_dataclasses.py` which just converts the response content to dataclass objects.
