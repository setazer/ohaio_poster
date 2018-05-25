# -*- coding: utf-8 -*-
import argparse
import datetime as dt
import logging
import os
import time
from functools import wraps

import cherrypy
import dateutil.relativedelta as rd
import requests
import telebot
from PIL import Image
from sqlalchemy.orm import joinedload

import grabber
import markup_templates
import util
# Испорт рег. данных
from creds import *
from db_mng import User, Tag, Pic, QueueItem, HistoryItem, MonitorItem, Setting, session_scope
from markup_templates import InlinePaginator
from util import valid_artist_name


def main():
    # wrappers
    def bot_action(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retval = None
            for i in range(20):
                try:
                    retval = func(*args, **kwargs)
                except requests.exceptions.ConnectionError as exc:
                    time.sleep(err_wait[min(i, 5)])
                except telebot.apihelper.ApiException as exc:
                    o_logger.error(exc)
                    util.log_error(exc, args, kwargs)
                    break
                except Exception as exc:
                    o_logger.error(exc)
                    util.log_error(exc, args, kwargs)
                    time.sleep(err_wait[min(i, 3)])
                else:
                    break
            return retval

        return wrapper

    def access(access_number=0):
        def decorator(func):
            @wraps(func)
            def wrapper(message, *args):
                if users.get(message.from_user.id, 0) >= access_number:
                    func(message, *args)
                else:
                    if isinstance(message, telebot.types.CallbackQuery):
                        answer_callback(message.id, "Not allowed!")
                    else:
                        send_message(message.from_user.id, "Not allowed!")

            return wrapper

        return decorator

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
    def send_photo(chat_id, photo, caption=None, reply_to_message_id=None, reply_markup=None,
                   disable_notification=None):
        return bot.send_photo(chat_id=chat_id, photo=photo, caption=caption, reply_to_message_id=reply_to_message_id,
                              reply_markup=reply_markup,
                              disable_notification=disable_notification)

    @bot_action
    def answer_callback(callback_query_id, text=None, show_alert=None, url=None, cache_time=None):
        return bot.answer_callback_query(callback_query_id=callback_query_id, text=text, show_alert=show_alert, url=url,
                                         cache_time=cache_time)

    # bot main actions end

    def load_users():
        nonlocal users
        o_logger.debug("Loading users")
        with session_scope() as session:
            users = {user: access for user, access in session.query(User.user_id, User.access).all()}
        if not users:
            users = {OWNER_ROOM_ID: 100}
        o_logger.debug("Loaded users: " + str(users))

    def save_users():
        with session_scope() as session:
            for user in users:
                pg_user = User(user_id=user, access=users[user])
                session.merge(pg_user)
        o_logger.debug("Users saved")

    def say_to_owner(text):
        return send_message(OWNER_ROOM_ID, str(text))

    def move_mon_to_q(filename):
        os.rename(MONITOR_FOLDER + filename, QUEUE_FOLDER + filename)

    logging.Logger.propagate = False
    o_logger = logging.getLogger('OhaioPosterLogger')
    o_logger.propagate = False
    o_logger.setLevel(logging.DEBUG if args.debugging else logging.INFO)
    o_fh = logging.FileHandler(LOG_FILE)
    o_fh.setLevel(logging.DEBUG)
    o_fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [Listener] %(message)s"))
    o_ch = logging.StreamHandler()
    o_ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [Listener] %(message)s"))
    o_ch.setLevel(logging.ERROR)
    o_logger.addHandler(o_fh)
    o_logger.addHandler(o_ch)
    telebot.apihelper.proxy = REQUESTS_PROXY
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    next_steps = {}
    paginators = {}
    o_logger.debug("Initializing bot")
    users = {}
    # curjob = 1
    # job_queue = 0
    load_users()
    err_wait = [1, 5, 15, 30, 60, 300]
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
                # Эта функция обеспечивает проверку входящего сообщения
                bot.process_new_updates([update])
                return ''
            else:
                raise cherrypy.HTTPError(403)

    @bot.message_handler(commands=['start'])
    def start(message):
        if not message.chat.id in users:
            send_message(message.chat.id, "Привет! Заявка на регистрацию отправлена администратору.")
            send_message(OWNER_ROOM_ID,
                         f"Новый пользователь: {message.from_user.username} ({message.chat.id})",
                         reply_markup=markup_templates.gen_user_markup(message.chat.id))
        elif users[message.chat.id] == 1:
            send_message(message.chat.id, "Регистрация уже пройдена.")

        elif users[message.chat.id] == 0:
            send_message(message.chat.id, "Повторная заявка на регистрацию отправлена администратору.")
            send_message(OWNER_ROOM_ID,
                         f"Повторная регистрация: {message.from_user.username} ({message.chat.id})",
                         reply_markup=markup_templates.gen_user_markup(message.chat.id))

    @bot.message_handler(commands=['stop'], func=lambda m: bool(users.get(m.chat.id)))
    @access(1)
    def stop(message):
        send_message(message.chat.id, "Регистрация отозвана.")
        say_to_owner(f"Регистрация {message.from_user.username} ({message.chat.id}) отозвана.")
        users[message.chat.id] = 0
        save_users()

    @bot.message_handler(commands=['shutdown'], func=lambda m: bool(users.get(m.chat.id)))
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

    @bot.message_handler(commands=['uptime'], func=lambda m: bool(users.get(m.chat.id)))
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

    @bot.message_handler(commands=['remonitor'], func=lambda m: bool(users.get(m.chat.id)))
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
                    # elif (service, post_id) in monitor:
                    #     o_logger.debug("{} in monitor".format(entry))
                    #     with Image.open(entry) as im:
                    #         (width, height) = im.size
                    #     with open(entry, 'rb') as pic,session_scope() as session:
                    #         mon_item = session.query(MonitorItem).join(Pic).filter_by(service=service,post_id=post_id).first()
                    #         mon_msg = send_photo(TELEGRAM_CHANNEL_MON, pic,
                    #                        'ID: {}\n{}x{}'.format(post_id, width, height),
                    #                        reply_markup=markup_templates.gen_rec_new_markup(mon_item.pic_id,post_id, mon_item.to_del))
                    #         mon_item.tele_msg = mon_msg.message_id
                    #         session.merge(mon_item)
                    else:
                        o_logger.debug(f"{entry} not found, recreating")
                        with Image.open(MONITOR_FOLDER + entry) as im:
                            (width, height) = im.size

                        with open(MONITOR_FOLDER + entry, 'rb') as pic, session_scope() as session:
                            pic_item = session.query(Pic).filter_by(service=service, post_id=post_id).first()
                            if not pic_item:
                                (*_, authors, characters, copyrights) = grabber.get_metadata(service, post_id)
                                pic_item = Pic(service=service, post_id=post_id,
                                               authors=authors,
                                               chars=characters,
                                               copyright=copyrights)
                                session.add(pic_item)
                                session.flush()
                                session.refresh(pic_item)
                            mon_msg = send_photo(chat_id=TELEGRAM_CHANNEL_MON, photo=pic,
                                                 caption=f'ID: {post_id}\n{width}x{height}',
                                                 reply_markup=markup_templates.gen_rec_new_markup(pic_item.id, post_id))
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

    @bot.callback_query_handler(func=lambda call: 'pag_' not in call.data and bool(users.get(call.from_user.id)))
    @access(1)
    def callback_query(call):
        # nonlocal curjob
        if call.data.startswith("user_allow"):
            user = int(call.data[len("user_allow"):])
            users[user] = 1
            save_users()
            send_message(user, "Регистрация подтверждена.")
            edit_message(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Готово.")

        elif call.data.startswith("user_deny"):
            user = int(call.data[len("user_deny"):])
            users[user] = 0
            save_users()
            send_message(user, "Регистрация отклонена.")
            edit_message(chat_id=call.message.chat.id, message_id=call.message.message_id, text="Готово.")

        elif call.data.startswith("user_block"):
            user = int(call.data[len("user_block"):])
            users[user] = -1
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
                    post_id = mon_item.pic.post_id
                    mon_item.to_del = checked
                edit_markup(call.message.chat.id, call.message.message_id,
                            reply_markup=markup_templates.gen_rec_new_markup(id, post_id, checked))


            elif call.data.startswith("rec_finish"):
                answer_callback(call.id, "Обработка началась")

                id = call.data[len("rec_finish"):]
                util.move_back_to_mon()  # just in case last check failed for some reason
                with session_scope() as session:
                    mon_id = session.query(MonitorItem).filter_by(pic_id=id).first().id
                    mon_items = session.query(MonitorItem).options(joinedload(MonitorItem.pic)).filter(
                        MonitorItem.id <= mon_id).all()
                    o_logger.debug(f"{call.from_user.username} finished recommendations check")
                    prog_msg = send_message(chat_id=call.from_user.id, text="Обработка монитора")
                    # text=f"Пикча ID {item.pic.post_id} ({service_db[item.pic.service]['name']}) перенесена в очередь.")
                    deleted = {service_db[key]['name']: [] for key in service_db}
                    added = {service_db[key]['name']: [] for key in service_db}
                    deleted['count'] = added['count'] = 0
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
                    edit_message(
                        text=f"Обработка завершена. Добавлено {added['count']} пикч. Всего постов: {post_total}\n" +
                             "\n".join([f"{service}: {', '.join(ids)}" for service, ids in added.items() if
                                        service != 'count' and ids != []]),
                        chat_id=prog_msg.chat.id, message_id=prog_msg.message_id)
                    if not call.from_user.id == OWNER_ROOM_ID:
                        say_to_owner(
                            f"Обработка монитора пользователем {call.from_user.username} завершена. Добавлено {added['count']} пикч.\nВсего постов: {post_total}.\n" +
                            "\n".join([f"{service}: {', '.join(ids)}" for service, ids in added.items() if
                                       service != 'count' and ids != []]))
                send_message(call.message.chat.id, f"Последняя проверка: {time.strftime('%d %b %Y %H:%M:%S UTC+0')}")
            elif call.data.startswith("rec_fix"):
                tag = call.data[len("rec_fix"):]
                service = 'dan'
                alter_names = util.get_artist_suggestions(tag, service)
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
                msg = bot.send_message(call.message.chat.id, "Тег на замену:")
                next_steps[call.from_user.id] = (service, tag)
                bot.register_next_step_handler(msg, rename_tag_reciever)

    def rename_tag_reciever(message):
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
                         "Бот почему-то ожидал ответа на переименование тега, но данных об заменяемом теге нет.")

    @bot.message_handler(commands=['queue'], func=lambda m: bool(users.get(m.chat.id)))
    @access(1)
    def check_queue(message):
        bot.send_chat_action(message.chat.id, 'upload_photo')
        o_logger.debug(f"{message.from_user.username} issued queue grid generation")
        util.generate_queue_image()
        o_logger.debug("Queue grid picture generation complete. Sending...")
        with open(QUEUE_GEN_FILE, 'rb') as doc:
            bot.send_document(message.chat.id, doc, caption="Очередь")

    @bot.message_handler(commands=['delete'], func=lambda m: bool(users.get(m.chat.id)))
    @access(1)
    # @wait_for_job("Delete", False)
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

    # @bot.message_handler(commands=['rebuild_history'])
    # @access(2)
    # # @wait_for_job("Rebuild history")
    # def rebuild_history(message):
    #     with session_scope() as session:
    #         session.query(QueueItem).delete()
    #         session.query(HistoryItem).delete()
    #     util.refill_history()
    #     send_message(message.chat.id, "История перезаполнена.")

    @bot.message_handler(commands=['add_tag'], func=lambda m: bool(users.get(m.chat.id)))
    @access(1)
    def add_recommendation_tag(message):
        try:
            param = message.text.split()[1:]
        except IndexError:
            send_message(message.chat.id, text="А тег-то какой?")
            return
        try:
            last_check = param[1]
        except IndexError:
            last_check = 0
        tag = param[0]
        with session_scope() as session:
            rec_tag = session.query(Tag).filter_by(tag=tag, service='dan').first()
            if not rec_tag:
                rec_tag = Tag(tag=tag, service='dan', last_check=last_check, missing_times=0)
                session.add(rec_tag)
                send_message(message.chat.id, text="Тег добавлен")
            else:
                send_message(message.chat.id, text="Тег уже есть")

    @bot.message_handler(func=lambda m: bool(users.get(m.chat.id)))
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
                    service, post_url = \
                        [(service, service_data['post_url']) for service, service_data in service_db.items() if
                         service_data['post_url'] in link][0]
                except IndexError:
                    continue

                offset = link.find(post_url)
                question_cut = link.find('?') if link.find('?') != -1 and link.find('?') > offset else None
                post_number = link[len(post_url) + offset:question_cut].strip()
                if post_number.isdigit():
                    o_logger.debug(
                        f"Found ID: {post_number} Service: {service_db[service]['name']}")
                    queue_picture(message.from_user, service, post_number)
                else:
                    send_message(message.chat.id, f"Не распарсил: {post_number}")
        else:
            send_message(message.chat.id, "Не распарсил.")

    # @wait_for_job("Post")
    def queue_picture(sender, service, post_id):
        with session_scope() as session:
            pics_total = session.query(QueueItem).count()
            pic = session.query(Pic).options(joinedload(Pic.history_item), joinedload(Pic.monitor_item)).filter_by(
                service=service, post_id=post_id).first()
            if pic:
                new_pic = pic
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
                                 text=f"Пикча ID {post_id} ({service_db[service]['name']}) сохранена. "
                                      f"Всего пикч: {pics_total+1}.")
                    return
            o_logger.debug("Getting post info")
            (pic_name, direct, authors, characters, copyrights) = grabber.get_metadata(service, post_id)
            if not direct:
                send_message(sender.id, "Скачивание пикчи не удалось. Забаненный пост?")
                return
            new_pic = Pic(service=service, post_id=post_id, authors=authors, chars=characters, copyright=copyrights)
            new_pic.queue_item = QueueItem(sender=sender.id, pic_name=pic_name)
            dl_msg = send_message(sender.id, "Скачиваю пикчу")
            if grabber.download(direct, QUEUE_FOLDER + pic_name):
                session.add(new_pic)
                edit_message(chat_id=dl_msg.chat.id, message_id=dl_msg.message_id,
                             text=f"Пикча ID {post_id} ({service_db[service]['name']}) сохранена. "
                                  f"Всего пикч: {pics_total+1}.")
                if sender.id != OWNER_ROOM_ID:
                    say_to_owner(
                        f"Новая пикча ID {post_id} ({service_db[service]['name']}) добавлена пользователем {sender.username}. "
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
