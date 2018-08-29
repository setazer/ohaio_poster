import os
import time

import requests
import vk_requests
from sqlalchemy import and_

from creds import VK_TOKEN, VK_GROUP_ID, service_db, REQUESTS_PROXY, QUEUE_FOLDER, OWNER_ID
from db_mng import session_scope, Setting, Tag, Pic, QueueItem


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
                print(f"{i}/{total}", tag.tag)
            except Exception:
                session.delete(tag)
                continue
            else:
                tag.last_check = int(post)
            finally:
                i += 1


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
                pic.queue_item = QueueItem(sender=OWNER_ID, pic_name=entry)
                session.merge(pic)
        print(session.query(QueueItem).count())
