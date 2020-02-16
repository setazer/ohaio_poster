from Ohaio.utils import prepare_logger
from . import PictureSource

log = prepare_logger(__name__)


class Pixiv(PictureSource):
    service = 'pix'
    base_url = 'www.pixiv.net'
    picture_url = '/artworks/{}'
    author_url = '/member.php?id={}'

    def get_author(self, author: str):
        return self.data_client.get(self.get_full_url(self.author_url.format(author)))
