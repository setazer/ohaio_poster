from datetime import date
from typing import List

import vk_requests
from dateutil.relativedelta import relativedelta

from creds import VK_TOKEN, VK_GROUP_ID
from db_mng import Setting, session_scope

with session_scope() as session:
    current_album = session.query(Setting).filter_by(setting='current_album').first()
    previous_album = session.query(Setting).filter_by(setting='previous_album').first()
today = date.today()
d = today - relativedelta(months=1)
month_start, month_end = date(d.year, d.month, 1), date(today.year, today.month, 1) - relativedelta(days=1)
api = vk_requests.create_api(service_token=VK_TOKEN, api_version=5.71)


def get_photos(cur_album, old_album, offset=0) -> List[dict]:
    acc: List[dict] = []
    req = api.photos.get(owner_id='-' + VK_GROUP_ID, album_id=cur_album, extended=1, rev=1, count=1000, offset=offset)
    acc += req['items']
    if req['count'] < 1000 and old_album:
        pics_got = req['count']
        cur_album = old_album
        acc += api.photos.get(owner_id='-' + VK_GROUP_ID, album_id=cur_album, extended=1, rev=1,
                              count=1000 - pics_got)['items']
    return acc


photos = []
photos.extend(get_photos(current_album, previous_album, 0))
photos.extend(get_photos(current_album, previous_album, 1000))

usable_photos = {photo['id']: photo['likes']['count'] for photo in photos if
                 month_start <= date.fromtimestamp(photo['date']) <= month_end}
top_photos = [(photo_id, usable_photos[photo_id]) for photo_id in sorted(usable_photos, key=usable_photos.get,
                                                                         reverse=True)]
photo_links = [f'photo-{VK_GROUP_ID}_{photo_id}' for (photo_id, rest) in top_photos[:10]]

msg = "#monthly@ohaio\nСамые популярные картинки за прошлый месяц:"

wall_id = api.wall.post(message=msg, owner_id='-' + VK_GROUP_ID, attachments=(*photo_links,))
api.wall.pin(owner_id='-' + VK_GROUP_ID, post_id=wall_id['post_id'])
