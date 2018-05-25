from db_mng import *
import vk
from datetime import date
from dateutil.relativedelta import relativedelta
from datetime import date

import vk
from dateutil.relativedelta import relativedelta

from db_mng import *

# current_album = '250477287'
with session_scope() as session:
    current_album = session.query(Setting).filter_by(setting='current_album').first().value
    previous_album = session.query(Setting).filter_by(setting='previous_album').first().value
today = date.today()
d = today - relativedelta(months=1)
month_start, month_end = date(d.year, d.month, 1), date(today.year, today.month, 1) - relativedelta(days=1)
vk_session = vk.Session(access_token=VK_TOKEN)
api = vk.API(vk_session,v=5.71)

def get_photos(cur_album,old_album,offset=0):
    acc=[]
    req = api.photos.get(owner_id='-'+VK_GROUP_ID,album_id=cur_album,extended=1,rev=1,count=1000,offset=offset)
    acc += req['items']
    if req['count']<1000:
        pics_got = req['count']
        cur_album = old_album
        acc += api.photos.get(owner_id='-' + VK_GROUP_ID, album_id=cur_album, extended=1, rev=1, count=1000-pics_got)['items']
    return acc

photos = []
photos += get_photos(current_album,previous_album,0)
photos += get_photos(current_album,previous_album,1000)
usable_photos = {photo['id']:photo['likes']['count'] for photo in photos if month_start<=date.fromtimestamp(photo['date'])<=month_end}
top_photos = [(id,usable_photos[id]) for id in sorted(usable_photos,key=usable_photos.get, reverse=True)]
photo_links = [f'photo-{VK_GROUP_ID}_{id}' for (id,rest) in top_photos[:10]]

msg="#monthly@ohaio\nСамые популярные картинки за прошлый месяц:"

wall_id = api.wall.post(message=msg, owner_id='-' + VK_GROUP_ID, attachments=(*photo_links, ))
api.wall.pin(owner_id='-' + VK_GROUP_ID,post_id=wall_id['post_id'])