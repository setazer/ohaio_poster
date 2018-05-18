# -*- coding: utf-8 -*-
import argparse

import cherrypy
import datetime as dt
import logging
import os
import requests
import telebot
import time
from functools import wraps

import dateutil.relativedelta as rd
from PIL import Image
from sqlalchemy.orm import joinedload

import grabber
import markup_templates
import util
# Испорт рег. данных
from creds import *
from db_mng import User, Tag, Pic, QueueItem, HistoryItem, MonitorItem, Setting, session_scope
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
                    util.log_error(exc,args,kwargs)
                    break
                except Exception as exc:
                    o_logger.error(exc)
                    util.log_error(exc,args,kwargs)
                    time.sleep(err_wait[min(i, 3)])
                else:
                    break
            return retval

        return wrapper

    def access(access_number=0):
        def decorator(func):
            @wraps(func)
            def wrapper(message):
                if users.get(message.from_user.id, 0) >= access_number:
                    func(message)
                else:
                    if isinstance(message,telebot.types.CallbackQuery):
                        answer_callback(message.id,"Not allowed!")
                    else:
                        send_message(message.from_user.id, "Not allowed!")

            return wrapper

        return decorator

    # def wait_for_job(job_name, increase_curjob=True):
    #     def decorator(func):
    #         @wraps(func)
    #         def wrapper(*args):
    #             nonlocal job_queue, curjob
    #             job_queue += 1
    #             job_n = job_queue
    #             o_logger.debug("Job [{}] #{} added. Curjob #{}".format(job_name, job_n, curjob))
    #             while job_n > curjob:
    #                 time.sleep(1)
    #             o_logger.debug("Job [{}] #{} started.".format(job_name, job_n, curjob))
    #             try:
    #                 retval = func(*args)
    #             except Exception as ex:
    #                 o_logger.debug("Job  [{}] #{} ended with error.".format(job_name, job_n))
    #                 util.log_error(ex)
    #                 retval = None
    #             if increase_curjob:
    #                 curjob += 1
    #             o_logger.debug("Job  [{}] #{} ended.".format(job_name, job_n))
    #             return retval
    #
    #         return wrapper
    #
    #     return decorator

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
        return bot.send_photo( chat_id=chat_id, photo=photo, caption=caption, reply_to_message_id=reply_to_message_id, reply_markup=reply_markup,
                   disable_notification=disable_notification)

    @bot_action
    def answer_callback(callback_query_id,text=None, show_alert=None, url=None, cache_time=None):
        return bot.answer_callback_query(callback_query_id=callback_query_id, text=text, show_alert=show_alert, url=url, cache_time=cache_time)

    # bot main actions end

    def load_users():
        nonlocal users
        o_logger.debug("Loading users")
        with session_scope() as session:
            users = {user: access for user, access in session.query(User.user_id, User.access).all()}
        if not users:
            users = {OWNER_ROOM_ID: 2}
        o_logger.debug("Loaded users: " + str(users))

    def save_users():
        with session_scope() as session:
            for user in users:
                pg_user = User(user_id=user, access=users[user])
                session.merge(pg_user)
        o_logger.debug("Users saved")

    def say_to_seto(text):
        return send_message(OWNER_ROOM_ID, str(text))

    def move_mon_to_q(filename):
        os.rename(MONITOR_FOLDER+filename,QUEUE_FOLDER+filename)


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
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    next_steps ={}
    o_logger.debug("Initializing bot")
    users = {}
    curjob = 1
    job_queue = 0
    load_users()
    err_wait = [1, 5, 15, 30, 60, 300]
    error_msg=None
    shutting_down = False
    up_time = dt.datetime.fromtimestamp(time.time())
    cherrypy.config.update({
        'server.socket_host': WEBHOOK_LISTEN,
        'server.socket_port': WEBHOOK_PORT,
        'server.ssl_module': 'builtin',
        'server.ssl_certificate': WEBHOOK_SSL_CERT,
        'server.ssl_private_key': WEBHOOK_SSL_PRIV,
        'engine.autoreload.on' : False

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
                         "Новый пользователь: {} ({})".format(message.from_user.username, message.chat.id),
                         reply_markup=markup_templates.gen_user_markup(message.chat.id))
        elif users[message.chat.id] == 1:
            send_message(message.chat.id, "Регистрация уже пройдена.")

        elif users[message.chat.id] == 0:
            send_message(message.chat.id, "Повторная заявка на регистрацию отправлена администратору.")
            send_message(OWNER_ROOM_ID,
                         "Повторная регистрация: {} ({})".format(message.from_user.username, message.chat.id),
                         reply_markup=markup_templates.gen_user_markup(message.chat.id))

    @bot.message_handler(commands=['stop'])
    @access(1)
    def stop(message):
        send_message(message.chat.id, "Регистрация отозвана.")
        say_to_seto("Регистрация {} ({}) отозвана.".format(message.from_user.username, message.chat.id))
        users[message.chat.id] = 0
        save_users()

    @bot.message_handler(commands=['shutdown'])
    @access(2)
    def shutdown(message):
        with session_scope() as session:
            last_shutdown = session.query(Setting).filter_by(setting='last_shutdown').first()
            if not last_shutdown:
                last_shutdown = '0_0'
            if last_shutdown == '{}_{}'.format(message.chat.id, message.message_id):
                return
            else:
                ls_setting = Setting(setting='last_shutdown', value='{}_{}'.format(message.chat.id, message.message_id))
                session.merge(ls_setting)
        nonlocal shutting_down
        o_logger.debug("Shutting down")
        say_to_seto("Останавливаюсь...")
        shutting_down = True
        cherrypy.engine.exit()

    @bot.message_handler(commands=['uptime'])
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

    @bot.message_handler(commands=['remonitor'])
    @access(2)
    def refill_monitor(message):
        o_logger.debug("refill started")
        with session_scope() as session:
            queue = [(queue_item.pic.service,queue_item.pic.post_id) for queue_item in session.query(QueueItem).options(joinedload(QueueItem.pic)).all()]
            history = [(history_item.pic.service,history_item.pic.post_id) for history_item in session.query(HistoryItem).options(joinedload(HistoryItem.pic)).all()]
            monitor= session.query(MonitorItem)
            monitor.delete(synchronize_session=False)
        for entry in os.listdir(MONITOR_FOLDER):
            if os.path.isfile(MONITOR_FOLDER+entry):
                (name, ext) = os.path.splitext(entry)
                if ext in ['.jpg', '.jpeg', '.png', '.gif']:
                    try:
                        (service, post_id) = name.split('.')
                    except ValueError:
                        continue
                    if (service, post_id) in queue:
                        o_logger.debug("{} in queue".format(entry))
                        os.remove(MONITOR_FOLDER+entry)
                        continue
                    elif (service, post_id) in history:
                        o_logger.debug("{} in history".format(entry))
                        os.remove(MONITOR_FOLDER+entry)
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
                        o_logger.debug("{} not found, recreating".format(entry))
                        with Image.open(MONITOR_FOLDER+entry) as im:
                            (width, height) = im.size

                        with open(MONITOR_FOLDER+entry, 'rb') as pic,session_scope() as session:
                            pic_item = session.query(Pic).filter_by(service=service,post_id=post_id).first()
                            if not pic_item:
                                (*rest, authors, characters, copyrights) = grabber.grab_booru(service, post_id)
                                pic_item = Pic(service=service, post_id=post_id,
                                             authors=authors,
                                             chars=characters,
                                             copyright=copyrights)
                                session.add(pic_item)
                                session.flush()
                                session.refresh(pic_item)
                            mon_msg = send_photo(chat_id=TELEGRAM_CHANNEL_MON, photo=pic,caption='ID: {}\n{}x{}'.format(post_id, width, height),
                                       reply_markup=markup_templates.gen_rec_new_markup(pic_item.id,post_id))
                            pic_item.monitor_item = MonitorItem(pic_name=entry, tele_msg = mon_msg.message_id)
                            session.merge(pic_item)
        send_message(chat_id=message.chat.id, text="Перезаполнение монитора завершено")

    @bot.callback_query_handler(func=lambda call: True)
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
        elif call.data == "del_finish":
            edit_message(chat_id=call.message.chat.id, message_id=call.message.message_id,
                         text="Удаление завершено.")
            o_logger.debug("Delete job ended.")

            # curjob += 1
        elif call.data.startswith("del"):
            idx = int(call.data[len('del'):])
            with session_scope() as session:
                pg_item = session.query(QueueItem).filter_by(id=idx).first()
                os.remove(pg_item.pic_name)
                session.delete(pg_item)
                queue = [{'id':queue_item.id,'post_id':queue_item.pic.post_id,'service':queue_item.pic.service} for queue_item in session.query(QueueItem).all()]
            edit_message(chat_id=call.message.chat.id, message_id=call.message.message_id,
                         text="Что удаляем?",
                         reply_markup=markup_templates.gen_delete_markup(queue))
        elif call.data.startswith("rec"):
            if call.data.startswith("rec_del"):
                with session_scope() as session:
                    data = call.data[len("rec_del"):]
                    id, salt = data.split()
                    o_logger.debug("Marked {} for deletion by {}".format(id, call.from_user.username))
                    mon_item = session.query(MonitorItem).filter_by(pic_id=id).first()
                    checked = not mon_item.to_del
                    post_id = mon_item.pic.post_id
                    mon_item.to_del = checked
                    session.merge(mon_item)
                edit_markup(call.message.chat.id, call.message.message_id,
                            reply_markup=markup_templates.gen_rec_new_markup(id,post_id, checked))


            elif call.data.startswith("rec_finish"):
                answer_callback(call.id,"Обработка началась")

                id = call.data[len("rec_finish"):]
                with session_scope() as session:
                    mon_id = session.query(MonitorItem).filter_by(pic_id=id).first().id
                    mon_items = session.query(MonitorItem).options(joinedload(MonitorItem.pic)).filter(MonitorItem.id<=mon_id).all()
                    o_logger.debug("{} finished recommendations check".format(call.from_user.username))
                    for item in mon_items:
                        if item.to_del:
                            if os.path.exists(MONITOR_FOLDER+item.pic_name):
                                os.remove(MONITOR_FOLDER+item.pic_name)

                            session.delete(item.pic)
                        else:
                            pic = item.pic
                            if pic.queue_item:
                                send_message(call.from_user.id,
                                             "ID {} ({}) уже в очереди!".format(pic.post_id, service_db[pic.service]['name']))
                                continue
                            if pic.history_item:
                                send_message(call.from_user.id,
                                             "ID {} ({}) уже было!".format(pic.post_id,
                                                                                service_db[pic.service]['name']))
                                continue
                            pic.queue_item = QueueItem(sender=call.from_user.id,pic_name=item.pic_name)

                            send_message(chat_id = call.from_user.id, text = "Пикча ID {} ({}) сохранена. "
                            "Всего пикч: {}.".format(pic.post_id, service_db[pic.service]['name'],
                                                     session.query(QueueItem).count()))
                            if call.from_user.id != OWNER_ROOM_ID:
                                say_to_seto("Новая пикча ID {} ({}) добавлена пользователем {}. "
                                            "Всего пикч: {}.".format(pic.post_id, service_db[pic.service]['name'],
                                                                     call.from_user.username,
                                                                     session.query(QueueItem).count()))
                            session.delete(item)
                            session.merge(pic)
                            session.flush()
                            move_mon_to_q(item.pic_name)
                        delete_message(call.message.chat.id, item.tele_msg)
                answer_callback(call.id, "Обработка завершена",show_alert=True)
                send_message(call.message.chat.id,"Последняя проверка: {}".format(time.strftime("%d %b %Y %H:%M:%S UTC+0")))
            elif call.data.startswith("rec_fix"):
                tag = call.data[len("rec_fix"):]
                service='dan'
                alter_names = util.get_artist_suggestions(tag,service)
                msg = ""
                if alter_names:
                    msg += "Найдены возможные замены:\n"
                    for name, alt_names in alter_names.items():
                        msg += "Тег: {}\nАльтернативные имена:{}\n\n".format(name,alt_names.replace(tag,'>{}<'.format(tag)))
                msg += "Что делать с тегом '{}'?".format(tag)
                send_message(call.from_user.id,msg,reply_markup=markup_templates.gen_tag_fix_markup(tag,alter_names.keys()))
        elif call.data.startswith("tag"):
            if call.data.startswith("tag_rep"):
                data = call.data[len("tag_rep"):]
                service = 'dan'
                tag, alt_tag = data.split()
                with session_scope() as session:
                    tag_item = session.query(Tag).filter_by(tag=tag,service=service).first()
                    tag_item.tag = alt_tag
                answer_callback(call.id,"Тег обновлён")
                delete_message(call.message.chat.id,call.message.message_id)
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
                msg = bot.send_message(call.message.chat.id,"Тег на замену:")
                next_steps[call.from_user.id] = (service, tag)
                bot.register_next_step_handler(msg,rename_tag_reciever)


    def rename_tag_reciever(message):
        new_tag = message.text
        if not valid_artist_name(new_tag):
            send_message(message.chat.id,"Невалидное имя для тега!")
            return
        if message.from_user.id in next_steps:
            old_tag, service = next_steps[message.from_user.id]
            with session_scope() as session:
                tag_item = session.query(Tag).filter_by(tag=old_tag, service=service).first()
                tag_item.tag = new_tag
            send_message(message.chat.id,"Тег обновлён.")
            del next_steps[message.from_user.id]
        else:
            send_message(message.chat.id,"Бот почему-то ожидал ответа на переименование тега, но данных об заменяемом теге нет.")

    @bot.message_handler(commands=['queue'])
    @access(1)
    def check_queue(message):
        bot.send_chat_action(message.chat.id, 'upload_photo')
        o_logger.debug("{} issued queue grid generation".format(message.from_user.username))
        util.generate_queue_image()
        o_logger.debug("Queue grid picture generation complete. Sending...")
        with open(QUEUE_GEN_FILE,'rb') as doc:
            bot.send_document(message.chat.id,doc,caption="Очередь")


    @bot.message_handler(commands=['delete'])
    @access(2)
    # @wait_for_job("Delete", False)
    def delete_queue(message):
        nonlocal curjob
        with session_scope() as session:
            queue = [{'id':queue_item.id,'post_id':queue_item.pic.post_id,'service':queue_item.pic.service} for queue_item in session.query(QueueItem).options(joinedload(QueueItem.pic)).all()]
        if queue:
            send_message(message.chat.id, "Что удаляем?",
                         reply_markup=markup_templates.gen_delete_markup(queue))
        else:
            send_message(message.chat.id, "Очередь пуста.")
            curjob += 1

    # @bot.message_handler(commands=['rebuild_history'])
    # @access(2)
    # # @wait_for_job("Rebuild history")
    # def rebuild_history(message):
    #     with session_scope() as session:
    #         session.query(QueueItem).delete()
    #         session.query(HistoryItem).delete()
    #     util.refill_history()
    #     send_message(message.chat.id, "История перезаполнена.")

    @bot.message_handler(commands=['add_tag'])
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

    @bot.message_handler()
    @access(1)
    def got_new_message(message):
        o_logger.debug("Got new message: '{}'".format(message.text))
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
                    o_logger.debug("Found ID: {} Service: {}".format(post, service_db[service]['name']))
                    queue_picture(message, service, post)
                else:
                    send_message(message.chat.id, "Не распарсил: {}".format(post))
        elif param[0].isdigit():
            o_logger.debug("Found numeric ID")
            posts = param
            for post in posts:
                if post.isdigit():
                    o_logger.debug("Found ID: {} Service: {}".format(post, service_db[SERVICE_DEFAULT]['name']))
                    queue_picture(message, SERVICE_DEFAULT, post)
        elif any(service_db_item['post_url'] in param[0] for service_db_item in service_db.values()):
            o_logger.debug("Found service link")
            list_of_links = [x.strip() for x in filter(None, message.text.split())]
            for link in list_of_links:
                for service, service_data in service_db.items():
                    post_url = service_data['post_url']
                    if post_url in link:
                        break
                else:
                    continue

                offset = link.find(post_url)
                question_cut = link.find('?') if link.find('?') != -1 and link.find('?') > offset else None
                post_number = link[len(post_url) + offset:question_cut].strip()
                if post_number.isdigit():
                    o_logger.debug(
                        "Found ID: {} Service: {}".format(post_number, service_db[service]['name']))
                    queue_picture(message, service, post_number)
                else:
                    send_message(message.chat.id, "Не распарсил: {}".format(post_number))
        else:
            send_message(message.chat.id, "Не распарсил.")

    def download(dl_msg, url, filename, preview=False):
        rep_subdomains = ["assets.", "assets2.", "simg3.", "simg4."]
        for subdomain in rep_subdomains:
            url = url.replace(subdomain, '')
        if url.startswith('//'):
            url = 'http:' + url

        if filename.startswith('dan'):
            proxies = TELEGRAM_PROXY
        else:
            proxies = {}
        req = requests.get(url, stream=True, proxies=proxies)
        total_length = req.headers.get('content-length', 0)
        if os.path.exists(filename) and os.path.getsize(filename) == int(total_length):
            return True
        if not total_length:  # no content length header
            return False
        with open(QUEUE_FOLDER + filename, 'wb') as f:
            dl = 0
            start = time.clock()
            for chunk in req.iter_content(1024):
                f.write(chunk)
                if not preview:
                    dl += len(chunk)
                    done = int(100 * dl / int(total_length))
                    if (time.clock() - start) > 1:
                        edit_markup(chat_id=dl_msg.chat.id, message_id=dl_msg.message_id,
                                    reply_markup=markup_templates.gen_progress(done))
                        start = time.clock()
        return True

    # @wait_for_job("Post")
    def queue_picture(message, service, post_id):
        with session_scope() as session:
            post_in_queue = session.query(QueueItem).join(Pic).filter_by(service=service, post_id=post_id).first()
            post_in_history = session.query(HistoryItem).join(Pic).filter_by(service=service, post_id=post_id).first()
            post_in_monitor = session.query(MonitorItem).join(Pic).filter_by(service=service, post_id=post_id).first()
            if post_in_queue:
                send_message(message.chat.id,
                             "ID {} ({}) уже в очереди!".format(post_id, service_db[service]['name']))
                return

            if post_in_history:
                send_message(message.chat.id, "ID {} ({}) уже было!".format(post_id, service_db[service]['name']),
                             reply_markup=markup_templates.gen_post_link(post_in_history.wall_id))
                return

            if post_in_monitor:
                q_pic = post_in_monitor.pic
                q_pic.queue_item = QueueItem(sender=message.chat.id, pic_name=post_in_monitor.pic_name)
                delete_message(TELEGRAM_CHANNEL_MON, post_in_monitor.tele_msg)
                session.delete(post_in_monitor)
                session.merge(q_pic)
                send_message(chat_id=message.chat.id, text="Пикча ID {} ({}) сохранена. "
                                                             "Всего пикч: {}.".format(post_id,
                                                                                      service_db[service]['name'],
                                                                                      session.query(QueueItem).count()+1))
                move_mon_to_q(post_in_monitor.pic_name)
                return


            o_logger.debug("Getting post info")
            (pic_name, direct, authors, characters, copyrights) = grabber.grab_booru(service, post_id)
            if not direct:
                send_message(message.chat.id, "Скачивание пикчи не удалось.")
                return
            dl_msg = send_message(message.chat.id, "Скачиваю пикчу")
            new_pic = Pic(service=service, post_id=post_id, authors=authors, chars=characters, copyright=copyrights)
            new_pic.queue_item = QueueItem(sender=message.chat.id, pic_name=pic_name)
            session.merge(new_pic)
            if download(dl_msg, direct, pic_name):
                edit_message(chat_id=dl_msg.chat.id, message_id=dl_msg.message_id,
                             text="Пикча ID {} ({}) сохранена. "
                                  "Всего пикч: {}.".format(post_id, service_db[service]['name'],
                                                           session.query(QueueItem).count()))
                if message.chat.id != OWNER_ROOM_ID:
                    say_to_seto("Новая пикча ID {} ({}) добавлена пользователем {}. "
                                "Всего пикч: {}.".format(post_id, service_db[service]['name'],
                                                         message.from_user.username if message.from_user.id != bot.get_me().id else message.chat.username,
                                                         session.query(QueueItem).count()))
            else:
                edit_message(chat_id=dl_msg.chat.id, message_id=dl_msg.message_id,
                             text="Пикча ({}: {}) не скачалась. Заглушка роскомнадзора? Отменено.".format(
                                 service_db[service]['name'], post_id))
                session.rollback()

    telebot.apihelper.proxy = TELEGRAM_PROXY
    with session_scope() as session:
        for user, in session.query(User.user_id).filter(User.access>=1).all():
            send_message(user, "I'm alive!",disable_notification=True)
    for i in range(1,5):
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
                error_msg = say_to_seto("Бот упал, новая попытка ({}/5)".format(i + 1))
            else:
                edit_message("Бот упал, новая попытка ({}/5)".format(i + 1),
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
