# -*- coding: utf-8 -*-

import vk_requests
from aiogram import types
from aiogram.utils.emoji import emojize
from aiohttp import web

from bot_mng import send_message
from creds import TELEGRAM_CHANNEL_VKUPDATES, VK_GROUP_ID, VK_TOKEN

WEBHOOK_LISTEN = '0.0.0.0'
WEBHOOK_PORT = 8237


async def handle(request):
    if ('content-length' in request.headers
            and 'content-type' in request.headers
            and request.headers['content-type'] == 'application/json'):
        request_body_dict = await request.json()
        text = await process_request(request_body_dict)
        return web.Response(text=text)
    else:
        return web.Response(status=403)


async def process_request(update) -> str:
    api = vk_requests.create_api(service_token=VK_TOKEN, api_version="5.80")
    if update.get("type") == "confirmation":
        await send_message(TELEGRAM_CHANNEL_VKUPDATES, emojize(":white_heavy_check_mark: Получен запрос от VK"))
        return 'ad9b6a46'
    elif update.get("type") == "message_new":
        await send_message(TELEGRAM_CHANNEL_VKUPDATES, emojize(":envelope: В сообществе новое личное сообщение."),
                     reply_markup=messages_link())
        return 'ok'
    elif update.get("type") == "photo_comment_new":
        user_data = api.users.get(user_ids=update['object']['from_id'])[0]
        await send_message(TELEGRAM_CHANNEL_VKUPDATES,
                           emojize(
                               f":sunrise_over_mountains: Новый комментарий к фотографии.\n\n{user_data['first_name']} "
                               f"{user_data['last_name']}:\n{update['object']['text']}"),
                           reply_markup=photo_link(update))
        return 'ok'
    elif update.get("type") == "wall_repost":
        await send_message(TELEGRAM_CHANNEL_VKUPDATES,
                           emojize(f":loudspeaker: Новый репост\nhttps://vk.com/wall"
                                   f"{update['object']['owner_id']}_{update['object']['id']}"),
                     reply_markup=post_link(update))
        return 'ok'
    elif update.get("type") == "wall_reply_new":
        user_data = api.users.get(user_ids=update['object']['from_id'])[0]
        await send_message(TELEGRAM_CHANNEL_VKUPDATES,
                           emojize(f":page_with_curl: Новый комментарий на стене.\n\n{user_data['first_name']} "
                                   f"{user_data['last_name']}:\n{update['object']['text']}"),
                           reply_markup=comment_link(update))
        return 'ok'
    elif update.get("type") == "wall_post_new":
        await send_message(TELEGRAM_CHANNEL_VKUPDATES, emojize(f":information: Новая запись на стене:\n\n"
                                                               f"{update['object']['text']}"),
                     reply_markup=post_link(update))
        return 'ok'
    else:
        await send_message(TELEGRAM_CHANNEL_VKUPDATES,
                           emojize(f":question_mark: Необработанный апдейт:\n\n{repr(update)}"))
        print(emojize(f":question_mark: Необработанный апдейт:\n\n{repr(update)}"))
        return 'ok'


async def comment_link(update):
    sender_url = f"https://vk.com/id{update['object']['from_id']}"
    post_url = (f"https://vk.com/wall{update['object']['post_owner_id']}_"
                f"{update['object']['post_id']}?reply={update['object']['id']}")
    link_markup = types.InlineKeyboardMarkup()
    link_markup.add(types.InlineKeyboardButton(text="Отправитель", url=sender_url),
                    types.InlineKeyboardButton(text="Перейти к комментарию", url=post_url))
    return link_markup


async def post_link(update):
    post_url = f"https://vk.com/wall{update['object']['owner_id']}_{update['object']['id']}"
    link_markup = types.InlineKeyboardMarkup()
    link_markup.add(types.InlineKeyboardButton(text="Перейти к посту", url=post_url))
    return link_markup


async def photo_link(update):
    photo_url = f"https://vk.com/photo{update['object']['photo_owner_id']}_{update['object']['photo_id']}"
    link_markup = types.InlineKeyboardMarkup()
    link_markup.add(types.InlineKeyboardButton(text="Перейти к фотографии", url=photo_url))
    return link_markup


async def messages_link():
    url = f"https://vk.com/gim{VK_GROUP_ID}"
    link_markup = types.InlineKeyboardMarkup()
    link_markup.add(types.InlineKeyboardButton(text="Перейти в сообщения сообщества", url=url))
    return link_markup


app = web.Application()
app.add_routes([web.get('/', handle),
                web.post('/', handle)])

web.run_app(app)
