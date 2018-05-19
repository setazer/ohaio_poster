# -*- coding: utf-8 -*-
import random
from math import ceil

from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from creds import VK_GROUP_ID, service_db


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

def gen_user_markup(user):
    user_markup = InlineKeyboardMarkup()
    user_markup.row_width = 2
    user_markup.add(InlineKeyboardButton("Да", callback_data="user_allow{}".format(user)),
                    InlineKeyboardButton("Нет", callback_data="user_deny{}".format(user)))
    user_markup.row(InlineKeyboardButton("Забанить", callback_data="user_block{}".format(user)))
    return user_markup



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


class InlinePaginator():
    def __init__(self, msg, data, items_per_page=25):
        self.data = data
        self.current_page = 1
        self.items_per_page = items_per_page
        self.max_pages = ceil(len(self.data) / self.items_per_page)
        self.selector = None
        self.finisher = None
        self.msg = msg
        self.bot = None

    def __del__(self):
        if self.bot:
            for index, callback_handler in enumerate(self.bot.callback_query_handlers):
                if callback_handler['function'] == self.navigation_process:
                    del self.bot.callback_query_handlers[index]
                    break

    def add_data_item(self, item):
        try:
            self.data.append((item[0], item[1]))
        except (TypeError, IndexError) as ex:
            raise ValueError("Invalid item for addition")
        else:
            self.max_pages = ceil(len(self.data) / self.items_per_page)
            if self.current_page == self.max_pages:
                self.show_current_page()

    def delete_data_item(self, item):
        try:
            idx = self.data.index((item[0], item[1]))
            self.data.remove((item[0], item[1]))
        except (TypeError, IndexError):
            raise ValueError("Invalid item for removal")
        except ValueError:
            raise ValueError("Item not found")
        else:
            self.max_pages = int(ceil(len(self.data) / self.items_per_page))
            if self.current_page > self.max_pages:
                self.current_page = self.max_pages
                self.show_current_page()
                return
            if idx in range((self.current_page - 1) * self.items_per_page, self.current_page * self.items_per_page):
                self.show_current_page()

    def update_data(self):
        self.max_pages = ceil(len(self.data) / self.items_per_page)
        if self.current_page > self.max_pages:
            self.current_page = self.max_pages
        self.show_current_page()

    def show_current_page(self):
        markup = InlineKeyboardMarkup()
        markup.row_width = 5
        buttons = []
        for text, value in self.data[(self.current_page - 1) * self.items_per_page:
        self.current_page * self.items_per_page]:
            buttons.append(InlineKeyboardButton(text=text, callback_data=f'pag_item{value}'))
        markup.add(*buttons)
        nav_buttons = []
        if self.current_page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⏪", callback_data='pag_first'))
            nav_buttons.append(InlineKeyboardButton(text="◀️", callback_data='pag_prev'))
        else:
            nav_buttons += [InlineKeyboardButton(text="⏺", callback_data='pag_cur')] * 2

        nav_buttons.append(InlineKeyboardButton(text=emojize_number(self.current_page), callback_data='pag_cur'))
        if self.current_page < self.max_pages:
            nav_buttons.append(InlineKeyboardButton(text="▶️", callback_data='pag_next'))
            nav_buttons.append(InlineKeyboardButton(text="️⏩", callback_data='pag_last'))
        else:
            nav_buttons += [InlineKeyboardButton(text="⏺", callback_data='pag_cur')] * 2
        markup.row(*nav_buttons)
        markup.row(InlineKeyboardButton(text="✅ Завершить", callback_data='pag_finish'))

        if self.bot:
            self.bot.edit_message_reply_markup(self.msg.chat.id, self.msg.message_id, reply_markup=markup)

    def navigation_process(self, call):
        if 'pag_cur' in call.data:
            return
        if 'pag_item' in call.data:
            if self.selector:
                self.selector(call.data[len('pag_item'):], call)
        elif 'pag_finish' in call.data:
            self.bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id)
            self.finisher(call)
        else:
            if 'pag_first' in call.data:
                self.current_page = 1
            elif 'pag_prev' in call.data:
                self.current_page -= 1
            elif 'pag_next' in call.data:
                self.current_page += 1
            elif 'pag_last' in call.data:
                self.current_page = self.max_pages
            self.show_current_page()

    def hook_telebot(self, bot, func_item_selected, finisher=lambda f: None):
        self.bot = bot
        self.selector = func_item_selected
        self.finisher = finisher
        self.navigation_process = bot.callback_query_handler(func=lambda call: 'pag_' in call.data)(
            self.navigation_process)
        self.show_current_page()


def emojize_number(num):
    digits = {'0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣', '5': '5️⃣', '6': '6️⃣', '7': '7️⃣',
              '8': '8️⃣', '9': '9️⃣'}
    result = ''
    for char in str(num):
        result += digits[char]
    return result
