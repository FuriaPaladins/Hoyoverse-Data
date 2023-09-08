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
    start_time = datetime.now()
    ## Get data from ambr.top
    characters, weapons = get_characters(), get_weapons()
    chars_n_weapons = characters + weapons

    ## Get fandom data
    fandom_data = get_fandom_page()
    ## Find all spans that have an ID with Version_ in it. (Doesn't matter what number afterwards)
    all_versions = [float(i.get('id').split('Version_')[-1]) for i in
                    fandom_data.find_all('span', {'id': lambda x: x and 'Version_' in x})]

    banners = {'permanent': [], 'character': [], 'weapon': []}
    ## Get banners by type

    for i in all_versions:
        span_tag = fandom_data.find('span', {'id': f"Version_{i}"})

        if 'No Results' in span_tag.find_next('p').text:
            ## If there's no banner data for an update, do not add it cause then it'll end up grabbing the whole Character Banner table
            continue

        table_tag = span_tag.find_next('table')

        for row in table_tag.find_all('tr')[1:]:
            # Extract data from each TD in the row
            tds = row.find_all('td')

            ## first_td has the banner image and name
            first_td = tds[0]
            try:
                image_url = f"{str(first_td.find('img')['data-src']).split('/revision')[0]}" if first_td.find(
                    'img') is not None else None
            except:
                image_url = f"{str(first_td.find('img')['src']).split('/revision')[0]}" if first_td.find(
                    'img') is not None else None

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
            for drop in drop_data:
                for item in chars_n_weapons:
                    if drop == item['name']:
                        if item['rank'] == 5:
                            uprate_5.append({'id': item['id'], 'name': item['name']})
                        elif item['rank'] == 4:
                            uprate_4.append({'id': item['id'], 'name': item['name']})

            ## Add the banner to the list
            # Note: Base start/end time is EU. NA is +6 hours, Asia is -6 hours
            if "Beginners' Wish" in banner_name or "Wanderlust Invocation" in banner_name:
                banner_type = 'permanent'
                banners['permanent'].append(
                    {'name': banner_name, 'image': image_url, 'version': i, 'uprate_5': uprate_5, 'uprate_4': uprate_4,
                     'date': {'eu': {'start': start, 'end': end}, 'na': {'start': start + 21600, 'end': end + 21600},
                              'asia': {'start': start - 25200, 'end': end - 25200}} if start is not None else None})
            elif "Epitome Invocation" in banner_name:
                banner_type = 'weapon'
                banners['weapon'].append(
                    {'name': banner_name, 'image': image_url, 'version': i, 'uprate_5': uprate_5, 'uprate_4': uprate_4,
                     'date': {'eu': {'start': start, 'end': end}, 'na': {'start': start + 21600, 'end': end + 21600},
                              'asia': {'start': start - 25200, 'end': end - 25200}} if start is not None else None})
            else:
                banner_type = 'character'
                banners['character'].append(
                    {'name': banner_name, 'image': image_url, 'version': i, 'uprate_5': uprate_5, 'uprate_4': uprate_4,
                     'date': {'eu': {'start': start, 'end': end}, 'na': {'start': start + 21600, 'end': end + 21600},
                              'asia': {'start': start - 25200, 'end': end - 25200}} if start is not None else None})

            ## Download the banner images if they aren't already downloaded
            download_image(image_url, f"assets/genshin/{banner_type}/{banner_name}.png")

    ## Save the banner data to json
    save_banner_json(banners)
    print(f"Finished scraping Genshin data in {datetime.now() - start_time}")
