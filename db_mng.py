# -*- coding: utf-8 -*-
import logging
import os
from contextlib import contextmanager

import sqlalchemy
from sqlalchemy import Column, Integer, String, Boolean, Sequence, UniqueConstraint, PrimaryKeyConstraint, ForeignKey, \
    func
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import sessionmaker, relationship, joinedload

from bot_mng import bot
from creds import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME, OWNER_ID
from creds_template import MONITOR_FOLDER, QUEUE_FOLDER, SERVICE_DEFAULT, QUEUE_LIMIT

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


# extra = session.query(User).filter_by(user_id=999999999).first()
# session.delete(extra)
# session.commit()
# for row in session.query(User):
#     print(row, row.user_id, row.access)

# def save_setting(setting, value):
#     with postgresql.open(conn_string) as db:
#         ins = db.prepare(
#             'INSERT INTO settings (setting, value) VALUES ($1, $2) on conflict (setting) do update set value = $2 where settings.setting = $1')
#         ins(setting, str(value))
#
#
# def save_tag(tag, last_check, missing_times):
#     with postgresql.open(conn_string) as db:
#         ins = db.prepare(
#             'INSERT INTO tags (tag,last_check,missing_times) VALUES ($1, $2, $3) on conflict (tag) do update set (last_check,missing_times) = ($2, $3) where tags.tag = $1')
#         ins(tag, last_check, missing_times)
#
#
# def save_user(user, access):
#     with postgresql.open(conn_string) as db:
#         ins = db.prepare(
#             'INSERT INTO users (user_id, access) VALUES ($1, $2) on conflict (user_id) do update set access = $2 where users.user_id = $1')
#         ins(user, access)
#
#
# def save_queue_row(service, post_id, sender, pic_name, authors, chars, copyright):
#     with postgresql.open(conn_string) as db:
#         ins = db.prepare(
#             'INSERT INTO queue (service, post_id, sender,pic_name, authors, chars, copyright) VALUES ($1, $2, $3, $4, $5, $6, $7) on conflict (service, post_id) do nothing')
#         ins(service, post_id, sender, pic_name, authors, chars, copyright)
#
#
# def save_history_row(service, post_id, wall_id):
#     with postgresql.open(conn_string) as db:
#         ins = db.prepare(
#             'INSERT INTO history (service, post_id, wall_id) VALUES ($1, $2, $3) on conflict (service, post_id) do nothing')
#         ins(service, post_id, wall_id)
#
#

def get_used_pics(include_history=True, include_queue=False, include_monitor=False):
    with session_scope() as session:
        query = session.query(Pic)
        if include_history:
            query = query.filter(Pic.history_item != None)
        if include_queue:
            query = query.filter(Pic.queue_item != None)
        if include_monitor:
            query = query.filter(Pic.monitor_item != None)
        used_pics = set((pic.service, pic.post_id) for pic in query.all())
    return used_pics


def save_pic(new_pic):
    with session_scope() as session:
        session.add(new_pic)


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

# dump_db()
# load_db()
def get_user_limits():
    with session_scope() as session:
        db_users = {user.user_id: {'username': bot.get_chat(user.user_id).username, 'limit': user.limit} for
                    user in session.query(User).all()}
        return db_users


def get_posts_stats():
    with session_scope() as session:
        post_stats = {f"{sender}: {count}/{bot.users[sender]['limit']}" for sender, count in
                      session.query(QueueItem.sender, func.count(QueueItem.sender)).group_by(
                          QueueItem.sender).all()}
        return post_stats


def clean_monitor():
    with session_scope() as session:
        monitor = session.query(MonitorItem)
        monitor.delete(synchronize_session=False)


def save_monitor_pic(pic_item):
    with session_scope() as session:
        session.add(pic_item)
        session.flush()
        session.refresh(pic_item)
        return pic_item.id


def is_pic_exists(service, post_id):
    with session_scope() as session:
        pic_item = session.query(Pic).filter_by(service=service, post_id=post_id).first()
        return bool(pic_item)


def mark_post_for_deletion(pic_id):
    with session_scope() as session:
        mon_item = session.query(MonitorItem).filter_by(pic_id=pic_id).first()
        checked = not mon_item.to_del
        service = mon_item.pic.service
        post_id = mon_item.pic.post_id
        mon_item.to_del = checked
    return service, post_id, checked


def move_back_to_mon():
    with session_scope() as session:
        mon_items = session.query(MonitorItem).all()
        q_items = [item.pic_name for item in session.query(QueueItem).all()]
        for mon_item in mon_items:
            if not os.path.exists(MONITOR_FOLDER + mon_item.pic_name):
                if os.path.exists(QUEUE_FOLDER + mon_item.pic_name) and mon_item.pic_name not in q_items:
                    os.rename(QUEUE_FOLDER + mon_item.pic_name, MONITOR_FOLDER + mon_item.pic_name)
                else:
                    session.delete(mon_item)


