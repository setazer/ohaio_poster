from Ohaio.data_objects import Tag, Picture
from Ohaio.sources import PictureSource, Booru


class QueueController:
    def __init__(self, queue_provider, history_storage, channel_list):
        self.queue = queue_provider
        self.channels = channel_list
        self.history = history_storage

    def store(self, data: Picture, **kwargs):
        self.queue.put(data, **kwargs)

    def publish(self, **kwargs):
        pics = self.queue.get(**kwargs)
        if not pics:
            return
        for channel in self.channels:
            channel.publish(pics, **kwargs)
        self.history.write(pics)


class MonitorController:
    def __init__(self, monitor_storage, ohaio_controller):
        self.monitor = monitor_storage
        self.ohaio = ohaio_controller

    def store(self, data: Picture, **kwargs):
        self.monitor.write(data, **kwargs)

    def publish(self, filter_=None, **kwargs):
        data = self.monitor.search(filter_, **kwargs)
        for item in data:
            self.ohaio.store(item, **kwargs)
            self.monitor.remove(lambda x: x in data)


class MonitorChecker:
    def __init__(self, tags_storage, monitor_controller, source_list):
        self.monitor = monitor_controller
        self.tags = tags_storage
        self.sources = source_list

    def _get_tags(self):
        return

    def check(self):
        def sources_filter(item):
            return any(item.service == source.service for source in self.sources)
        tags = self.tags.search(filter_=sources_filter)
        for tag in tags:
            tag: Tag
            source: Booru = next(source for source in self.sources if tag.service == source.service)
            last_check = tag.last_check
            req = source.search(tag.name)


