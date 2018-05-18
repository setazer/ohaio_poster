# -*- coding: utf-8 -*-
import telebot,cherrypy, json, util
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from creds import TELEGRAM_TOKEN, TELEGRAM_CHANNEL_VKUPDATES, TELEGRAM_PROXY, VK_GROUP_ID

WEBHOOK_LISTEN = '0.0.0.0'
WEBHOOK_PORT = 8237
telebot.apihelper.proxy = TELEGRAM_PROXY
bot = telebot.TeleBot(TELEGRAM_TOKEN,False)

class WebhookServer(object):
    @cherrypy.expose
    def index(self):
        if 'content-length' in cherrypy.request.headers and \
                        'content-type' in cherrypy.request.headers and \
                        cherrypy.request.headers['content-type'] == 'application/json':
            length = int(cherrypy.request.headers['content-length'])
            json_string = cherrypy.request.body.read(length).decode("utf-8")

            # Эта функция обеспечивает проверку входящего сообщения
            # bot.send_message(TELEGRAM_CHANNEL_VKUPDATES,json_string)
            return process_request(json_string)
        else:
            raise cherrypy.HTTPError(403)

def send_message(chat_id, text, disable_web_page_preview=None, reply_to_message_id=None, reply_markup=None,
                 parse_mode=None, disable_notification=None):
    try:
        msg = bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=disable_web_page_preview,
                            reply_to_message_id=reply_to_message_id, reply_markup=reply_markup,
                            parse_mode=parse_mode, disable_notification=disable_notification)
    except Exception as ex:
        util.log_error(ex)
        return None
    return msg

def process_request(json_string):
    update = json.loads(json_string)
    if update["type"] == "confirmation":
        send_message(TELEGRAM_CHANNEL_VKUPDATES, "✅ Получен запрос от VK")
        return 'ad9b6a46'
    elif update["type"] == "message_new":
        send_message(TELEGRAM_CHANNEL_VKUPDATES, "✉️ В сообществе новое личное сообщение.",reply_markup=messages_link())
        return 'ok'
    elif update["type"] == "photo_comment_new":
        send_message(TELEGRAM_CHANNEL_VKUPDATES, "🌄️ Новый комментарий к фотографии.\n\n{}".format(update['object']['text']),reply_markup=photo_link(update))
        return 'ok'
    elif update["type"] == "wall_repost":
        send_message(TELEGRAM_CHANNEL_VKUPDATES, "📢️ Новый репост\nhttps://vk.com/wall{}_{}".format(update['object']['owner_id'], update['object']['id']), reply_markup=post_link(update))
        return 'ok'
    elif update["type"] == "wall_reply_new":
        send_message(TELEGRAM_CHANNEL_VKUPDATES, "📃️ Новый комментарий на стене.\n\n{}".format(update['object']['text']), reply_markup=comment_link(update))
        return 'ok'
    elif update["type"] == "wall_post_new":
        send_message(TELEGRAM_CHANNEL_VKUPDATES, "ℹ️ Новая запись на стене:\n\n{}".format(update['object']['text']), reply_markup=post_link(update))
        return 'ok'
    else:
        send_message(TELEGRAM_CHANNEL_VKUPDATES, "❓ Необработанный апдейт:\n\n{}".format(update),
                     reply_markup=post_link(update))
        return 'ok'

def comment_link(update):
    sender_url = "https://vk.com/id{}".format(update['object']['from_id'])
    post_url = "https://vk.com/wall{}_{}?reply={}".format(update['object']['post_owner_id'], update['object']['post_id'],update['object']['id'])
    link_markup = InlineKeyboardMarkup()
    link_markup.add(InlineKeyboardButton(text="Отправитель", url=sender_url),InlineKeyboardButton(text="Перейти к комментарию", url=post_url))
    return link_markup

def post_link(update):
    post_url = "https://vk.com/wall{}_{}".format(update['object']['owner_id'], update['object']['id'])
    link_markup = InlineKeyboardMarkup()
    link_markup.add(InlineKeyboardButton(text="Перейти к посту", url=post_url))
    return link_markup

def photo_link(update):
    photo_url = "https://vk.com/photo{}_{}".format(update['object']['photo_owner_id'], update['object']['photo_id'])
    link_markup = InlineKeyboardMarkup()
    link_markup.add(InlineKeyboardButton(text="Перейти к фотографии", url=photo_url))
    return link_markup

def messages_link():
    url = "https://vk.com/gim" + VK_GROUP_ID
    link_markup = InlineKeyboardMarkup()
    link_markup.add(InlineKeyboardButton(text="Перейти в сообщения сообщества", url=url))
    return link_markup




cherrypy.config.update({
    'engine.autoreload.on' : False,
    'server.socket_host': WEBHOOK_LISTEN,
    'server.socket_port': WEBHOOK_PORT

    # 'server.ssl_module': 'builtin',
    # 'server.ssl_certificate': WEBHOOK_SSL_CERT,
    # 'server.ssl_private_key': WEBHOOK_SSL_PRIV
})

cherrypy.quickstart(WebhookServer(), '/', {'/': {}})