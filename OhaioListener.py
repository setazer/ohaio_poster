# -*- coding: utf-8 -*-
import argparse
import asyncio
import logging
import os
import re
import sys
import time
from datetime import datetime as dt
from functools import wraps

import aiohttp
import dateutil.relativedelta as rd
import math
import pixivpy3
import vk_requests
from PIL import Image, ImageOps, ImageDraw, ImageFont
from aiogram import types
from aiogram.types import ChatType
from aiogram.utils.executor import start_webhook
from sqlalchemy import func
from sqlalchemy.orm import joinedload

import grabber
import markups
from OhaioMonitor import check_recommendations
from bot_mng import bot, dp, NewNameSetup, LimitSetup
from bot_mng import send_message, send_photo, answer_callback, edit_message, edit_markup, delete_message, send_document
from creds import *
from db_mng import User, Tag, Pic, QueueItem, HistoryItem, MonitorItem, session_scope, Setting
from markups import InlinePaginator
from util import in_thread, human_readable


def access(access_number=0):
    def decorator(func):
        @wraps(func)
        async def wrapper(message, *args):
            user_access = bot.users[message.from_user.id]['access'] if message.from_user.id in bot.users else 0
            if user_access >= access_number:
                await func(message, *args)
            elif user_access > 0:
                if isinstance(message, types.CallbackQuery):
                    await answer_callback(message.id, "Not allowed!")
                else:
                    await send_message(message.from_user.id, "Not allowed!")

        return wrapper

    return decorator


parser = argparse.ArgumentParser()
parser.add_argument('-d', '--debug', dest='debugging', action='store_true', help='Verbose output')
args = parser.parse_args()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(f'ohaioposter.{__name__}')
log.setLevel(logging.DEBUG if args.debugging else logging.INFO)


def load_users():
    log.debug("Loading bot.users")
    with session_scope() as session:
        bot.users = {user: {"access": access, "limit": limit} for user, access, limit in
                     session.query(User.user_id, User.access, User.limit).all()}
    if not bot.users:
        bot.users = {OWNER_ID: {"access": 100, "limit": QUEUE_LIMIT}}
    log.debug(f'Loaded users: {", ".join(str(user) for user in bot.users)}')


def save_users():
    with session_scope() as session:
        for user, userdata in bot.users.items():
            db_user = User(user_id=user, access=userdata['access'], limit=userdata['limit'])
            session.merge(db_user)
    log.debug("Users saved")


log.debug("Initializing bot")
load_users()


async def say_to_owner(text):
    return await send_message(OWNER_ID, str(text))


def move_mon_to_q(filename):
    os.rename(MONITOR_FOLDER + filename, QUEUE_FOLDER + filename)


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
@access(1)
async def stop(message):
    await send_message(message.chat.id, "Регистрация отозвана.")
    await say_to_owner(f"Регистрация {message.from_user.username} ({message.chat.id}) отозвана.")
    bot.users[message.chat.id]['access'] = 0
    await in_thread(save_users)


def is_new_shutdown(chat_id, message_id) -> bool:
    # TODO ASYNC SQLA
    with session_scope() as session:
        last_shutdown = session.query(Setting).filter_by(setting='last_shutdown').first()
        if not last_shutdown:
            last_shutdown = '0_0'
        if last_shutdown != f'{chat_id}_{message_id}':
            ls_setting = Setting(setting='last_shutdown', value=f'{chat_id}_{message_id}')
            session.merge(ls_setting)
            return True
        else:
            return False


@dp.message_handler(ChatType.is_private, commands=['shutdown'])
@access(2)
async def shutdown(message):
    chat_id = message.chat.id
    message_id = message.message_id
    new_shutdown = await in_thread(is_new_shutdown, chat_id=chat_id, message_id=message_id)
    if new_shutdown:
        log.debug("Shutting down")
        await say_to_owner("Останавливаюсь...")
        sys.exit()


@dp.message_handler(ChatType.is_private, commands=['uptime'])
@access(1)
async def uptime(message):
    cur_time = dt.fromtimestamp(time.perf_counter())
    diff = ' '.join(human_readable(rd.relativedelta(cur_time, bot.start_time)))
    await send_message(message.chat.id, "Бот работает уже:\n" + diff)


