from Ohaio.data_objects import Picture
from Ohaio.utils import prepare_logger
from . import Booru

log = prepare_logger(__name__)


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
            pic_data = self.data_client.get(self.get_full_url(post_data['file_url']), stream=True).raw
        except Exception:
            # TODO narrow down exception clause
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
