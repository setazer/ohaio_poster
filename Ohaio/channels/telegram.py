from Ohaio.utils import prepare_logger
from . import Channel

log = prepare_logger(__name__)


class TelegramChannel(Channel):
    def __init__(self, config):
        section = config['Telegram']
        self.token = section['token']
        self.group_id = section['group_id']

    def process(self, data):
        log.info(f'Posted {data} to Telegram')
