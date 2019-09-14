# -*- coding: utf-8 -*-
import asyncio
import json
import logging
from collections import namedtuple, ChainMap
from urllib.parse import quote

import aiohttp
from aiogram.utils import executor
from sqlalchemy.orm import joinedload

import grabber
import markups
from bot_mng import send_message, edit_message, edit_markup, send_photo, delete_message, dp
from creds import LOG_FILE, TELEGRAM_CHANNEL_MON, service_db, BANNED_TAGS, REQUESTS_PROXY, \
    MONITOR_FOLDER, SERVICE_DEFAULT, MAX_NEW_POST_COUNT
from db_mng import MonitorItem, session_scope, get_used_pics, create_pic, append_pic_data, get_info, \
    fix_dupe_tag, save_tg_msg_to_monitor_item, update_tag_last_check


async def fetch(tag, url, session):
    async with session.get(url, proxy=REQUESTS_PROXY) as resp:
        print(f'Fetching {tag}')
        return {tag: await resp.json()}


async def bound_fetch(tag, sem, url, session):
    # Getter function with semaphore.
    async with sem:
        return await fetch(tag, url, session)


async def check_recommendations(new_tag=None):
    if not new_tag:
        repost_msg = await send_message(TELEGRAM_CHANNEL_MON, "Перевыкладываю выдачу прошлой проверки")
        await repost_previous_monitor_check()
        await delete_message(repost_msg.chat.id, repost_msg.message_id)
    srvc_msg = await send_message(TELEGRAM_CHANNEL_MON, "Получаю обновления тегов")
    service = SERVICE_DEFAULT
    used_pics = get_used_pics(include_queue=True)
    hashes, tags_total, tags = get_info(service=service, new_tag=new_tag)
    tags_api = 'http://' + service_db[service]['posts_api']
    login = service_db[service]['payload']['user']
    api_key = service_db[service]['payload']['api_key']
    # post_api = 'https://' + service_db[service]['post_api']
    new_posts = {}
    proxy = REQUESTS_PROXY
    async with aiohttp.ClientSession() as session:
        tags_slices = (list(tags.keys())[i:i + 5] for i in range(0, len(tags), 5))
        for (n, tags_slice) in enumerate(tags_slices, 1):
            tag_aliases = {}
            tags_url = (f"{tags_api.format('+'.join('~' + quote(tag) for tag in tags_slice))}"
                        f"+-rating:explicit&login={login}&api_key={api_key}&limit=200")
            async with session.get(tags_url, proxy=proxy) as resp:
                try:
                    posts = await resp.json()
                except json.decoder.JSONDecodeError as ex:
                    log.error(f'tags:{tags_slice}')
                    log.error(f'text:{await resp.text()}')
                    log.error(ex)
                    posts = []
            new_post_count = {tag: 0 for tag in tags_slice}
            for post in posts:
                try:
                    post_id = post['id']
                except TypeError as ex:
                    log.error(f'posts:{posts}')
                    log.error(ex)
                    break
                has_banned_tags = any(b_tag in post['tag_string'] for b_tag in BANNED_TAGS)
                no_urls = not any([post.get('large_file_url'), post.get('file_url')])
                invalid_ext = any(item in post['file_ext'] for item in ['webm', 'zip'])
                if any((has_banned_tags, no_urls, invalid_ext)):
                    continue
                if (service, str(post_id)) in used_pics:
                    continue
                if tag_aliases:
                    for tag, alias in tag_aliases.items():
                        post['tag_string_artist'].replace(alias, tag)
                try:
                    # get particular author tag in case post have multiple
                    post_tag = set(post['tag_string_artist'].split()).intersection(set(tags_slice)).pop()
                except KeyError:  # post artist not in current tags slice - means database have artist's old alias
                    tag_aliases_api = 'http://' + service_db[service]['tag_alias_api']
                    for artist in post['tag_string_artist'].split():
                        async with session.get(tag_aliases_api.format(artist), proxy=proxy) as resp:
                            tags_json = await resp.json()
                        tag_antecedents = [tag for item in tags_json for tag in tags_slice
                                           if item['status'] == 'active' and tag in item['antecedent_name']]
                        if not tag_antecedents:
                            continue
                        else:
                            tag = tag_antecedents.pop()
                            tag_aliases[tag] = artist
                            post_tag = tag
                            break
                    else:
                        await send_message(srvc_msg.chat.id,
                                           f'Алиас тега для поста {service}:{post_id} с авторами '
                                           f'"{post["tag_string_artist"]}" не найден.\n'
                                           f'Должен быть один из: {", ".join(tags_slice)}')
                        continue

                if (new_post_count[post_tag] < MAX_NEW_POST_COUNT and
                        post_id > tags[post_tag].get('last_check', 0)):
                    new_post_count[post_tag] += 1
                    new_posts[str(post_id)] = {
                        'authors': ' '.join({f'#{x}' for x in post.get('tag_string_artist').split()}),
                        'chars': ' '.join({f"#{x.split('_(')[0]}" for x in
                                           post.get('tag_string_character').split()}),
                        'copyright': ' '.join({f'#{x}'.replace('_(series)', '') for x in
                                               post['tag_string_copyright'].split()}),
                        'tag': post_tag, 'sample_url': post['file_url'],
                        'file_url': post['large_file_url'], 'file_ext': post['file_ext'],
                        'dimensions': f"{post['image_height']}x{post['image_width']}",
                        'safe': post['rating'] == "s"}
            if (n % 5) == 0:
                await edit_markup(srvc_msg.chat.id, srvc_msg.message_id,
                                  reply_markup=markups.gen_status_markup(
                                      f"{tag} [{(n * 5)}/{tags_total}]",
                                      f"Новых постов: {len(new_posts)}"))
            for tag in tags_slice:
                if not new_post_count[tag]:
                    tags[tag]['missing_times'] += 1
                    if tags[tag]['missing_times'] > 4:
                        await send_message(srvc_msg.chat.id,
                                           f"У тега {tag} нет постов уже после {tags[tag]['missing_times']} проверок",
                                           reply_markup=markups.gen_del_tag_markup(tag))
                else:
                    tags[tag]['missing_times'] = 0
                had_dupes, got_renamed = fix_dupe_tag(service=service, tag=tag,
                                                      dupe_tag=tag_aliases.get(tag),
                                                      missing_times=tags[tag]['missing_times'])
                if had_dupes:
                    if got_renamed:
                        await send_message(srvc_msg.chat.id, f'Удалён алиас "{tag}" тега "{tag_aliases[tag]}"')
                    else:
                        await send_message(srvc_msg.chat.id, f'Тег "{tag}" переименован в "{tag_aliases[tag]}"')

        await edit_message("Выкачиваю сэмплы обновлений", srvc_msg.chat.id, srvc_msg.message_id)
        # srt_new_posts = sorted(new_posts)
        for (n, post_id) in enumerate(new_posts, 1):
            await edit_markup(srvc_msg.chat.id, srvc_msg.message_id,
                              reply_markup=markups.gen_status_markup(
                                  f"Новых постов: {len(new_posts)}",
                                  f"Обработка поста: {n}/{len(new_posts)}"))
            new_post = new_posts[post_id]
            if new_post['file_url'] or new_post['sample_url']:
                pic_ext = new_post['file_ext']
                pic_name = f"{service}.{post_id}.{pic_ext}"
            else:
                pic_name = ''
            dl_url = new_post['file_url']
            post_hash = await grabber.download(dl_url, MONITOR_FOLDER + pic_name)
            if post_hash:
                new_posts[post_id]['pic_name'] = pic_name
                new_posts[post_id]['hash'] = post_hash
            else:
                new_posts[post_id]['pic_name'] = None
        await edit_message("Выкладываю обновления", srvc_msg.chat.id, srvc_msg.message_id)
        for post_id in new_posts:
            new_post = new_posts[post_id]
            if new_post['pic_name']:
                pic_id = create_pic(service=service, post_id=post_id, new_post=new_post)
                is_dupe = new_post['hash'] in hashes
                if not is_dupe:
                    hashes[new_post['hash']] = post_id
                mon_msg = await send_photo(TELEGRAM_CHANNEL_MON, MONITOR_FOLDER + new_post['pic_name'],
                                           f"#{new_post['tag']} ID: {post_id}\n{new_post['dimensions']}",
                                           reply_markup=markups.gen_rec_new_markup(pic_id, service, post_id,
                                                                                   not new_post['safe'] or is_dupe,
                                                                                   hashes[new_post[
                                                                                       'hash']] if is_dupe else None))

                monitor_item = MonitorItem(tele_msg=mon_msg.message_id, pic_name=new_post['pic_name'],
                                           to_del=not new_post['safe'] or is_dupe)
                file_id = mon_msg.photo[0].file_id
                append_pic_data(pic_id=pic_id, monitor_item=monitor_item, file_id=file_id)
                update_tag_last_check(service=service, tag=new_post['tag'], last_check=int(post_id))
        await delete_message(srvc_msg.chat.id, srvc_msg.message_id)