def get_user_limits():
    # TODO ASYNC SQLA
    with session_scope() as session:
        db_users = {user.user_id: {'username': bot.get_chat(user.user_id).username, 'limit': user.limit} for
                    user in session.query(User).all()}
        return db_users


@dp.message_handler(ChatType.is_private, commands=['set_limit'])
@access(1)
async def set_limit(message):
    # TODO ASYNC SQLA
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


def get_posts_stats():
    # TODO ASYNC SQLA
    with session_scope() as session:
        post_stats = {f"{sender}: {count}/{bot.users[sender]['limit']}" for sender, count in
                      session.query(QueueItem.sender, func.count(QueueItem.sender)).group_by(
                          QueueItem.sender).all()}
        return post_stats


@dp.message_handler(ChatType.is_private, commands=['stats'])
@access(2)
async def stats(message):
    # TODO ASYNC SQLA
    post_stats = await in_thread(get_posts_stats)
    msg = f"Статистика пользователей:\n" + "\n".join(post_stats)
    await send_message(message.chat.id, msg)


def get_used_pics():
    # TODO ASYNC SQLA
    with session_scope() as session:
        used_pics = set((pic.service, pic.post_id) for pic in
                        session.query(Pic).filter(Pic.history_item.isnot(None), Pic.queue_item.isnot(None)).all())
    return used_pics


def clean_monitor():
    # TODO ASYNC SQLA
    with session_scope() as session:
        monitor = session.query(MonitorItem)
        monitor.delete(synchronize_session=False)


def save_new_pic(entry, service, post_id):
    # TODO ASYNC SQLA
    with Image.open(MONITOR_FOLDER + entry) as im:
        (width, height) = im.size
    with session_scope() as session:
        pic_item = session.query(Pic).filter_by(service=service, post_id=post_id).first()
        if not pic_item:
            (*_, authors, characters, copyrights) = await grabber.metadata(service, post_id)
            pic_item = Pic(service=service, post_id=post_id,
                           authors=authors,
                           chars=characters,
                           copyright=copyrights)
            session.add(pic_item)
            session.flush()
            session.refresh(pic_item)
        mon_msg = await send_photo(chat_id=TELEGRAM_CHANNEL_MON, photo_filename=MONITOR_FOLDER + entry,
                                   caption=f'ID: {post_id}\n{width}x{height}',
                                   reply_markup=markups.gen_rec_new_markup(pic_item.id, service,
                                                                           post_id))
        pic_item.monitor_item = MonitorItem(pic_name=entry, tele_msg=mon_msg.message_id)


@dp.message_handler(commands=['remonitor'], func=lambda m: m.chat.type == "private")
@access(2)
async def refill_monitor(message):
    log.debug("refill started")
    used_pics = await in_thread(get_used_pics)
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
                    await in_thread(save_new_pic, entry=entry, service=service, post_id=post_id)
    await send_message(chat_id=message.chat.id, text="Перезаполнение монитора завершено")


@access(1)
def delete_callback(call, data):
    with session_scope() as session:
        queue_item = session.query(QueueItem).options(joinedload(QueueItem.pic)).filter_by(id=int(data)).first()
        bot.paginators[(call.message.chat.id, call.message.message_id)].delete_data_item(int(data))
        if queue_item:
            session.delete(queue_item)
        else:
            await answer_callback(call.id, "Элемент не найден. Уже удалён?")


def get_wall_total(api):
    return api.wall.get(owner_id="-" + VK_GROUP_ID)['count']


def get_wall_page(api, page_n):
    return api.wall.get(owner_id="-" + VK_GROUP_ID, offset=page_n * 100, count=100)['items']


def add_new_pic(pic: Pic):
    with session_scope() as session:
        session.add(pic)


