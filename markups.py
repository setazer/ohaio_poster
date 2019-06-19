# -*- coding: utf-8 -*-
from aiogram import types, Dispatcher
from aiogram.dispatcher.filters import BoundFilter
from aiogram.utils.callback_data import CallbackData
from aiogram.utils.emoji import emojize
from math import ceil

from bot_mng import bot_action
from creds import VK_GROUP_ID, service_db

user_manager_cb = CallbackData('user', 'user_id', 'action')


def gen_user_markup(user):
    user_markup = types.InlineKeyboardMarkup()
    user_markup.row_width = 2
    user_markup.add(types.InlineKeyboardButton("Да", callback_data=user_manager_cb.new(user_id=user, action="allow")),
                    types.InlineKeyboardButton("Нет", callback_data=user_manager_cb.new(user_id=user, action="deny")))
    user_markup.row(types.InlineKeyboardButton("Забанить",
                                               callback_data=user_manager_cb.new(user_id=user, action="block")))
    return user_markup


dupes_cb = CallbackData('dupe', 'service', 'dupe_id', 'action')


def gen_dupe_markup(service, dupe_id):
    dupe_markup = types.InlineKeyboardMarkup()
    dupe_markup.row_width = 2
    dupe_markup.row(types.InlineKeyboardButton(text="Походу это дубликат",
                                               url="".join(["https://", service_db[service]['post_url'], dupe_id])))
    dupe_markup.add(types.InlineKeyboardButton(emojize(":white_heavy_check_mark: Оставить"),
                                               callback_data=dupes_cb.new(service=service, dupe_id=dupe_id,
                                                                          action="allow")),
                    types.InlineKeyboardButton(emojize(":cross_mark: Удалить"),
                                               callback_data=dupes_cb.new(service=service, dupe_id=dupe_id,
                                                                          action="delete")))
    return dupe_markup


rebuild_history_cb = CallbackData('rebuild', 'action')


def gen_rebuild_history_markup():
    rebuild_history_markup = types.InlineKeyboardMarkup()
    rebuild_history_markup.row_width = 2
    rebuild_history_markup.add(types.InlineKeyboardButton(emojize(":white_heavy_check_mark: Да"),
                                                          callback_data=rebuild_history_cb.new(action='allow')),
                               types.InlineKeyboardButton(emojize(":cross_mark: Нет"),
                                                          callback_data=rebuild_history_cb.new(action='deny')))
    return rebuild_history_markup


limit_cb = CallbackData('limit', 'user_id')


def gen_user_limit_markup(users):
    user_limit_markup = types.InlineKeyboardMarkup()
    user_limit_markup.row_width = 2
    buttons = []
    for user, data in users.items():
        buttons.append(
            types.InlineKeyboardButton(f"{data['username'] or user}: {data['limit']}",
                                       callback_data=limit_cb.new(user_id=user)))
    user_limit_markup.add(*buttons)
    return user_limit_markup


def gen_post_link(wall_id):
    if wall_id == -1:
        return None
    link = f"https://vk.com/wall-{VK_GROUP_ID}_{wall_id}"
    link_markup = types.InlineKeyboardMarkup()
    link_markup.add(types.InlineKeyboardButton(text="Перейти к посту", url=link))
    return link_markup


def gen_status_markup(*args):
    status_markup = types.InlineKeyboardMarkup()
    for arg in args:
        status_markup.row(
            types.InlineKeyboardButton(text=arg, callback_data='progress'))
    return status_markup


rec_fix_cb = CallbackData('rec_fix', 'tag')


def gen_del_tag_markup(tag):
    del_tag_markup = types.InlineKeyboardMarkup()
    del_tag_markup.add(
        types.InlineKeyboardButton(text="Попытаться исправить", callback_data=rec_fix_cb.new(tag=tag)),
        types.InlineKeyboardButton(text="Загуглить", url=rf"https://www.google.ru/search?q={tag}"))
    return del_tag_markup


post_rec_cb = CallbackData('post_rec', 'pic_id', 'action')


def gen_rec_new_markup(id, service, post_id, checked=False, dupe_id=None):
    rec_new_markup = types.InlineKeyboardMarkup()
    to_del = emojize(":cross_mark_button:" if not checked else ":cross_mark:")
    rec_new_markup.row_width = 2
    rec_new_markup.add(
        types.InlineKeyboardButton(text=f"{to_del} Удалить",
                                   callback_data=post_rec_cb.new(pic_id=id, action="delete")),
        types.InlineKeyboardButton(text=emojize(":play_button:️ Обработать"),
                                   callback_data=post_rec_cb.new(pic_id=id, action="finish")),
        types.InlineKeyboardButton(text="Оригинал",
                                   url="".join(["https://", service_db[service]['post_url'], post_id])))
    if dupe_id:
        rec_new_markup.row(types.InlineKeyboardButton(text=f"Дубликат ID:{dupe_id}",
                                                      url="".join(
                                                          ["https://", service_db[service]['post_url'], dupe_id])))
    return rec_new_markup


