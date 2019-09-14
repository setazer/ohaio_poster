# -*- coding: utf-8 -*-
import argparse
import asyncio
import logging
import os
import re
import sys
import time
from collections import namedtuple
from datetime import datetime as dt
from functools import wraps
from operator import attrgetter

import aiohttp
import dateutil.relativedelta as rd
import math
import pixivpy3
import vk_requests
from PIL import Image, ImageOps, ImageDraw, ImageFont
from aiogram import types
from aiogram.types import ChatType
from aiogram.utils import executor
from aiogram.utils.executor import start_webhook
from sqlalchemy.orm import joinedload

import grabber
import markups
from OhaioMonitor import check_recommendations
from bot_mng import bot, dp, NewNameSetup, LimitSetup
from bot_mng import send_message, send_photo, answer_callback, edit_message, edit_markup, delete_message, send_document
from creds import *
from creds import service_db, TELEGRAM_CHANNEL_MON
from db_mng import User, Tag, Pic, QueueItem, HistoryItem, MonitorItem, session_scope, get_used_pics, save_pic, \
    get_user_limits, get_posts_stats, clean_monitor, save_monitor_pic, is_pic_exists, \
    mark_post_for_deletion, move_back_to_mon, delete_pic_by_id, replace_tag, delete_tag, rename_tag, clear_history, \
    delete_duplicate, get_queue_picnames, get_delete_queue, is_tag_exists, write_new_tag, create_pic, append_pic_data, \
    get_queue_stats, get_hashes, get_bot_admins, add_new_pic, is_new_shutdown, load_users, save_users
from markups import InlinePaginator
from util import in_thread, human_readable, ignored


def bot_access(access_number=0):
    def decorator(function):
        @wraps(function)
        async def wrapper(message, *args):
            user_access = bot.users[message.from_user.id]['access'] if message.from_user.id in bot.users else 0
            if user_access >= access_number:
                await function(message, *args)
            elif user_access > 0:
                if isinstance(message, types.CallbackQuery):
                    await answer_callback(message.id, "Not allowed!")
                else:
                    await send_message(message.from_user.id, "Not allowed!")

        return wrapper

    return decorator


parser = argparse.ArgumentParser()
parser.add_argument('-d', '--debug', dest='debugging', action='store_true', help='Verbose output')
script_args = parser.parse_args()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(f'ohaio.{__name__}')
log.setLevel(logging.DEBUG if script_args.debugging else logging.INFO)

log.debug("Initializing bot")
load_users()


async def say_to_owner(text):
    return await send_message(OWNER_ID, str(text))


def move_mon_to_q(filename):
    with ignored(FileExistsError):
        os.rename(f"{MONITOR_FOLDER}{filename}", f"{QUEUE_FOLDER}{filename}")


@dp.errors_handler()
async def error_handler(update, error):
    log.error(f"{update}\n\n{error}")


@dp.message_handler(commands=['start'])
async def start(message):
    if message.chat.id not in bot.users:
        await send_message(message.chat.id, "Привет! Заявка на регистрацию отправлена администратору.")
        await send_message(OWNER_ID,
                           f"Новый пользователь: {message.from_user.username} ({message.chat.id})",
                           reply_markup=markups.gen_user_markup(message.chat.id))
    elif bot.users[message.chat.id]['access'] == 1:
        await send_message(message.chat.id, "Регистрация уже пройдена.")

    elif bot.users[message.chat.id]['access'] == 0:
        await send_message(message.chat.id, "Повторная заявка на регистрацию отправлена администратору.")
        await send_message(OWNER_ID,
                           f"Повторная регистрация: {message.from_user.username} ({message.chat.id})",
                           reply_markup=markups.gen_user_markup(message.chat.id))


@dp.message_handler(ChatType.is_private, commands=['stop'])
@bot_access(1)
async def stop(message):
    await send_message(message.chat.id, "Регистрация отозвана.")
    await say_to_owner(f"Регистрация {message.from_user.username} ({message.chat.id}) отозвана.")
    bot.users[message.chat.id]['access'] = 0
    await in_thread(save_users)


@dp.message_handler(ChatType.is_private, commands=['shutdown'])
@bot_access(2)
async def shutdown(message):
    chat_id = message.chat.id
    message_id = message.message_id
    new_shutdown = await in_thread(is_new_shutdown, chat_id=chat_id, message_id=message_id)
    if new_shutdown:
        log.debug("Shutting down")
        await say_to_owner("Останавливаюсь...")
        sys.exit()


