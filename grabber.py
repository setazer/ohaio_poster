# -*- coding: utf-8 -*-
import os

import requests
# import imagehash
from PIL import Image
from bs4 import BeautifulSoup

import util
from creds import service_db, REQUESTS_PROXY


# def hash(image_file):
#     return imagehash.average_hash(Image.open(image_file))
#
# def hash_diff(hash1:imagehash.ImageHash,hash2:imagehash.ImageHash):
#     return (hash1-hash2)/(hash1.hash)**2


def metadata(service, post_id, pic_name=None):
    if service == 'gel':
        service_api = 'https://' + service_db[service]['post_api']
        service_tag_api = 'https://' + service_db[service]['tag_api']
        service_login = 'https://' + service_db[service]['login_url']
        service_payload = service_db[service]['payload']

        with requests.Session() as ses:
            ses.post(service_login, data=service_payload)
            gel_xml = ses.get(service_api + post_id)
            try:
                post = BeautifulSoup(gel_xml.text, 'lxml').posts.post
            except (IndexError, NameError, AttributeError):
                return (pic_name, '', '', '', '')
            pic_ext = os.path.splitext(post['sample_url'])[1]
            pic_name = service + '.' + post_id + pic_ext
            tag_page = ses.get(service_tag_api + post['tags'])
            tags = BeautifulSoup(tag_page.text, 'lxml').find_all('tag')
            authors = ' '.join(['#' + x['name'] for x in tags
                                if x['type'] == '1' and x['name'] != '' and x['name'] != 'artist_request'])
            characters = ' '.join(['#' + x.split('_(')[0] for x in tags
                                   if x['type'] == '4' and x['name'] != '' and x[
                                       'name'] != 'character_request'])
            copyrights = ' '.join(['#' + x['name'].replace('_(series)', '') for x in tags
                                   if x['type'] == '3' and x['name'] != '' and x[
                                       'name'] != 'copyright_request'])
            direct = post['sample_url']
    elif service == 'dan':
        service_api = 'http://' + service_db[service]['post_api']
        service_login = 'http://' + service_db[service]['login_url']
        service_payload = service_db[service]['payload']
        proxies = REQUESTS_PROXY
        with requests.Session() as ses:

            ses.headers = {'user-agent': 'OhaioPoster',
                           'content-type': 'application/json; charset=utf-8'}
            ses.post(service_login, data=service_payload)
            response = ses.get(service_api.format(post_id), proxies=proxies).json()
            if response['is_banned']:
                return ('', '', [], [], [])
            authors = ' '.join({f'#{x}' for x in response['tag_string_artist'].split()})
            copyrights = ' '.join({f'#{x}'.replace('_(series)', '') for x in
                                   response['tag_string_copyright'].split()})
            characters = ' '.join({f"#{x.split('_(')[0]}" for x in
                                   response['tag_string_character'].split()})
            direct = response['file_url']
            pic_ext = response['file_ext']
            pic_name = f"{service}.{post_id}.{pic_ext}"
    else:
        pic_name = ''
        direct = ''
        authors = []
        characters = []
        copyrights = []
    return (pic_name, direct, authors, characters, copyrights)

def usable_url(url, service):
    if url.startswith('//'):
        url = "https:" + url
    elif url.startswith("/"):
        url = f"https://{service_db[service]['base_url']}{url}"
    return url


def download(url, filename):
    service = os.path.basename(filename).split('.')[0]
    usable_url(url, service)
    proxies = REQUESTS_PROXY
    headers = {'user-agent': 'OhaioPoster'}
    if service == 'pix':
        headers['Referer'] = 'https://app-api.pixiv.net/'
        proxies = {}
    try:
        req = requests.get(url, stream=True, proxies=proxies, headers=headers)
    except requests.exceptions.RequestException as ex:
        util.log_error(ex)
        return False
    total_length = req.headers.get('content-length', 0)
    if os.path.exists(filename) and os.path.getsize(filename) == int(total_length):
        return True
    # if not total_length:  # no content length header
    #     return False
    try:
        im = Image.open(req.raw)
    except OSError:
        return False
    aspect = im.height / im.width
    if not (3 >= aspect >= 0.3):
        return False
    im.thumbnail((2000, 2000))
    im.save(filename)
    return True