tag_fix_cb = CallbackData('tag_fix', 'tag', 'action', 'replace_to')


def gen_tag_fix_markup(tag, suggestions):
    rec_new_markup = types.InlineKeyboardMarkup()
    rec_new_markup.row_width = 2
    s_buttons = []
    for item in suggestions:
        s_buttons.append(types.InlineKeyboardButton(text=emojize(f":repeat_button: Заменить на '{item}'"),
                                                    callback_data=tag_fix_cb.new(tag=tag, action="replace",
                                                                                 replace_to=item)))

    rec_new_markup.add(types.InlineKeyboardButton(text=emojize(":pencil:️ Переименовать"),
                                                  callback_data=tag_fix_cb.new(tag=tag, action="rename",
                                                                               replace_to="none")),
                       types.InlineKeyboardButton(text=emojize(":cross_mark: Удалить"),
                                                  callback_data=tag_fix_cb.new(tag=tag, action="delete",
                                                                               replace_to="none")))
    if s_buttons:
        rec_new_markup.row(types.InlineKeyboardButton("Заменить на: ", callback_data="separator"))
        rec_new_markup.add(*s_buttons)
    return rec_new_markup


def gen_channel_inline(new_post, wall_id):
    text = f"{service_db[new_post['service']]['name']} {new_post['post_id']}"
    url = f"http://{service_db[new_post['service']]['post_url']}{new_post['post_id'].partition('_p')[0]}"
    channel_markup = types.InlineKeyboardMarkup()
    vk_link = f"https://vk.com/wall-{VK_GROUP_ID}_{wall_id}"
    buttons = []
    buttons.append(types.InlineKeyboardButton(text=text, url=url))
    if wall_id != -1:
        buttons.append(types.InlineKeyboardButton(text="Пост в ВК", url=vk_link))
    channel_markup.add(*buttons)
    return channel_markup


paginator_cb = CallbackData('pag', 'user_id', 'action', 'item')


class InlinePaginator:
    def __init__(self, msg, data, user_id, items_per_row=5, max_rows=5):
        self.data = data
        self.user_id = user_id
        self.current_page = 1
        self.items_per_row = items_per_row
        self.items_per_page = items_per_row * max_rows
        self.max_pages = ceil(len(self.data) / self.items_per_page)
        self.on_select = None
        self.on_finish = None
        self.msg = msg
        self.bot = None

    async def add_data_item(self, button_data, button_text):
        self.data.append((button_data, button_text))
        await self.refresh()

    async def delete_data_item(self, button_data=None, button_text=None):
        if not any((button_data, button_text)):
            return
        else:
            # поиск с условием "и" при указании обоих аргументов, и "или" при указании только одного
            found_buttons = [item for item in self.data if (
                (item[0] == button_data and item[1] == button_text) if all([button_data, button_text]) else (
                        item[0] == button_data or item[1] == button_text))]
            if found_buttons:
                for item in found_buttons:
                    self.data.remove(item)
                await self.refresh()
                return
            else:
                raise ValueError("Items not found")

    async def refresh(self):
        self.max_pages = ceil(len(self.data) / self.items_per_page)
        if self.current_page > self.max_pages:
            self.current_page = self.max_pages
        await self.show_current_page()

    async def switch_page(self, new_page):
        if self.current_page != new_page:
            self.current_page = new_page
            await self.refresh()

    async def show_current_page(self):
        markup = types.InlineKeyboardMarkup()
        markup.row_width = self.items_per_row
        # блок кнопок с данными
        buttons = []
        cur_page = self.current_page
        items_per_page = self.items_per_page
        cur_page_slice = self.data[(cur_page - 1) * items_per_page:cur_page * items_per_page]
        for value, text in cur_page_slice:
            buttons.append(types.InlineKeyboardButton(text=text,
                                                      callback_data=paginator_cb.new(user_id=self.user_id,
                                                                                     action="item",
                                                                                     item=value)))
        markup.add(*buttons)
        nav_buttons = []
        # первые две кнопки навигации
        # плейсхолдеры на первой странице, "к первой" и "предыдущая" в противном случае
        if self.current_page > 1:
            nav_buttons.append(
                types.InlineKeyboardButton(text=emojize(":fast_reverse_button:") + emojize_number(1),
                                           callback_data=paginator_cb.new(user_id=self.user_id, action="switch",
                                                                          item=1)))
            nav_buttons.append(
                types.InlineKeyboardButton(text=emojize(":reverse_button:") + emojize_number(self.current_page - 1),
                                           callback_data=paginator_cb.new(user_id=self.user_id, action="switch",
                                                                          item=self.current_page - 1)))
        else:
            nav_buttons += [types.InlineKeyboardButton(text=emojize(":record_button:"),
                                                       callback_data=paginator_cb.new(user_id=self.user_id,
                                                                                      action="current",
                                                                                      item="none"))] * 2
        # кнопка текущей страницы
        nav_buttons.append(types.InlineKeyboardButton(text=emojize_number(self.current_page),
                                                      callback_data=paginator_cb.new(user_id=self.user_id,
                                                                                     action="current",
                                                                                     item="none")))

        # последние две кнопки с навигацией
        # плейсхолдеры на последней странице, "вперёд" и "к последней" в противном случае
        if self.current_page < self.max_pages:
            nav_buttons.append(
                types.InlineKeyboardButton(text=emojize(":play_button:️") + emojize_number(self.current_page + 1),
                                           callback_data=paginator_cb.new(user_id=self.user_id, action="switch",
                                                                          item=self.current_page + 1)))
            nav_buttons.append(
                types.InlineKeyboardButton(text=emojize("️:fast-forward_button:") + emojize_number(self.max_pages),
                                           callback_data=paginator_cb.new(user_id=self.user_id, action="switch",
                                                                          item=self.max_pages)))
        else:
            nav_buttons += [types.InlineKeyboardButton(text=emojize(":record_button:"),
                                                       callback_data=paginator_cb.new(user_id=self.user_id,
                                                                                      action="current",
                                                                                      item="none"))] * 2
        markup.row(*nav_buttons)
        markup.row(
            types.InlineKeyboardButton(text=emojize(":white_heavy_check_mark: Завершить"),
                                       callback_data=paginator_cb.new(user_id=self.user_id, action="finish",
                                                                      item="none")))

        if self.bot:
            await bot_action(self.bot.edit_message_reply_markup)(self.msg.chat.id, self.msg.message_id,
                                                                 reply_markup=markup)

    # подвязка пагинатора к боту для указания конкретных вызываемых функций
    # при выборе элемента и завершении работы с пагинатором
    async def hook_bot(self, bot, func_on_select, func_on_finish=None):
        self.bot = bot
        self.on_select = func_on_select
        self.on_finish = func_on_finish
        await self.show_current_page()


