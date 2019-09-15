# -*- coding: utf-8 -*-
import time
import traceback

from creds import ERROR_LOGS_DIR
from sqlalchemy import func

from db_mng import *


def log_error(exception, args=None, kwargs=None):
    args = args or []
    kwargs = kwargs or {}
    with open(ERROR_LOGS_DIR + time.strftime('%Y%m%d_%H%M%S') + ".txt", 'a') as err_file:
        if args:
            err_file.write("ARGS: " + str(args) + "\n")
        if kwargs:
            err_file.write("KEYWORD ARGS:\n")
            for key in kwargs:
                err_file.write(str(key) + " : " + str(kwargs[key]) + "\n")
        err_file.write(f'{exception}\n\n'.upper())
        traceback.print_exc(file=err_file)


def sync_tags_last_posts():
    with session_scope() as session:
        tags_and_post_ids = session.query(Tag, func.max(Pic.post_id)).join(Pic, Pic.authors.like(
            "%" + Tag.tag + "%")).group_by(Tag.tag).all()
        for tag_item, post_id in tags_and_post_ids:
            if post_id.isnumeric() and int(post_id) > tag_item.last_check:
                tag_item.last_check = int(post_id)
