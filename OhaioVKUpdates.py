# -*- coding: utf-8 -*-
import json

import cherrypy
import vk_requests
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from bot_mng import send_message
from creds import TELEGRAM_CHANNEL_VKUPDATES, VK_GROUP_ID, VK_TOKEN

WEBHOOK_LISTEN = '0.0.0.0'
WEBHOOK_PORT = 8237

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


def process_request(json_string):
    api = vk_requests.create_api(service_token=VK_TOKEN, api_version=5.71)
    update = json.loads(json_string)
    if update["type"] == "confirmation":
        send_message(TELEGRAM_CHANNEL_VKUPDATES, "✅ Получен запрос от VK")
        return 'ad9b6a46'
    elif update["type"] == "message_new":
        send_message(TELEGRAM_CHANNEL_VKUPDATES, "✉️ В сообществе новое личное сообщение.",
                     reply_markup=messages_link())
        return 'ok'
    elif update["type"] == "photo_comment_new":
        user_data = api.users.get(user_ids=update['object']['from_id'])[0]
        send_message(TELEGRAM_CHANNEL_VKUPDATES,
                     f"🌄️ Новый комментарий к фотографии.\n\n{user_data['first_name']} {user_data['last_name']}:\n{update['object']['text']}",
                     reply_markup=photo_link(update))
        return 'ok'
    elif update["type"] == "wall_repost":
        send_message(TELEGRAM_CHANNEL_VKUPDATES,
                     f"📢️ Новый репост\nhttps://vk.com/wall{update['object']['owner_id']}_{update['object']['id']}",
                     reply_markup=post_link(update))
        return 'ok'
    elif update["type"] == "wall_reply_new":
        user_data = api.users.get(user_ids=update['object']['from_id'])[0]
        send_message(TELEGRAM_CHANNEL_VKUPDATES,
                     f"📃️ Новый комментарий на стене.\n\n{user_data['first_name']} {user_data['last_name']}:\n{update['object']['text']}",
                     reply_markup=comment_link(update))
        return 'ok'
    elif update["type"] == "wall_post_new":
        send_message(TELEGRAM_CHANNEL_VKUPDATES, f"ℹ️ Новая запись на стене:\n\n{update['object']['text']}",
                     reply_markup=post_link(update))
        return 'ok'
    else:
        send_message(TELEGRAM_CHANNEL_VKUPDATES, f"❓ Необработанный апдейт:\n\n{update}")
        return 'ok'


def comment_link(update):
    sender_url = f"https://vk.com/id{update['object']['from_id']}"
    post_url = f"https://vk.com/wall{update['object']['post_owner_id']}_{update['object']['post_id']}?reply={update['object']['id']}"
    link_markup = InlineKeyboardMarkup()
    link_markup.add(InlineKeyboardButton(text="Отправитель", url=sender_url),
                    InlineKeyboardButton(text="Перейти к комментарию", url=post_url))
    return link_markup


def post_link(update):
    post_url = f"https://vk.com/wall{update['object']['owner_id']}_{update['object']['id']}"
    link_markup = InlineKeyboardMarkup()
    link_markup.add(InlineKeyboardButton(text="Перейти к посту", url=post_url))
    return link_markup


def photo_link(update):
    photo_url = f"https://vk.com/photo{update['object']['photo_owner_id']}_{update['object']['photo_id']}"
    link_markup = InlineKeyboardMarkup()
    link_markup.add(InlineKeyboardButton(text="Перейти к фотографии", url=photo_url))
    return link_markup


def messages_link():
    url = f"https://vk.com/gim{VK_GROUP_ID}"
    link_markup = InlineKeyboardMarkup()
    link_markup.add(InlineKeyboardButton(text="Перейти в сообщения сообщества", url=url))
    return link_markup


cherrypy.config.update({
    'engine.autoreload.on': False,
    'server.socket_host': WEBHOOK_LISTEN,
    'server.socket_port': WEBHOOK_PORT

    # 'server.ssl_module': 'builtin',
    # 'server.ssl_certificate': WEBHOOK_SSL_CERT,
    # 'server.ssl_private_key': WEBHOOK_SSL_PRIV
})

cherrypy.quickstart(WebhookServer(), '/', {'/': {}})
