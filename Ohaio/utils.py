import logging

from imagehash import dhash


def get_picture_hash(image, size=8):
    return dhash(image, hash_size=size)


def add_scheme(url: str):
    return '://'.join(['https', url]) if not url.startswith('http') else url

def prepare_logger(name):
    logger = logging.getLogger(name)
    logger.propagate = False
    con = logging.StreamHandler()
    con.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(asctime)s\t%(message)s"))
    logger.addHandler(con)
    return logger
