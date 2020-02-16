import itertools
import os
import urllib.parse
import json

from bs4 import BeautifulSoup
from imagehash import dhash

from Ohaio.data_objects import Picture
from Ohaio.utils import add_scheme, prepare_logger

log = prepare_logger(__name__)


class PictureSource:
    service: str = NotImplemented
    base_url: str = NotImplemented
    picture_url: str = NotImplemented
    data_client = NotImplemented

    def __init__(self, data_client):
        self.data_client = data_client

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

    def __init__(self, config, data_client):
        super().__init__(data_client)
        section = config['Booru']
        self.banned_tags = section['banned_tags'].split(',')
        self.login(data=dict(config[self.login_section]))

    def login(self, **kwargs):
        return self.data_client.post(self.get_full_url(self.login_url), **kwargs)

    def get_usable_url(self, url: str):
        parsed_url = urllib.parse.urlparse(url)._replace(scheme='https')
        if not parsed_url.netloc:
            parsed_url = parsed_url._replace(netloc=self.base_url)
        return parsed_url.geturl()

    def get_picture_info(self, post_id: str):
        return self.get_json(self.get_full_url(self.picture_api.format(post_id)))

    def search(self, tags: str):
        return self.get_json(self.get_full_url(self.search_api.format(tags)))

    def get_json(self, url: str):
        req = self.data_client.get(url)
        try:
            data = req.json()
        except json.JSONDecodeError:
            log.error("Couldn't decode json response", exc_info=True)
            return None
        return data


class Gelbooru(Booru):
    service = 'gel'
    base_url = 'gelbooru.com'
    picture_url = '/index.php?page=post&s=view&id={}'
    picture_api = '/index.php?page=dapi&s=post&q=index&json=1&id={}'
    search_api = '/index.php?page=dapi&s=post&q=index&json=1&tags={}'
    tag_api = '/index.php?page=dapi&s=tag&q=index&json=1&names={}'
    login_url = '/index.php?page=account&s=login&code=00'
    login_section = 'Gelbooru'

    def tags_info(self, tags):
        return self.get_json(self.get_full_url(self.tag_api.format(tags)))

    def get_picture_info(self, post_id: str):
        posts = super().get_picture_info(post_id)
        if not posts:
            return None

        post = next(item for item in posts)
        tags_info = self.tags_info(post['tags'])
        try:
            pic_data = self.data_client.get(self.get_usable_url(post['file_url']), stream=True).raw
        except Exception as ex:
            #TODO narrow down exception clause
            log.error("Error while getting file raw data", exc_info=True)
            return None

        file_type = os.path.splitext(post['image'])[1]
        pic = Picture.from_mapping({
            'filename': ''.join([post_id, file_type]),
            'file_type': file_type.strip('.'),
            'height': post['height'],
            'width': post['width'],
            'authors': set(author['tag'] for author in tags_info
                           if author['type'] == 'author'),
            'characters': set(author['tag'].replace('_(series)', '') for author in tags_info
                              if author['type'] == 'character'),
            'copyright': set(author['tag'] for author in tags_info
                             if author['type'] == 'copyright'),
            'url': post['file_url'],
            'service': self.service,
            'post_id': post_id,
            # TODO IDEA Lazy load
            'data': pic_data,
        })
        return pic


class Danbooru(Booru):
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
        super().login(headers=headers, **kwargs)

    def get_picture_info(self, post_id: str):
        post_data = super().get_picture_info(post_id)
        try:
            pic_data = self.data_client.get(self.get_usable_url(post_data['file_url']), stream=True).raw
        except Exception:
            #TODO narrow down exception clause
            log.error("Error while getting file raw data", exc_info=True)
            return None
        pic = Picture.from_mapping({
            'filename': ''.join([post_id, post_data['file_ext']]),
            'file_type': post_data['file_ext'],
            'height': post_data['image_height'],
            'width': post_data['image_width'],
            'authors': set(post_data['tag_string_artist'].split()),
            'characters': set(post_data['tag_string_character'].split()),
            'copyright': set(post_data['tag_string_copyright'].replace('_(series)', '').split()),
            'url': post_data['file_url'],
            'service': self.service,
            'post_id': post_id,
            # TODO IDEA Lazy load
            'data': pic_data,
        })
        return pic


class Pixiv(PictureSource):
    service = 'pix'
    base_url = 'www.pixiv.net'
    picture_url = '/artworks/{}'
    author_url = '/member.php?id={}'

    def get_author(self, author: str):
        return self.data_client.get(self.get_full_url(self.author_url.format(author)))
