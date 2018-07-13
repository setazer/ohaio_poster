# -*- coding: utf-8 -*-
import argparse
import datetime
import logging
import os

import pytumblr
import requests
import telebot
import vk_requests
from PIL import Image, ImageDraw, ImageFont

import markup_templates
import util
from bot_mng import send_photo, send_message
from creds import TELEGRAM_CHANNEL, OWNER_ROOM_ID, LOG_FILE, REQUESTS_PROXY, QUEUE_FOLDER, QUEUE_LIMIT, VK_TOKEN, \
    VK_GROUP_ID, TUMBLR_CONSUMER_KEY, TUMBLR_CONSUMER_SECRET, TUMBLR_OAUTH_TOKEN, TUMBLR_OAUTH_SECRET, TUMBLR_BLOG_NAME
from creds import service_db
from db_mng import Pic, QueueItem, HistoryItem, session_scope, Setting


def update_header():
    with session_scope() as session:
        queue_num = session.query(QueueItem).count()
    # api = vk_requests.create_api(APP_ID, VK_LOGIN, VK_PASS, scope=['wall', 'photos'], v=5.62)
    # api = vk_requests.create_api(access_token=VK_TOKEN, v=5.62)
    api = vk_requests.create_api(service_token=VK_TOKEN, api_version=5.71)
    img = Image.open('header.png')
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype("VISITOR_RUS.TTF", 10)
    draw.text((3, img.height - 12), f"Пикч в очереди: {queue_num}", (255, 255, 255), font=font)
    img.save('cur_header.png')
    with open('cur_header.png', 'rb') as pic:
        upload_url = api.photos.getOwnerCoverPhotoUploadServer(group_id=VK_GROUP_ID, crop_x2=795, crop_y2=200)[
            'upload_url']
        img = {'photo': ('cur_header.jpg', pic)}
        response = requests.post(upload_url, files=img)
        result = response.json()
        api.photos.saveOwnerCoverPhoto(**result)


def get_current_album():
    with session_scope() as session:
        cur_album = session.query(Setting).filter_by(setting='current_album').first()
        num_photos = session.query(Setting).filter_by(setting='num_photos').first()
        if int(num_photos.value) < 10000:
            return cur_album.value
        elif num_photos == '10000':
            api = vk_requests.create_api(service_token=VK_TOKEN, api_version=5.71)
            albums = api.photos.getAlbums(owner_id='-' + VK_GROUP_ID, album_ids=(int(cur_album.value),))['items']
            # latest_album = [id for id in sorted(albums, key=lambda k: k['updated'], reverse=True)][0]
            latest_album = albums[0]
            if latest_album['size'] < 10000:
                num_photos.value = str(latest_album['size'])
                return cur_album.value

            next_number = int(latest_album['title'].replace("Feed #", "")) + 1
            prev_album = session.query(Setting).filter_by(setting='previous_album').first()
            new_album = api.photos.createAlbum(title=f"Feed #{next_number:03}", group_id=VK_GROUP_ID,
                                               upload_by_admins_only=1, comments_disabled=1)
            prev_album.value = cur_album.value
            cur_album.value = str(new_album['id'])
            num_photos.value = '0'
            return str(new_album['id'])


def post_picture(new_post, msg='#ohaioposter'):
    post_url = 'http://' + service_db[new_post['service']]['post_url'] + new_post['post_id']
    # Авторизация
    msg += "\nОригинал: " + post_url
    api = vk_requests.create_api(service_token=VK_TOKEN, api_version=5.71)
    # Загрузка картинки на сервер
    with open(QUEUE_FOLDER + new_post['pic_name'], 'rb') as pic:
        current_album = get_current_album()
        upload_url = api.photos.getUploadServer(group_id=VK_GROUP_ID, album_id=current_album)['upload_url']
        img = {'file1': (new_post['pic_name'], pic)}
        response = requests.post(upload_url, files=img)
        result = response.json()
        result['server'] = int(result['server'])
        uploaded_photo = api.photos.save(group_id=VK_GROUP_ID, album_id=current_album, caption=post_url, **result)
        photo_link = 'photo' + str(uploaded_photo[0]['owner_id']) + '_' + str(uploaded_photo[0]['id'])
        wall_id = api.wall.post(message=msg, owner_id='-' + VK_GROUP_ID, attachments=(photo_link,))
    with session_scope() as session:
        num_photos = session.query(Setting).filter_by(setting='num_photos').first()
        num_photos.value = str(int(num_photos.value) + 1)
    return wall_id['post_id']


def post_to_tumblr(new_post):
    post_url = 'http://' + service_db[new_post['service']]['post_url'] + new_post['post_id']
    msg = "Оригинал: " + post_url
    tags_raw = new_post.get('authors').split() + new_post.get('chars').split() + new_post.get('copyright').split()
    tags = list({tag.replace('_', ' ').replace('#', '') for tag in tags_raw})
    t_api = pytumblr.TumblrRestClient(TUMBLR_CONSUMER_KEY, TUMBLR_CONSUMER_SECRET, TUMBLR_OAUTH_TOKEN,
                                      TUMBLR_OAUTH_SECRET)
    t_api.create_photo(TUMBLR_BLOG_NAME, state='published', tags=tags, data=QUEUE_FOLDER + new_post['pic_name'],
                       caption=msg)


