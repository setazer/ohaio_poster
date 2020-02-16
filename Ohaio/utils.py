import logging

from imagehash import dhash


def get_picture_hash(image, size=8):
    return dhash(image, hash_size=size)


def prepare_logger(name):
    logger = logging.getLogger(name)
    logger.propagate = False
    con = logging.StreamHandler()
    con.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(name)s\t\t%(message)s"))
    logger.addHandler(con)
    return logger