async def refill_history():
    api = vk_requests.create_api(service_token=VK_TOKEN, api_version=5.71)
    postsnum = await in_thread(get_wall_total, api=api)
    max_queries = (postsnum - 1) // 100
    post_history = {}
    for querynum in range(max_queries + 1):
        posts = await in_thread(get_wall_page, api=api, page_n=querynum)
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
    proxies = REQUESTS_PROXY
    headers = {'user-agent': 'OhaioPosterBot',
               'content-type': 'application/json; charset=utf-8'}
    async with aiohttp.ClientSession() as session:
        await session.post(service_login, data=service_payload, headers=headers)
        async with session.get(service_artist_api.format(tag), proxies=proxies) as resp:
            response = await resp.json()
    suggestions = {artist['name']: artist['other_names'] for artist in response}
    return suggestions


def valid_artist_name(name):
    pat = re.compile(r'[\w()-+]*$')
    return pat.match(name)


@dp.callback_query_handler(markups.user_manager_cb.filter(action='allow'))
@access(1)
async def callback_user_allow(call, callback_data):
    user = callback_data['user']
    bot.users[user]['access'] = 1
    # TODO ASYNC SQLA
    await in_thread(save_users)
    await send_message(user, "Регистрация подтверждена.")
    await edit_message(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Готово.")


@dp.callback_query_handler(markups.user_manager_cb.filter(action='deny'))
@access(1)
async def callback_user_deny(call, callback_data):
    user = callback_data['user']
    bot.users[user]['access'] = 0
    # TODO ASYNC SQLA
    await in_thread(save_users)
    await send_message(user, "Регистрация отклонена.")
    await edit_message(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Готово.")


@dp.callback_query_handler(markups.user_manager_cb.filter(action='block'))
@access(1)
async def callback_user_block(call, callback_data):
    user = callback_data['user']
    bot.users[user]['access'] = -1
    await in_thread(save_users)
    await send_message(user, "Регистрация отклонена и заблокирована.")
    await edit_message(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Готово.")


def mark_post_for_deletion(pic_id):
    with session_scope() as session:
        mon_item = session.query(MonitorItem).filter_by(pic_id=pic_id).first()
        checked = not mon_item.to_del
        service = mon_item.pic.service
        post_id = mon_item.pic.post_id
        mon_item.to_del = checked
    return service, post_id, checked


@dp.callback_query_handler(markups.post_rec_cb.filter(action='delete'))
@access(1)
async def callback_mark_for_deletion(call, callback_data):
    pic_id = callback_data['pic_id']
    log.debug(f"Marked {pic_id} for deletion by {call.from_user.username}")
    service, post_id, checked = await in_thread(mark_post_for_deletion, pic_id=pic_id)
    await edit_markup(call.message.chat.id, call.message.message_id,
                      reply_markup=markups.gen_rec_new_markup(pic_id, service, post_id, checked))


def move_back_to_mon():
    with session_scope() as session:
        mon_items = session.query(MonitorItem).all()
        q_items = [item.pic_name for item in session.query(QueueItem).all()]
        for mon_item in mon_items:
            if not os.path.exists(MONITOR_FOLDER + mon_item.pic_name):
                if os.path.exists(QUEUE_FOLDER + mon_item.pic_name) and not mon_item.pic_name in q_items:
                    os.rename(QUEUE_FOLDER + mon_item.pic_name, MONITOR_FOLDER + mon_item.pic_name)
                else:
                    session.delete(mon_item)


# TODO finish monithor check
@dp.callback_query_handler(markups.post_rec_cb.filter(action='finish'))
@access(1)
async def callback_finish_monitor(call, callback_data):
    pic_id = callback_data['pic_id']
    await answer_callback(call.id, "Обработка началась")

    # TODO ASYNC SQLA
    await in_thread(move_back_to_mon)  # just in case last check failed for some reason
    with session_scope() as session:
        mon_id = session.query(MonitorItem).filter_by(pic_id=pic_id).first().id
        mon_items = session.query(MonitorItem).options(joinedload(MonitorItem.pic)).filter(
            MonitorItem.id <= mon_id).all()
        log.debug(f"{call.from_user.username} finished recommendations check")
        prog_msg = await send_message(chat_id=call.from_user.id, text="Обработка монитора")
        deleted = {service_db[key]['name']: [] for key in service_db}
        added = {service_db[key]['name']: [] for key in service_db}
        deleted['count'] = added['count'] = 0
        for i, item in enumerate(mon_items):
            if item.to_del:
                if os.path.exists(MONITOR_FOLDER + item.pic_name):
                    os.remove(MONITOR_FOLDER + item.pic_name)
                await delete_message(call.message.chat.id, item.tele_msg)
                session.delete(item.pic)
                session.flush()
                deleted['count'] = deleted['count'] + 1
                deleted[service_db[item.pic.service]['name']].append(item.pic.post_id)
            else:
                item.pic.queue_item = QueueItem(sender=call.from_user.id, pic_name=item.pic_name)
                await delete_message(TELEGRAM_CHANNEL_MON, item.tele_msg)
                move_mon_to_q(item.pic_name)
                session.delete(item)
                added['count'] = added['count'] + 1
                added[service_db[item.pic.service]['name']].append(item.pic.post_id)
            if i % 5 == 0:
                await edit_markup(prog_msg.chat.id, prog_msg.message_id,
                                  reply_markup=markups.gen_status_markup(
                                      f"Текущий пост: {item.pic.post_id} ({service_db[item.pic.service]['name']})",
                                      f"Добавлено: {added['count']}",
                                      f"Удалено: {deleted['count']}"))
        post_total = session.query(QueueItem).count()
        user_total = session.query(QueueItem).filter_by(sender=call.from_user.id).count()
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
@access(1)
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


def replace_tag(tag, alt_tag):
    service = SERVICE_DEFAULT
    with session_scope() as session:
        tag_item = session.query(Tag).filter_by(tag=tag, service=service).first()
        tag_item.tag = alt_tag


@dp.callback_query_handler(markups.tag_fix_cb.filter(action='replace'))
@access(1)
async def callback_tag_replace(call, callback_data):
    tag, alt_tag = callback_data['tag'], callback_data['replace_to']
    await in_thread(replace_tag, tag=tag, alt_tag=alt_tag)
    await answer_callback(call.id, "Тег обновлён")
    await delete_message(call.message.chat.id, call.message.message_id)


def delete_tag(tag):
    service = SERVICE_DEFAULT
    with session_scope() as session:
        tag_item = session.query(Tag).filter_by(tag=tag, service=service).first()
        session.delete(tag_item)


@dp.callback_query_handler(markups.tag_fix_cb.filter(action='delete'))
@access(1)
async def callback_tag_delete(call, callback_data):
    tag = callback_data['tag']
    await in_thread(delete_tag, tag=tag)
    await answer_callback(call.id, "Тег удалён")
    await delete_message(call.message.chat.id, call.message.message_id)


def rename_tag(service, old_name, new_name):
    with session_scope() as session:
        tag_item = session.query(Tag).filter_by(tag=old_name, service=service).first()
        tag_item.tag = new_name


@dp.message_handler(state=NewNameSetup.new_name)
async def rename_tag_receiver(message, state):
    new_tag = message.text
    if not valid_artist_name(new_tag):
        await send_message(message.chat.id, "Невалидное имя для тега!")
        return
    async with state.proxy() as data:
        old_tag = data['old_tag']
        service = data['service']
        await in_thread(rename_tag, service=service, old_name=old_tag, new_name=new_tag)
        await send_message(message.chat.id, "Тег обновлён.")
        data.state = None


@dp.callback_query_handler(markups.tag_fix_cb.filter(action='rename'))
@access(1)
async def callback_tag_rename(call, callback_data, state):
    tag = callback_data['tag']
    service = callback_data['service']
    await send_message(call.message.chat.id, "Тег на замену:")
    await NewNameSetup.new_name.set()
    async with state.proxy() as data:
        data['old_tag'] = tag
        data['service'] = service


def clear_history():
    with session_scope() as session:
        session.query(HistoryItem).delete()


@dp.callback_query_handler(markups.rebuild_history_cb.filter())
@access(1)
async def callback_rebuild_history(call, callback_data):
    if callback_data['action'] == 'allow':
        await in_thread(clear_history)
        await refill_history()
        await send_message(call.message.chat.id, "История перезаполнена.")
    elif callback_data['action'] == 'deny':
        await delete_message(call.message.chat.id, call.message.message_id)


@dp.callback_query_handler(markups.limit_cb.filter(), state=LimitSetup.user)
@access(1)
async def callback_set_limit(call, callback_data, state):
    user = int(callback_data['user_id'])
    await delete_message(call.message.chat.id, call.message.message_id)
    with state.proxy() as data:
        data['user'] = user
    await LimitSetup.next()
    await send_message(call.message.chat.id, "Новый лимит:")


def delete_duplicate(service, post_id):
    with session_scope() as session:
        pic = session.query(Pic).filter_by(service=service, post_id=post_id).first()
        session.delete(pic.queue_item)
        pic.history_item = HistoryItem(wall_id=-1)


@dp.callback_query_handler(markups.dupes_cb.filter())
@access(1)
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


def get_queue_picnames():
    with session_scope() as session:
        pic_names = [q_item.pic_name for q_item in session.query(QueueItem).order_by(QueueItem.id).all()]
        return pic_names


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
    grid = await pil_grid(images)
    await in_thread(grid.save, QUEUE_GEN_FILE)


@dp.message_handler(ChatType.is_private, commands=['queue'])
@access(1)
async def check_queue(message):
    await bot.send_chat_action(message.chat.id, 'upload_photo')
    log.debug(f"{message.from_user.username} issued queue grid generation")
    await generate_queue_image()
    log.debug("Queue grid picture generation complete. Sending...")
    await send_document(message.chat.id, data_filename=QUEUE_GEN_FILE, caption="Очередь")


def get_delete_queue():
    # TODO ASYNC SQLA
    with session_scope() as session:
        queue = [(queue_item.id, f"{queue_item.pic.service}:{queue_item.pic.post_id}") for queue_item in
                 session.query(QueueItem).options(joinedload(QueueItem.pic)).order_by(QueueItem.id).all()]
        return queue


@dp.message_handler(ChatType.is_private, commands=['delete'])
@access(1)
async def delete_queue(message):
    queue = await in_thread(get_delete_queue)
    if queue:
        msg = await send_message(message.chat.id, "Что удаляем?")
        bot.paginators[(msg.chat.id, msg.message_id)] = InlinePaginator(msg, queue, message.from_user.id, 3)
        bot.paginators[(msg.chat.id, msg.message_id)].hook_bot(bot, in_thread(delete_callback))
    else:
        await send_message(message.chat.id, "Очередь пуста.")


@dp.message_handler(ChatType.is_private, commands=['rebuild_history'])
@access(2)
async def rebuild_history(message):
    await send_message(message.chat.id, "ВЫ АБСОЛЮТНО ТОЧНО В ЭТОМ УВЕРЕНЫ?!",
                       reply_markup=markups.gen_rebuild_history_markup())


@dp.message_handler(ChatType.is_private, commands=['broadcast'])
@access(2)
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


def check_tag_exists(tag):
    with session_scope() as session:
        tag_in_db = session.query(Tag).filter_by(tag=tag, service=SERVICE_DEFAULT).first()
    return bool(tag_in_db)


def write_new_tag(tag):
    with session_scope() as session:
        session.add(tag)


@dp.message_handler(ChatType.is_private, commands=['add_tag'])
@access(1)
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

    tag_exists = await in_thread(check_tag_exists, tag=tag)
    if tag_exists:
        await send_message(message.chat.id, text="Тег уже есть")
        return
    else:
        new_tag = Tag(tag=tag, service=SERVICE_DEFAULT, last_check=last_check, missing_times=0)
        await in_thread(write_new_tag, tag=new_tag)
        await send_message(message.chat.id, text="Тег добавлен")
    # TODO new teg monitor
    check_recommendations(tag)


@dp.message_handler(ChatType.is_private)
@access(1)
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
                # TODO new picture addition
                queue_picture(message.from_user, service, post)
            else:
                await send_message(message.chat.id, f"Не распарсил: {post}")
    elif param[0].isdigit():
        log.debug("Found numeric ID")
        posts = param
        for post in posts:
            if post.isdigit():
                log.debug(f"Found ID: {post} Service: {service_db[SERVICE_DEFAULT]['name']}")
                # TODO new picture addition
                queue_picture(message.from_user, SERVICE_DEFAULT, post)
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
                    # TODO new picture addition
                    queue_pixiv_illust(message.from_user, post_number)
                else:
                    # TODO new picture addition
                    queue_picture(message.from_user, service, post_number)
            else:
                await send_message(message.chat.id, f"Не распарсил: {post_number}")
    else:
        await send_message(message.chat.id, "Не распарсил.")


def queue_pixiv_illust(sender, post_id):
    service = 'pix'
    with session_scope() as session:
        queue = [(queue_item.pic.service, queue_item.pic.post_id) for queue_item in
                 session.query(QueueItem).options(joinedload(QueueItem.pic)).all()]
        history = [(history_item.pic.service, history_item.pic.post_id) for history_item in
                   session.query(HistoryItem).options(joinedload(HistoryItem.pic)).all()]
        monitor = [(monitor_item.pic.service, monitor_item.pic.post_id) for monitor_item in
                   session.query(MonitorItem).options(joinedload(MonitorItem.pic)).all()]
    qhm = queue + history + monitor
    api = pixivpy3.AppPixivAPI()
    api.login(service_db['pix']['payload']['user'],
              service_db['pix']['payload']['pass'])
    req = api.illust_detail(int(post_id))
    if not req.get('error', False):
        pixiv_msg = send_message(chat_id=sender.id, text="Получены данные о работе, скачивание пикч")
        new_posts = {}
        if req['illust']['meta_pages']:
            illustrations_urls = [item['image_urls']['original'] for item in req['illust']['meta_pages']]
        else:
            illustrations_urls = [item for item in req['illust']['meta_single_page'].values()]
        total = len(illustrations_urls)
        present_pics = []
        for idx, url in enumerate(illustrations_urls):
            post_id = os.path.splitext(os.path.basename(url))[0]
            if (service, post_id) in qhm:
                present_pics.append(post_id)
                continue

            pic_name = 'pix.' + os.path.basename(url)
            edit_markup(pixiv_msg.chat.id, pixiv_msg.message_id,
                        reply_markup=markups.gen_status_markup(f"{idx}/{total}"))
            pic_hash = grabber.download(url, MONITOR_FOLDER + pic_name)
            if pic_hash:
                new_posts[post_id] = {'pic_name': pic_name, 'authors': "#" + req['illust']['user']['account'],
                                      'chars': '', 'copyright': '', 'hash': pic_hash}
            else:
                send_message(sender.id, f"Не удалось скачать {pic_name}")
        if present_pics:
            send_message(sender.id, f"Уже было: {', '.join(present_pics)}")
        if not new_posts:
            edit_message("Нет пикч для добавления. Возможно все пикчи с данной ссылки уже были.", pixiv_msg.chat.id,
                         pixiv_msg.message_id)
            return
        edit_message("Выкладываю пикчи в монитор", pixiv_msg.chat.id, pixiv_msg.message_id)
        for post_id, new_post in new_posts.items():
            if new_post['pic_name']:
                with session_scope() as session:
                    pic = session.query(Pic).filter_by(service=service, post_id=post_id).first()
                    if not pic:
                        pic = Pic(
                            service=service,
                            post_id=post_id,
                            authors=new_post['authors'],
                            chars=new_post['chars'],
                            copyright=new_post['copyright'],
                            hash=new_post['hash'])
                        session.add(pic)
                        session.flush()
                        session.refresh(pic)
                    mon_msg = send_photo(TELEGRAM_CHANNEL_MON, MONITOR_FOLDER + new_post['pic_name'],
                                         f"{new_post['authors']} ID: {post_id}",
                                         reply_markup=markups.gen_rec_new_markup(pic.id, service,
                                                                                 pic.post_id))
                    pic.monitor_item = MonitorItem(tele_msg=mon_msg.message_id, pic_name=new_post['pic_name'])
                    pic.file_id = mon_msg.photo[0].file_id
        delete_message(pixiv_msg.chat.id, pixiv_msg.message_id)
    else:
        send_message(chat_id=sender.id, text="Ошибка при получении данных")


def queue_picture(sender, service, post_id):
    with session_scope() as session:
        pics_total = session.query(QueueItem).count()
        user_total = session.query(QueueItem).filter_by(sender=sender.id).count()
        hashes = {pic_item.hash: pic_item.post_id for pic_item in session.query(Pic).all()}
        pic = session.query(Pic).options(joinedload(Pic.history_item), joinedload(Pic.monitor_item)).filter_by(
            service=service, post_id=post_id).first()
        if pic:
            if pic.queue_item:
                send_message(sender.id, f"ID {post_id} ({service_db[service]['name']}) уже в очереди!")
                return
            if pic.history_item:
                send_message(sender.id, f"ID {post_id} ({service_db[service]['name']}) уже было!",
                             reply_markup=markups.gen_post_link(pic.history_item.wall_id))
                return
            if pic.monitor_item:
                pic.queue_item = QueueItem(sender=sender.id, pic_name=pic.monitor_item.pic_name)
                delete_message(TELEGRAM_CHANNEL_MON, pic.monitor_item.tele_msg)
                move_mon_to_q(pic.monitor_item.pic_name)
                session.delete(pic.monitor_item)
                send_message(chat_id=sender.id,
                             text=f"Пикча ID {post_id} ({service_db[service]['name']}) сохранена. \n"
                             f"В персональной очереди: {user_total + 1}/{bot.users[sender.id]['limit']}.\n"
                             f"Всего пикч: {pics_total + 1}.")
                return
        log.debug("Getting post info")
        (pic_name, direct, authors, characters, copyrights) = grabber.metadata(service, post_id)
        if not direct:
            send_message(sender.id, "Скачивание пикчи не удалось. Забаненный пост?")
            return
        new_pic = Pic(service=service, post_id=post_id, authors=authors, chars=characters, copyright=copyrights)
        new_pic.queue_item = QueueItem(sender=sender.id, pic_name=pic_name)
        dl_msg = send_message(sender.id, "Скачиваю пикчу")
        pic_hash = grabber.download(direct, QUEUE_FOLDER + pic_name)
        if pic_hash:
            is_dupe = pic_hash in hashes
            new_pic.hash = pic_hash
            session.add(new_pic)
            edit_message(chat_id=dl_msg.chat.id, message_id=dl_msg.message_id,
                         text=f"Пикча ID {post_id} ({service_db[service]['name']}) сохранена.\n"
                         f"В персональной очереди: {user_total + 1}/{bot.users[sender.id]['limit']}.\n"
                         f"Всего пикч: {pics_total + 1}.",
                         reply_markup=markups.gen_dupe_markup(service, post_id) if is_dupe else None)
            if sender.id != OWNER_ID:
                say_to_owner(
                    f"Новая пикча ID {post_id} ({service_db[service]['name']}) "
                    f"добавлена пользователем {sender.username}.\n"
                    f"В персональной очереди: {user_total + 1}/{bot.users[sender.id]['limit']}.\n"
                    f"Всего пикч: {pics_total + 1}.")
        else:
            edit_message(chat_id=dl_msg.chat.id, message_id=dl_msg.message_id,
                         text=f"Пикча {post_id} ({service_db[service]['name']}) не скачалась. "
                         f"Заглушка роскомнадзора? Отменено.")
            session.rollback()


def get_bot_admins():
    with session_scope() as session:
        admins = [user for user, in session.query(User.user_id).filter(User.access >= 1).all()]
    return admins


async def on_startup(dp):
    admins = await in_thread(get_bot_admins)
    for admin in admins:
        await send_message(admin, "I'm alive!", disable_notification=True)
    await bot.set_webhook(WEBHOOK_URL)


async def on_shutdown(app):
    # Remove webhook.
    await bot.delete_webhook()


if __name__ == '__main__':
    start_webhook(dispatcher=dp, webhook_path=WEBHOOK_URL, on_startup=on_startup, on_shutdown=on_shutdown,
                  skip_updates=False, host=WEBHOOK_HOST, port=WEBHOOK_PORT)
