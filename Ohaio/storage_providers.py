class MemoryStorage:
    def __init__(self, name, data=None):
        self._name = name
        self._storage = set(data or tuple())

    def __iter__(self):
        return iter(self._storage)

    def __repr__(self):
        return "MemoryStorage({})".format(self._storage)

    def write(self, data):
        self._storage.add(data)
        print('stored', data, 'to', self._name)

    def search(self, filter_=None, **kwargs):
        if filter_ is None:
            return self._storage.copy()
        return [item for item in self._storage if filter_(item)]

    def remove(self, filter_: callable):
        for item in self._storage.copy():
            if filter_(item):
                self._storage.remove(item)



