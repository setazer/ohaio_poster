# -*- coding: utf-8 -*-
import logging
import os
from collections import namedtuple
from contextlib import contextmanager
from functools import wraps

import sqlalchemy
from sqlalchemy import (Column, Integer, String, Boolean, Sequence, UniqueConstraint, PrimaryKeyConstraint, ForeignKey,
                        or_, create_engine, func)
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import sessionmaker, relationship, joinedload

import markups
import util
from aiobot import bot
from creds import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME, OWNER_ID
from creds_template import MONITOR_FOLDER, QUEUE_FOLDER, QUEUE_LIMIT, service_db, TELEGRAM_CHANNEL_MON
from util import ignored

Base = declarative_base()


def print_table_row(instance):
    mapper = inspect(instance)
    class_name = mapper.class_.__name__
    columns = ', '.join(f"{attr.key}='{getattr(instance, attr.key)}'" for attr in mapper.attrs)
    return f"<{class_name}({columns})>"


class User(Base):
    __tablename__ = 'users'
    user_id = Column(Integer, primary_key=True)
    access = Column(Integer)
    limit = Column(Integer)

    def __repr__(self):
        return print_table_row(self)


class Tag(Base):
    __tablename__ = 'tags'
    service = Column(String(15), nullable=False)
    tag = Column(String(50), nullable=False)
    last_check = Column(Integer)
    missing_times = Column(Integer)
    __table_args__ = (PrimaryKeyConstraint('service', 'tag', name='tag_pkey'),)

    def __repr__(self):
        return print_table_row(self)


class Pic(Base):
    __tablename__ = 'pics'
    id = Column(Integer, Sequence('pics_id_seq'), primary_key=True)
    service = Column(String(15), nullable=False)
    post_id = Column(String(15), nullable=False)
    file_id = Column(String(80))
    hash = Column(String(64))
    authors = Column(String(300))
    chars = Column(String(300))
    copyright = Column(String(300))
    queue_item = relationship("QueueItem", uselist=False, back_populates="pic", cascade="all, delete-orphan")
    history_item = relationship("HistoryItem", uselist=False, back_populates="pic", cascade="all, delete-orphan")
    monitor_item = relationship("MonitorItem", uselist=False, back_populates="pic", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint('service', 'post_id', name='pics_service_post_id_key'),)

    def __repr__(self):
        return print_table_row(self)


class Setting(Base):
    __tablename__ = 'settings'
    setting = Column(String(30), primary_key=True)
    value = Column(String(30), nullable=False)

    def __repr__(self):
        return print_table_row(self)


class QueueItem(Base):
    __tablename__ = 'queue'
    id = Column(Integer, Sequence('queue_id_seq'), primary_key=True)
    sender = Column(Integer, nullable=False)
    pic_id = Column(Integer, ForeignKey('pics.id'))
    pic = relationship("Pic", back_populates="queue_item")
    # service = Column(String(15), nullable=False)
    # post_id = Column(String(15), nullable=False)
    pic_name = Column(String(30))

    #  authors = Column(String(300))
    #  chars = Column(String)
    #  copyright = Column(String)
    # __table_args__ = (UniqueConstraint('service', 'post_id', name='queue_service_post_id_key'),)

    def __repr__(self):
        return print_table_row(self)


class MonitorItem(Base):
    __tablename__ = 'monitor'
    id = Column(Integer, Sequence('monitor_id_seq'), primary_key=True)
    pic_id = Column(Integer, ForeignKey('pics.id'))
    pic = relationship("Pic", back_populates="monitor_item")
    tele_msg = Column(Integer, nullable=False)
    pic_name = Column(String(30))
    to_del = Column(Boolean)

    def __repr__(self):
        return print_table_row(self)


class HistoryItem(Base):
    __tablename__ = 'history'
    # service = Column(String(15), nullable=False)
    # post_id = Column(String(15), nullable=False)
    id = Column(Integer, Sequence('history_id_seq'), primary_key=True)
    pic_id = Column(Integer, ForeignKey('pics.id'))
    pic = relationship("Pic", back_populates="history_item")
    wall_id = Column(Integer)

    # __table_args__ = (PrimaryKeyConstraint('service', 'post_id', name='history_pkey'),)

    def __repr__(self):
        return print_table_row(self)


