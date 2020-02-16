import configparser
from Ohaio.channels import VkChannel, TelegramChannel, TumblrChannel
from Ohaio.queue_providers import MemoryQueue, MultiMemoryQueue
from Ohaio.controllers import QueueController, MonitorController
from Ohaio.sources import Danbooru, Gelbooru
from Ohaio.storage_providers import MemoryStorage
cfg = configparser.ConfigParser()
cfg.read('config.ini')
channels = VkChannel(cfg), TelegramChannel(cfg), TumblrChannel(cfg)
queue = MultiMemoryQueue('main queue')
history = MemoryStorage('history storage')
ohaio = QueueController(queue, history, channels)
mon_storage = MemoryStorage('monitor storage')
mon = MonitorController(mon_storage, ohaio)
def get_number():
    i = 0
    while True:
        yield i
        i += 1


gen = get_number()
def gen_data_packet():
    return {'post_id': str(next(gen))}

ohaio.store('data packet {}'.format(next(gen)), queue=1)
ohaio.store('data packet {}'.format(next(gen)), queue=2)
ohaio.store('data packet {}'.format(next(gen)), queue=1)
print(ohaio.queue)
ohaio.publish()
ohaio.publish()
ohaio.publish()
ohaio.store('data packet {}'.format(next(gen)), queue=2)
ohaio.store('data packet {}'.format(next(gen)), queue=2)
ohaio.store('data packet {}'.format(next(gen)), queue=1)
ohaio.publish()
ohaio.publish()
ohaio.publish()
mon.store('data packet mon {}'.format(next(gen)))
mon.store('data packet mon {}'.format(next(gen)))
mon.store('data packet mon {}'.format(next(gen)))
mon.publish(queue=1)
ohaio.publish()
ohaio.publish()
ohaio.publish()
print(ohaio.history)

# dan = Gelbooru(cfg)
# req = dan.get_post_info('123456')
# print(req.text)
