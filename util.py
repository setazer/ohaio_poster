# -*- coding: utf-8 -*-
import asyncio
import functools
from concurrent.futures.thread import ThreadPoolExecutor
from contextlib import contextmanager

_executor = ThreadPoolExecutor(20)


def human_readable(delta):
    attrs = ['years', 'months', 'days', 'hours', 'minutes', 'seconds']
    date_parts = ["Лет", "Месяцев", "Дней", "Часов", "Минут", "Секунд"]
    return ['{date_part}: {amount}'.format(amount=getattr(delta, attr), date_part=date_parts[n])
            for n, attr in enumerate(attrs) if getattr(delta, attr)]


async def in_thread(func, *args, **kwargs):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(_executor, functools.partial(func, *args, **kwargs))


@contextmanager
def ignored(*exceptions):
    try:
        yield
    except exceptions:
        pass
