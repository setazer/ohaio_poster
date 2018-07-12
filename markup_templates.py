# -*- coding: utf-8 -*-
import random
from math import ceil
from random import randint

from telebot.apihelper import ApiException
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

from creds import VK_GROUP_ID, service_db


def gen_post_link(wall_id):
    if wall_id == -1:
        return None
    link = f"https://vk.com/wall-{VK_GROUP_ID}_{wall_id}"
    link_markup = InlineKeyboardMarkup()
    link_markup.add(InlineKeyboardButton(text="Перейти к посту", url=link))
    return link_markup

def gen_user_markup(user):
    user_markup = InlineKeyboardMarkup()
    user_markup.row_width = 2
    user_markup.add(InlineKeyboardButton("Да", callback_data=f"user_allow{user}"),
                    InlineKeyboardButton("Нет", callback_data=f"user_deny{user}"))
    user_markup.row(InlineKeyboardButton("Забанить", callback_data=f"user_block{user}"))
    return user_markup


def gen_rebuild_history_markup():
    rebuild_history_markup = InlineKeyboardMarkup()
    rebuild_history_markup.row_width = 2
    rebuild_history_markup.add(InlineKeyboardButton("✅ Да", callback_data=f"rh_yes"),
                               InlineKeyboardButton("❌ Нет", callback_data=f"rh_no"))
    return rebuild_history_markup

def gen_status_markup(*args):
    status_markup = InlineKeyboardMarkup()
    for arg in args:
        status_markup.row(
            InlineKeyboardButton(text=arg, callback_data='progress'))
    return status_markup


def gen_del_tag_markup(tag):
    del_tag_markup = InlineKeyboardMarkup()
    del_tag_markup.add(
        InlineKeyboardButton(text="Попытаться исправить", callback_data=f"rec_fix{tag}"),
        InlineKeyboardButton(text="Загуглить", url=rf"https://www.google.ru/search?q=gelbooru {tag}"))
    return del_tag_markup


def gen_rec_new_markup(id, post_id, checked=False):
    rec_new_markup = InlineKeyboardMarkup()
    to_del = "❎" if not checked else "❌"
    rec_new_markup.row_width = 2
    rec_new_markup.add(
        InlineKeyboardButton(text=f"{to_del} Удалить", callback_data=f"rec_del{id} {random.randint(1,1000000)}"),
        InlineKeyboardButton(text="▶️ Обработать", callback_data=f"rec_finish{id}"),
        InlineKeyboardButton(text="Оригинал",
                             url=rf"http://danbooru.donmai.us/posts/{post_id}"))
    return rec_new_markup


def gen_tag_fix_markup(tag, suggestions):
    rec_new_markup = InlineKeyboardMarkup()
    rec_new_markup.row_width = 2
    s_buttons = []
    for item in suggestions:
        s_buttons.append(InlineKeyboardButton(text=f"🔁 Заменить на '{item}'", callback_data=f"tag_rep{tag} {item}"))

    rec_new_markup.add(InlineKeyboardButton(text="✏️ Переименовать", callback_data=f"tag_ren{tag}"),
                       InlineKeyboardButton(text="❌ Удалить", callback_data=f"tag_del{tag}"))
    if s_buttons:
        rec_new_markup.row(InlineKeyboardButton("Заменить на: ", callback_data="separator"))
        rec_new_markup.add(*s_buttons)
    return rec_new_markup


def gen_channel_inline(new_post, wall_id):
    text = f"{service_db[new_post['service']]['name']} {new_post['post_id']}"
    url = f"http://{service_db[new_post['service']]['post_url']}{new_post['post_id']}"
    channel_markup = InlineKeyboardMarkup()
    vk_link = f"https://vk.com/wall-{VK_GROUP_ID}_{wall_id}"
    buttons = []
    buttons.append(InlineKeyboardButton(text=text, url=url))
    if wall_id != -1:
        buttons.append(InlineKeyboardButton(text="Пост в ВК", url=vk_link))
    channel_markup.add(*buttons)
    return channel_markup