def check_queue():
    with session_scope() as session:
        posts = session.query(QueueItem).order_by(QueueItem.id).all()
        new_post = None
        for post in posts:
            if os.path.exists(QUEUE_FOLDER + post.pic_name) and not post.pic.history_item:
                new_post = {'service': post.pic.service, 'post_id': post.pic.post_id, 'authors': post.pic.authors,
                            'chars': post.pic.chars, 'copyright': post.pic.copyright, 'pic_name': post.pic_name,
                            'sender': post.sender}
                break
            else:
                session.delete(post)
    return new_post


def add_to_history(new_post, wall_id):
    with session_scope() as session:
        pic = session.query(Pic).filter_by(post_id=new_post['post_id'],
                                           service=new_post['service']).first()
        if pic.history_item:
            session.delete(pic.history_item)
            session.flush()
            session.refresh(pic)
        pic.history_item = HistoryItem(wall_id=wall_id)
        session.delete(pic.queue_item)
        session.merge(pic)


def main(log):
    telebot.apihelper.proxy = REQUESTS_PROXY
    vk_posting_times = [(55, 60), (0, 5), (25, 35)]

    log.debug('Checking queue for new posts')
    new_post = check_queue()
    if not new_post:
        log.debug('No posts in queue')
        return
    log.debug('Queue have posts')
    msg = ''
    tel_msg = ''
    if new_post.get('authors'):
        msg += "Автор(ы): " + new_post['authors'] + "\n"
        tel_msg += "Автор(ы): " + new_post['authors'] + "\n"
    if new_post.get('chars'):
        msg += "Персонаж(и): " + " ".join([x + "@ohaio" for x in new_post['chars'].split()]) + '\n'
        tel_msg += "Персонаж(и): " + new_post['chars'] + '\n'
    if new_post.get('copyright'):
        msg += "Копирайт: " + " ".join([x + "@ohaio" for x in new_post['copyright'].split()])
        tel_msg += "Копирайт: " + new_post['copyright']
    if not msg:
        msg = "#ohaioposter"
    log.debug(f"Posting {service_db[new_post['service']]['name']}:{new_post['post_id']} to VK")
    with session_scope() as session:
        pic = session.query(Pic).filter_by(service=new_post['service'],
                                           post_id=new_post['post_id']).first()
        queue_len = session.query(QueueItem).count()
        file_id = pic.file_id
        minute = datetime.datetime.now().minute
        if args.forced_post or any(time_low <= minute <= time_high for time_low, time_high in vk_posting_times):
            try:
                wall_id = post_picture(new_post, msg)
            except Exception as ex:
                o_logger.error(ex)
                util.log_error(ex)
                wall_id = -1
        elif queue_len > QUEUE_LIMIT:
            wall_id = -1
        else:
            return
    log.debug('Adding to history')
    add_to_history(new_post, wall_id)
    log.debug('Posting to Telegram')
    if file_id:
        send_photo(chat_id=TELEGRAM_CHANNEL, photo_filename=file_id, caption=tel_msg,
                   reply_markup=markup_templates.gen_channel_inline(new_post, wall_id))
    else:
        send_photo(chat_id=TELEGRAM_CHANNEL, photo_filename=QUEUE_FOLDER + new_post['pic_name'], caption=tel_msg,
                   reply_markup=markup_templates.gen_channel_inline(new_post, wall_id))
    try:
        post_to_tumblr(new_post)
    except Exception as ex:
        o_logger.error(ex)
        util.log_error(ex)
    os.remove(QUEUE_FOLDER + new_post['pic_name'])
    send_message(new_post['sender'],
                     f"ID {new_post['post_id']} ({service_db[new_post['service']]['name']}) опубликован.")
    if new_post['sender'] != OWNER_ROOM_ID:
        send_message(OWNER_ROOM_ID,
                         f"ID {new_post['post_id']} ({service_db[new_post['service']]['name']}) опубликован.")
    log.debug('Posting finished')
    update_header()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--force', dest='forced_post', action='store_true', help='Forced posting')
    parser.add_argument('-d', '--debug', dest='debugging', action='store_true', help='Verbose output')
    args = parser.parse_args()

    o_logger = logging.getLogger('OhaioPosterLogger')
    o_logger.setLevel(logging.DEBUG if args.debugging else logging.INFO)
    o_fh = logging.FileHandler(LOG_FILE)
    o_fh.setLevel(logging.DEBUG)
    o_fh.setFormatter(logging.Formatter('%(asctime)s [Poster] %(levelname)-8s %(message)s'))
    o_ch = logging.StreamHandler()
    o_ch.setFormatter(logging.Formatter('%(asctime)s [Poster] %(levelname)-8s %(message)s'))
    o_ch.setLevel(logging.DEBUG)
    o_logger.addHandler(o_fh)
    o_logger.addHandler(o_ch)
    main(o_logger)
