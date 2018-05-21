# -*- coding: utf-8 -*-
import os
import requests
from bs4 import BeautifulSoup

from creds import service_db, TELEGRAM_PROXY


def grab_booru(service, post_id,pic_name=None):
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
        proxies = TELEGRAM_PROXY
        with requests.Session() as ses:
            ses.headers = {'user-agent': 'OhaioPoster/{0}'.format('0.0.0.1'),
                           'content-type': 'application/json; charset=utf-8'}
            ses.post(service_login, data=service_payload)
            response = ses.get(service_api.format(post_id), proxies=proxies).json()
            if response['is_banned']:
                return ('', '', [], [], [])
            authors = ' '.join(['#{}'.format(x) for x in response['tag_string_artist'].split()])
            copyrights = ' '.join(['#{}'.format(x).replace('_(series)', '') for x in
                          response['tag_string_copyright'].split()])
            characters = ' '.join(['#{}'.format(x[:len(x) if not '_(' in x else x.find('_(')]) for x in
                          response['tag_string_character'].split()])
            direct = 'http://' + service_db[service]['base_url'] + response['large_file_url'] if response['large_file_url'].startswith('/') else response['large_file_url'].replace('https','http')
            pic_ext = os.path.splitext(response['large_file_url'])[1]
            pic_name = service + '.' + post_id + pic_ext
    else:
        pic_name = ''
        direct = ''
        authors = []
        characters = []
        copyrights = []
    return (pic_name, direct, authors, characters, copyrights)
