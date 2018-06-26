# -*- coding: utf-8 -*-
import math
import os
import re
import time
import traceback

import pytumblr
import requests
import vk_requests
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import and_

from creds import *
from db_mng import Tag, Pic, QueueItem, MonitorItem, Setting, session_scope


def log_error(exception, args=[], kwargs={}):
    with open(ERROR_LOGS_DIR + time.strftime('%Y%m%d_%H%M%S') + ".txt", 'a') as err_file:
        if args:
            err_file.write("ARGS: " + str(args) + "\n")
        if kwargs:
            err_file.write("KEYWORD ARGS:\n")
            for key in kwargs:
                err_file.write(str(key) + " : " + str(kwargs[key]) + "\n")
        err_file.write(f'{exception}\n\n'.upper())
        traceback.print_exc(file=err_file)


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


# def refill_history():
#     with session_scope() as session:
#         api = vk_requests.create_api(APP_ID, VK_LOGIN, VK_PASS, scope=['wall', 'photos'], v=5.62)
#         postsnum = api.wall.get(owner_id="-" + GROUP_ID)['count']
#         max_queries = (postsnum - 1) // 100
#         post_history = {}
#         for querynum in range(max_queries + 1):
#             posts = api.wall.get(owner_id="-" + GROUP_ID, offset=querynum * 100, count=100)['items']
#             for post in posts:
#                 if contains(service_db, lambda x: service_db[x]['post_url'] in post['text']):
#                     links = post['text'].split()
#                     for link in links:
#                         if contains(service_db, lambda x: service_db[x]['post_url'] in link):
#                             service = list_entry(service_db, lambda x: service_db[x]['post_url'] in link)
#                             offset = link.find(service_db[service]['post_url'])
#                             post_n = link[len(service_db[service]['post_url']) + offset:].strip()
#                             if post_n.isdigit() and not (service, post_n) in post_history:
#                                 post_history[(service, post_n)] = post['id']
#                                 new_pic = Pic(post_id=post_n, service=service)
#                                 new_pic.history_item = HistoryItem(wall_id=post['id'])
#                                 session.add(new_pic)
#
#                 if post.get('attachments'):
#                     for att in post['attachments']:
#                         if att['type'] == 'link':
#                             if contains(service_db, lambda x: service_db[x]['post_url'] in att['link']['url']):
#                                 linkstr = list(att['link']['url'].split('http')[1:])
#                                 for post_str in linkstr:
#                                     service = list_entry(service_db, lambda x: service_db[x]['post_url'] in post_str)
#                                     offset = post_str.find(service_db[service]['post_url'])
#                                     post_n = post_str[len(service_db[service]['post_url']) + offset:].strip()
#                                     if post_n.isdigit() and not (service, post_n) in post_history:
#                                         post_history[(service, post_n)] = post['id']
#                                         pg_post_history = HistoryItem(service=service, post_id=post_n,
#                                                                       wall_id=post['id'])
#                                         session.add(pg_post_history)
#             time.sleep(0.4)
#         print(list(post_history.keys()))
#         last_re_post = api.wall.search(owner_id="-" + GROUP_ID, query='post', count=1)
#         last_repost = last_re_post['items'][0]['id']
#         rep_count = last_re_post['count']
#         session.merge(Setting(setting='last_repost',value=last_repost))
#         session.merge(Setting(setting='rep_count',value=rep_count))

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


def sync_num_photos():
    with session_scope() as session:
        cur_album = session.query(Setting).filter_by(setting='current_album').first()
        num_photos = session.query(Setting).filter_by(setting='num_photos').first()
        api = vk_requests.create_api(service_token=VK_TOKEN, api_version=5.71)
        albums = api.photos.getAlbums(owner_id='-' + VK_GROUP_ID, album_ids=(int(cur_album.value),))['items']
        latest_album = albums[0]
        num_photos.value = str(latest_album['size'])


def get_last_posts_ids(service):
    service_payload = service_db[service]['payload']
    service_login = 'http://' + service_db[service]['login_url']
    tags_api = 'http://' + service_db[service]['posts_api']
    proxies = REQUESTS_PROXY
    with session_scope() as session, requests.Session() as ses:
        ses.post(service_login, data=service_payload)
        i = 1
        total = session.query(Tag).filter_by(service=service).count()
        for tag in session.query(Tag).filter_by(service=service).order_by(Tag.tag).all():
            response = ses.get(tags_api.format(tag.tag) + '+-rating:explicit&limit=1', proxies=proxies)
            try:
                time.sleep(0.05)
                post = response.json()[0]['id']
                print("{i}/{total}", tag.tag)
            except Exception:
                session.delete(tag)
                continue
            else:
                tag.last_check = int(post)
            finally:
                i += 1


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
    pat = re.compile(r'[\w()-]*$')
    return pat.match(name)


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


def requeue():
    with session_scope() as session:
        for entry in os.listdir(QUEUE_FOLDER):
            if os.path.isfile(QUEUE_FOLDER + entry):
                (name, ext) = os.path.splitext(entry)
                if ext in ['.jpg', '.jpeg', '.png', '.gif']:
                    try:
                        (service, post_id) = name.split('.')
                    except ValueError:
                        continue
                pic = session.query(Pic).filter(and_(Pic.service == service, Pic.post_id == post_id)).first()
                pic.queue_item = QueueItem(sender=OWNER_ROOM_ID, pic_name=entry)
                session.merge(pic)
        print(session.query(QueueItem).count())


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