@dp.message_handler(ChatType.is_private, commands=['uptime'])
@bot_access(1)
async def uptime(message):
    cur_time = dt.fromtimestamp(time.perf_counter())
    diff = ' '.join(human_readable(rd.relativedelta(cur_time, bot.start_time)))
    await send_message(message.chat.id, "Бот работает уже:\n" + diff)


@dp.message_handler(ChatType.is_channel, commands=['whereami'])
@bot_access(1)
async def whereami(message):
    await send_message(message.chat.id, f"{message.chat.id}\n{message.message_id}")


@dp.message_handler(ChatType.is_private, commands=['set_limit'])
@bot_access(1)
async def set_limit(message):
    db_users = await in_thread(get_user_limits)
    LimitSetup.user.set()
    await send_message(message.chat.id, "Выберите пользователя для изменения лимита:",
                       reply_markup=markups.gen_user_limit_markup(db_users))


@dp.message_handler(state=LimitSetup.limit)
async def change_limit(message, state):
    if message.text.isdigit():
        with state.proxy() as data:
            user = data['user']
            new_limit = int(message.text)
            bot.users[user]['limit'] = new_limit
            await in_thread(save_users)
            await send_message(message.chat.id, "Новый лимит установлен.")
            if message.from_user.id != OWNER_ID:
                await say_to_owner(f"Новый лимит установлен для пользователя {user}:{new_limit}.")
        state.finish()
    else:
        await send_message(message.chat.id, "Неверное значение лимита. Ожидается число.")


@dp.message_handler(ChatType.is_private, commands=['stats'])
@bot_access(2)
async def stats(message):
    post_stats = await in_thread(get_posts_stats)
    msg = f"Статистика пользователей:\n" + "\n".join(post_stats)
    await send_message(message.chat.id, msg)


@dp.message_handler(types.ChatType.is_private, commands=['remonitor'])
@bot_access(2)
async def refill_monitor(message):
    log.debug("refill started")
    used_pics = await in_thread(get_used_pics, include_monitor=False)
    await in_thread(clean_monitor)
    for entry in os.listdir(MONITOR_FOLDER):
        if os.path.isfile(MONITOR_FOLDER + entry):
            (name, ext) = os.path.splitext(entry)
            if ext in ['.jpg', '.jpeg', '.png', '.gif']:
                try:
                    (service, post_id) = name.split('.')
                except ValueError:
                    continue
                if (service, post_id) in used_pics:
                    log.debug(f"{entry} was before")
                    os.remove(f"{MONITOR_FOLDER}{entry}")
                    continue
                else:
                    log.debug(f"{entry} not found, recreating")
                    with Image.open(MONITOR_FOLDER + entry) as im:
                        (width, height) = im.size
                    if not await in_thread(is_pic_exists, service=service, post_id=post_id):
                        (*_, authors, characters, copyrights) = await grabber.metadata(service, post_id)
                        pic_item = Pic(service=service, post_id=post_id,
                                       authors=authors,
                                       chars=characters,
                                       copyright=copyrights)
                        pic_id = await in_thread(save_monitor_pic, pic_item)
                        mon_msg = await send_photo(chat_id=TELEGRAM_CHANNEL_MON, photo_filename=MONITOR_FOLDER + entry,
                                                   caption=f'ID: {post_id}\n{width}x{height}',
                                                   reply_markup=markups.gen_rec_new_markup(pic_id, service,
                                                                                           post_id))
                        monitor_item = MonitorItem(pic_name=entry, tele_msg=mon_msg.message_id)
                        file_id = mon_msg.photo[0].file_id
                        await in_thread(append_pic_data, pic_id=pic_id, monitor_item=monitor_item, file_id=file_id)
    await send_message(chat_id=message.chat.id, text="Перезаполнение монитора завершено")


@bot_access(1)
def delete_callback(call, data):
    with session_scope() as session:
        queue_item = session.query(QueueItem).options(joinedload(QueueItem.pic)).filter_by(id=int(data)).first()
        bot.paginators[(call.message.chat.id, call.message.message_id)].delete_data_item(int(data))
        if queue_item:
            session.delete(queue_item)


def get_wall_total(api):
    return api.wall.get(owner_id="-" + VK_GROUP_ID)['count']


