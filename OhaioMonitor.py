# -*- coding: utf-8 -*-
import json
import logging
import time
from functools import wraps
from urllib.parse import quote

import requests
import telebot
from sqlalchemy.orm import joinedload

import grabber
import markup_templates
import util
from creds import LOG_FILE, TELEGRAM_TOKEN, TELEGRAM_CHANNEL_MON, service_db, BANNED_TAGS, REQUESTS_PROXY, \
    MONITOR_FOLDER
from db_mng import Tag, QueueItem, HistoryItem, Pic, MonitorItem, session_scope

err_wait = [1, 5, 15, 30, 60, 300]


def bot_action(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        retval = None
        for i in range(20):
            try:
                retval = func(*args, **kwargs)
            except requests.exceptions.ConnectionError:
                time.sleep(err_wait[min(i, 5)])
            except (telebot.apihelper.ApiException, FileNotFoundError) as exc:
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


def check_recommendations(new_tag=None):
    bot = telebot.TeleBot(TELEGRAM_TOKEN)

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
    def send_photo(chat_id, photo_filename, caption=None, reply_to_message_id=None, reply_markup=None,
                   parse_mode=None, disable_notification=None):
        with open(photo_filename, 'rb') as photo:
            return bot.send_photo(chat_id=chat_id, photo=photo, caption=caption,
                                  reply_to_message_id=reply_to_message_id, reply_markup=reply_markup,
                                  parse_mode=parse_mode, disable_notification=disable_notification)

    telebot.apihelper.proxy = REQUESTS_PROXY
    srvc_msg = send_message(TELEGRAM_CHANNEL_MON, "Перевыкладываю выдачу прошлой проверки")
    repost_previous_monitor_check(bot)
    edit_message("Получаю обновления тегов", srvc_msg.chat.id, srvc_msg.message_id)
    service = 'dan'
    with session_scope() as session:
        queue = [(queue_item.pic.service, queue_item.pic.post_id) for queue_item in
                 session.query(QueueItem).options(joinedload(QueueItem.pic)).all()]
        history = [(history_item.pic.service, history_item.pic.post_id) for history_item in
                   session.query(HistoryItem).options(joinedload(HistoryItem.pic)).all()]
        tags_total = session.query(Tag).filter_by(service=service).count() if not new_tag else 1
        tags = {item.tag: {'last_check': item.last_check or 0, 'missing_times': item.missing_times or 0} for item in (
            session.query(Tag).filter_by(service=service).order_by(Tag.tag).all() if not new_tag else session.query(
                Tag).filter_by(service=service, tag=new_tag).all())}
    qnh = queue + history
    max_new_posts_per_tag = 20
    tags_api = 'http://' + service_db[service]['posts_api']
    login = service_db[service]['payload']['user']
    api_key = service_db[service]['payload']['api_key']
    # post_api = 'https://' + service_db[service]['post_api']
    new_posts = {}
    proxies = REQUESTS_PROXY
    ses = requests.Session()
    tags_slices = [list(tags.keys())[i:i + 5] for i in range(0, len(tags), 5)]
    for (n, tags_slice) in enumerate(tags_slices, 1):
        tag_aliases = {}
        req = ses.get(tags_api.format('+'.join(
            ['~' + quote(tag) for tag in tags_slice])) + f'+-rating:explicit&login={login}&api_key={api_key}&limit=200',
                      proxies=proxies)
        try:
            posts = req.json()
        except json.decoder.JSONDecodeError as ex:
            util.log_error(ex, kwargs={'tags': tags_slice, 'text': req.text})
            posts = []
        new_post_count = {tag: 0 for tag in tags_slice}
        for post in posts:
            try:
                post_id = post['id']
            except TypeError as ex:
                util.log_error(ex, kwargs=posts)
                o_logger.debug(ex)
                o_logger.debug(posts)
                break
            skip = any(b_tag in post['tag_string'] for b_tag in BANNED_TAGS)
            no_urls = not any([post.get('large_file_url'), post.get('file_url')])
            if skip or no_urls: continue
            if (service, str(post_id)) in qnh or any(item in post['file_ext'] for item in ['webm', 'zip']):
                continue
            if tag_aliases:
                for tag, alias in tag_aliases.items():
                    post['tag_string_artist'].replace(alias, tag)
            try:
                # get particular author tag in case post have multiple
                post_tag = set(post['tag_string_artist'].split()).intersection(set(tags_slice)).pop()
            except KeyError:  # post artist not in  checking slice - means database have artist old alias
                artist_api = 'http://' + service_db[service]['artist_api']
                stop = False
                for artist in post['tag_string_artist'].split():
                    artist_data = ses.get(artist_api.format(artist), proxies=proxies).json()[0]
                    for tag in tags_slice:
                        if tag in artist_data['other_names']:
                            tag_aliases[tag] = artist
                            post_tag = tag
                            stop = True
                            break
                    if stop:
                        break


            if (new_post_count[post_tag] < max_new_posts_per_tag and
                    post_id > tags[post_tag].get('last_check')):
                new_post_count[post_tag] += 1
                new_posts[str(post_id)] = {
                    'authors': ' '.join({f'#{x}' for x in post.get('tag_string_artist').split()}),
                    'chars': ' '.join({f"#{x.split('_(')[0]}" for x in
                                       post.get('tag_string_character').split()}),
                    'copyright': ' '.join({f'#{x}'.replace('_(series)', '') for x in
                                           post['tag_string_copyright'].split()}),
                    'tag': post_tag, 'sample_url': post['file_url'],
                    'file_url': post['large_file_url'], 'file_ext': post['file_ext'],
                    'dimensions': f"{post['image_height']}x{post['image_width']}"}
        if (n % 5) == 0:
            edit_markup(srvc_msg.chat.id, srvc_msg.message_id,
                        reply_markup=markup_templates.gen_status_markup(
                            f"{tag} [{(n*5)}/{tags_total}]",
                            f"Новых постов: {len(new_posts)}"))
        with session_scope() as session:
            for tag in tags_slice:
                if not new_post_count[tag]:
                    tags[tag]['missing_times'] += 1
                    if tags[tag]['missing_times'] > 4:
                        send_message(srvc_msg.chat.id,
                                     f"У тега {tag} нет постов уже после {tags[tag]['missing_times']} проверок",
                                     reply_markup=markup_templates.gen_del_tag_markup(tag))
                else:
                    tags[tag]['missing_times'] = 0
                db_tag = session.query(Tag).filter_by(tag=tag, service=service).first()
                if tag_aliases.get(tag):
                    db_tag.tag = tag_aliases[tag]
                    send_message(srvc_msg.chat.id, f'Тег "{tag}" переименован в "{tag_aliases[tag]}"')
                db_tag.missing_times = tags[tag]['missing_times']
    edit_message("Выкачиваю сэмплы обновлений", srvc_msg.chat.id, srvc_msg.message_id)
    srt_new_posts = sorted(new_posts)
    for (n, post_id) in enumerate(srt_new_posts, 1):
        edit_markup(srvc_msg.chat.id, srvc_msg.message_id,
                    reply_markup=markup_templates.gen_status_markup(
                        f"Новых постов: {len(new_posts)}",
                        f"Обработка поста: {n}/{len(srt_new_posts)}"))
        new_post = new_posts[post_id]
        if new_post['file_url'] or new_post['sample_url']:
            pic_ext = new_post['file_ext']
            pic_name = f"{service}.{post_id}.{pic_ext}"
        else:
            pic_name = ''
        dl_url = grabber.get_less_sized_url(new_post['sample_url'], new_post['file_url'], service=service)
        if grabber.download(dl_url, MONITOR_FOLDER + pic_name):
            new_posts[post_id]['pic_name'] = pic_name
        else:
            new_posts[post_id]['pic_name'] = None
    edit_message("Выкладываю обновления", srvc_msg.chat.id, srvc_msg.message_id)
    for post_id in srt_new_posts:
        new_post = new_posts[post_id]
        if new_post['pic_name']:
            with session_scope() as session:
                pic = session.query(Pic).filter_by(service=service, post_id=post_id).first()
                if not pic:
                    pic = Pic(
                        service=service,
                        post_id=post_id,
                        authors=new_post['authors'],
                        chars=new_post['chars'],
                        copyright=new_post['copyright'])
                    session.add(pic)
                    session.flush()
                    session.refresh(pic)
                mon_msg = send_photo(TELEGRAM_CHANNEL_MON, MONITOR_FOLDER + new_post['pic_name'],
                                         f"#{new_post['tag']} ID: {post_id}\n{new_post['dimensions']}",
                                     reply_markup=markup_templates.gen_rec_new_markup(pic.id, pic.post_id))
                pic.monitor_item = MonitorItem(tele_msg=mon_msg.message_id, pic_name=new_post['pic_name'])
                pic.file_id = mon_msg.photo[0].file_id
                session.query(Tag).filter_by(tag=new_post['tag'],
                                             service=service).first().last_check = int(post_id)
    delete_message(srvc_msg.chat.id, srvc_msg.message_id)


def repost_previous_monitor_check(bot: telebot.TeleBot):
    with session_scope() as session:
        mon_items = session.query(MonitorItem).options(joinedload(MonitorItem.pic)).order_by(MonitorItem.id).all()
        for mon_item in mon_items:
            try:
                bot.delete_message(TELEGRAM_CHANNEL_MON, mon_item.tele_msg)
            except telebot.apihelper.ApiException as exc:
                o_logger.error(exc)
                util.log_error(exc)
            try:
                new_msg = bot.send_photo(TELEGRAM_CHANNEL_MON, photo=mon_item.pic.file_id,
                                         caption=f"{' '.join([f'{author}' for author in mon_item.pic.authors.split()])}\n"
                                                 f"ID: {mon_item.pic.post_id}",
                                         reply_markup=markup_templates.gen_rec_new_markup(mon_item.pic.id,
                                                                                          mon_item.pic.post_id))
            except telebot.apihelper.ApiException as exc:
                o_logger.error(exc)
                util.log_error(exc)
                continue
            mon_item.tele_msg = new_msg.message_id


if __name__ == '__main__':
    o_logger = logging.getLogger('OhaioPosterLogger')
    o_logger.setLevel(logging.DEBUG)
    o_fh = logging.FileHandler(LOG_FILE)
    o_fh.setLevel(logging.DEBUG)
    o_fh.setFormatter(logging.Formatter('%(asctime)s [Monitor] %(levelname)-8s %(message)s'))
    o_ch = logging.StreamHandler()
    o_ch.setFormatter(logging.Formatter('%(asctime)s [Monitor] %(levelname)-8s %(message)s'))
    o_ch.setLevel(logging.DEBUG)
    o_logger.addHandler(o_fh)
    o_logger.addHandler(o_ch)
    check_recommendations()