# logging.basicConfig()
# logging.getLogger('sqlalchemy.engine').setLevel(logging.INFO)
# conn_string = "postgresql://{user}:{password}@{host}:{port}/{db}".format(user=DB_USER, password=DB_PASSWORD,
#                                                                          host=DB_HOST,
#                                                                          port=DB_PORT, db=DB_NAME)
db_log = logging.getLogger('ohaio.db')

try:
    conn_string = f"mysql+mysqldb://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    engine = create_engine(conn_string)
    Base.metadata.create_all(engine)
except OperationalError:
    conn_string = "sqlite:///local.db"
    engine = create_engine(conn_string)
    Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)


@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""

    session = Session()
    try:
        yield session
        session.commit()
    except sqlalchemy.exc.SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


def transactional(f):
    @wraps(f)
    async def wrapper(*args, **kwargs):
        try:
            def in_wrapper():
                with session_scope() as session:
                    return f(session, *args, **kwargs)

            return await util.in_thread(in_wrapper)
        except Exception as e:
            db_log.error("Error with database", exc_info=True)
            raise from e

    return wrapper


@transactional
def get_used_pics(session, include_history=True, include_queue=False, include_monitor=False):
    query = session.query(Pic)
    expr = [True]
    if include_history:
        expr.append(Pic.history_item.isnot(None))
    if include_queue:
        expr.append(Pic.queue_item.isnot(None))
    if include_monitor:
        expr.append(Pic.monitor_item.isnot(None))
    query = query.filter(or_(*expr))
    used_pics = set((pic.service, pic.post_id) for pic in query.all())
    return used_pics


@transactional
def get_user_limits(session):
    db_users = {user.user_id: {'username': bot.get_chat(user.user_id).username, 'limit': user.limit} for
                user in session.query(User).all()}
    return db_users


@transactional
def get_posts_stats(session):
    post_stats = {f"{sender}: {count}/{bot.users[sender]['limit']}" for sender, count in
                  session.query(QueueItem.sender, func.count(QueueItem.sender)).group_by(
                      QueueItem.sender).all()}
    return post_stats


@transactional
def clean_monitor(session):
    monitor = session.query(MonitorItem)
    monitor.delete(synchronize_session=False)


@transactional
def save_monitor_pic(session, pic_item):
    session.add(pic_item)
    session.flush()
    session.refresh(pic_item)
    return pic_item.id


@transactional
def is_pic_exists(session, service, post_id):
    pic_item = session.query(Pic).filter_by(service=service, post_id=post_id).first()
    return bool(pic_item)


@transactional
def mark_post_for_deletion(session, pic_id):
    mon_item = session.query(MonitorItem).filter_by(pic_id=pic_id).first()
    checked = not mon_item.to_del
    service = mon_item.pic.service
    post_id = mon_item.pic.post_id
    mon_item.to_del = checked

    return service, post_id, checked


@transactional
def move_back_to_mon(session):
    mon_items = session.query(MonitorItem).all()
    q_items = [item.pic_name for item in session.query(QueueItem).all()]
    for mon_item in mon_items:
        if not os.path.exists(MONITOR_FOLDER + mon_item.pic_name):
            if os.path.exists(QUEUE_FOLDER + mon_item.pic_name) and mon_item.pic_name not in q_items:
                os.rename(QUEUE_FOLDER + mon_item.pic_name, MONITOR_FOLDER + mon_item.pic_name)
            else:
                session.delete(mon_item)


@transactional
def delete_pic_by_id(session, pic_id):
    pic = session.query(Pic).filter_by(id=pic_id).first()
    session.delete(pic)


@transactional
def get_users(session, access_level=0):
    return [user for user, in session.query(User.user_id).filter(User.access >= access_level).all()]


def get_active_users():
    return get_users(access_level=1)


def get_bot_admins():
    return get_users(access_level=2)


