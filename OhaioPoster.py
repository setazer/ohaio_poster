# -*- coding: utf-8 -*-
import argparse
import logging
import os
import sys
from datetime import datetime as dt

import pytumblr
import requests
import vk_requests
from PIL import Image, ImageDraw, ImageFont
from aiogram.utils import executor
from sqlalchemy import func

import markups
import util
from bot_mng import send_photo, send_message, dp
from creds import (TELEGRAM_CHANNEL, OWNER_ID,
                   LOG_FILE, QUEUE_FOLDER, QUEUE_LIMIT,
                   VK_TOKEN, VK_GROUP_ID,
                   TUMBLR_CONSUMER_KEY, TUMBLR_CONSUMER_SECRET,
                   TUMBLR_OAUTH_TOKEN, TUMBLR_OAUTH_SECRET, TUMBLR_BLOG_NAME)
from creds import service_db
from db_mng import Pic, QueueItem, HistoryItem, session_scope, Setting, User


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
    api = vk_requests.create_api(service_token=VK_TOKEN, api_version=5.71)
    with session_scope() as session:
        cur_album = session.query(Setting).filter_by(setting='current_album').first()
        num_photos = session.query(Setting).filter_by(setting='num_photos').first()
        if not num_photos:
            num_photos = Setting(setting='num_photos', value="0")
            session.add(num_photos)
        if not cur_album:
            new_album = create_album(api, 1)
            cur_album = Setting(setting='current_album', value=str(new_album['id']))
            session.add(cur_album)
            return str(new_album['id'])
        if int(num_photos.value) < 10000:
            return cur_album.value
        else:

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


def create_album(api, number):
    new_album = api.photos.createAlbum(title=f"Feed #{number:03}", group_id=VK_GROUP_ID,
                                       upload_by_admins_only=1, comments_disabled=1)
    return new_album

def post_to_vk(new_post):
    log = logging.getLogger(f'ohaio.{__name__}')
    if new_post['post_to_vk']:
        try:
            wall_id = post_to_vk_via_api(new_post, gen_msg(new_post))
        except Exception as ex:
            log.error(ex)
            util.log_error(ex)
            wall_id = -1
        else:
            with session_scope() as session:
                last_poster = Setting(setting='last_poster', value=str(new_post['sender']))
                session.merge(last_poster)
    else:
        wall_id = -1
    return wall_id


def post_to_vk_via_api(new_post, msg):
    post_url = 'https://' + service_db[new_post['service']]['post_url'] + new_post['post_id'].split('_p')[0]
    # Авторизация
    post_msg = f"{msg}\nОригинал: {post_url}"
    api = vk_requests.create_api(service_token=VK_TOKEN, api_version=5.71)
    # Загрузка картинки на сервер
    with open(f"{QUEUE_FOLDER}{new_post['pic_name']}", 'rb') as pic:
        current_album = get_current_album()
        upload_url = api.photos.getUploadServer(group_id=VK_GROUP_ID, album_id=current_album)['upload_url']
        img = {'file1': (new_post['pic_name'], pic)}
        response = requests.post(upload_url, files=img)
        result = response.json()
        result['server'] = int(result['server'])
        uploaded_photo = api.photos.save(group_id=VK_GROUP_ID, album_id=current_album, caption=post_url, **result)
        photo_link = 'photo' + str(uploaded_photo[0]['owner_id']) + '_' + str(uploaded_photo[0]['id'])
        wall_id = api.wall.post(message=post_msg, owner_id='-' + VK_GROUP_ID, attachments=(photo_link,))
    with session_scope() as session:
        num_photos = session.query(Setting).filter_by(setting='num_photos').first()
        num_photos.value = str(int(num_photos.value) + 1)
    return wall_id['post_id']


async def post_to_tg(new_post, wall_id):
    photo = new_post.get('file_id', f"{QUEUE_FOLDER}{new_post['pic_name']}")
    await send_photo(chat_id=TELEGRAM_CHANNEL, photo=photo,
                     caption=gen_msg(new_post, True), reply_markup=markups.gen_channel_inline(new_post, wall_id))


async def post_info(new_post):
    await send_message(new_post['sender'],
                       f"ID {new_post['post_id']} ({service_db[new_post['service']]['name']}) опубликован.")
    if new_post['sender'] != OWNER_ID:
        await send_message(OWNER_ID,
                           f"ID {new_post['post_id']} ({service_db[new_post['service']]['name']}) опубликован.")


def post_to_tumblr(new_post):
    post_url = 'https://' + service_db[new_post['service']]['post_url'] + new_post['post_id'].split('_p')[0]
    msg = "Post source: " + post_url
    tags_raw = new_post.get('authors').split() + new_post.get('chars').split() + new_post.get('copyright').split()
    tags = list({tag.replace('_', ' ').replace('#', '') for tag in tags_raw})
    t_api = pytumblr.TumblrRestClient(TUMBLR_CONSUMER_KEY, TUMBLR_CONSUMER_SECRET, TUMBLR_OAUTH_TOKEN,
                                      TUMBLR_OAUTH_SECRET)
    t_api.create_photo(TUMBLR_BLOG_NAME, state='published', tags=tags, data=QUEUE_FOLDER + new_post['pic_name'],
                       caption=msg)


