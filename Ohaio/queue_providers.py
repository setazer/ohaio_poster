import collections

from Ohaio.utils import prepare_logger

log = prepare_logger(__name__)


class MemoryQueue:
    def __init__(self, name):
        self._name = name
        self._queue = collections.deque()

    def __bool__(self):
        return bool(self._queue)

    def __len__(self):
        return len(self._queue)

    def __contains__(self, item):
        return item in self._queue

    def __iter__(self):
        return iter(self._queue)

    def __repr__(self):
        return "MemoryQueue({})".format(self._queue)

    def put(self, data):
        self._queue.appendleft(data)
        log.info(f'added {data} to {self._name}')

    def get(self):
        try:
            return self._queue.pop()
        except IndexError:
            return None


class MultiMemoryQueue:
    def __init__(self, name):
        self._name = name
        self._queues = collections.OrderedDict()

    def __len__(self):
        return sum(map(len, self._queues))

    def __bool__(self):
        return bool(self._queues)

    def __contains__(self, item):
        return any(item in queue for queue in self._queues)

    def __repr__(self):
        return "MultiMemoryQueue([{}])".format('\n'.join(['{queue}: {data}'.format(queue=queue, data=items) for queue, items in self._queues.items()]))

    def put(self, data, queue):
        self._queues.setdefault(queue, MemoryQueue(f'subqueue{queue}')).put(data)
        log.info(f'added {data} to {self._name}')

    def get(self, switch=True):
        try:
            queue = next(iter(self._queues))
        except StopIteration:
            return None
        if switch:
            self._queues.move_to_end(queue)
        item = self._queues[queue].get()
        if not len(self._queues[queue]):
            del self._queues[queue]
        return item