@transactional
def delete_tag(session, service, tag):
    tag_item = session.query(Tag).filter_by(tag=tag, service=service).first()
    session.delete(tag_item)


@transactional
def rename_tag(session, service, old_name, new_name):
    tag_item = session.query(Tag).filter_by(tag=old_name, service=service).first()
    tag_item.tag = new_name


@transactional
def clear_history(session):
    session.query(HistoryItem).delete()


@transactional
def delete_duplicate(session, service, post_id):
    pic = session.query(Pic).filter_by(service=service, post_id=post_id).first()
    session.delete(pic.queue_item)
    pic.history_item = HistoryItem(wall_id=-1)


@transactional
def get_queue_picnames(session):
    pic_names = [q_item.pic_name for q_item in session.query(QueueItem).order_by(QueueItem.id).all()]
    return pic_names


@transactional
def get_delete_queue(session):
    queue = [(queue_item.id, f"{queue_item.pic.service}:{queue_item.pic.post_id}") for queue_item in
             session.query(QueueItem).options(joinedload(QueueItem.pic)).order_by(QueueItem.id).all()]
    return queue


@transactional
def is_tag_exists(session, service, tag):
    tag_in_db = session.query(Tag).filter_by(tag=tag, service=service).first()
    return bool(tag_in_db)


@transactional
def add_new_tag(session, tag):
    session.add(tag)


@transactional
def create_pic(session, service, post_id, new_post):
    pic = session.query(Pic).filter_by(service=service, post_id=post_id).first()
    if not pic:
        pic = Pic(
            service=service,
            post_id=post_id,
            authors=new_post['authors'],
            chars=new_post['chars'],
            copyright=new_post['copyright'],
            hash=new_post['hash'])
        session.add(pic)
        session.flush()
        session.refresh(pic)
    return pic.id


@transactional
def append_pic_data(session, pic_id, **kwargs):
    pic = session.query(Pic).filter_by(id=pic_id).first()
    for key, value in kwargs.items():
        setattr(pic, key, value)


@transactional
def get_queue_stats(session, sender):
    pics_total = session.query(QueueItem).count()
    user_total = session.query(QueueItem).filter_by(sender=sender).count()

    return pics_total, user_total


@transactional
def get_hashes(session):
    hashes = {pic_item.hash: pic_item.post_id for pic_item in session.query(Pic).all()}

    return hashes


@transactional
def add_new_pic(session, pic: Pic):
    session.add(pic)


@transactional
def add_rebuilt_history_pic(session, url, wall_id, history):
    try:
        service = next(service for service in service_db if service_db[service]['post_url'] in url)
    except StopIteration:
        return
    offset = url.find(service_db[service]['post_url'])
    post_n = url[len(service_db[service]['post_url']) + offset:].strip()
    if post_n.isdigit() and (service, post_n) not in history:
        history[(service, post_n)] = wall_id
        new_pic = Pic(post_id=post_n, service=service)
        new_pic.history_item = HistoryItem(wall_id=wall_id)
        session.add(new_pic)


@transactional
def is_new_shutdown(session, chat_id, message_id):
    last_shutdown = session.query(Setting).filter_by(setting='last_shutdown').first()
    if not last_shutdown:
        last_shutdown = '0_0'
    if last_shutdown != f'{chat_id}_{message_id}':
        ls_setting = Setting(setting='last_shutdown', value=f'{chat_id}_{message_id}')
        session.merge(ls_setting)
        return True
    else:
        return False


def load_users():
    log = logging.getLogger(f'ohaio.{__name__}')
    log.debug("Loading bot.users")
    with session_scope() as session:
        bot.users = {user: {"access": access, "limit": limit} for user, access, limit in
                     session.query(User.user_id, User.access, User.limit).all()}
    if not bot.users:
        bot.users = {OWNER_ID: {"access": 100, "limit": QUEUE_LIMIT}}
        save_users()
    log.debug(f'Loaded users: {", ".join(str(user) for user in bot.users)}')


@transactional
def save_users(session):
    log = logging.getLogger(f'ohaio.{__name__}')
    for user, userdata in bot.users.items():
        db_user = User(user_id=user, access=userdata['access'], limit=userdata['limit'])
        session.merge(db_user)
    log.debug("Users saved")


