import os
import requests


def create_dir(path):
    if not os.path.exists(path):
        os.makedirs(path)


def download_image(url, filename):
    """
    Downloads an image from a URL to a filename
    """
    create_dir(os.path.dirname(filename))
    ## If it exists already, don't download it again
    if os.path.exists(filename):
        return
    try:
        r = requests.get(url, stream=True)
        if r.status_code == 200:
            with open(filename, 'wb') as f:
                for chunk in r:
                    f.write(chunk)
    except Exception:
        pass