async def new_check(new_tag=None):
    if not new_tag:
        repost_msg = await send_message(TELEGRAM_CHANNEL_MON, "Перевыкладываю выдачу прошлой проверки")
        await repost_previous_monitor_check()
        await delete_message(repost_msg.chat.id, repost_msg.message_id)
    service = SERVICE_DEFAULT
    srvc_msg = await send_message(TELEGRAM_CHANNEL_MON, "Получаю обновления тегов")
    used_pics = get_used_pics(include_queue=True)
    hashes, tags_total, tags = get_info(service=service, new_tag=new_tag)
    tags_api = 'http://' + service_db[service]['posts_api']
    tag_aliases_api = 'http://' + service_db[service]['tag_alias_api']
    login = service_db[service]['payload']['user']
    api_key = service_db[service]['payload']['api_key']
    sem = asyncio.Semaphore(20)
    async with aiohttp.ClientSession() as session:
        requests = []
        for tag in tags:
            last_id = 0
            tags_url = (f"{tags_api.format(f'+{quote(tag)}')}"
                        f"+-rating:explicit+id:>{last_id}&login={login}&api_key={api_key}&limit=50")
            requests.append(bound_fetch(tag, sem, tags_url, session))
        posts = dict(ChainMap(*(await asyncio.gather(*requests))))
        new_post_count = {}
        new_posts = {}
        for n, (tag, tag_posts) in enumerate(posts.items()):
            tag_alias = None
            post_tag = tag
            missing_times = tags[tag]['missing_times']
            if not tag_posts:
                missing_times += 1
                if missing_times > 4:
                    await send_message(srvc_msg.chat.id,
                                       f"У тега {tag} нет постов уже после {tags[tag]['missing_times']} проверок",
                                       reply_markup=markups.gen_del_tag_markup(tag))
                continue
            else:
                missing_times = 0
            for post in tag_posts:
                if tag not in post.get('tag_string_artist'):
                    pass  # actualize tag name
                new_post_count.setdefault(tag, 0)
                try:
                    post_id = post['id']
                except TypeError as ex:
                    # log.error(f'posts:{posts}')
                    # log.error(ex)
                    break
                has_banned_tags = any(b_tag in post['tag_string'] for b_tag in BANNED_TAGS)
                no_urls = not any([post.get('large_file_url'), post.get('file_url')])
                invalid_ext = any(item in post['file_ext'] for item in ['webm', 'zip'])
                if any((has_banned_tags, no_urls, invalid_ext)):
                    continue
                if (service, str(post_id)) in used_pics:
                    continue
                if tag_alias:
                    post['tag_string_artist'].replace(tag, tag_alias)
                if tag not in post['tag_string_artist']:
                    for artist in post['tag_string_artist'].split():
                        async with session.get(tag_aliases_api.format(artist), proxy=REQUESTS_PROXY) as resp:
                            tags_json = await resp.json()
                        if any(item['antecedent_name'] == tag and item['status'] == 'active' for item in tags_json):
                            tag_alias = post_tag = artist
                            break
                else:
                    await send_message(srvc_msg.chat.id,
                                       f'Алиас тега для поста {service}:{post_id} с авторами '
                                       f'"{post["tag_string_artist"]}" не найден.\n')
                    continue
                if new_post_count[post_tag] < MAX_NEW_POST_COUNT:
                    new_post_count[post_tag] += 1
                    new_posts[str(post_id)] = {
                        'authors': ' '.join({f'#{x}' for x in post.get('tag_string_artist').split()}),
                        'chars': ' '.join({f"#{x.split('_(')[0]}" for x in
                                           post.get('tag_string_character').split()}),
                        'copyright': ' '.join({f'#{x}'.replace('_(series)', '') for x in
                                               post['tag_string_copyright'].split()}),
                        'tag': tag, 'sample_url': post['file_url'],
                        'file_url': post['large_file_url'], 'file_ext': post['file_ext'],
                        'dimensions': f"{post['image_height']}x{post['image_width']}",
                        'safe': post['rating'] == "s"}
            if (n % 10) == 0:
                await edit_markup(srvc_msg.chat.id, srvc_msg.message_id,
                                  reply_markup=markups.gen_status_markup(
                                      f"{tag} [{n}/{tags_total}]",
                                      f"Новых постов: {len(new_posts)}"))
            had_dupes, got_renamed = fix_dupe_tag(service=service, tag=tag,
                                                  dupe_tag=tag_alias,
                                                  missing_times=missing_times)
            if had_dupes:
                if got_renamed:
                    await send_message(srvc_msg.chat.id, f'Удалён алиас "{tag}" тега "{tag_alias}"')
                else:
                    await send_message(srvc_msg.chat.id, f'Тег "{tag}" переименован в "{tag_alias}"')
        await edit_message("Выкачиваю сэмплы обновлений", srvc_msg.chat.id, srvc_msg.message_id)
        srt_new_posts = sorted(new_posts)
        for (n, post_id) in enumerate(srt_new_posts, 1):
            await edit_markup(srvc_msg.chat.id, srvc_msg.message_id,
                              reply_markup=markups.gen_status_markup(
                                  f"Новых постов: {len(new_posts)}",
                                  f"Обработка поста: {n}/{len(srt_new_posts)}"))
            new_post = new_posts[post_id]
            if new_post['file_url'] or new_post['sample_url']:
                pic_ext = new_post['file_ext']
                pic_name = f"{service}.{post_id}.{pic_ext}"
            else:
                pic_name = ''
            dl_url = new_post['file_url']
            post_hash = await grabber.download(dl_url, MONITOR_FOLDER + pic_name)
            if post_hash:
                new_posts[post_id]['pic_name'] = pic_name
                new_posts[post_id]['hash'] = post_hash
            else:
                new_posts[post_id]['pic_name'] = None
        await edit_message("Выкладываю обновления", srvc_msg.chat.id, srvc_msg.message_id)
        for post_id in srt_new_posts:
            new_post = new_posts[post_id]
            if new_post['pic_name']:
                pic_id = create_pic(service=service, post_id=post_id, new_post=new_post)
                is_dupe = new_post['hash'] in hashes
                if not is_dupe:
                    hashes[new_post['hash']] = post_id
                mon_msg = await send_photo(TELEGRAM_CHANNEL_MON, MONITOR_FOLDER + new_post['pic_name'],
                                           f"#{new_post['tag']} ID: {post_id}\n{new_post['dimensions']}",
                                           reply_markup=markups.gen_rec_new_markup(pic_id, service, post_id,
                                                                                   not new_post['safe'] or is_dupe,
                                                                                   hashes[new_post[
                                                                                       'hash']] if is_dupe else None))

                monitor_item = MonitorItem(tele_msg=mon_msg.message_id, pic_name=new_post['pic_name'],
                                           to_del=not new_post['safe'] or is_dupe)
                file_id = mon_msg.photo[0].file_id
                append_pic_data(pic_id=pic_id, monitor_item=monitor_item, file_id=file_id)
                update_tag_last_check(service=service, tag=new_post['tag'], last_check=int(post_id))
        await delete_message(srvc_msg.chat.id, srvc_msg.message_id)
    return new_posts


