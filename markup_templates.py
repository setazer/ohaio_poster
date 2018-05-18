# -*- coding: utf-8 -*-
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from creds import VK_GROUP_ID, service_db
import random

def gen_progress(progress):
    prog_markup = InlineKeyboardMarkup()
    prog_markup.add(InlineKeyboardButton(text="{0:.2f}%".format(progress), callback_data='progress'))
    return prog_markup


def gen_post_link(wall_id):
    if wall_id==-1:
        return None
    link = "https://vk.com/wall-{}_{}".format(VK_GROUP_ID, wall_id)
    link_markup = InlineKeyboardMarkup()
    link_markup.add(InlineKeyboardButton(text="Перейти к посту", url=link))
    return link_markup


def gen_recom_list_buttons(recom_list, status):
    recom_list_markup = InlineKeyboardMarkup()
    recom_list_markup.row_width = 3
    buttons = []
    for (n, ((service, id, pic_name), enabled)) in enumerate(zip(recom_list, status)):
        check = "✅" if enabled else "❌"
        buttons.append(InlineKeyboardButton(text=check, callback_data="rec{}".format(n)))
        buttons.append(InlineKeyboardButton(text="Preview", callback_data="rec_pw{}".format(n)))
        buttons.append(InlineKeyboardButton(text=id, url="http://{}{}".format(service_db[service]['post_url'], id)))
        if (n + 1) % 5 == 0:
            recom_list_markup.add(*buttons)
            recom_list_markup.row(InlineKeyboardButton("Готово", callback_data="rec_complete"))
            buttons = []
    if buttons:
        recom_list_markup.add(*buttons)
        recom_list_markup.row(InlineKeyboardButton("Готово", callback_data="rec_complete"))
    return recom_list_markup


del_pw_markup = InlineKeyboardMarkup()
del_pw_markup.add(InlineKeyboardButton("Убрать", callback_data="rec_del_pw"))


def gen_user_markup(user):
    user_markup = InlineKeyboardMarkup()
    user_markup.row_width = 2
    user_markup.add(InlineKeyboardButton("Да", callback_data="user_allow{}".format(user)),
                    InlineKeyboardButton("Нет", callback_data="user_deny{}".format(user)))
    user_markup.row(InlineKeyboardButton("Забанить", callback_data="user_block{}".format(user)))
    return user_markup


def gen_delete_markup(queue):
    delete_markup = InlineKeyboardMarkup()
    delete_markup.row_width = 2
    buttons = []
    for pic in queue:
        buttons.append(InlineKeyboardButton('#{} - ID: {} ({}) '.format(pic['id'],
                                                                        pic['post_id'],
                                                                        service_db[pic['service']]['name']),
                                            callback_data='del{}'.format(pic['id'])))
    buttons.append(InlineKeyboardButton('Готово', callback_data='del_finish'))
    delete_markup.add(*buttons)
    return delete_markup


def gen_status_markup(*args):
    status_markup = InlineKeyboardMarkup()
    for arg in args:
        status_markup.row(
            InlineKeyboardButton(text=arg, callback_data='progress'))
    return status_markup


def gen_del_tag_markup(tag):
    del_tag_markup = InlineKeyboardMarkup()
    del_tag_markup.add(
        InlineKeyboardButton(text="Попытаться исправить", callback_data="rec_fix{}".format(tag)),
        InlineKeyboardButton(text="Загуглить", url=r"https://www.google.ru/search?q=gelbooru {}".format(tag)))
    return del_tag_markup


def gen_rec_new_markup(id,post_id,checked=False):
    rec_new_markup = InlineKeyboardMarkup()
    to_del = "❎" if not checked else "❌"
    rec_new_markup.row_width = 2
    rec_new_markup.add(InlineKeyboardButton(text="{} Удалить".format(to_del), callback_data="rec_del{} {}".format(id,random.randint(1,1000000))),
                       InlineKeyboardButton(text="▶️ Обработать", callback_data="rec_finish{}".format(id)),
                       InlineKeyboardButton(text="Оригинал",
                                            url=r"http://danbooru.donmai.us/posts/{}".format(post_id)))
    return rec_new_markup

def gen_tag_fix_markup(tag,suggestions):
    rec_new_markup = InlineKeyboardMarkup()
    rec_new_markup.row_width = 2
    s_buttons = []
    for item in suggestions:
        s_buttons.append(InlineKeyboardButton(text="🔁 Заменить на '{}'".format(item), callback_data="tag_rep{} {}".format(tag,item)))

    rec_new_markup.add(InlineKeyboardButton(text="✏️ Переименовать", callback_data="tag_ren{}".format(tag)),
                       InlineKeyboardButton(text="❌ Удалить", callback_data="tag_del{}".format(tag)))
    if s_buttons:
        rec_new_markup.row(InlineKeyboardButton("Заменить на: ", callback_data="separator"))
        rec_new_markup.add(*s_buttons)
    return rec_new_markup

def gen_channel_inline(new_post,wall_id):
    text = "{} {}".format(service_db[new_post['service']]['name'], new_post['post_id'])
    url = "http://{}{}".format(service_db[new_post['service']]['post_url'], new_post['post_id'])
    channel_markup = InlineKeyboardMarkup()
    vk_link = "https://vk.com/wall-{}_{}".format(VK_GROUP_ID, wall_id)
    buttons = []
    buttons.append(InlineKeyboardButton(text=text, url=url))
    if wall_id != -1:
        buttons.append(InlineKeyboardButton(text="Пост в ВК", url=vk_link))
    channel_markup.add(*buttons)
    return channel_markup


rec_finish_markup=InlineKeyboardMarkup()
rec_finish_markup.add(InlineKeyboardButton(text="Завершить обработку рекомендаций", callback_data="rec_finish"))

post_markup = InlineKeyboardMarkup()
post_markup.row_width = 2
buttons = []
for service in service_db:
    buttons.append(InlineKeyboardButton(service_db[service]['name'], callback_data=service))
post_markup.add(*buttons)
