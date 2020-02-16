from Ohaio.utils import prepare_logger

log = prepare_logger(__name__)


class Channel:
    def publish(self, data):
        self.preprocess(data)
        result = self.process(data)
        self.postprocess(data)
        return result

    def preprocess(self, data):
        pass

    def process(self, data):
        return NotImplemented

    def postprocess(self, data):
        pass


class VkChannel(Channel):
    def __init__(self, config):
        section = config['VK']
        self.token = section['token']
        self.group_id = section['group_id']
        self.app_id = section['app_id']

    def process(self, data):
        log.info(f'Posted {data} to VK')


class TelegramChannel(Channel):
    def __init__(self, config):
        section = config['Telegram']
        self.token = section['token']
        self.group_id = section['group_id']

    def process(self, data):
        log.info(f'Posted {data} to Telegram')


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


