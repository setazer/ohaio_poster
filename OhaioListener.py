# -*- coding: utf-8 -*-
import argparse
import datetime as dt
import json
import logging
import math
import os
import re
import time
from functools import wraps
from operator import attrgetter
from urllib.parse import quote

import cherrypy
import dateutil.relativedelta as rd
import pixivpy3
import requests
import telebot
import vk_requests
from PIL import Image, ImageOps, ImageDraw, ImageFont
from sqlalchemy import func
from sqlalchemy.orm import joinedload

import grabber
import markup_templates
import util
from OhaioMonitor import check_recommendations
from bot_mng import bot, send_message, send_photo, answer_callback, edit_message, edit_markup, delete_message, \
    send_document
from creds import *
from db_mng import User, Tag, Pic, QueueItem, HistoryItem, MonitorItem, Setting, session_scope
from markup_templates import InlinePaginator


def main():

    def access(access_number=0):
        def decorator(func):
            @wraps(func)
            def wrapper(message, *args):
                user_access = users[message.from_user.id]['access'] if message.from_user.id in users else 0
                if user_access >= access_number:
                    func(message, *args)
                elif user_access > 0:
                    if isinstance(message, telebot.types.CallbackQuery):
                        answer_callback(message.id, "Not allowed!")
                    else:
                        send_message(message.from_user.id, "Not allowed!")

            return wrapper

        return decorator

    def load_users():
        nonlocal users
        o_logger.debug("Loading users")
        with session_scope() as session:
            users = {user: {"access": access, "limit": limit} for user, access, limit in
                     session.query(User.user_id, User.access, User.limit).all()}
        if not users:
            users = {OWNER_ID: {"access": 100, "limit": QUEUE_LIMIT}}
        o_logger.debug(f'Loaded users: {", ".join(str(user) for user in users.keys())}')

    def save_users():
        with session_scope() as session:
            for user, userdata in users.items():
                db_user = User(user_id=user, access=userdata['access'], limit=userdata['limit'])
                session.merge(db_user)
        o_logger.debug("Users saved")

    def say_to_owner(text):
        return send_message(OWNER_ID, str(text))

    def move_mon_to_q(filename):
        os.rename(MONITOR_FOLDER + filename, QUEUE_FOLDER + filename)

    logging.Logger.propagate = False
    o_logger = logging.getLogger('OhaioPosterLogger')
    o_logger.propagate = False
    o_logger.setLevel(logging.DEBUG if args.debugging else logging.INFO)
    if args.debugging:
        telebot.logger.setLevel(logging.DEBUG)
    o_fh = logging.FileHandler(LOG_FILE)
    o_fh.setLevel(logging.DEBUG)
    o_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [Listener] %(message)s"))
    o_ch = logging.StreamHandler()
    o_ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [Listener] %(message)s"))
    o_ch.setLevel(logging.ERROR)
    o_logger.addHandler(o_fh)
    o_logger.addHandler(o_ch)

    next_steps = {}
    paginators = {}
    o_logger.debug("Initializing bot")
    users = {}
    load_users()

    error_msg = None
    shutting_down = False
    up_time = dt.datetime.fromtimestamp(time.time())
    cherrypy.config.update({
        'server.socket_host': WEBHOOK_LISTEN,
        'server.socket_port': WEBHOOK_PORT,
        'server.ssl_module': 'builtin',
        'server.ssl_certificate': WEBHOOK_SSL_CERT,
        'server.ssl_private_key': WEBHOOK_SSL_PRIV,
        'engine.autoreload.on': False

    })

    class WebhookServer(object):
        @cherrypy.expose
        def index(self):
            if 'content-length' in cherrypy.request.headers and \
                    'content-type' in cherrypy.request.headers and \
                    cherrypy.request.headers['content-type'] == 'application/json':
                length = int(cherrypy.request.headers['content-length'])
                json_string = cherrypy.request.body.read(length).decode("utf-8")
                update = telebot.types.Update.de_json(json_string)
                bot.process_new_updates([update])
                return ''
            else:
                raise cherrypy.HTTPError(403)

    @bot.message_handler(commands=['start'])
    def start(message):
        if message.chat.id not in users:
            send_message(message.chat.id, "Привет! Заявка на регистрацию отправлена администратору.")
            send_message(OWNER_ID,
                         f"Новый пользователь: {message.from_user.username} ({message.chat.id})",
                         reply_markup=markup_templates.gen_user_markup(message.chat.id))
        elif users[message.chat.id]['access'] == 1:
            send_message(message.chat.id, "Регистрация уже пройдена.")

        elif users[message.chat.id]['access'] == 0:
            send_message(message.chat.id, "Повторная заявка на регистрацию отправлена администратору.")
            send_message(OWNER_ID,
                         f"Повторная регистрация: {message.from_user.username} ({message.chat.id})",
                         reply_markup=markup_templates.gen_user_markup(message.chat.id))

    @bot.message_handler(commands=['stop'], func=lambda m: m.chat.type == "private")
    @access(1)
    def stop(message):
        send_message(message.chat.id, "Регистрация отозвана.")
        say_to_owner(f"Регистрация {message.from_user.username} ({message.chat.id}) отозвана.")
        users[message.chat.id]['access'] = 0
        save_users()

    @bot.message_handler(commands=['shutdown'], func=lambda m: m.chat.type == "private")
    @access(2)
    def shutdown(message):
        with session_scope() as session:
            last_shutdown = session.query(Setting).filter_by(setting='last_shutdown').first()
            if not last_shutdown:
                last_shutdown = '0_0'
            if last_shutdown == f'{message.chat.id}_{message.message_id}':
                return
            else:
                ls_setting = Setting(setting='last_shutdown', value=f'{message.chat.id}_{message.message_id}')
                session.merge(ls_setting)
        nonlocal shutting_down
        o_logger.debug("Shutting down")
        say_to_owner("Останавливаюсь...")
        shutting_down = True
        cherrypy.engine.exit()

    @bot.message_handler(commands=['uptime'], func=lambda m: m.chat.type == "private")
    @access(1)
    def uptime(message):
        nonlocal up_time
        cur_time = dt.datetime.fromtimestamp(time.time())
        attrs = ['years', 'months', 'days', 'hours', 'minutes', 'seconds']
        human_readable = lambda delta: [
            '%d %s' % (getattr(delta, attr), getattr(delta, attr) > 1 and attr or attr[:-1])
            for attr in attrs if getattr(delta, attr)]
        diff = ' '.join(human_readable(rd.relativedelta(cur_time, up_time)))
        send_message(message.chat.id, "Bot is running for: " + diff)

    @bot.message_handler(commands=['set_limit'], func=lambda m: m.chat.type == "private")
    @access(1)
    def set_limit(message):
        with session_scope() as session:
            db_users = {user.user_id: {'username': bot.get_chat(user.user_id).username, 'limit': user.limit} for
                        user in session.query(User).all()}
            send_message(message.chat.id, "Выберите пользователя для изменения лимита:",
                         reply_markup=markup_templates.gen_user_limit_markup(db_users))

    def change_limit(message, user=None):
        if message.text.isdigit():
            new_limit = int(message.text)
            users[user]['limit'] = new_limit
            save_users()
            send_message(message.chat.id, "Новый лимит установлен.")
            if message.from_user.id != OWNER_ID:
                say_to_owner(f"Новый лимит установлен для пользователя {user}:{new_limit}.")
        else:
            send_message(message.chat.id, "Неверное значение лимита. Ожидается число.")

    @bot.message_handler(commands=['stats'], func=lambda m: m.chat.type == "private")
    @access(2)
    def stats(message):
        with session_scope() as session:
            post_stats = {f"{sender}: {count}/{users[sender]['limit']}" for sender, count in
                          session.query(QueueItem.sender, func.count(QueueItem.sender)).group_by(
                              QueueItem.sender).all()}
            msg = f"Статистика пользователей:\n" + "\n".join(post_stats)
            send_message(message.chat.id, msg)


    @bot.message_handler(commands=['remonitor'], func=lambda m: m.chat.type == "private")
    @access(2)
    def refill_monitor(message):
        o_logger.debug("refill started")
        with session_scope() as session:
            queue = [(queue_item.pic.service, queue_item.pic.post_id) for queue_item in
                     session.query(QueueItem).options(joinedload(QueueItem.pic)).all()]
            history = [(history_item.pic.service, history_item.pic.post_id) for history_item in
                       session.query(HistoryItem).options(joinedload(HistoryItem.pic)).all()]
            monitor = session.query(MonitorItem)
            monitor.delete(synchronize_session=False)
        for entry in os.listdir(MONITOR_FOLDER):
            if os.path.isfile(MONITOR_FOLDER + entry):
                (name, ext) = os.path.splitext(entry)
                if ext in ['.jpg', '.jpeg', '.png', '.gif']:
                    try:
                        (service, post_id) = name.split('.')
                    except ValueError:
                        continue
                    if (service, post_id) in queue:
                        o_logger.debug(f"{entry} in queue")
                        os.remove(MONITOR_FOLDER + entry)
                        continue
                    elif (service, post_id) in history:
                        o_logger.debug(f"{entry} in history")
                        os.remove(MONITOR_FOLDER + entry)
                    else:
                        o_logger.debug(f"{entry} not found, recreating")
                        with Image.open(MONITOR_FOLDER + entry) as im:
                            (width, height) = im.size

                        with session_scope() as session:
                            pic_item = session.query(Pic).filter_by(service=service, post_id=post_id).first()
                            if not pic_item:
                                (*_, authors, characters, copyrights) = grabber.metadata(service, post_id)
                                pic_item = Pic(service=service, post_id=post_id,
                                               authors=authors,
                                               chars=characters,
                                               copyright=copyrights)
                                session.add(pic_item)
                                session.flush()
                                session.refresh(pic_item)
                            mon_msg = send_photo(chat_id=TELEGRAM_CHANNEL_MON, photo_filename=MONITOR_FOLDER + entry,
                                                 caption=f'ID: {post_id}\n{width}x{height}',
                                                 reply_markup=markup_templates.gen_rec_new_markup(pic_item.id, service,
                                                                                                  post_id))
                            pic_item.monitor_item = MonitorItem(pic_name=entry, tele_msg=mon_msg.message_id)
        send_message(chat_id=message.chat.id, text="Перезаполнение монитора завершено")

    @access(1)
    def delete_callback(call, data):
        with session_scope() as session:
            queue_item = session.query(QueueItem).options(joinedload(QueueItem.pic)).filter_by(id=int(data)).first()
            paginators[(call.message.chat.id, call.message.message_id)].delete_data_item(int(data))
            if queue_item:
                session.delete(queue_item)
            else:
                answer_callback(call.id, "Элемент не найден. Уже удалён?")

    def dead_paginator(call):
        del paginators[(call.message.chat.id, call.message.message_id)]

    def refill_history():
        with session_scope() as session:
            api = vk_requests.create_api(service_token=VK_TOKEN, api_version=5.71)
            postsnum = api.wall.get(owner_id="-" + VK_GROUP_ID)['count']
            max_queries = (postsnum - 1) // 100
            post_history = {}
            for querynum in range(max_queries + 1):
                posts = api.wall.get(owner_id="-" + VK_GROUP_ID, offset=querynum * 100, count=100)['items']
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
                                    session.add(new_pic)

                    if post.get('attachments'):
                        for att in post['attachments']:
                            if att['type'] == 'link':
                                if any(service_db[x]['post_url'] in att['link']['url'] for x in service_db):
                                    linkstr = att['link']['url'].split(r'://')[1:]
                                    for post_str in linkstr:
                                        service = next(service for service in service_db if
                                                       service_db[service]['post_url'] in post_str)
                                        offset = post_str.find(service_db[service]['post_url'])
                                        post_n = post_str[len(service_db[service]['post_url']) + offset:].strip()
                                        if post_n.isdigit() and (service, post_n) not in post_history:
                                            post_history[(service, post_n)] = post['id']
                                            new_pic = Pic(post_id=post_n, service=service)
                                            new_pic.history_item = HistoryItem(wall_id=post['id'])
                                            session.add(new_pic)
                time.sleep(0.4)

    def get_artist_suggestions(tag, service):
        suggestions = {}
        service_artist_api = 'http://' + service_db[service]['artist_api']
        service_login = 'http://' + service_db[service]['login_url']
        service_payload = service_db[service]['payload']
        proxies = REQUESTS_PROXY
        with requests.Session() as ses:
            ses.headers = {'user-agent': 'OhaioPoster/{0}'.format('0.0.0.1'),
                           'content-type': 'application/json; charset=utf-8'}
            ses.post(service_login, data=service_payload)
            response = ses.get(service_artist_api.format(tag), proxies=proxies).json()
            for artist in response:
                suggestions[artist['name']] = artist['other_names']
        return suggestions

    def valid_artist_name(name):
        pat = re.compile(r'[\w()-+]*$')
        return pat.match(name)

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

    @bot.callback_query_handler(func=lambda call: not call.data.startswith('pag_'))
    @access(1)
    def callback_query(call):
        if call.data.startswith("user_allow"):
            user = int(call.data[len("user_allow"):])
            users[user]['access'] = 1
            save_users()
            send_message(user, "Регистрация подтверждена.")
            edit_message(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Готово.")

        elif call.data.startswith("user_deny"):
            user = int(call.data[len("user_deny"):])
            users[user]['access'] = 0
            save_users()
            send_message(user, "Регистрация отклонена.")
            edit_message(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Готово.")

        elif call.data.startswith("user_block"):
            user = int(call.data[len("user_block"):])
            users[user]['access'] = -1
            save_users()
            send_message(user, "Регистрация отклонена и заблокирована.")
            edit_message(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Готово.")
        elif call.data.startswith("rec"):
            if call.data.startswith("rec_del"):
                with session_scope() as session:
                    data = call.data[len("rec_del"):]
                    id, salt = data.split()
                    o_logger.debug(f"Marked {id} for deletion by {call.from_user.username}")
                    mon_item = session.query(MonitorItem).filter_by(pic_id=id).first()
                    checked = not mon_item.to_del
                    service = mon_item.pic.service
                    post_id = mon_item.pic.post_id
                    mon_item.to_del = checked
                edit_markup(call.message.chat.id, call.message.message_id,
                            reply_markup=markup_templates.gen_rec_new_markup(id, service, post_id, checked))
            elif call.data.startswith("rec_finish"):
                answer_callback(call.id, "Обработка началась")

                id = call.data[len("rec_finish"):]
                move_back_to_mon()  # just in case last check failed for some reason
                with session_scope() as session:
                    mon_id = session.query(MonitorItem).filter_by(pic_id=id).first().id
                    mon_items = session.query(MonitorItem).options(joinedload(MonitorItem.pic)).filter(
                        MonitorItem.id <= mon_id).all()
                    o_logger.debug(f"{call.from_user.username} finished recommendations check")
                    prog_msg = send_message(chat_id=call.from_user.id, text="Обработка монитора")
                    deleted = {service_db[key]['name']: [] for key in service_db}
                    added = {service_db[key]['name']: [] for key in service_db}
                    deleted['count'] = added['count'] = 0
                    mon_items.sort(key=attrgetter('pic.post_id'))
                    for i, item in enumerate(mon_items):
                        if item.to_del:
                            if os.path.exists(MONITOR_FOLDER + item.pic_name):
                                os.remove(MONITOR_FOLDER + item.pic_name)
                            delete_message(call.message.chat.id, item.tele_msg)
                            session.delete(item.pic)
                            session.flush()
                            deleted['count'] = deleted['count'] + 1
                            deleted[service_db[item.pic.service]['name']].append(item.pic.post_id)
                        else:
                            item.pic.queue_item = QueueItem(sender=call.from_user.id, pic_name=item.pic_name)
                            delete_message(TELEGRAM_CHANNEL_MON, item.tele_msg)
                            move_mon_to_q(item.pic_name)
                            session.delete(item)
                            added['count'] = added['count'] + 1
                            added[service_db[item.pic.service]['name']].append(item.pic.post_id)
                        if i % 5 == 0:
                            edit_markup(prog_msg.chat.id, prog_msg.message_id,
                                        reply_markup=markup_templates.gen_status_markup(
                                            f"Текущий пост: {item.pic.post_id} ({service_db[item.pic.service]['name']})",
                                            f"Добавлено: {added['count']}",
                                            f"Удалено: {deleted['count']}"))
                    post_total = session.query(QueueItem).count()
                    user_total = session.query(QueueItem).filter_by(sender=call.from_user.id).count()
                    edit_message(
                        text=f"Обработка завершена. Добавлено {added['count']} пикч.\n"
                             f"В персональной очереди: {user_total}/{users[call.from_user.id]['limit']}\n"
                             f"Всего постов: {post_total}\n" +
                             "\n".join([f"{service}: {', '.join(ids)}" for service, ids in added.items() if
                                        service != 'count' and ids != []]),
                        chat_id=prog_msg.chat.id, message_id=prog_msg.message_id)
                    if not call.from_user.id == OWNER_ID:
                        say_to_owner(
                            f"Обработка монитора пользователем {call.from_user.username} завершена.\n"
                            f"Добавлено {added['count']} пикч.\n"
                            f"В персональной очереди: {user_total}/{users[call.from_user.id]['limit']}\n"
                            f"Всего постов: {post_total}.\n" +
                            "\n".join([f"{service}: {', '.join(ids)}" for service, ids in added.items() if
                                       service != 'count' and ids != []]))
                send_message(call.message.chat.id, f"Последняя проверка: {time.strftime('%d %b %Y %H:%M:%S UTC+0')}")
            elif call.data.startswith("rec_fix"):
                tag = call.data[len("rec_fix"):]
                service = 'dan'
                alter_names = get_artist_suggestions(tag, service)
                msg = ""
                if alter_names:
                    msg += "Найдены возможные замены:\n"
                    for name, alt_names in alter_names.items():
                        msg += f"Тег: {name}\nАльтернативные имена:{alt_names.replace(tag,f'>{tag}<')}\n\n"
                msg += f"Что делать с тегом '{tag}'?"
                send_message(call.from_user.id, msg,
                             reply_markup=markup_templates.gen_tag_fix_markup(tag, alter_names.keys()))
        elif call.data.startswith("tag"):
            if call.data.startswith("tag_rep"):
                data = call.data[len("tag_rep"):]
                service = 'dan'
                tag, alt_tag = data.split()
                with session_scope() as session:
                    tag_item = session.query(Tag).filter_by(tag=tag, service=service).first()
                    tag_item.tag = alt_tag
                answer_callback(call.id, "Тег обновлён")
                delete_message(call.message.chat.id, call.message.message_id)
            elif call.data.startswith("tag_del"):
                tag = call.data[len("tag_del"):]
                service = 'dan'
                with session_scope() as session:
                    tag_item = session.query(Tag).filter_by(tag=tag, service=service).first()
                    session.delete(tag_item)
                answer_callback(call.id, "Тег удалён")
                delete_message(call.message.chat.id, call.message.message_id)
            elif call.data.startswith("tag_ren"):
                tag = call.data[len("tag_ren"):]
                service = 'dan'
                msg = send_message(call.message.chat.id, "Тег на замену:")
                next_steps[call.from_user.id] = (service, tag)
                bot.register_next_step_handler(msg, rename_tag_receiver)
        elif call.data.startswith("rh"):
            if call.data.startswith("rh_yes"):
                with session_scope() as session:
                    session.query(HistoryItem).delete()
                refill_history()
                send_message(call.message.chat.id, "История перезаполнена.")
            elif call.data.startswith("rh_no"):
                delete_message(call.message.chat.id, call.message.message_id)
        elif call.data.startswith("limit"):
            user = call.data[len("limit"):]
            delete_message(call.message.chat.id, call.message.message_id)
            msg = send_message(call.message.chat.id, "Новый лимит:")
            bot.register_next_step_handler(msg, change_limit, user=int(user))
        elif call.data.startswith("dupe"):
            if call.data.startswith("dupe_allow"):
                edit_markup(call.message.chat.id, call.message.message_id)
            elif call.data.startswith("dupe_remove"):
                data = call.data[len("dupe_remove"):]
                service, post_id = data.split()
                with session_scope() as session:
                    pic = session.query(Pic).filter_by(service=service, post_id=post_id).first()
                    session.delete(pic.queue_item)
                    pic.history_item = HistoryItem(wall_id=-1)
                    edit_markup(call.message.chat.id, call.message.message_id)


    def rename_tag_receiver(message):
        new_tag = message.text
        if not valid_artist_name(new_tag):
            send_message(message.chat.id, "Невалидное имя для тега!")
            return
        if message.from_user.id in next_steps:
            old_tag, service = next_steps[message.from_user.id]
            with session_scope() as session:
                tag_item = session.query(Tag).filter_by(tag=old_tag, service=service).first()
                tag_item.tag = new_tag
            send_message(message.chat.id, "Тег обновлён.")
            del next_steps[message.from_user.id]
        else:
            send_message(message.chat.id,
                         "Бот почему-то ожидал ответа на переименование тега, но данных о заменяемом теге нет.")

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

    def generate_queue_image():
        with session_scope() as session:
            queue = session.query(QueueItem).order_by(QueueItem.id).all()
            images = []
            for q_item in queue:
                try:
                    im = Image.open(QUEUE_FOLDER + q_item.pic_name)
                except Exception:
                    thumb = Image.open('corrupted.jpg')
                else:
                    size = 128, 128
                    thumb = ImageOps.fit(im, size, Image.ANTIALIAS)
                images.append(thumb)
        grid = pil_grid(images)
        grid.save(QUEUE_GEN_FILE)

    @bot.message_handler(commands=['queue'], func=lambda m: m.chat.type == "private")
    @access(1)
    def check_queue(message):
        bot.send_chat_action(message.chat.id, 'upload_photo')
        o_logger.debug(f"{message.from_user.username} issued queue grid generation")
        generate_queue_image()
        o_logger.debug("Queue grid picture generation complete. Sending...")
        send_document(message.chat.id, data_filename=QUEUE_GEN_FILE, caption="Очередь")

    @bot.message_handler(commands=['delete'], func=lambda m: m.chat.type == "private")
    @access(1)
    def delete_queue(message):
        with session_scope() as session:
            queue = [(queue_item.id, f"{queue_item.pic.service}:{queue_item.pic.post_id}") for queue_item in
                     session.query(QueueItem).options(joinedload(QueueItem.pic)).order_by(QueueItem.id).all()]
        if queue:
            msg = send_message(message.chat.id, "Что удаляем?")
            paginators[(msg.chat.id, msg.message_id)] = InlinePaginator(msg, queue, 3)
            paginators[(msg.chat.id, msg.message_id)].hook_telebot(bot, delete_callback, dead_paginator)

            paginators[(msg.chat.id, msg.message_id)].navigation_process = access(1)(
                paginators[(msg.chat.id, msg.message_id)].navigation_process)

        else:
            send_message(message.chat.id, "Очередь пуста.")

    @bot.message_handler(commands=['rebuild_history'], func=lambda m: m.chat.type == "private")
    @access(2)
    def rebuild_history(message):
        send_message(message.chat.id, "ВЫ АБСОЛЮТНО ТОЧНО В ЭТОМ УВЕРЕНЫ?!",
                     reply_markup=markup_templates.gen_rebuild_history_markup())

    @bot.message_handler(commands=['broadcast'], func=lambda m: m.chat.type == "private")
    @access(2)
    def broadcast_message(message):
        try:
            param = message.text.split()[1:]
        except IndexError:
            send_message(message.chat.id, text="А что передавать?")
            return
        msg = f"Сообщение от {message.from_user.username}:\n{' '.join(param)}"
        with session_scope() as session:
            for user, in session.query(User.user_id).filter(User.access >= 1).all():
                if user != message.chat.id:
                    send_message(user, msg)
        send_message(message.chat.id, text="Броадкаст отправлен.")

    @bot.message_handler(commands=['add_tag'], func=lambda m: m.chat.type == "private")
    @access(1)
    def add_recommendation_tag(message):
        param = message.text.split()[1:]
        if not param:
            send_message(message.chat.id, text="А тег-то какой?")
            return
        try:
            last_check = param[1]
        except IndexError:
            last_check = 0
        tag = param[0]
        tags_api = 'http://' + service_db[SERVICE_DEFAULT]['posts_api']
        login = service_db[SERVICE_DEFAULT]['payload']['user']
        api_key = service_db[SERVICE_DEFAULT]['payload']['api_key']
        ses = requests.Session()
        proxies = REQUESTS_PROXY
        with session_scope() as session:
            rec_tag = session.query(Tag).filter_by(tag=tag, service='dan').first()
            if rec_tag:
                send_message(message.chat.id, text="Тег уже есть")
                return
            resp = ses.get(tags_api.format(f'{quote(tag)}&login={login}&api_key={api_key}&limit=1'),
                           proxies=proxies)
            try:
                posts = resp.json()
            except json.decoder.JSONDecodeError as ex:
                util.log_error(ex, kwargs={'tag': tag, 'text': resp.text})
                posts = []
            if not posts:
                send_message(message.chat.id, "Ошибка при получении постов тега. Отмена.")
                return
            rec_tag = Tag(tag=tag, service=SERVICE_DEFAULT, last_check=last_check, missing_times=0)
            session.add(rec_tag)
        send_message(message.chat.id, text="Тег добавлен")
        check_recommendations(tag)

    @bot.message_handler(func=lambda m: m.chat.type == "private")
    @access(1)
    def got_new_message(message):
        o_logger.debug(f"Got new message: '{message.text}'")
        param = message.text.split()
        if param[0] in service_db:
            service = param[0]
            try:
                posts = param[1:]
            except IndexError:
                send_message(message.chat.id, "А что постить-то?")
                return
            for post in posts:
                if post.isdigit():
                    o_logger.debug(f"Found ID: {post} Service: {service_db[service]['name']}")
                    queue_picture(message.from_user, service, post)
                else:
                    send_message(message.chat.id, f"Не распарсил: {post}")
        elif param[0].isdigit():
            o_logger.debug("Found numeric ID")
            posts = param
            for post in posts:
                if post.isdigit():
                    o_logger.debug(f"Found ID: {post} Service: {service_db[SERVICE_DEFAULT]['name']}")
                    queue_picture(message.from_user, SERVICE_DEFAULT, post)
        elif any(service_db_item['post_url'] in param[0] for service_db_item in service_db.values()):
            o_logger.debug("Found service link")
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
                    o_logger.debug(
                        f"Found ID: {post_number} Service: {service_db[service]['name']}")
                    if service == "pix":
                        # pixiv stores pictures WAY different than booru sites, so exceptional behavior
                        queue_pixiv_illust(message.from_user, post_number)
                    else:
                        queue_picture(message.from_user, service, post_number)
                else:
                    send_message(message.chat.id, f"Не распарсил: {post_number}")
        else:
            send_message(message.chat.id, "Не распарсил.")

    def queue_pixiv_illust(sender, pix_post_id):
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
        req = api.illust_detail(int(pix_post_id))
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
                            reply_markup=markup_templates.gen_status_markup(f"{idx}/{total}"))
                pic_hash = grabber.download(url, MONITOR_FOLDER + pic_name)
                if pic_hash:
                    new_posts[post_id] = {'pic_name': pic_name, 'authors': f"#{req['illust']['user']['account']}",
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
                                             reply_markup=markup_templates.gen_rec_new_markup(pic.id, service,
                                                                                              pix_post_id))
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
                                 reply_markup=markup_templates.gen_post_link(pic.history_item.wall_id))
                    return
                if pic.monitor_item:
                    pic.queue_item = QueueItem(sender=sender.id, pic_name=pic.monitor_item.pic_name)
                    delete_message(TELEGRAM_CHANNEL_MON, pic.monitor_item.tele_msg)
                    move_mon_to_q(pic.monitor_item.pic_name)
                    session.delete(pic.monitor_item)
                    send_message(chat_id=sender.id,
                                 text=f"Пикча ID {post_id} ({service_db[service]['name']}) сохранена. \n"
                                      f"В персональной очереди: {user_total+1}/{users[sender.id]['limit']}.\n"
                                      f"Всего пикч: {pics_total+1}.")
                    return
            o_logger.debug("Getting post info")
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
                                  f"В персональной очереди: {user_total+1}/{users[sender.id]['limit']}.\n"
                                  f"Всего пикч: {pics_total+1}.",
                             reply_markup=markup_templates.gen_dupe_markup(service, post_id) if is_dupe else None)
                if sender.id != OWNER_ID:
                    say_to_owner(
                        f"Новая пикча ID {post_id} ({service_db[service]['name']}) добавлена пользователем {sender.username}.\n"
                        f"В персональной очереди: {user_total+1}/{users[sender.id]['limit']}.\n"
                        f"Всего пикч: {pics_total+1}.")
            else:
                edit_message(chat_id=dl_msg.chat.id, message_id=dl_msg.message_id,
                             text=f"Пикча {post_id} ({service_db[service]['name']}) не скачалась. "
                                  f"Заглушка роскомнадзора? Отменено.")
                session.rollback()

    with session_scope() as session:
        for user, in session.query(User.user_id).filter(User.access >= 1).all():
            send_message(user, "I'm alive!", disable_notification=True)
    for i in range(1, 5):
        try:
            bot.remove_webhook()
            bot.set_webhook(url=WEBHOOK_URL_BASE + WEBHOOK_URL_PATH,
                            certificate=open(WEBHOOK_SSL_CERT, 'r'))
            cherrypy.quickstart(WebhookServer(), WEBHOOK_URL_PATH, {'/': {}})
            if shutting_down:
                break
        except Exception as ex:
            o_logger.error(ex)
            util.log_error(ex)
            if not error_msg:
                error_msg = say_to_owner(f"Бот упал, новая попытка ({i + 1}/5)")
            else:
                edit_message(f"Бот упал, новая попытка ({i + 1}/5)",
                             error_msg.chat.id,
                             error_msg.message_id)
    # for i in range(5):
    #     try:
    #         bot.polling(none_stop=True)
    #         if shutting_down:
    #             break
    #     except requests.exceptions.ReadTimeout:
    #         if not error_msg:
    #             error_msg = say_to_seto("Longpoll умер, новая попытка ({}/5)".format(i + 1))
    #         else:
    #             edit_message("Longpoll умер, новая попытка ({}/5)".format(i + 1),
    #                          error_msg.chat.id,
    #                          error_msg.message_id)
    #     except Exception as ex:
    #         util.log_error(ex)
    #         bot.stop_polling()
    #         if not error_msg:
    #             error_msg = say_to_seto("Бот упал, новая попытка ({}/5)".format(i + 1))
    #         else:
    #             edit_message("Бот упал, новая попытка ({}/5)".format(i + 1),
    #                          error_msg.chat.id,
    #                          error_msg.message_id)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--debug', dest='debugging', action='store_true', help='Verbose output')
    args = parser.parse_args()
    try:
        main()
    except Exception as ex:
        util.log_error(ex)