class InlinePaginator():
    def __init__(self, msg, data, items_per_row=5, max_rows=5):
        self.data = data
        self.current_page = 1
        self.items_per_row = items_per_row
        self.items_per_page = self.items_per_row * max_rows
        self.max_pages = ceil(len(self.data) / self.items_per_page)
        self.navigation_process = None
        self.selector = None
        self.finisher = None
        self.msg = msg
        self.bot = None

    def __del__(self):
        pass

    def add_data_item(self, button_data, button_text):
        self.data.append((button_data, button_text))
        self.refresh()

    def delete_data_item(self, button_data=None, button_text=None):
        if not any([button_data, button_text]):
            return
        else:
            found_buttons = [item for item in self.data if (
                (item[0] == button_data and item[1] == button_text) if all([button_data, button_text]) else (
                        item[0] == button_data or item[1] == button_text))]
            if found_buttons:
                for item in found_buttons:
                    self.data.remove(item)
                self.refresh()
                return
            else:
                raise ValueError("Items not found")

    def refresh(self):
        self.max_pages = ceil(len(self.data) / self.items_per_page)
        if self.current_page > self.max_pages:
            self.current_page = self.max_pages
        self.show_current_page()

    def show_current_page(self):
        markup = InlineKeyboardMarkup()
        markup.row_width = self.items_per_row
        buttons = []
        for value, text in self.data[(self.current_page - 1) * self.items_per_page:
        self.current_page * self.items_per_page]:
            buttons.append(InlineKeyboardButton(text=text, callback_data=f'pag_item{value}'))
        markup.add(*buttons)
        nav_buttons = []
        if self.current_page > 1:
            nav_buttons.append(InlineKeyboardButton(text="⏪" + emojize_number(1), callback_data='pag_switch1'))
            nav_buttons.append(InlineKeyboardButton(text="◀️" + emojize_number(self.current_page - 1),
                                                    callback_data=f'pag_switch{self.current_page - 1}'))
        else:
            nav_buttons += [InlineKeyboardButton(text="⏺", callback_data='pag_cur')] * 2

        nav_buttons.append(InlineKeyboardButton(text=emojize_number(self.current_page),
                                                callback_data=f'pag_cur{randint(0,1000000000)}'))
        if self.current_page < self.max_pages:
            nav_buttons.append(InlineKeyboardButton(text="▶️" + emojize_number(self.current_page + 1),
                                                    callback_data=f'pag_switch{self.current_page + 1}'))
            nav_buttons.append(InlineKeyboardButton(text="️⏩" + emojize_number(self.max_pages),
                                                    callback_data=f'pag_switch{self.max_pages}'))
        else:
            nav_buttons += [InlineKeyboardButton(text="⏺", callback_data='pag_cur')] * 2
        markup.row(*nav_buttons)
        markup.row(InlineKeyboardButton(text="✅ Завершить", callback_data='pag_finish'))

        if self.bot:
            try:
                self.bot.edit_message_reply_markup(self.msg.chat.id, self.msg.message_id, reply_markup=markup)
            except ApiException:
                pass

    def _navigation_process(self, call):
        if 'pag_cur' in call.data:
            self.refresh()
            return
        if 'pag_item' in call.data:
            if self.selector:
                self.selector(call, call.data[len('pag_item'):])
        elif 'pag_finish' in call.data:
            if self.bot:
                for index, callback_handler in enumerate(self.bot.callback_query_handlers):
                    if callback_handler['function'] == self._navigation_process:
                        del self.bot.callback_query_handlers[index]
                        break
            self.bot.delete_message(call.message.chat.id, call.message.message_id)
            self.finisher(call)
        elif 'pag_switch' in call.data:
            new_page = int(call.data.replace('pag_switch', ''))
            if self.current_page != new_page:
                self.current_page = new_page
                self.show_current_page()

    def hook_telebot(self, bot, func_item_selected, finisher=lambda f: None):
        self.bot = bot
        self.selector = func_item_selected
        self.finisher = finisher
        self.navigation_process = bot.callback_query_handler(func=lambda
            call: 'pag_' in call.data and call.message.chat.id == self.msg.chat.id and call.message.message_id == self.msg.message_id)(
            self._navigation_process)

        self.show_current_page()


def emojize_number(num):
    digits = {'0': '0️⃣', '1': '1️⃣', '2': '2️⃣', '3': '3️⃣', '4': '4️⃣', '5': '5️⃣', '6': '6️⃣', '7': '7️⃣',
              '8': '8️⃣', '9': '9️⃣'}
    result = ''.join(digits[char] for char in str(num))
    return result
