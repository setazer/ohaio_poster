from Ohaio.utils import prepare_logger
from . import Channel

log = prepare_logger(__name__)


class TumblrChannel(Channel):
    def __init__(self, config):
        section = config['Tumblr']
        self.blog_name = section['blog_name']
        self.consumer_key = section['consumer_key']
        self.consumer_secret = section['consumer_secret']
        self.oauth_token = section['oauth_token']
        self.oauth_secret = section['oauth_secret']

    def process(self, data):
        log.info(f'Posted {data} to Tumblr')