MonitorData = namedtuple('MonitorData',
                         ['id', 'tele_msg', 'to_del', 'pic_id', 'service', 'post_id', 'file_id', 'authors'])


def get_monitor():
    with session_scope() as session:
        mon_items = [MonitorData(mon_item.id, mon_item.tele_msg, mon_item.to_del, mon_item.pic.id,
                                 mon_item.pic.service, mon_item.pic.post_id, mon_item.pic.authors, mon_item.file_id) for
                     mon_item in
                     session.query(MonitorItem).options(joinedload(MonitorItem.pic)).order_by(MonitorItem.id).all()]
        return mon_items


async def repost_previous_monitor_check():
    mon_items = get_monitor()
    for mon_item in mon_items:
        await delete_message(TELEGRAM_CHANNEL_MON, mon_item.tele_msg)
        new_msg = await send_photo(TELEGRAM_CHANNEL_MON, mon_item.file_id,
                                   caption=f"{mon_item.authors}\n"
                                   f"ID: {mon_item.post_id}",
                                   reply_markup=markups.gen_rec_new_markup(mon_item.id,
                                                                           mon_item.service,
                                                                           mon_item.post_id,
                                                                           mon_item.to_del))
        if new_msg:
            save_tg_msg_to_monitor_item(mon_id=mon_item.id, tg_msg=new_msg.message_id)


if __name__ == '__main__':
    log = logging.getLogger(f'ohaio.{__name__}')
    log.setLevel(logging.DEBUG)
    fh = logging.FileHandler(LOG_FILE)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter('%(asctime)s [Monitor] %(levelname)-8s %(message)s'))
    sh = logging.StreamHandler()
    sh.setFormatter(logging.Formatter('%(asctime)s [Monitor] %(levelname)-8s %(message)s'))
    sh.setLevel(logging.DEBUG)
    log.addHandler(fh)
    log.addHandler(sh)
    executor.start(dp, check_recommendations())
