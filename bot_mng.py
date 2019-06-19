import asyncio
import logging
import os
import time
from functools import wraps

import aiogram
import datetime.datetime as dt
from aiogram import types
from aiogram.utils import exceptions

from creds import TELEGRAM_TOKEN, REQUESTS_PROXY

# bot = telebot.TeleBot(TELEGRAM_TOKEN)
log = logging.getLogger('ohaioposter')
loop = asyncio.get_event_loop()
bot = aiogram.Bot(TELEGRAM_TOKEN, proxy=REQUESTS_PROXY)
dp = aiogram.Dispatcher(bot, loop=loop)
bot.start_time = dt.fromtimestamp(time.perf_counter())
bot.users = {}
bot.paginators = {}
bot.error_msg = None
# wrappers
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

# wrappers end

# bot main actions
@bot_action
async def send_message(chat_id, text, disable_web_page_preview=None, reply_to_message_id=None, reply_markup=None,
                       parse_mode=None, disable_notification=None):
    return await bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=disable_web_page_preview,
                                  reply_to_message_id=reply_to_message_id, reply_markup=reply_markup,
                                  parse_mode=parse_mode, disable_notification=disable_notification)


@bot_action
async def edit_message(text, chat_id=None, message_id=None, inline_message_id=None, parse_mode=None,
                       disable_web_page_preview=None, reply_markup=None):
    return await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id,
                                       inline_message_id=inline_message_id,
                                       parse_mode=parse_mode,
                                       disable_web_page_preview=disable_web_page_preview, reply_markup=reply_markup)


@bot_action
async def edit_markup(chat_id=None, message_id=None, inline_message_id=None, reply_markup=None):
    return await bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id,
                                         inline_message_id=inline_message_id, reply_markup=reply_markup)


@bot_action
async def delete_message(chat_id, message_id):
    return await bot.delete_message(chat_id=chat_id, message_id=message_id)


@bot_action
async def forward_message(chat_id, from_chat_id, message_id, disable_notification=None):
    return await bot.forward_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id,
                               disable_notification=disable_notification)


@bot_action
async def send_photo(chat_id, photo, caption=None, reply_to_message_id=None, reply_markup=None,
                     disable_notification=None):
    photo_arg = types.InputFile(photo) if os.path.exists(photo) else photo
    return await bot.send_photo(chat_id=chat_id, photo=photo_arg, caption=caption,
                                reply_to_message_id=reply_to_message_id,
                                reply_markup=reply_markup,
                                disable_notification=disable_notification)


@bot_action
async def answer_callback(callback_query_id, text=None, show_alert=None, url=None, cache_time=None):
    return await bot.answer_callback_query(callback_query_id=callback_query_id, text=text, show_alert=show_alert,
                                           url=url,
                                           cache_time=cache_time)


@bot_action
async def send_document(chat_id, document, reply_to_message_id=None, caption=None, reply_markup=None,
                        parse_mode=None, disable_notification=None):
    doc_arg = types.InputFile(document) if os.path.exists(document) else document
    return await bot.send_document(chat_id=chat_id, document=doc_arg, reply_to_message_id=reply_to_message_id,
                                   caption=caption, reply_markup=reply_markup,
                                   parse_mode=parse_mode, disable_notification=disable_notification)

# bot main actions end
