# -*- coding: utf-8 -*-
import logging
import markup_templates
import os
import requests
import telebot
import time
import util
from functools import wraps

from sqlalchemy.orm import joinedload

from creds import LOG_FILE, TELEGRAM_TOKEN, TELEGRAM_CHANNEL_MON, service_db, BANNED_TAGS, TELEGRAM_PROXY, \
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
            except telebot.apihelper.ApiException as exc:
                o_logger.error(exc)
                util.log_error(exc)
                break
            except Exception as exc:
                o_logger.error(exc)
                util.log_error(exc)
                time.sleep(err_wait[min(i, 3)])
            else:
                break
        return retval
    return wrapper

def download(sample_url, file_url, filename):
    if not sample_url and not file_url:
        return
    rep_subdomains = ["assets.","assets2.","simg3.","simg4."]
    for subdomain in rep_subdomains:
        sample_url = sample_url.replace(subdomain, '')
        file_url = file_url.replace(subdomain, '')
    if sample_url.startswith('//'):
        sample_url = 'https:' + sample_url
    if file_url.startswith('//'):
        file_url = 'https:' + file_url
    if filename.startswith('dan'):
        proxies = {
            'http': "proxy.antizapret.prostovpn.org:3128",
            'https': "proxy.antizapret.prostovpn.org:3128",
            #'https': "proxy.antizapret.prostovpn.org:3143",
        }

        if sample_url.startswith('/'):
            sample_url= "https://" + service_db['dan']['base_url'] + sample_url
        if file_url.startswith('/'):
            file_url = "https://" + service_db['dan']['base_url'] + file_url
    else:
        proxies = {}
    headers = {'user-agent': 'OhaioPoster',
                   'content-type': 'application/json; charset=utf-8'}
    if sample_url==file_url:
        try:
            dl_req = requests.get(sample_url, stream=True, proxies=proxies, headers=headers)
        except requests.exceptions.RequestException as ex:
            util.log_error(ex)
            o_logger.debug(ex)
            return False
    else:
        try:
            s_req = requests.get(sample_url, stream=True, proxies=proxies, headers=headers)
        except requests.exceptions.RequestException as ex:
            util.log_error(ex)
            o_logger.debug(ex)
            s_req = None

        try:
            f_req = requests.get(file_url, stream=True, proxies=proxies,headers=headers)
        except requests.exceptions.RequestException as ex:
            util.log_error(ex)
            o_logger.debug(ex)
            f_req = None
        if not any([s_req,f_req]):
            return False
        if all([s_req,f_req]):
            s_len = int(s_req.headers.get('content-length', 0))
            f_len = int(f_req.headers.get('content-length',0))
            if all([s_len,f_len]):
                if min(f_len,s_len) ==  s_len:
                    dl_req= s_req
                else:
                    dl_req = f_req
        elif s_req:
            dl_req=s_req
        elif f_req:
            dl_req = f_req
        else:
            return False
    total_length = int(dl_req.headers.get('content-length',0))
    if not total_length:
        return False
    if os.path.exists(filename) and os.path.getsize(filename) == total_length:
        return True
    with open(MONITOR_FOLDER + filename, 'wb') as f:
        for chunk in dl_req.iter_content(1024):
            f.write(chunk)
    return True