def check_queue(args):
    vk_posting_times = [(55, 60), (0, 5), (25, 35)]
    minute = dt.now().minute
    is_vk_time = args.forced_post or any(time_low <= minute <= time_high for time_low, time_high in vk_posting_times)
    with session_scope() as session:
        post_stats = {sender: count for sender, count in
                      session.query(QueueItem.sender, func.count(QueueItem.sender)).group_by(QueueItem.sender).all()}
        if not post_stats:
            return None
        db_last_poster = session.query(Setting).filter_by(setting='last_poster').first()
        db_users = [user.user_id for user in session.query(User).order_by(User.user_id).all()]  # order is important
        limits = {user.user_id: user.limit for user in session.query(User).order_by(User.user_id).all()}
        last_user = int(db_last_poster.value) if db_last_poster else OWNER_ID
        shifted_users = db_users[db_users.index(last_user):] + db_users[:db_users.index(last_user)]
        # shift users to start from next user for vk
        vk_users = shifted_users[1:] + shifted_users[:1]
        new_poster = None
        if is_vk_time:
            for user in vk_users:
                if post_stats.get(user, 0) > 0:
                    new_poster = user
                    break
        else:  # can stay same if appropriate
            for user in shifted_users:
                if post_stats.get(user, 0) >= limits.get(user, QUEUE_LIMIT):
                    new_poster = user
                    break
            else:
                return None  # don't post if no user exceeds limit
        posts = session.query(QueueItem).filter_by(sender=new_poster).order_by(QueueItem.id).all()
        queue_post = None
        for post in posts:
            if not post.pic.history_item:
                queue_post = {'service': post.pic.service, 'post_id': post.pic.post_id, 'authors': post.pic.authors,
                              'chars': post.pic.chars, 'copyright': post.pic.copyright,
                              'sender': post.sender, 'post_to_vk': is_vk_time}
                if os.path.exists(f"{QUEUE_FOLDER}{post.pic_name}"):
                    queue_post['pic_name'] = post.pic_name
                elif post.pic.file_id:
                    queue_post['file_id'] = post.pic.file_id
                else:  # how this even happened?
                    session.delete(post)
                    continue
                break
            else:
                session.delete(post)
    return queue_post


def add_to_history(new_post, wall_id):
    with session_scope() as session:
        pic = session.query(Pic).filter_by(post_id=new_post['post_id'],
                                           service=new_post['service']).first()
        pic.history_item = HistoryItem(wall_id=wall_id)  # orphaned history_item deletes itself
        pic.queue_item = None  # orphaned queue_item deletes itself


def add_ohaio(original_string):
    return " ".join(map(lambda x: f'{x}@ohaio', original_string.split()))


def gen_msg(post, to_tg=False):
    authors_list = post.get('authors')
    if not to_tg:
        char_list = add_ohaio(post.get('chars', ''))
        cr_list = add_ohaio(post.get('copyright', ''))
    else:
        char_list = post.get('chars', '')
        cr_list = post.get('copyright', '')

    authors = f"Автор(ы): {authors_list}\n" if authors_list else ""
    characters = f"Персонаж(и): {char_list}\n" if char_list else ""
    copyrights = f"Копирайт: {cr_list}" if cr_list else ""

    ret_msg = f"{authors}{characters}{copyrights}" if any((authors, characters, copyrights)) else "#ohaioposter"
    return ret_msg


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--force', dest='forced_post', action='store_true', help='Forced posting')
    parser.add_argument('-d', '--debug', dest='debugging', action='store_true', help='Verbose output')
    args = parser.parse_args()

    log = logging.getLogger(f'ohaio.{__name__}')
    log.setLevel(logging.DEBUG if args.debugging else logging.INFO)
    fh = logging.FileHandler(LOG_FILE)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s [Poster] %(levelname)-8s %(message)s'))
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter('%(asctime)s [Poster] %(levelname)-8s %(message)s'))
    sh.setLevel(logging.DEBUG)
    log.addHandler(fh)
    log.addHandler(sh)

    log.debug('Checking queue for new posts')
    new_post = check_queue(args)
    if not new_post:
        log.debug('No posts in queue')
        sys.exit()
    log.debug('Queue have posts')
    log.debug(f"Posting {service_db[new_post['service']]['name']}:{new_post['post_id']} to VK")
    wall_id = post_to_vk(new_post)
    log.debug('Adding to history')
    add_to_history(new_post, wall_id)
    log.debug('Posting to Telegram')
    await post_to_tg(new_post, wall_id)
    log.debug('Posting to Tumblr')
    try:
        post_to_tumblr(new_post)
    except Exception as ex:
        log.error(ex)
        util.log_error(ex)
    if new_post.get('pic_name'):
        os.remove(QUEUE_FOLDER + new_post['pic_name'])
    await post_info(new_post)
    log.debug('Posting finished')
    update_header()


if __name__ == '__main__':
    executor.start(dp, main())
