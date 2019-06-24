# -*- coding: utf-8 -*-
import asyncio
import functools
import time
import traceback
from concurrent.futures.thread import ThreadPoolExecutor

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


_executor = ThreadPoolExecutor(10)

def human_readable(delta):
    attrs = ['years', 'months', 'days', 'hours', 'minutes', 'seconds']
    date_parts = ["Лет", "Месяцев", "Дней", "Часов", "Минут", "Секунд"]
    return ['{date_part}: {amount}'.format(amount=getattr(delta, attr), date_part=date_parts[n])
            for n, attr in enumerate(attrs) if getattr(delta, attr)]

async def in_thread(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, functools.partial(func, *args, **kwargs))