def get_wall_page(api, page_n):
    return api.wall.get(owner_id="-" + VK_GROUP_ID, offset=page_n * 100, count=100)['items']


async def refill_history():
    api = vk_requests.create_api(service_token=VK_TOKEN, api_version=5.71)
    post_count = await in_thread(get_wall_total, api=api)
    max_queries = (post_count - 1) // 100
    post_history = {}
    for query_count in range(max_queries + 1):
        posts = await in_thread(get_wall_page, api=api, page_n=query_count)
        for post in posts:
            if any(service_db[x]['post_url'] in post['text'] for x in service_db):
                links = post['text'].split()
                for link in links:
                    if any(service_db[x]['post_url'] in link for x in service_db):
                        service = next(
                            service for service in service_db if service_db[service]['post_url'] in link)
                        offset = link.find(service_db[service]['post_url'])
                        post_n = link[len(service_db[service]['post_url']) + offset:].strip()
                        if post_n.isdigit() and (service, post_n) not in post_history:
                            post_history[(service, post_n)] = post['id']
                            new_pic = Pic(post_id=post_n, service=service)
                            new_pic.history_item = HistoryItem(wall_id=post['id'])
                            await in_thread(add_new_pic, pic=new_pic)

            for att in post.get('attachments', {}):
                if att['type'] == 'link':
                    if any(service_db[x]['post_url'] in att['link']['url'] for x in service_db):
                        linkstr = att['link']['url'].partition(r'://')[2]
                        for post_str in linkstr:
                            service = next(service for service in service_db if
                                           service_db[service]['post_url'] in post_str)
                            offset = post_str.find(service_db[service]['post_url'])
                            post_n = post_str[len(service_db[service]['post_url']) + offset:].strip()
                            if post_n.isdigit() and (service, post_n) not in post_history:
                                post_history[(service, post_n)] = post['id']
                                new_pic = Pic(post_id=post_n, service=service)
                                new_pic.history_item = HistoryItem(wall_id=post['id'])
                                await in_thread(add_new_pic, pic=new_pic)
        await asyncio.sleep(0.4)


async def get_artist_suggestions(tag, service):
    service_artist_api = 'http://' + service_db[service]['artist_api']
    service_login = 'http://' + service_db[service]['login_url']
    service_payload = service_db[service]['payload']
    proxy = REQUESTS_PROXY
    headers = {'user-agent': 'OhaioPosterBot',
               'content-type': 'application/json; charset=utf-8'}
    async with aiohttp.ClientSession() as session:
        await session.post(service_login, data=service_payload, headers=headers)
        async with session.get(service_artist_api.format(tag), proxy=proxy) as resp:
            response = await resp.json()
    suggestions = {artist['name']: artist['other_names'] for artist in response}
    return suggestions


def is_valid_artist_name(name):
    pat = re.compile(r'[\w()-+]*$')
    return bool(pat.match(name))