def delete_pic_by_id(pic_id):
    with session_scope() as session:
        pic = session.query(Pic).filter_by(id=pic_id).first()
        session.delete(pic)


def replace_tag(tag, alt_tag):
    service = SERVICE_DEFAULT
    with session_scope() as session:
        tag_item = session.query(Tag).filter_by(tag=tag, service=service).first()
        tag_item.tag = alt_tag


def delete_tag(tag):
    service = SERVICE_DEFAULT
    with session_scope() as session:
        tag_item = session.query(Tag).filter_by(tag=tag, service=service).first()
        session.delete(tag_item)


def rename_tag(service, old_name, new_name):
    with session_scope() as session:
        tag_item = session.query(Tag).filter_by(tag=old_name, service=service).first()
        tag_item.tag = new_name


def clear_history():
    with session_scope() as session:
        session.query(HistoryItem).delete()


def delete_duplicate(service, post_id):
    with session_scope() as session:
        pic = session.query(Pic).filter_by(service=service, post_id=post_id).first()
        session.delete(pic.queue_item)
        pic.history_item = HistoryItem(wall_id=-1)


def get_queue_picnames():
    with session_scope() as session:
        pic_names = [q_item.pic_name for q_item in session.query(QueueItem).order_by(QueueItem.id).all()]
        return pic_names


def get_delete_queue():
    with session_scope() as session:
        queue = [(queue_item.id, f"{queue_item.pic.service}:{queue_item.pic.post_id}") for queue_item in
                 session.query(QueueItem).options(joinedload(QueueItem.pic)).order_by(QueueItem.id).all()]
        return queue


def is_tag_exists(tag):
    with session_scope() as session:
        tag_in_db = session.query(Tag).filter_by(tag=tag, service=SERVICE_DEFAULT).first()
    return bool(tag_in_db)


def write_new_tag(tag):
    with session_scope() as session:
        session.add(tag)


def create_pic(service, post_id, new_post):
    with session_scope() as session:
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


def append_pic_data(pic_id, data: dict):
    with session_scope() as session:
        pic = session.query(Pic).filter_by(id=pic_id).first()
        for key, value in data.items():
            setattr(pic, key, value)


def get_queue_stats(sender):
    with session_scope() as session:
        pics_total = session.query(QueueItem).count()
        user_total = session.query(QueueItem).filter_by(sender=sender).count()
    return pics_total, user_total


def get_hashes():
    with session_scope() as session:
        hashes = {pic_item.hash: pic_item.post_id for pic_item in session.query(Pic).all()}
    return hashes


def get_bot_admins():
    with session_scope() as session:
        admins = [user for user, in session.query(User.user_id).filter(User.access >= 1).all()]
    return admins


def add_new_pic(pic: Pic):
    with session_scope() as session:
        session.add(pic)


def is_new_shutdown(chat_id, message_id) -> bool:
    with session_scope() as session:
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
    log.debug(f'Loaded users: {", ".join(str(user) for user in bot.users)}')


def save_users():
    log = logging.getLogger(f'ohaio.{__name__}')
    with session_scope() as session:
        for user, userdata in bot.users.items():
            db_user = User(user_id=user, access=userdata['access'], limit=userdata['limit'])
            session.merge(db_user)
    log.debug("Users saved")


def get_info(service, new_tag):
    with session_scope() as session:
        hashes = {pic_item.hash: pic_item.post_id for pic_item in session.query(Pic).all()}
        tags_total = session.query(Tag).filter_by(service=service).count() if not new_tag else 1
        tags = {item.tag: {'last_check': item.last_check or 0, 'missing_times': item.missing_times or 0} for item in (
            session.query(Tag).filter_by(service=service).order_by(Tag.tag).all() if not new_tag else session.query(
                Tag).filter_by(service=service, tag=new_tag).all())}
    return hashes, tags_total, tags


def fix_dupe_tag(service, tag, dupe_tag, missing_times):
    with session_scope() as session:
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
            return False, None


def update_tag_last_check(service, tag, last_check):
    with session_scope() as session:
        session.query(Tag).filter_by(tag=tag, service=service).first().last_check = last_check


def save_tg_msg_to_monitor_item(mon_id, tg_msg):
    with session_scope() as session:
        mon_item = session.query(MonitorItem).filter_by(id=mon_id).first()
        mon_item.tele_msg = tg_msg
