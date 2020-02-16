import requests


class HTTPClientMixin:
    def __init__(self, config, *args, **kwargs):
        super().__init__(self, config, *args, **kwargs)
        self.data_client = HTTPClient(config)


class HTTPClient:
    def __init__(self, config):
        self._session = None
        try:
            section = dict(config['Proxies'])
        except KeyError:
            section = {}
        self._proxies = section or None

    @property
    def session(self):
        if not self._session:
            self._session = requests.Session()
        return self._session

    def get(self, url, **kwargs):
        return self.session.get(url=url, proxies=self._proxies, **kwargs)

    def post(self, url, **kwargs):
        return self.session.post(url=url, proxies=self._proxies, **kwargs)

