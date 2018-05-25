# -*- coding: utf-8 -*-
import os

import requests
from bs4 import BeautifulSoup

import util
from creds import service_db, REQUESTS_PROXY


def get_metadata(service, post_id, pic_name=None):
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
            characters = ' '.join(['#' + x['name'][
                                         :len(x['name']) if not '_(' in x['name'] else x['name'].find(
                                             '_(')] for x in tags
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
            direct = get_less_sized_url(response['large_file_url'], response['file_url'], service=service)
            pic_ext = response['file_ext']
            pic_name = f"{service}.{post_id}{pic_ext}"
    else:
        pic_name = ''
        direct = ''
        authors = []
        characters = []
        copyrights = []
    return (pic_name, direct, authors, characters, copyrights)


def get_less_sized_url(*urls, service):
    sizes = {}
    for url in urls:
        url = make_usable_url(url, service)
        req = requests.get(url, stream=True, proxies=REQUESTS_PROXY)
        req_size = req.headers.get('content-length')
        if req_size:
            sizes[url] = int(req_size)
    least_sized = sorted(sizes, key=sizes.get)[0]
    return least_sized


def make_usable_url(url, service):
    if url.startswith('//'):
        url = "https:" + url
    elif url.startswith("/"):
        url = f"https://{service_db[service]['base_url']}{url}"
    return url


def download(url, filename):
    make_usable_url(url, os.path.basename(filename).split('.')[0])
    proxies = REQUESTS_PROXY
    headers = {'user-agent': 'OhaioPoster',
               'content-type': 'application/json; charset=utf-8'}
    try:
        req = requests.get(url, stream=True, proxies=proxies, headers=headers)
    except requests.exceptions.RequestException as ex:
        util.log_error(ex)
        return False
    total_length = req.headers.get('content-length', 0)
    if os.path.exists(filename) and os.path.getsize(filename) == int(total_length):
        return True
    if not total_length:  # no content length header
        return False
    with open(filename, 'wb') as f:
        # dl = 0
        # start = time.clock()
        for chunk in req.iter_content(1024):
            f.write(chunk)
            # dl += len(chunk)
            # done = int(100 * dl / int(total_length))
            # if (time.clock() - start) > 1:
            #     edit_markup(chat_id=dl_msg.chat.id, message_id=dl_msg.message_id,
            #                 reply_markup=markup_templates.gen_progress(done))
            #     start = time.clock()
    return True