@dp.callback_query_handler(markups.user_manager_cb.filter(action='allow'))
@bot_access(1)
async def callback_user_allow(call, callback_data):
    user = callback_data['user']
    bot.users[user]['access'] = 1

    await in_thread(save_users)
    await send_message(user, "Регистрация подтверждена.")
    await edit_message(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Готово.")


@dp.callback_query_handler(markups.user_manager_cb.filter(action='deny'))
@bot_access(1)
async def callback_user_deny(call, callback_data):
    user = callback_data['user']
    bot.users[user]['access'] = 0

    await in_thread(save_users)
    await send_message(user, "Регистрация отклонена.")
    await edit_message(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Готово.")


@dp.callback_query_handler(markups.user_manager_cb.filter(action='block'))
@bot_access(1)
async def callback_user_block(call, callback_data):
    user = callback_data['user']
    bot.users[user]['access'] = -1
    await in_thread(save_users)
    await send_message(user, "Регистрация отклонена и заблокирована.")
    await edit_message(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Готово.")


@dp.callback_query_handler(markups.post_rec_cb.filter(action='delete'))
@bot_access(1)
async def callback_mark_for_deletion(call, callback_data):
    pic_id = callback_data['pic_id']
    log.debug(f"Marked {pic_id} for deletion by {call.from_user.username}")
    service, post_id, checked = await in_thread(mark_post_for_deletion, pic_id=pic_id)
    await edit_markup(call.message.chat.id, call.message.message_id,
                      reply_markup=markups.gen_rec_new_markup(pic_id, service, post_id, checked))


MonitorData = namedtuple('MonitorData', ['to_del', 'pic_name', 'tele_msg', 'pic_id', 'service', 'post_id'])


@dp.callback_query_handler(markups.post_rec_cb.filter(action='finish'))
@bot_access(1)
async def callback_finish_monitor(call, callback_data):
    pic_id = callback_data['pic_id']
    await answer_callback(call.id, "Обработка началась")

    await in_thread(move_back_to_mon)  # just in case last check failed for some reason
    log.debug(f"{call.from_user.username} finished recommendations check")
    prog_msg = await send_message(chat_id=call.from_user.id, text="Обработка монитора")
    deleted = {service_db[key]['name']: [] for key in service_db}
    added = {service_db[key]['name']: [] for key in service_db}
    deleted['count'] = added['count'] = 0
    mon_items = await in_thread(get_monitor_before_id, pic_id=pic_id)
    mon_items.sort(key=attrgetter('post_id'))
    for i, item in enumerate(mon_items):

        if item.to_del:
            if os.path.exists(MONITOR_FOLDER + item.pic_name):
                os.remove(MONITOR_FOLDER + item.pic_name)
            await delete_message(call.message.chat.id, item.tele_msg)
            await in_thread(delete_pic_by_id, item.pic_id)
            deleted['count'] = deleted['count'] + 1
            deleted[service_db[item.service]['name']].append(item.post_id)
        else:
            queue_item = QueueItem(sender=call.from_user.id, pic_name=item.pic_name)
            await in_thread(append_pic_data, pic_id=item.pic_id, queue_item=queue_item, monitor_item=None)
            await delete_message(TELEGRAM_CHANNEL_MON, item.tele_msg)
            move_mon_to_q(item.pic_name)

            # await in_thread(delete_pic_by_id, item.pic_id)
            added['count'] = added['count'] + 1
            added[service_db[item.service]['name']].append(item.post_id)
        if i % 5 == 0:
            await edit_markup(prog_msg.chat.id, prog_msg.message_id,
                              reply_markup=markups.gen_status_markup(
                                  f"Текущий пост: {item.post_id} ({service_db[item.service]['name']})",
                                  f"Добавлено: {added['count']}",
                                  f"Удалено: {deleted['count']}"))

    post_total, user_total = await in_thread(get_queue_stats, sender=call.from_user.id)
    await edit_message(
        text=f"Обработка завершена. Добавлено {added['count']} пикч.\n"
             f"В персональной очереди: {user_total}/{bot.users[call.from_user.id]['limit']}\n"
             f"Всего постов: {post_total}\n" +
             "\n".join([f"{service}: {', '.join(ids)}" for service, ids in added.items() if
                        service != 'count' and ids != []]),
        chat_id=prog_msg.chat.id, message_id=prog_msg.message_id)
    if not call.from_user.id == OWNER_ID:
        await say_to_owner(
            f"Обработка монитора пользователем {call.from_user.username} завершена.\n"
            f"Добавлено {added['count']} пикч.\n"
            f"В персональной очереди: {user_total}/{bot.users[call.from_user.id]['limit']}\n"
            f"Всего постов: {post_total}.\n" +
            "\n".join([f"{service}: {', '.join(ids)}" for service, ids in added.items() if
                       service != 'count' and ids != []]))
    await send_message(call.message.chat.id, f"Последняя проверка: {time.strftime('%d %b %Y %H:%M:%S UTC+0')}")


@dp.callback_query_handler(markups.rec_fix_cb.filter())
@bot_access(1)
async def callback_tag_fix(call, callback_data):
    tag = callback_data['tag']
    service = SERVICE_DEFAULT
    alter_names = await get_artist_suggestions(tag, service)
    msg = ""
    if alter_names:
        msg += "Найдены возможные замены:\n"
        for name, alt_names in alter_names.items():
            msg += f"Тег: {name}\nАльтернативные имена:{alt_names.replace(tag, f'>{tag}<')}\n\n"
    msg += f"Что делать с тегом '{tag}'?"
    await send_message(call.from_user.id, msg,
                       reply_markup=markups.gen_tag_fix_markup(service, tag, alter_names.keys()))


@dp.callback_query_handler(markups.tag_fix_cb.filter(action='replace'))
@bot_access(1)
async def callback_tag_replace(call, callback_data):
    tag, alt_tag = callback_data['tag'], callback_data['replace_to']
    await in_thread(replace_tag, tag=tag, alt_tag=alt_tag)
    await answer_callback(call.id, "Тег обновлён")
    await delete_message(call.message.chat.id, call.message.message_id)


@dp.callback_query_handler(markups.tag_fix_cb.filter(action='delete'))
@bot_access(1)
async def callback_tag_delete(call, callback_data):
    tag = callback_data['tag']
    await in_thread(delete_tag, tag=tag)
    await answer_callback(call.id, "Тег удалён")
    await delete_message(call.message.chat.id, call.message.message_id)


@dp.message_handler(state=NewNameSetup.new_name)
async def rename_tag_receiver(message, state):
    new_tag = message.text
    if not is_valid_artist_name(new_tag):
        await send_message(message.chat.id, "Невалидное имя для тега!")
        return
    async with state.proxy() as data:
        old_tag = data['old_tag']
        service = data['service']
        await in_thread(rename_tag, service=service, old_name=old_tag, new_name=new_tag)
        await send_message(message.chat.id, "Тег обновлён.")
        data.state = None


@dp.callback_query_handler(markups.tag_fix_cb.filter(action='rename'))
@bot_access(1)
async def callback_tag_rename(call, callback_data, state):
    tag = callback_data['tag']
    service = callback_data['service']
    await send_message(call.message.chat.id, "Тег на замену:")
    await NewNameSetup.new_name.set()
    async with state.proxy() as data:
        data['old_tag'] = tag
        data['service'] = service


@dp.callback_query_handler(markups.rebuild_history_cb.filter())
@bot_access(1)
async def callback_rebuild_history(call, callback_data):
    if callback_data['action'] == 'allow':
        await in_thread(clear_history)
        await refill_history()
        await send_message(call.message.chat.id, "История перезаполнена.")
    elif callback_data['action'] == 'deny':
        await delete_message(call.message.chat.id, call.message.message_id)


@dp.callback_query_handler(markups.limit_cb.filter(), state=LimitSetup.user)
@bot_access(1)
async def callback_set_limit(call, callback_data, state):
    user = int(callback_data['user_id'])
    await delete_message(call.message.chat.id, call.message.message_id)
    with state.proxy() as data:
        data['user'] = user
    await LimitSetup.next()
    await send_message(call.message.chat.id, "Новый лимит:")


@dp.callback_query_handler(markups.dupes_cb.filter())
@bot_access(1)
async def callback_duplicates(call, callback_data):
    if callback_data['action'] == 'allow':
        await edit_markup(call.message.chat.id, call.message.message_id)
    elif callback_data['action'] == 'delete':
        service, post_id = callback_data['service'], callback_data['dupe_id']
        await in_thread(delete_duplicate, service=service, post_id=post_id)
        await edit_markup(call.message.chat.id, call.message.message_id)


def pil_grid(images):
    n_images = len(images)
    max_per_line = math.ceil(math.sqrt(n_images))
    max_lines = math.ceil(n_images / max_per_line)
    im_grid = Image.new('RGB', (max_per_line * 128, max_lines * 128), color='white')
    draw = ImageDraw.Draw(im_grid)
    font = ImageFont.truetype("VISITOR_RUS.TTF", 15)
    for i, im in enumerate(images):
        x = (i % max_per_line) * 128
        y = (i // max_per_line) * 128
        im_grid.paste(im, (x, y))
        tx = x + 3
        ty = y + 110
        # outline
        draw.text((tx - 1, ty), str(i + 1), (0, 0, 0), font=font)
        draw.text((tx + 1, ty), str(i + 1), (0, 0, 0), font=font)
        draw.text((tx, ty - 1), str(i + 1), (0, 0, 0), font=font)
        draw.text((tx, ty + 1), str(i + 1), (0, 0, 0), font=font)
        # text
        draw.text((tx, ty), str(i + 1), (255, 255, 255), font=font)
    return im_grid


async def generate_queue_image():
    pic_names = await in_thread(get_queue_picnames)
    images = []
    for pic_name in pic_names:
        try:
            im = Image.open(f"{QUEUE_FOLDER}{pic_name}")
        except OSError:
            thumb = Image.open('corrupted.jpg')
        else:
            size = 128, 128
            thumb = ImageOps.fit(im, size, Image.ANTIALIAS)
        images.append(thumb)
    grid = pil_grid(images)
    await in_thread(grid.save, QUEUE_GEN_FILE)


@dp.message_handler(ChatType.is_private, commands=['queue'])
@bot_access(1)
async def check_queue(message):
    await bot.send_chat_action(message.chat.id, 'upload_photo')
    log.debug(f"{message.from_user.username} issued queue grid generation")
    await generate_queue_image()
    log.debug("Queue grid picture generation complete. Sending...")
    await send_document(message.chat.id, data_filename=QUEUE_GEN_FILE, caption="Очередь")


@dp.message_handler(ChatType.is_private, commands=['delete'])
@bot_access(1)
async def delete_queue(message):
    queue = await in_thread(get_delete_queue)
    if queue:
        msg = await send_message(message.chat.id, "Что удаляем?")
        bot.paginators[(msg.chat.id, msg.message_id)] = InlinePaginator(msg, queue, message.from_user.id, 3)
        bot.paginators[(msg.chat.id, msg.message_id)].hook_bot(bot, in_thread(delete_callback))
    else:
        await send_message(message.chat.id, "Очередь пуста.")


@dp.message_handler(ChatType.is_private, commands=['rebuild_history'])
@bot_access(2)
async def rebuild_history(message):
    await send_message(message.chat.id, "ВЫ АБСОЛЮТНО ТОЧНО В ЭТОМ УВЕРЕНЫ?!",
                       reply_markup=markups.gen_rebuild_history_markup())


@dp.message_handler(ChatType.is_private, commands=['broadcast'])
@bot_access(2)
async def broadcast_message(message):
    try:
        param = message.text.split()[1:]
    except IndexError:
        await send_message(message.chat.id, text="А что передавать?")
        return
    msg = f"Сообщение от {message.from_user.username}:\n{' '.join(param)}"
    with session_scope() as session:
        for user, in session.query(User.user_id).filter(User.access >= 1).all():
            if user != message.chat.id:
                await send_message(user, msg)
    await send_message(message.chat.id, text="Броадкаст отправлен.")


@dp.message_handler(ChatType.is_private, commands=['add_tag'])
@bot_access(1)
async def add_recommendation_tag(message):
    param = message.text.split()[1:]
    if not param:
        await send_message(message.chat.id, text="А тег-то какой?")
        return
    try:
        last_check = param[1]
    except IndexError:
        last_check = 0
    tag = param[0]

    tag_exists = await in_thread(is_tag_exists, tag=tag)
    if tag_exists:
        await send_message(message.chat.id, text="Тег уже есть")
        return
    else:
        new_tag = Tag(tag=tag, service=SERVICE_DEFAULT, last_check=last_check, missing_times=0)
        await in_thread(write_new_tag, tag=new_tag)
        await send_message(message.chat.id, text="Тег добавлен")
    await check_recommendations(tag)


@dp.message_handler(ChatType.is_private)
@bot_access(1)
async def got_new_message(message):
    log.debug(f"Got new message: '{message.text}'")
    param = message.text.split()
    if param[0] in service_db:
        service = param[0]
        try:
            posts = param[1:]
        except IndexError:
            await send_message(message.chat.id, "А что постить-то?")
            return
        for post in posts:
            if post.isdigit():
                log.debug(f"Found ID: {post} Service: {service_db[service]['name']}")
                await queue_picture(message.from_user, service, post)
            else:
                await send_message(message.chat.id, f"Не распарсил: {post}")
    elif param[0].isdigit():
        log.debug("Found numeric ID")
        posts = param
        for post in posts:
            if post.isdigit():
                log.debug(f"Found ID: {post} Service: {service_db[SERVICE_DEFAULT]['name']}")
                await queue_picture(message.from_user, SERVICE_DEFAULT, post)
    elif any(service_db_item['post_url'] in param[0] for service_db_item in service_db.values()):
        log.debug("Found booru link")
        list_of_links = [x.strip() for x in filter(None, message.text.split())]
        for link in list_of_links:
            try:
                service, post_url = next((service, data['post_url']) for service, data in service_db.items() if
                                         data['post_url'] in link)
            except StopIteration:
                continue

            offset = link.find(post_url)
            question_cut = link.find('?') if link.find('?') != -1 and link.find('?') > offset + len(
                post_url) else None
            post_number = link[len(post_url) + offset:question_cut].strip()
            if post_number.isdigit():
                log.debug(
                    f"Found ID: {post_number} Service: {service_db[service]['name']}")
                if service == "pix":
                    # pixiv stores pictures WAY different than booru sites, so exceptional behavior
                    await queue_pixiv_illust(message.from_user, post_number)
                else:
                    await queue_picture(message.from_user, service, post_number)
            else:
                await send_message(message.chat.id, f"Не распарсил: {post_number}")
    else:
        await send_message(message.chat.id, "Не распарсил.")


def get_pixiv_post_details(post_id):
    api = pixivpy3.AppPixivAPI()
    api.login(service_db['pix']['payload']['user'],
              service_db['pix']['payload']['pass'])
    req = api.illust_detail(int(post_id))
    return req


async def queue_pixiv_illust(sender, post_id):
    service = 'pix'
    used_pics = await in_thread(get_used_pics, include_queue=True, include_monitor=True)
    req = await in_thread(get_pixiv_post_details, post_id=post_id)
    if not req.get('error', False):
        pixiv_msg = await send_message(chat_id=sender.id, text="Получены данные о работе, скачивание пикч")
        new_posts = {}
        if req['illust']['meta_pages']:
            illustrations_urls = [item['image_urls']['original'] for item in req['illust']['meta_pages']]
        else:
            illustrations_urls = [item for item in req['illust']['meta_single_page'].values()]
        total = len(illustrations_urls)
        present_pics = []
        for idx, url in enumerate(illustrations_urls):
            post_id = os.path.splitext(os.path.basename(url))[0]
            if (service, post_id) in used_pics:
                present_pics.append(post_id)
                continue

            pic_name = f'{service}.{os.path.basename(url)}'
            await edit_markup(pixiv_msg.chat.id, pixiv_msg.message_id,
                              reply_markup=markups.gen_status_markup(f"{idx}/{total}"))
            pic_hash = await grabber.download(url, f"{MONITOR_FOLDER}{pic_name}")
            if pic_hash:
                new_posts[post_id] = {'pic_name': pic_name, 'authors': "#" + req['illust']['user']['account'],
                                      'chars': '', 'copyright': '', 'hash': pic_hash}
            else:
                await send_message(sender.id, f"Не удалось скачать {pic_name}")
        if present_pics:
            await send_message(sender.id, f"Уже было: {', '.join(present_pics)}")
        if not new_posts:
            await edit_message("Нет пикч для добавления. Возможно все пикчи с данной ссылки уже были.",
                               pixiv_msg.chat.id, pixiv_msg.message_id)
            return
        await edit_message("Выкладываю пикчи в монитор", pixiv_msg.chat.id, pixiv_msg.message_id)
        for post_id, new_post in new_posts.items():
            if new_post['pic_name']:
                pic_id = await in_thread(create_pic, service=service, post_id=post_id, new_post=new_post)
                mon_msg = await send_photo(TELEGRAM_CHANNEL_MON, MONITOR_FOLDER + new_post['pic_name'],
                                           f"{new_post['authors']} ID: {post_id}",
                                           reply_markup=markups.gen_rec_new_markup(pic_id, service,
                                                                                   post_id))
                monitor_item = MonitorItem(tele_msg=mon_msg.message_id, pic_name=new_post['pic_name'])
                file_id = mon_msg.photo[0].file_id
                await in_thread(append_pic_data, pic_id=pic_id, monitor_item=monitor_item, file_id=file_id)
        await delete_message(pixiv_msg.chat.id, pixiv_msg.message_id)
    else:
        await send_message(chat_id=sender.id, text="Ошибка при получении данных")


async def queue_picture(sender, service, post_id):
    pics_total, user_total = await in_thread(get_queue_stats, sender=sender)
    text, markup, del_msg_chat_id, del_msg_id = await in_thread(is_pic_used, sender=sender,
                                                                service=service, post_id=post_id)
    if text:
        await send_message(sender.id, text, reply_markup=markup)
        if del_msg_chat_id:
            await delete_message(del_msg_chat_id, del_msg_id)
        return
    hashes = await in_thread(get_hashes)
    log.debug("Getting post info")
    pic_name, direct, authors, characters, copyrights = await grabber.metadata(service, post_id)
    if not direct:
        await send_message(sender.id, "Скачивание пикчи не удалось. Забаненный пост?")
        return
    new_pic = Pic(service=service, post_id=post_id, authors=authors, chars=characters, copyright=copyrights)
    new_pic.queue_item = QueueItem(sender=sender.id, pic_name=pic_name)
    dl_msg = await send_message(sender.id, "Скачиваю пикчу")
    pic_hash = grabber.download(direct, QUEUE_FOLDER + pic_name)
    if pic_hash:
        is_dupe = pic_hash in hashes
        new_pic.hash = pic_hash
        await in_thread(save_pic, new_pic=new_pic)
        await edit_message(chat_id=dl_msg.chat.id, message_id=dl_msg.message_id,
                           text=f"Пикча ID {post_id} ({service_db[service]['name']}) сохранена.\n"
                           f"В персональной очереди: {user_total + 1}/{bot.users[sender.id]['limit']}.\n"
                           f"Всего пикч: {pics_total + 1}.",
                           reply_markup=markups.gen_dupe_markup(service, post_id) if is_dupe else None)
        if sender.id != OWNER_ID:
            await say_to_owner(
                f"Новая пикча ID {post_id} ({service_db[service]['name']}) "
                f"добавлена пользователем {sender.username}.\n"
                f"В персональной очереди: {user_total + 1}/{bot.users[sender.id]['limit']}.\n"
                f"Всего пикч: {pics_total + 1}.")
    else:
        await edit_message(chat_id=dl_msg.chat.id, message_id=dl_msg.message_id,
                           text=f"Пикча {post_id} ({service_db[service]['name']}) не скачалась. "
                           f"Заглушка роскомнадзора? Отменено.")


async def notify_admins(text):
    admins = await in_thread(get_bot_admins)
    for admin in admins:
        await send_message(admin, text, disable_notification=True)


async def on_startup_webhook(dp):
    await notify_admins("I'm alive!")
    await bot.set_webhook(WEBHOOK_URL)


async def on_startup_polling(dp):
    await notify_admins("I'm alive!")


async def on_shutdown(dp):
    await bot.delete_webhook()


def get_monitor_before_id(pic_id):
    with session_scope() as session:
        mon_id = session.query(MonitorItem).filter_by(pic_id=pic_id).first().id
        mon_items = [MonitorData(item.to_del, item.pic_name, item.tele_msg,
                                 item.pic.id, item.pic.service, item.pic.post_id)
                     for item in session.query(MonitorItem).options(joinedload(MonitorItem.pic)).filter(
                MonitorItem.id <= mon_id).all()]
    return mon_items


def is_pic_used(sender, service, post_id, pics_total, user_total):
    with session_scope() as session:
        pic = session.query(Pic).options(joinedload(Pic.history_item), joinedload(Pic.monitor_item)).filter_by(
            service=service, post_id=post_id).first()
        if pic:
            if pic.queue_item:
                text = f"ID {post_id} ({service_db[service]['name']}) уже в очереди!"
                return text, None, None, None
            if pic.history_item:
                text = f"ID {post_id} ({service_db[service]['name']}) уже было!"
                markup = markups.gen_post_link(pic.history_item.wall_id)
                return text, markup, None, None
            if pic.monitor_item:
                pic.queue_item = QueueItem(sender=sender.id, pic_name=pic.monitor_item.pic_name)
                del_msg_chat_id, del_msg_id = TELEGRAM_CHANNEL_MON, pic.monitor_item.tele_msg
                move_mon_to_q(pic.monitor_item.pic_name)
                session.delete(pic.monitor_item)
                text = f"Пикча ID {post_id} ({service_db[service]['name']}) сохранена. \n" \
                    f"В персональной очереди: {user_total + 1}/{bot.users[sender.id]['limit']}.\n" \
                    f"Всего пикч: {pics_total + 1}."
                return text, None, del_msg_chat_id, del_msg_id
        return None, None, None, None


if __name__ == '__main__':
    if script_args.debugging:
        executor.start_polling(dp, reset_webhook=True, on_startup=on_startup_polling)
    else:
        start_webhook(dispatcher=dp, webhook_path=WEBHOOK_URL_PATH, on_startup=on_startup_webhook,
                      on_shutdown=on_shutdown, host=WEBHOOK_HOST, port=WEBHOOK_PORT)
