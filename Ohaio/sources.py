import os
import urllib.parse
import json

from bs4 import BeautifulSoup
from imagehash import dhash

from Ohaio.data_objects import Picture
from Ohaio.mixins import HTTPClientMixin
from Ohaio.utils import add_scheme


class PictureSource:
    service: str = NotImplemented
    base_url: str = NotImplemented
    picture_url: str = NotImplemented

    def __contains__(self, url: str):
        return self.base_url in url

    def get_full_url(self, path: str):
        return urllib.parse.urljoin(add_scheme(self.base_url), path)

    def get_picture_url(self, post_id: str):
        return self.get_full_url(self.picture_url.format(post_id))


class Booru(PictureSource):
    picture_api: str = NotImplemented
    search_api: str = NotImplemented
    login_url: str = NotImplemented
    login_section: str = NotImplemented

    def __init__(self, config: dict):
        section = config['Booru']
        self.banned_tags = section['banned_tags'].split(',')
        self.login(data=dict(config[self.login_section]))

    def login(self, **kwargs):
        return NotImplemented

    def get_usable_url(self, url: str):
        parsed_url = urllib.parse.urlparse(url)._replace(scheme='https')
        if not parsed_url.netloc:
            parsed_url = parsed_url._replace(netloc=self.base_url)
        return parsed_url.geturl()

    def get_picture_info(self, post_id: str):
        return self.parse_picture_info(self.get_full_url(self.picture_api.format(post_id)), post_id)

    def parse_picture_info(self, url: str, post_id:str):
        return NotImplemented

    def search(self, tags: str):
        return self.parse_search(self.get_full_url(self.search_api.format(tags)), tags)

    def parse_search(self, url: str, tags:str):
        return NotImplemented


class Gelbooru(HTTPClientMixin, Booru):
    service = 'gel'
    base_url = 'gelbooru.com'
    picture_url = '/index.php?page=post&s=view&id={}'
    picture_api = '/index.php?page=dapi&s=post&q=index&id={}'
    search_api = '/index.php?page=dapi&s=post&q=index&tags={}'
    login_url = '/index.php?page=account&s=login&code=00'
    login_section = 'Gelbooru'





class Danbooru(HTTPClientMixin, Booru):
    service = 'dan'
    base_url = 'danbooru.donmai.us'
    picture_url = '/posts/{}'
    picture_api = '/posts/{}.json'
    search_api = '/posts.json?tags={}'
    login_url = '/session/new'
    login_section = 'Danbooru'

    def login(self, **kwargs):
        headers = {'user-agent': 'OhaioPoster',
                   'content-type': 'application/json; charset=utf-8'}
        self.data_client.post(headers=headers, **kwargs)

    def parse_picture_info(self, url: str, post_id: str):
        req = self.data_client.get(url)
        try:
            data = req.json
        except json.JSONDecodeError:
            return None
        filename = os.path.basename(url)
        try:
            pic_data = self.data_client.get(self.get_usable_url(data['file_url'])).raw
        except Exception:
            #TODO narrow down exception clause
            return None
        pic = Picture.from_mapping({
        'filename':filename,
        'file_type':data['file_ext'],
        'authors':set(data['tag_string_artist'].split()),
        'characters':set(data['tag_string_character'].split()),
        'copyright':set(data['tag_string_copyright'].replace('_(series)', '').split()),
        'url': data['file_url'],
        'service': self.service,
        'post_id': post_id,
        'data': pic_data,
        })
        return pic



class Pixiv(HTTPClientMixin, PictureSource):
    service = 'pix'
    base_url = 'www.pixiv.net'
    picture_url = '/artworks/{}'
    author_url = '/member.php?id={}'

    def get_author(self, author: str):
        return self.data_client.get(self.get_full_url(self.author_url.format(author)))
