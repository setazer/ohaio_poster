from Ohaio.utils import get_picture_hash


class DataObject:
    def to_dict(self):
        return dict(vars(self))

    @classmethod
    def from_mapping(cls, data: dict):
        pic = cls()
        for attr, value in data.items():
            setattr(pic, attr, value)
        return pic


class Picture(DataObject):
    filename: str = None
    file_type: str = None
    authors: str = None
    characters: str = None
    copyright: str = None
    url: str = None
    service: str = None
    post_id: str = None
    hash: str = None

    def __init__(self):
        self._data = None

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = value
        self.hash = get_picture_hash(value)


class Tag(DataObject):
    service: str = None
    name: str = None
    aliases: str = None
    last_check: int = 0
    missing_times: int = 0
