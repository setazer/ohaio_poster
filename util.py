# -*- coding: utf-8 -*-
import asyncio
import functools
import time
import traceback

from creds import ERROR_LOGS_DIR


def log_error(exception, args=[], kwargs={}):
    with open(ERROR_LOGS_DIR + time.strftime('%Y%m%d_%H%M%S') + ".txt", 'a') as err_file:
        if args:
            err_file.write("ARGS: " + str(args) + "\n")
        if kwargs:
            err_file.write("KEYWORD ARGS:\n")
            for key in kwargs:
                err_file.write(str(key) + " : " + str(kwargs[key]) + "\n")
        err_file.write(f'{exception}\n\n'.upper())
        traceback.print_exc(file=err_file)


loop = asyncio.get_event_loop()


async def in_thread(func, *args, **kwargs):
    return await loop.run_in_executor(None, functools.partial(func, *args, **kwargs))
