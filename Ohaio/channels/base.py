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
