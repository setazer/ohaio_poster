# -*- coding: utf-8 -*-
from datetime import datetime
import os
import hashlib
import pixivpy3

import aiofiles as aiofiles
import aiohttp
from PIL import Image
from bs4 import BeautifulSoup
from imagehash import dhash

from creds import service_db, REQUESTS_PROXY
from util import in_thread


async def metadata(service, post_id, pic_name=None):
    if service == 'gel':
        service_api = 'https://' + service_db[service]['post_api']
        service_tag_api = 'https://' + service_db[service]['tag_api']
        service_login = 'https://' + service_db[service]['login_url']
        service_payload = service_db[service]['payload']
        proxy = REQUESTS_PROXY
        async with aiohttp.ClientSession() as session:
            await session.post(service_login, data=service_payload)
            async with session.get(service_api + post_id, proxy=proxy) as gel_xml:
                try:
                    post = BeautifulSoup(await gel_xml.text(), 'lxml').posts.post
                except (IndexError, NameError, AttributeError):
                    return (pic_name, '', '', '', '')
            pic_ext = os.path.splitext(post['sample_url'])[1]
            pic_name = service + '.' + post_id + pic_ext
            async with session.get(service_tag_api + post['tags'], proxy=proxy) as tag_page:
                tags = BeautifulSoup(await tag_page.text(), 'lxml').find_all('tag')
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
        proxy = REQUESTS_PROXY
        async with aiohttp.ClientSession() as session:
            headers = {'user-agent': 'OhaioPoster',
                       'content-type': 'application/json; charset=utf-8'}
            await session.post(service_login, data=service_payload, headers=headers)
            async with session.get(service_api.format(post_id), proxy=proxy) as req:
                response = await req.json()
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
    return pic_name, direct, authors, characters, copyrights


def usable_url(url, service):
    if url.startswith('//'):
        url = "https:" + url
    elif url.startswith("/"):
        url = f"https://{service_db[service]['base_url']}{url}"
    return url


async def get_file(url, service, filename):
    url = usable_url(url, service)
    proxy = REQUESTS_PROXY
    headers = {'user-agent': 'OhaioPoster'}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, proxy=proxy) as req:
            async with aiofiles.open(filename, 'wb') as f:
                await f.write(await req.read())


def get_pixiv_pic(url, filename):
    api = pixivpy3.AppPixivAPI()
    api.download(url, path='', name=filename)


async def download(url, filename):
    service = os.path.basename(filename).partition('.')[0]
    if service == 'pix':
        await in_thread(get_pixiv_pic, url, filename)
    else:
        await get_file(url, service, filename)

    try:
        im = Image.open(filename)
    except OSError:
        return None

    aspect = im.height / im.width
    if not (3 >= aspect >= 1 / 3):
        return None  # skip pictures that are too tall or too wide
    im.thumbnail((2000, 2000))
    im_hash = dhash(im, hash_size=8)
    im.save(filename)
    return str(im_hash)
