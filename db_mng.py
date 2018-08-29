# -*- coding: utf-8 -*-
from contextlib import contextmanager

from sqlalchemy import Column, Integer, String, Boolean, Sequence, UniqueConstraint, PrimaryKeyConstraint, ForeignKey
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

from creds import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME

Base = declarative_base()


class User(Base):
    __tablename__ = 'users'
    user_id = Column(Integer, primary_key=True)
    access = Column(Integer)
    limit = Column(Integer)

    def __repr__(self):
        return f"<User(user_id='{self.user_id}', access='{self.access}')>"


class Tag(Base):
    __tablename__ = 'tags'
    service = Column(String(15), nullable=False)
    tag = Column(String(50), nullable=False)
    last_check = Column(Integer)
    missing_times = Column(Integer)
    __table_args__ = (PrimaryKeyConstraint('service', 'tag', name='tag_pkey'),)

    def __repr__(self):
        return f"<Tag(tag='{self.tag}', last_check='{self.last_check}, missing_times='{self.missing_times}')>"


class Pic(Base):
    __tablename__ = 'pics'
    id = Column(Integer, Sequence('pics_id_seq'), primary_key=True)
    service = Column(String(15), nullable=False)
    post_id = Column(String(15), nullable=False)
    file_id = Column(String(80))
    authors = Column(String(300))
    chars = Column(String(300))
    copyright = Column(String(300))
    queue_item = relationship("QueueItem", uselist=False, back_populates="pic", cascade="all, delete-orphan")
    history_item = relationship("HistoryItem", uselist=False, back_populates="pic", cascade="all, delete-orphan")
    monitor_item = relationship("MonitorItem", uselist=False, back_populates="pic", cascade="all, delete-orphan")
    __table_args__ = (UniqueConstraint('service', 'post_id', name='pics_service_post_id_key'),)

    def __repr__(self):
        return f"<Pic(id='{self.id}',service='{self.service}', post_id='{self.post_id}', file_id='{self.file_id}', authors='{self.authors}', chars='{self.chars}', copyright='{self.copyright}')>"


class Setting(Base):
    __tablename__ = 'settings'
    setting = Column(String(30), primary_key=True)
    value = Column(String(30), nullable=False)

    def __repr__(self):
        return f"<Setting(setting='{self.setting}', value='{self.value}')>"


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
        return f"<QueueItem(id='{self.id}', pic_id='{self.pic_id}', sender='{self.sender}', pic_name='{self.pic_name}')>"


class MonitorItem(Base):
    __tablename__ = 'monitor'
    id = Column(Integer, Sequence('monitor_id_seq'), primary_key=True)
    pic_id = Column(Integer, ForeignKey('pics.id'))
    pic = relationship("Pic", back_populates="monitor_item")
    tele_msg = Column(Integer, nullable=False)
    pic_name = Column(String(30))
    to_del = Column(Boolean)

    def __repr__(self):
        return f"<MonitorItem(id='{self.id}', pic_id='{self.pic_id}', tele_msg='{self.tele_msg}', pic_name='{self.pic_name}', to_del='{self.to_del}')>"


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
        return f"<HistoryItem(pic_id='{self.pic_id}', wall_id='{self.wall_id}')>"


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
    except:
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
