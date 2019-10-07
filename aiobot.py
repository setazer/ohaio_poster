import asyncio
import logging
import os
import time
from datetime import datetime as dt
from functools import wraps

import aiogram
from aiogram import types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram.utils import exceptions

from creds import TELEGRAM_TOKEN, BOT_PROXY

# bot = telebot.TeleBot(TELEGRAM_TOKEN)
log = logging.getLogger('ohaioposter')
bot = aiogram.Bot(TELEGRAM_TOKEN, proxy=BOT_PROXY)
storage = MemoryStorage()

dp = aiogram.Dispatcher(bot, storage=storage)
bot.start_time = dt.fromtimestamp(time.perf_counter())
bot.users = {}
bot.paginators = {}
bot.error_msg = None


class NewNameSetup(StatesGroup):
    new_name = State()


class LimitSetup(StatesGroup):
    user = State()
    limit = State()


def bot_action(func):
    @wraps(func)
    async def wrapped(*args, **kwargs):
        retval = None
        try:
            retval = await func(*args, **kwargs)
        except exceptions.BotBlocked:
            log.error(f"Unable to run {func.__name__}: blocked by user")
        except exceptions.ChatNotFound:
            log.error(f"Unable to run {func.__name__} invalid user ID")
        except exceptions.RetryAfter as e:
            log.error(f"Unable to run {func.__name__} Flood limit is exceeded. Sleep {e.timeout} seconds.")
            await asyncio.sleep(e.timeout)
            retval = await wrapped(*args, **kwargs)  # Recursive call
        except exceptions.UserDeactivated:
            log.error(f"Unable to run {func.__name__} user is deactivated")
        except exceptions.TelegramAPIError:
            log.exception(f"Unable to run {func.__name__} failed")
        return retval

    return wrapped


class MyBot(aiogram.Bot):
    send_message = bot_action(super().send_message)


def wrap_and_patch_bot_methods(bot_instance):
    bot_instance.send_message = bot_action(bot_instance.send_message)
    bot_instance.edit_message_text = bot_action(bot_instance.edit_message_text)
    bot_instance.edit_message_reply_markup = bot_action(bot_instance.edit_message_reply_markup)
    bot_instance.delete_message = bot_action(bot_instance.delete_message)
    bot_instance.forward_message = bot_action(bot_instance.forward_message)
    bot_instance.answer_callback_query = bot_action(bot_instance.answer_callback_query)

    def patcher(obj_, method):
        initial_method = getattr(obj_, method)

        async def patched_func(*args, **kwargs):
            new_args = list(args)
            try:
                new_args[1] = types.InputFile(args[1]) if os.path.exists(args[1]) else args[1]
            except TypeError:  # file argument already InputFile type
                pass
            return await initial_method(*new_args, **kwargs)

        setattr(obj_, method, patched_func)

    patcher(bot_instance, 'send_photo')
    patcher(bot_instance, 'send_document')
    bot_instance.send_photo = bot_action(bot_instance.send_photo)
    bot_instance.send_document = bot_action(bot_instance.send_document)


wrap_and_patch_bot_methods(bot)
