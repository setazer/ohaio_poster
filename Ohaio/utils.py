from imagehash import dhash


def get_picture_hash(image, size=8):
    return dhash(image, hash_size=size)


def add_scheme(url: str):
    return '://'.join(['https', url]) if not url.startswith('http') else url
