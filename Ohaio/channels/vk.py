from Ohaio.utils import prepare_logger
from . import Channel

log = prepare_logger(__name__)


class VkChannel(Channel):
    def __init__(self, config):
        section = config['VK']
        self.token = section['token']
        self.group_id = section['group_id']
        self.app_id = section['app_id']

    def process(self, data):
        log.info(f'Posted {data} to VK')