def main(log):
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
    @bot_action
    def send_message(*args, **kwargs):
        return bot.send_message(*args, **kwargs)

    @bot_action
    def edit_message(*args, **kwargs):
        return bot.edit_message_text(*args, **kwargs)

    @bot_action
    def edit_markup(*args, **kwargs):
        return bot.edit_message_reply_markup(*args, **kwargs)

    @bot_action
    def delete_message(*args, **kwargs):
        return bot.delete_message(*args, **kwargs)

    @bot_action
    def send_photo(*args, **kwargs):
        return bot.send_photo(*args, **kwargs)

    telebot.apihelper.proxy = TELEGRAM_PROXY
    srvc_msg = send_message(TELEGRAM_CHANNEL_MON, "Получаю обновления тегов")
    service = 'dan'
    with session_scope() as session:
        pic = None
        service_payload = service_db[service]['payload']
        service_login = 'http://' + service_db[service]['login_url']
        tags_api = 'http://' + service_db[service]['posts_api']
        # post_api = 'https://' + service_db[service]['post_api']
        new_posts = {}
        proxies = TELEGRAM_PROXY
        with requests.Session() as ses:
            ses.post(service_login, data=service_payload)
        queue = [(queue_item.pic.service, queue_item.pic.post_id) for queue_item in
                 session.query(QueueItem).options(joinedload(QueueItem.pic)).all()]
        history = [(history_item.pic.service, history_item.pic.post_id) for history_item in
                   session.query(HistoryItem).options(joinedload(HistoryItem.pic)).all()]
        tags_total = session.query(Tag).filter_by(service=service).count()
        #tags_total = 1
        tags = session.query(Tag).filter_by(service=service).order_by(Tag.tag).all()
        #tags = [Tag(tag='amekaze_yukinatsu',last_check=0,missing_times=0)]
        for (n, tag) in enumerate(tags, 1):
            last_id = tag.last_check
            tag.missing_times = tag.missing_times if tag.missing_times else 0
            req = ses.get(tags_api.format(tag.tag) + '+-rating:explicit&limit=20', proxies=proxies)
            posts = req.json()
            if not posts:
                tag.missing_times += 1
                if tag.missing_times > 4:
                    send_message(srvc_msg.chat.id,
                                     f"У тега {tag.tag} нет постов уже после {tag.missing_times} проверок",
                                     reply_markup=markup_templates.gen_del_tag_markup(tag.tag))
                continue
            else:
                tag.missing_times = 0
            qnh = queue + history
            for post in posts:
                try:
                    post_id = post['id']
                except TypeError as ex:
                    util.log_error(ex)
                    o_logger.debug(ex)
                    o_logger.debug(posts)
                    break
                skip = False
                for b_tag in BANNED_TAGS:
                    if b_tag in post.get('tag_string'):
                        skip = True
                        break
                if skip: continue
                if (service, str(post_id)) in qnh or '.webm' in post.get('file_url','') or '.webm' in post.get('large_file_url',''):
                    continue
                if post_id > last_id:
                    pic_item = session.query(Pic).filter_by(service=service,post_id=str(post_id)).first()
                    if pic_item:
                        pic = {'item':pic_item,'new':False}
                    else:
                        pic = {'item':Pic(service=service,post_id=post_id,
                                   authors=' '.join({f'#{x}' for x in post.get('tag_string_artist').split()}),
                                   chars = ' '.join({f"#{x.split('_(')[0]}" for x in
                          post.get('tag_string_character').split()}),copyright=' '.join({f'#{x}'.replace('_(series)', '') for x in
                                                        post.get('tag_string_copyright').split()})),'new':True}
                    new_posts[post_id] = {'tag': tag.tag, 'sample_url': post.get('file_url'), 'file_url': post.get('large_file_url'),
                                          'dimensions': f"{post['image_height']}x{post['image_width']}"
                        ,'pic':pic}
            else:
                tag.last_check = int(posts[0]['id'])
            if (n % 5) == 0:
                edit_markup(srvc_msg.chat.id, srvc_msg.message_id,
                                              reply_markup=markup_templates.gen_status_markup(
                                                  f"{tag.tag} [{n}/{tags_total}]",
                                                  f"Новых постов: {len(new_posts)}"))
        edit_message("Выкачиваю сэмплы обновлений", srvc_msg.chat.id, srvc_msg.message_id)
        srt_new_posts = sorted(new_posts)
        for (n, post_id) in enumerate(srt_new_posts, 1):
            edit_markup(srvc_msg.chat.id, srvc_msg.message_id,
                                          reply_markup=markup_templates.gen_status_markup(
                                              f"Новых постов: {len(new_posts)}",
                                              f"Обработка поста: {n}/{len(srt_new_posts)}"))
            new_post = new_posts[post_id]
            if (new_post['file_url'] or new_post['sample_url']):
                _, pic_ext = os.path.splitext(new_post['file_url'])
                pic_name = f"{service}.{post_id}{pic_ext}"
            else:
                pic_name = ''
            if download(new_post['sample_url'],new_post['file_url'], pic_name):
                new_posts[post_id]['pic_name'] = pic_name
            else:
                new_posts[post_id]['pic_name'] = None
        edit_message("Выкладываю обновления", srvc_msg.chat.id, srvc_msg.message_id)
        for post_id in srt_new_posts:
            new_post = new_posts[post_id]
            if new_post['pic_name']:
                pic = new_post['pic']['item']
                if new_post['pic']['new']:
                    session.add(pic)
                    session.flush()
                    session.refresh(pic)
                with open(MONITOR_FOLDER + new_post['pic_name'], 'rb') as picture:
                    mon_msg = send_photo(TELEGRAM_CHANNEL_MON, picture,
                                   f"#{new_post['tag']} ID: {post_id}\n{new_post['dimensions']}'",
                                   reply_markup=markup_templates.gen_rec_new_markup(pic.id,pic.post_id))
                pic.monitor_item = MonitorItem(tele_msg=mon_msg.message_id, pic_name=new_post['pic_name'])
                session.merge(pic)
        bot.delete_message(srvc_msg.chat.id, srvc_msg.message_id)


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
    main(o_logger)
