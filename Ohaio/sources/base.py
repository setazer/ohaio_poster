import json
from urllib.parse import urlparse, quote

from Ohaio.utils import prepare_logger

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
        parsed_url = urlparse(path)._replace(scheme='https')
        if not parsed_url.netloc:
            parsed_url = parsed_url._replace(netloc=self.base_url)
        return parsed_url.geturl()

    def get_picture_url(self, post_id: str):
        return self.get_full_url(self.picture_url.format(post_id))


class Booru(PictureSource):
    picture_api: str = NotImplemented
    search_api: str = NotImplemented
    search_exclude: str = 'rating:e'
    login_url: str = NotImplemented
    login_section: str = NotImplemented

    def __init__(self, config, data_client):
        super().__init__(data_client)
        section = config['Booru']
        self.banned_tags = section['banned_tags'].split(',')
        self.login(data=dict(config[self.login_section]))

    def login(self, **kwargs):
        return self.data_client.post(self.get_full_url(self.login_url), **kwargs)

    def get_picture_info(self, post_id: str):
        return self._get_json(self.get_full_url(self.picture_api.format(post_id)))

    def _search(self, query):
        return self._get_json(self.get_full_url(self.search_api.format(query)))

    def search(self, tags: str):
        tag_list = list(map(quote, tags.split()))
        tag_list.append(f'-{self.search_exclude}')
        search_query = '+'.join(tag_list)
        return self._search(search_query)

    def multi_search(self, tags: str):
        tags = '~'.join(map(quote, tags.split()))
        search_query = ''.join([tags, f'+-{self.search_exclude}'])
        return self._search(search_query)

    def _get_json(self, url: str):
        req = self.data_client.get(url)
        try:
            data = req.json()
        except json.JSONDecodeError:
            log.error("Couldn't decode json response", exc_info=True)
            return None
        return data