@transactional
def get_info(session, service, new_tag):
    hashes = {pic_item.hash: pic_item.post_id for pic_item in session.query(Pic).all()}
    tags_total = session.query(Tag).filter_by(service=service).count() if not new_tag else 1
    tags = {item.tag: {'last_check': item.last_check or 0, 'missing_times': item.missing_times or 0} for item in (
        session.query(Tag).filter_by(service=service).order_by(Tag.tag).all() if not new_tag else session.query(
            Tag).filter_by(service=service, tag=new_tag).all())}

    return hashes, tags_total, tags


@transactional
def fix_dupe_tag(session, service, tag, dupe_tag, missing_times):
    db_tag = session.query(Tag).filter_by(tag=tag, service=service).first()
    if dupe_tag:
        new_tag = session.query(Tag).filter_by(tag=dupe_tag, service=service).first()
        if new_tag:
            session.delete(db_tag)
            new_tag.missing_times = missing_times
            return True, True
        else:
            db_tag.tag = dupe_tag
            db_tag.missing_times = missing_times
            return True, False
    else:
        db_tag.missing_times = missing_times
        return False, None


@transactional
def update_tag_last_check(session, service, tag, last_check):
    tag_item = session.query(Tag).filter_by(tag=tag, service=service).first()
    tag_item.last_check = max((tag_item.last_check, last_check))


@transactional
def save_tg_msg_to_monitor_item(session, mon_id, tg_msg):
    mon_item = session.query(MonitorItem).filter_by(id=mon_id).first()
    mon_item.tele_msg = tg_msg


@transactional
def delete_callback(session, call, data):
    queue_item = session.query(QueueItem).options(joinedload(QueueItem.pic)).filter_by(id=int(data)).first()
    bot.paginators[(call.message.chat.id, call.message.message_id)].delete_data_item(int(data))
    if queue_item:
        session.delete(queue_item)


@transactional
def get_monitor_before_id(session, pic_id):
    mon_id = session.query(MonitorItem).filter_by(pic_id=pic_id).first().id
    mon_items = [MonitorData(item.to_del, item.pic_name, item.tele_msg,
                             item.pic.id, item.pic.service, item.pic.post_id)
                 for item in session.query(MonitorItem).options(joinedload(MonitorItem.pic)).filter(
            MonitorItem.id <= mon_id).all()]
    return mon_items


@transactional
def is_pic_used(session, sender, service, post_id, pics_total, user_total):
    pic = session.query(Pic).options(joinedload(Pic.history_item), joinedload(Pic.monitor_item)).filter_by(
        service=service, post_id=post_id).first()
    if pic:
        if pic.queue_item:
            text = f"ID {post_id} ({service_db[service]['name']}) уже в очереди!"
            return text, None, None, None
        if pic.history_item:
            text = f"ID {post_id} ({service_db[service]['name']}) уже было!"
            markup = markups.gen_post_link(pic.history_item.wall_id)
            return text, markup, None, None
        if pic.monitor_item:
            pic.queue_item = QueueItem(sender=sender.id, pic_name=pic.monitor_item.pic_name)
            del_msg_chat_id, del_msg_id = TELEGRAM_CHANNEL_MON, pic.monitor_item.tele_msg
            move_mon_to_q(pic.monitor_item.pic_name)
            session.delete(pic.monitor_item)
            text = f"Пикча ID {post_id} ({service_db[service]['name']}) сохранена. \n" \
                   f"В персональной очереди: {user_total + 1}/{bot.users[sender.id]['limit']}.\n" \
                   f"Всего пикч: {pics_total + 1}."
            return text, None, del_msg_chat_id, del_msg_id
    return None, None, None, None


MonitorData = namedtuple('MonitorData', ['to_del', 'pic_name', 'tele_msg', 'pic_id', 'service', 'post_id'])


def move_mon_to_q(filename):
    with ignored(FileExistsError):
        os.rename(f"{MONITOR_FOLDER}{filename}", f"{QUEUE_FOLDER}{filename}")
