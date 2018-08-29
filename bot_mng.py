import os
import time
from functools import wraps

import requests
import telebot

import util
from creds import TELEGRAM_TOKEN, REQUESTS_PROXY

telebot.apihelper.proxy = REQUESTS_PROXY
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# wrappers
def bot_action(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        err_wait = [1, 5, 15, 30, 60, 300]
        retval = None
        for i in range(20):
            try:
                retval = func(*args, **kwargs)
            except requests.exceptions.ConnectionError as exc:
                time.sleep(err_wait[min(i, 5)])
            except (telebot.apihelper.ApiException, FileNotFoundError) as exc:
                util.log_error(exc, args, kwargs)
                break
            except Exception as exc:
                util.log_error(exc, args, kwargs)
                time.sleep(err_wait[min(i, 3)])
            else:
                break
        return retval

    return wrapper


# wrappers end

# bot main actions
@bot_action
def send_message(chat_id, text, disable_web_page_preview=None, reply_to_message_id=None, reply_markup=None,
                 parse_mode=None, disable_notification=None):
    return bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=disable_web_page_preview,
                            reply_to_message_id=reply_to_message_id, reply_markup=reply_markup,
                            parse_mode=parse_mode, disable_notification=disable_notification)


@bot_action
def edit_message(text, chat_id=None, message_id=None, inline_message_id=None, parse_mode=None,
                 disable_web_page_preview=None, reply_markup=None):
    return bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id,
                                 inline_message_id=inline_message_id,
                                 parse_mode=parse_mode,
                                 disable_web_page_preview=disable_web_page_preview, reply_markup=reply_markup)


@bot_action
def edit_markup(chat_id=None, message_id=None, inline_message_id=None, reply_markup=None):
    return bot.edit_message_reply_markup(chat_id=chat_id, message_id=message_id,
                                         inline_message_id=inline_message_id, reply_markup=reply_markup)


@bot_action
def delete_message(chat_id, message_id):
    return bot.delete_message(chat_id=chat_id, message_id=message_id)


@bot_action
def forward_message(chat_id, from_chat_id, message_id, disable_notification=None):
    return bot.forward_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id,
                               disable_notification=disable_notification)


@bot_action
def send_photo(chat_id, photo_filename, caption=None, reply_to_message_id=None, reply_markup=None,
               disable_notification=None):
    if os.path.exists(photo_filename):
        with open(photo_filename, 'rb') as photo:
            return bot.send_photo(chat_id=chat_id, photo=photo, caption=caption,
                                  reply_to_message_id=reply_to_message_id,
                                  reply_markup=reply_markup,
                                  disable_notification=disable_notification)
    else:
        return bot.send_photo(chat_id=chat_id, photo=photo_filename, caption=caption,
                              reply_to_message_id=reply_to_message_id,
                              reply_markup=reply_markup,
                              disable_notification=disable_notification)


@bot_action
def answer_callback(callback_query_id, text=None, show_alert=None, url=None, cache_time=None):
    return bot.answer_callback_query(callback_query_id=callback_query_id, text=text, show_alert=show_alert, url=url,
                                     cache_time=cache_time)


@bot_action
def send_document(chat_id, data_filename, reply_to_message_id=None, caption=None, reply_markup=None,
                  parse_mode=None, disable_notification=None, timeout=None):
    if os.path.exists(data_filename):
        with open(data_filename, 'rb') as data:
            return bot.send_document(chat_id=chat_id, data=data, reply_to_message_id=reply_to_message_id,
                                     caption=caption, reply_markup=reply_markup,
                                     parse_mode=parse_mode, disable_notification=disable_notification, timeout=timeout)
    else:
        return bot.send_document(chat_id=chat_id, data=data_filename, reply_to_message_id=reply_to_message_id,
                                 caption=caption, reply_markup=reply_markup,
                                 parse_mode=parse_mode, disable_notification=disable_notification, timeout=timeout)
# bot main actions end
