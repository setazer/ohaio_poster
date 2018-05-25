# -*- coding: utf-8 -*-
import argparse
import datetime
import logging
import os

import telebot

import markup_templates
import util
from creds import TELEGRAM_TOKEN, TELEGRAM_CHANNEL, OWNER_ROOM_ID, LOG_FILE, TELEGRAM_PROXY, QUEUE_FOLDER
from creds import service_db
from db_mng import Pic, QueueItem, HistoryItem, session_scope


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
    telebot.apihelper.proxy = TELEGRAM_PROXY
    vk_posting_times = [(55, 60), (0, 5), (25, 35)]
    bot = telebot.TeleBot(TELEGRAM_TOKEN)
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
                wall_id = util.post_picture(new_post, msg)
            except Exception as ex:
                o_logger.error(ex)
                util.log_error(ex)
                wall_id = -1
        elif queue_len > 144:
            wall_id = -1
        else:
            return
    log.debug('Adding to history')
    add_to_history(new_post, wall_id)
    log.debug('Posting to Telegram')
    if file_id:
        try:
            bot.send_photo(chat_id=TELEGRAM_CHANNEL, photo=file_id, caption=tel_msg,
                           reply_markup=markup_templates.gen_channel_inline(new_post, wall_id))
        except Exception as ex:
            o_logger.error(ex)
            util.log_error(ex)
    else:
        with open(QUEUE_FOLDER + new_post['pic_name'], 'rb') as pic_file:
            try:
                bot.send_photo(chat_id=TELEGRAM_CHANNEL, photo=pic_file, caption=tel_msg,
                               reply_markup=markup_templates.gen_channel_inline(new_post, wall_id))
            except Exception as ex:
                o_logger.error(ex)
                util.log_error(ex)
    try:
        util.post_to_tumblr(new_post)
    except Exception as ex:
        o_logger.error(ex)
        util.log_error(ex)
    os.remove(QUEUE_FOLDER + new_post['pic_name'])
    bot.send_message(new_post['sender'],
                     f"ID {new_post['post_id']} ({service_db[new_post['service']]['name']}) опубликован.")
    if new_post['sender'] != OWNER_ROOM_ID:
        bot.send_message(OWNER_ROOM_ID,
                         f"ID {new_post['post_id']} ({service_db[new_post['service']]['name']}) опубликован.")
    log.debug('Posting finished')
    util.update_header()


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
