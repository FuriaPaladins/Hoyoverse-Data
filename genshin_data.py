import json
from datetime import datetime

import requests
from bs4 import BeautifulSoup as bs

from tools import download_image


def save_banner_json(data):
    with open('genshin_banners.json', 'w') as f:
        # Write the json with indent 4
        f.write(json.dumps(data, indent=4))


def get_characters():
    """
    Returns all characters from ambr.top for checking if a character is a 4* or a 5*
    """
    req = requests.get('https://api.ambr.top/v2/en/avatar').json()['data']
    return [req['items'][i] for i in req['items']]


def get_weapons():
    """
    Returns all weapons from ambr.top for checking if a weapon is a 4* or a 5*
    """
    req = requests.get('https://api.ambr.top/v2/en/weapon').json()['data']
    return [req['items'][i] for i in req['items']]


def get_fandom_page():
    """
    Main function that returns a bs4 object of the fandom page for banners
    """
    url = "https://genshin-impact.fandom.com/wiki/Wish/History#Wishes_by_Type"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0'
    }
    req = requests.get(url, headers=headers)
    soup = bs(req.text, 'html.parser')
    return soup


def genshin_main():
    ## Get data from ambr.top
    characters, weapons = get_characters(), get_weapons()

    ## Get fandom data
    fandom_data = get_fandom_page()

    banners = []
    ## Get banners by type
    for i in [('Character_Event_Wishes', 'character'), ('Weapon_Event_Wishes', 'weapon'), ('Permanent_Wishes', 'permanent')]:
        span_tag = fandom_data.find('span', {'id': i[0]})
        table_tag = span_tag.find_next('table')

        type_banners = []
        for row in table_tag.find_all('tr')[1:]:
            # Extract data from each TD in the row
            tds = row.find_all('td')

            ## first_td has the banner image and name
            first_td = tds[0]
            image_url = f"{str(first_td.find('img')['data-src']).split('.png')[0]}.png" if first_td.find('img') is not None else None
            banner_name = first_td.text.strip()

            ## second_td has the characters/weapons
            second_td = tds[1]
            drop_divs = second_td.find_all('div')
            drop_data = []
            for div in drop_divs:
                a_tag = div.find('a')
                drop_data.append(a_tag['href'].split('/')[-1].replace('_', ' ').replace('%27', "'"))

            ## third_td has the start and end dates
            third_td = tds[2]
            date_time = third_td['data-sort-value']
            if date_time != '' and 'none' not in date_time:
                ## If the date_time is not empty or none.
                # Empty - New/upcoming banner
                # None - Permanent banners
                start = int(datetime.strptime(date_time[len(date_time) // 2:], '%Y-%m-%d %H:%M:%S').timestamp() - 3600)
                end = int(datetime.strptime(date_time[:len(date_time) // 2], '%Y-%m-%d %H:%M:%S').timestamp() - 3600)
            else:
                ## Otherwise, no start or end date
                start, end = None, None

            ## Sort banner drops into 4* and 5*
            uprate_5, uprate_4 = [], []
            if i[1] == 'character':
                # If the banner is character banner, search for characters
                for character in drop_data:
                    for char in characters:
                        if character == char['name']:
                            if char['rank'] == 5:
                                uprate_5.append(character)
                            elif char['rank'] == 4:
                                uprate_4.append(character)

            elif i[1] == 'weapon':
                # If the banner is weapon banner, search for weapons
                for weapon in drop_data:
                    for wep in weapons:
                        if weapon == wep['name']:
                            if wep['rank'] == 5:
                                uprate_5.append(weapon)
                            elif wep['rank'] == 4:
                                uprate_4.append(weapon)

            ## Add the banner to the list
            # Note: Base start/end time is EU. NA is +6 hours, Asia is -6 hours
            type_banners.append(
                {'name': banner_name, 'image': image_url, 'uprate_5': uprate_5, 'uprate_4': uprate_4,
                 'date': {'eu': {'start': start, 'end': end}, 'na': {'start': start + 21600, 'end': end + 21600},
                          'asia': {'start': start - 21600, 'end': end - 21600}} if start is not None else None})

            ## Download the banner images if they aren't already downloaded
            download_image(image_url, f"assets/banners/{i[1]}/{banner_name}.png")

        ## Add banners to the list
        banners.append({'type': i[1], 'banners': type_banners})

    ## Save the banner data to json
    save_banner_json(banners)
