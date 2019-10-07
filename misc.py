import os
import time

import requests
import vk_requests
from sqlalchemy import and_

import grabber
from aiobot import send_message, edit_markup
from creds import VK_TOKEN, VK_GROUP_ID, service_db, REQUESTS_PROXY, QUEUE_FOLDER, OWNER_ID, TELEGRAM_CHANNEL_MON
from db_mng import session_scope, Setting, Tag, Pic, QueueItem, HistoryItem, User
from markups import gen_status_markup


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


def fill_hashes():
    with session_scope() as session:
        pics = session.query(Pic).filter_by(service='dan').all()
        pics_total = len(pics)
        h_msg = send_message(TELEGRAM_CHANNEL_MON, "Rebuilding hashes")
        for i, pic_item in enumerate(pics):
            if not pic_item.hash:
                try:
                    pic_name, direct, *__ = grabber.metadata(pic_item.service, pic_item.post_id)
                except Exception as ex:
                    send_message(OWNER_ID, str(ex)[:3000])
                    direct = None
                if direct and pic_name:
                    try:
                        pic_hash = grabber.download(direct, pic_name)
                    except Exception as ex:
                        send_message(OWNER_ID, str(ex)[:3000])
                        pic_hash = None
                    if pic_hash:
                        pic_item.hash = pic_hash
                        session.commit()
                        os.remove(pic_name)
                    edit_markup(h_msg.chat.id, h_msg.message_id,
                                reply_markup=gen_status_markup(f"{pic_item.service}: {pic_item.post_id}",
                                                  f"{i}/{pics_total}"))


def dump_db():
    sep_line = "@@@@@@@@@@\n"
    with session_scope() as session, open('dump.db', 'w') as db:
        h_items = session.query(HistoryItem).all()
        q_items = session.query(QueueItem).order_by(QueueItem.id).all()
        users = session.query(User).all()
        pics = session.query(Pic).all()
        settings = session.query(Setting).all()
        tags = session.query(Tag).all()
        for item in pics:
            line = f"{item.id}###{item.service}###{item.post_id}###{item.authors}###{item.chars}###{item.copyright}\n"
            db.write(line)
        db.write(sep_line)
        for item in h_items:
            line = f"{item.pic_id}###{item.wall_id}\n"
            db.write(line)
        db.write(sep_line)
        for item in q_items:
            line = f"{item.pic_id}###{item.sender}###{item.pic_name}\n"
            db.write(line)
        db.write(sep_line)
        for item in users:
            line = f"{item.user_id}###{item.access}\n"
            db.write(line)
        db.write(sep_line)
        for item in settings:
            line = f"{item.setting}###{item.value}\n"
            db.write(line)
        db.write(sep_line)
        for item in tags:
            line = f"{item.service}###{item.tag}###{item.last_check}###{item.missing_times}\n"
            db.write(line)
        print('Dump complete')


def load_db():
    sep_line = "@@@@@@@@@@\n"
    with session_scope() as session, open('dump.db', 'r') as db:
        pics = {}
        for line in db:
            if line == sep_line:
                break
            item = line[:-1].split('###')
            pics[item[0]] = Pic(service=item[1], post_id=item[2], authors=item[3] if item[3] != 'None' else None,
                                chars=item[4] if item[4] != 'None' else None,
                                copyright=item[5] if item[5] != 'None' else None)
        for line in db:
            if line == sep_line:
                break
            item = line[:-1].split('###')
            pic = pics[item[0]]
            pic.history_item = HistoryItem(wall_id=item[1])
        for line in db:
            if line == sep_line:
                break
            item = line[:-1].split('###')
            pic = pics[item[0]]
            pic.queue_item = QueueItem(sender=item[1], pic_name=item[2])

        for pic in pics.values():
            session.add(pic)

        for line in db:
            if line == sep_line:
                break
            item = line[:-1].split('###')
            user = User(user_id=item[0], access=item[1])
            session.add(user)
        for line in db:
            if line == sep_line:
                break
            item = line[:-1].split('###')
            setting = Setting(setting=item[0], value=item[1])
            session.add(setting)
        for line in db:
            item = line[:-1].split('###')
            tag = Tag(service=item[0], tag=item[1], last_check=item[2], missing_times=item[3])
            session.add(tag)
