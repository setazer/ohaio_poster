import os

from Ohaio.data_objects import Picture
from Ohaio.utils import prepare_logger
from . import Booru

log = prepare_logger(__name__)


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
        return self._get_json(self.get_full_url(self.tag_api.format(tags)))

    def get_picture_info(self, post_id: str):
        posts = super().get_picture_info(post_id)
        if not posts:
            return None

        post = next(item for item in posts)
        tags_info = self.tags_info(post['tags'])
        try:
            pic_data = self.data_client.get(self.get_full_url(post['file_url']), stream=True).raw
        except Exception as ex:
            # TODO narrow down exception clause
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