# цифры как эмодзи
def emojize_number(num):
    result = ''.join(emojize(f":keycap_{char}:") for char in str(num))
    return result


# подвязка диспатчера к словарю в котором должны храниться пагинаторы
# {user_id:InlinePaginator}
# хендлеры диспатчера обращаются к словарю для вызова конкретных методов пагинаторов
def hook_paginators_to_dispatcher(dispatcher: Dispatcher, paginators: dict):
    class PaginatorFilter(BoundFilter):
        key = 'pag_owner_called'

        def __init__(self, pag_owner_called: bool):
            self.pag_owner_called = pag_owner_called

        async def check(self, call: types.CallbackQuery):
            try:
                parsed = paginator_cb.parse(call.data)
            except ValueError:
                pass
            else:
                user_id = int(parsed['user_id'])
                return user_id == call.from_user.id

    dispatcher.filters_factory.bind(PaginatorFilter, event_handlers=[dispatcher.callback_query_handlers])

    @dispatcher.callback_query_handler(paginator_cb.filter(action="current"), pag_owner_called=True)
    async def callback_page_current(query: types.CallbackQuery, callback_data: dict):
        current_paginator = paginators[callback_data['user_id']]
        await current_paginator.refresh()

    @dispatcher.callback_query_handler(paginator_cb.filter(action="item"), pag_owner_called=True)
    async def callback_select_item(query: types.CallbackQuery, callback_data: dict):
        current_paginator = paginators[callback_data['user_id']]
        if current_paginator.on_select:
            await current_paginator.on_select(query, callback_data['item'])

    @dispatcher.callback_query_handler(paginator_cb.filter(action="finish"), pag_owner_called=True)
    async def callback_finish(query: types.CallbackQuery, callback_data: dict):
        current_paginator = paginators[callback_data['user_id']]
        await current_paginator.bot.delete_message(query.message.chat.id, query.message.message_id)
        if current_paginator.on_finish:
            await current_paginator.on_finish(query)
        del paginators[callback_data['user_id']]

    @dispatcher.callback_query_handler(paginator_cb.filter(action="switch"), pag_owner_called=True)
    async def callback_finish(query: types.CallbackQuery, callback_data: dict):
        current_paginator = paginators[callback_data['user_id']]
        new_page = int(callback_data['item'])
        await current_paginator.switch_page(new_page)
