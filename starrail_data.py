import json
from datetime import datetime

import requests
from bs4 import BeautifulSoup as bs

from tools import download_image
from rich import print


def save_banner_json(data):
    with open('starrail_banners.json', 'w') as f:
        # Write the json with indent 4
        f.write(json.dumps(data, indent=4))


def get_characters():
    """
    Returns all characters from yatta.top for checking if a character is a 4* or a 5*
    """
    req = requests.get('https://api.yatta.top/hsr/v2/en/avatar').json()['data']
    return [req['items'][i] for i in req['items']]


def get_weapons():
    """
    Returns all weapons from yatta.top for checking if a weapon is a 4* or a 5*
    """
    req = requests.get('https://api.yatta.top/hsr/v2/en/equipment').json()['data']
    return [req['items'][i] for i in req['items']]


def get_fandom_page():
    """
    Main function that returns a bs4 object of the fandom page for banners
    """
    url = "https://honkai-star-rail.fandom.com/wiki/Warp/List"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0'
    }
    req = requests.get(url, headers=headers)
    soup = bs(req.text, 'html.parser')
    return soup


def get_banner_datapage(banner, chars_n_weapons):
    banner_url = banner.get('href')

    url = f"https://honkai-star-rail.fandom.com{banner_url}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; rv:91.0) Gecko/20100101 Firefox/91.0'
    }
    req = requests.get(url, headers=headers)
    soup = bs(req.text, 'html.parser')

    start = 0
    end = 0
    for enum, i in enumerate(['time_start', 'time_end']):
        countdown = soup.find('td', {'data-source': i})
        try:
            time_value = datetime.strptime(
                countdown.text.replace('Start', '').replace('End', '').replace(' (Server Time)', ''),
                '%d %B, %Y %H:%M').timestamp()
        except ValueError:
            time_value = datetime.strptime(
                countdown.text.replace('Start', '').replace('End', '').replace(' (Server Time)', '').replace('GMT+8',
                                                                                                             '+0800'),
                '%d %B, %Y %H:%M %z').timestamp()
        if enum == 0:
            start = int(time_value)
        else:
            end = int(time_value)

    ## Get uprates
    # Find the next span with ID Promoted_or_Featured_with_a_Drop-Rate_Boost
    span_tag = soup.find('span', {'id': 'Promoted_or_Featured_with_a_Drop-Rate_Boost'})
    table = span_tag.find_next('table')
    ## Find all a tags, and get their text
    # Remove the first value as it's typically either "Characters" or "Light Cones"
    drop_data = [i.text for i in table.find_all('a') if i.text not in ['Characters', 'Light Cones', '']]

    del banner['href']
    #banner['start_time'] = start
    #banner['end_time'] = end

    ## Sort out uprates
    uprate_5, uprate_4 = [], []
    for drop in drop_data:
        for item in chars_n_weapons:
            if drop == item['name']:
                if item['rank'] == 5:
                    uprate_5.append({'id': item['id'], 'name': item['name']})
                elif item['rank'] == 4:
                    uprate_4.append({'id': item['id'], 'name': item['name']})

    banner['uprate_5'] = uprate_5
    banner['uprate_4'] = uprate_4

    banner['date'] = {'eu': {'start': start, 'end': end}, 'na': {'start': start + 21600, 'end': end + 21600}, 'asia': {'start': start - 25200, 'end': end - 25200}} if start is not None else None
    return banner


def starrail_main():
    start_time = datetime.now()
    ## Get data from yatta.top
    characters, weapons = get_characters(), get_weapons()
    chars_n_weapons = characters + weapons

    ## Get fandom data
    fandom_data = get_fandom_page()
    ## Find all spans that have an ID with Version_ in it. (Doesn't matter what number afterwards)

    banners = {'permanent': [], 'character': [], 'lightcone': []}
    ## Manually add permanent banners. (Formatted differently than the others, no need to make extra requests if the format never changes)
    banners['permanent'].append({'name': 'Stellar Warp',
                                 'image': 'https://static.wikia.nocookie.net/houkai-star-rail/images/6/6f/Stellar_Warp.png',
                                 'version': 1.0, 'uprate_5': [], 'uprate_4': [], 'date': None})
    banners['permanent'].append({'name': 'Departure Warp',
                                 'image': 'https://static.wikia.nocookie.net/houkai-star-rail/images/4/4c/Departure_Warp.png',
                                 'version': 1.0, 'uprate_5': [], 'uprate_4': [], 'date': None})
    for i in banners['permanent']:
        download_image(i['image'], f"assets/starrail/permanent/{i['image'].split('/')[-1].replace('.png', '').replace('.jpg', '')}.png")

    ## Get banners by type
    characters, light_cones = [], []
    for i in ['Event_Warps', 'Past']:

        ## Find the span tag with the ID of Current/Past
        span_tag = fandom_data.find('span', {'id': i})

        ## Get next table
        table = span_tag.find_next('table')

        # all_headers = table.find_all('tr')
        ## Remove the first 3 headers which are just the overall headers.
        # They are "Version", "Character Event Warp", and "Light Cone Event Warp"
        # all_headers = [i for i in all_headers if i.text not in ["Version", "Character Event Warp", "Light Cone Event Warp"]]

        all_rows = table.find_all('tr')[1:]
        current_version = 0.0

        for enum, header in enumerate(all_rows):

            for th in header.find_all('th'):
                ## a tag is the version.
                a = th.find_all('a')
                if a:
                    current_version = float(a[0].text)


            for td in header.find_all('td'):
                img_tag = td.find('img')
                img_data_src = img_tag.get('data-src')
                if img_data_src is not None:
                    img = img_data_src
                else:
                    img = img_tag.get('src')
                img = img.split('/revision')[0]

                ## If the a.href has a /{current_version}, break because it means it's reached upcomming content
                if f"/{current_version}" in td.find('a').get('href'):
                    break

                if "Brilliant Fixation" in td.text:
                    light_cones.append({'name': td.text, 'image': img, 'current': True if 'Event_Warps' in i else False,
                                        'href': td.find('a').get('href')})
                else:
                    characters.append({'name': td.text, 'image': img, 'current': True if 'Event_Warps' in i else False,
                                       'href': td.find('a').get('href')})

                download_image(img, f"assets/starrail/{'lightcone' if 'Brilliant Fixation' in td.text else 'character'}/{img.split('/')[-1].replace('.png', '').replace('.jpg', '')}.png")

    for char_banner in characters:
        banners['character'].append(get_banner_datapage(char_banner, chars_n_weapons))
    for light_cone_banner in light_cones:
        banners['lightcone'].append(get_banner_datapage(light_cone_banner, chars_n_weapons))
    ## Save the banner data to json
    save_banner_json(banners)

    print(f"Finished scraping Star Rail data in {datetime.now() - start_time}")
