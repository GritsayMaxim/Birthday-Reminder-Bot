import asyncio
import logging
import os
import random
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')

MOSCOW_TZ = ZoneInfo("Europe/Moscow")

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

router = Router()

DB_NAME = 'birthdays.db'

class BirthdayForm(StatesGroup):
    waiting_for_name = State()
    waiting_for_date = State()
    waiting_for_description = State()
    waiting_for_username = State()
    waiting_for_time = State()
    confirm_add = State()


class DeleteForm(StatesGroup):
    waiting_for_name_to_delete = State()
    confirm_delete = State()


class SettingsForm(StatesGroup):
    waiting_for_name_to_set = State()
    waiting_for_parameter = State()
    waiting_for_value = State()

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute('''
            CREATE TABLE IF NOT EXISTS birthdays (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                chat_id INTEGER,
                name TEXT,
                birthdate TEXT,
                description TEXT,
                telegram_username TEXT,
                reminder_time TEXT DEFAULT '09:00',
                remind_3_days BOOLEAN DEFAULT 1,
                remind_1_day BOOLEAN DEFAULT 1,
                remind_day BOOLEAN DEFAULT 1,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        await db.commit()


# Шаблоны для поздравлений
CONGRATS_TEMPLATES = [
    "🎉 С днем рождения, {name}! Пусть твой {age}-й год будет полон {idea} и приключений! Желаю счастья и удачи во всех начинаниях!",
    "🥳 Ура, {name}! {age} лет — это круто! Желаю море позитива, {gift_idea} и исполнения всех желаний!",
    "🎂 Дорогой {name}, с Днем Рождения! Пусть каждый день будет наполнен радостью и улыбками. Наслаждайся своим праздником!",
    "✨ {name}, поздравляю с {age}-летием! Пусть этот год принесет тебе {idea} и радость! Будь счастлив(а)!",
    "🎈 С Днем Рождения, {name}! {age} лет — прекрасный возраст для {gift_idea} и новых достижений! Удачи во всем!"
]

# Подарки по возрастам с учетом возрастных ограничений
GIFT_IDEAS = {
    'child': [  # 0-12 лет
        'игрушки', 'конструктора Lego', 'книги со сказками', 'велосипед',
        'настольные игры', 'мягкие игрушки', 'краски и альбомы для рисования',
        'спортивный инвентарь', 'наборы для творчества'
    ],
    'teen': [  # 13-17 лет
        'гаджеты', 'наушники', 'книги по саморазвитию', 'игровая консоль',
        'спортивная форма', 'модная одежда', 'аксессуары для телефона',
        'билеты на концерт', 'книги фэнтези', 'скейтборд или гироскутер'
    ],
    'young_adult': [  # 18-25 лет
        'книги', 'путешествия', 'билеты в кино или театр', 'подарочный сертификат',
        'модные аксессуары', 'курсы или мастер-классы', 'техника для учебы/работы',
        'стильный рюкзак', 'сертификат в книжный магазин'
    ],
    'adult': [  # 26-59 лет
        'парфюм', 'книги', 'путешествия', 'вино или кофе',
        'сертификат в спа-салон', 'удобные домашние тапочки', 'гаджеты для кухни',
        'билеты на спектакль', 'подписка на стриминг-сервис', 'набор для хобби'
    ],
    'elder': [  # 60+ лет
        'уютный плед', 'хорошие книги', 'теплые встречи', 'приятные воспоминания',
        'чайный набор', 'фотоальбом с семейными фото', 'комнатные растения',
        'удобное кресло', 'набор для рукоделия', 'сертификат в магазин для садовода'
    ]
}

def get_moscow_now():
    return datetime.now(MOSCOW_TZ)


def calculate_age(birthdate_str):
    birthdate = datetime.strptime(birthdate_str, '%d.%m.%Y').replace(tzinfo=MOSCOW_TZ)
    today = get_moscow_now()
    age = today.year - birthdate.year - ((today.month, today.day) < (birthdate.month, birthdate.day))
    return age

def calculate_age_on_date(birthdate_str, target_date):
    birthdate = datetime.strptime(birthdate_str, '%d.%m.%Y')
    age = target_date.year - birthdate.year - ((target_date.month, target_date.day) < (birthdate.month, birthdate.day))
    return age


# Определение возрастной категории с учетом ограничений по подаркам
def get_age_category(age):
    if age < 13:
        return 'child'
    elif age < 18:  # До 18 лет - подростки
        return 'teen'
    elif age < 26:  # 18-25 лет - молодые взрослые
        return 'young_adult'
    elif age < 60:  # 26-59 лет - взрослые
        return 'adult'
    else:  # 60+ лет
        return 'elder'


# Генерация ПОЗДРАВЛЕНИЯ с учетом возраста
def generate_congrats(name, birthdate_str, description=None):
    age = calculate_age(birthdate_str) + 1  # Возраст на этот день рождения
    age_category = get_age_category(age)
    template = random.choice(CONGRATS_TEMPLATES)
    gift_idea = random.choice(GIFT_IDEAS[age_category])

    # Для взрослых 18+ можно добавить разные варианты
    if age_category == 'young_adult' and age == 18:
        template = f"🎉 {name}, поздравляю с совершеннолетием! {age} лет — это начало взрослой жизни! Пусть она будет полна {gift_idea} и ярких моментов!"

    if description:
        # Добавляем описание в поздравление
        template = template.replace("Наслаждайся днем!", f"Наслаждайся днем! P.S. {description}")

    return template.format(
        name=name,
        age=age,
        idea=gift_idea,
        gift_idea=gift_idea
    )

def get_skip_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭️ Пропустить")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


# Клавиатура для подтверждения
def get_confirm_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Да, сохранить")],
            [KeyboardButton(text="❌ Нет, отменить")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


# Клавиатура для настроек
def get_settings_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏰ Изменить время")],
            [KeyboardButton(text="📅 Настроить напоминания")],
            [KeyboardButton(text="🔗 Изменить username")],
            [KeyboardButton(text="❌ Отмена")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


# Команда /start
@router.message(Command("start"))
async def cmd_start(message: Message):
    welcome_text = """
🎉 <b>Добро пожаловать в Birthday Reminder Bot!</b>

Я помогу вам не забывать о днях рождения.

<b>Основные команды:</b>
👤 /add - Добавить день рождения
📋 /list - Показать ваши дни рождения
🗑️ /delete - Удалить день рождения
⚙️ /settings - Настройки напоминаний

<b>Как это работает:</b>
1. Вы добавляете день рождения
2. Я напоминаю за 3 дня и за 1 день
3. В день рождения пришлю готовое поздравление

⏰ Все время указано в МСК
    """
    await message.answer(welcome_text)


# Команда /add - начало процесса добавления
@router.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    await state.set_state(BirthdayForm.waiting_for_name)
    await message.answer(
        "👤 <b>ШАГ 1 ИЗ 6: КОГО ДОБАВЛЯЕМ?</b>\n\n"
        "Введите <b>имя человека</b>, чей день рождения хотите отслеживать.\n"
        "Например: <i>Анна, Иван, Мария Петровна</i>",
        reply_markup=ReplyKeyboardRemove()
    )


# Шаг 1: Получение имени
@router.message(BirthdayForm.waiting_for_name, F.text.len() > 1)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await state.set_state(BirthdayForm.waiting_for_date)
    await message.answer(
        "📅 <b>ШАГ 2 ИЗ 6: КОГДА РОДИЛСЯ?</b>\n\n"
        "Введите <b>дату рождения</b> в формате:\n"
        "<b>ДД.ММ.ГГГГ</b>\n\n"
        "Например:\n"
        "<i>15.05.1990</i> - 15 мая 1990 года\n"
        "<i>03.12.2000</i> - 3 декабря 2000 года"
    )


# Шаг 2: Получение даты рождения
@router.message(BirthdayForm.waiting_for_date, F.text.regexp(r'^\d{2}\.\d{2}\.\d{4}$'))
async def process_date(message: Message, state: FSMContext):
    try:
        date_str = message.text.strip()
        datetime.strptime(date_str, '%d.%m.%Y')

        # Проверка на будущую дату
        birth_date = datetime.strptime(date_str, '%d.%m.%Y').replace(tzinfo=MOSCOW_TZ)
        today = get_moscow_now()
        if birth_date > today:
            await message.answer(
                "⚠️ <b>ОШИБКА:</b> Дата рождения не может быть в будущем!\n"
                "Пожалуйста, введите корректную дату:"
            )
            return

        await state.update_data(birthdate=date_str)
        await state.set_state(BirthdayForm.waiting_for_description)

        user_data = await state.get_data()
        age = calculate_age(date_str)

        await message.answer(
            f"📝 <b>ШАГ 3 ИЗ 6: ДОПОЛНИТЕЛЬНАЯ ИНФОРМАЦИЯ</b>\n\n"
            f"<b>Добавляем:</b> {user_data['name']}\n"
            f"<b>Дата рождения:</b> {date_str}\n"
            f"<b>Сейчас:</b> {age} лет\n\n"
            "💡 <b>Зачем нужно описание?</b>\n"
            "• Поможет вспомнить, что нравится человеку\n"
            "• Можно использовать для выбора подарка\n"
            "• Добавит персонализации в поздравления\n\n"
            "Например:\n"
            "<i>• Любит кошек и путешествия</i>\n"
            "<i>• Увлекается футболом</i>\n"
            "<i>• Коллекционирует марки</i>\n\n"
            "Или нажмите 'Пропустить' если не хотите добавлять описание",
            reply_markup=get_skip_keyboard()
        )
    except ValueError:
        await message.answer(
            "❌ <b>НЕВЕРНЫЙ ФОРМАТ ДАТЫ!</b>\n"
            "Пожалуйста, введите дату в формате <b>ДД.ММ.ГГГГ</b>\n"
            "Например: <i>15.05.1990</i>"
        )


# Шаг 3: Получение описания (можно пропустить)
@router.message(BirthdayForm.waiting_for_description)
async def process_description(message: Message, state: FSMContext):
    user_data = await state.get_data()

    if message.text == "⏭️ Пропустить":
        description = None
    else:
        description = message.text.strip()
        if len(description) > 200:
            await message.answer(
                "❌ <b>ОПИСАНИЕ СЛИШКОМ ДЛИННОЕ!</b>\n"
                "Пожалуйста, укажите описание до 200 символов:"
            )
            return

    await state.update_data(description=description)
    await state.set_state(BirthdayForm.waiting_for_username)

    age = calculate_age(user_data['birthdate'])

    await message.answer(
        f"👤 <b>ШАГ 4 ИЗ 6: TELEGRAM ПРОФИЛЬ</b>\n\n"
        f"<b>Добавляем:</b> {user_data['name']}\n"
        f"<b>Дата рождения:</b> {user_data['birthdate']}\n"
        f"<b>Сейчас:</b> {age} лет\n"
        f"<b>Описание:</b> {description if description else 'не указано'}\n\n"
        "🔗 <b>Введите username в Telegram</b> (например, @username):\n\n"
        "Это необязательно, но если вы укажете username, то в день рождения я смогу отправить ссылку на профиль именинника.\n\n"
        "Например:\n"
        "<i>@username</i> - просто введите username с @ или без\n\n"
        "Или нажмите 'Пропустить' если не хотите указывать username.",
        reply_markup=get_skip_keyboard()
    )


# Шаг 4: Получение username
@router.message(BirthdayForm.waiting_for_username)
async def process_username(message: Message, state: FSMContext):
    if message.text == "⏭️ Пропустить":
        telegram_username = None
    else:
        text = message.text.strip()
        if text.startswith('@'):
            telegram_username = text[1:]
        else:
            telegram_username = text

    await state.update_data(telegram_username=telegram_username)
    await state.set_state(BirthdayForm.waiting_for_time)

    user_data = await state.get_data()
    age = calculate_age(user_data['birthdate'])

    await message.answer(
        f"⏰ <b>ШАГ 5 ИЗ 6: КОГДА НАПОМИНАТЬ?</b>\n\n"
        f"<b>Добавляем:</b> {user_data['name']}\n"
        f"<b>Дата рождения:</b> {user_data['birthdate']}\n"
        f"<b>Сейчас:</b> {age} лет\n"
        f"<b>Описание:</b> {user_data['description'] if user_data['description'] else 'не указано'}\n"
        f"<b>Username:</b> {user_data.get('telegram_username', 'не указан')}\n\n"
        "⏱️ <b>В какое время присылать напоминания?</b>\n"
        "Введите время в формате <b>ЧЧ:ММ</b>\n\n"
        "Например:\n"
        "<i>09:00</i> - утром\n"
        "<i>13:00</i> - в обед\n"
        "<i>18:00</i> - вечером\n\n"
        "📌 <b>Важно:</b> время указывается в <b>Московском часовом поясе (МСК)</b>\n"
        "По умолчанию: <b>09:00</b> (если не указать другое)",
        reply_markup=ReplyKeyboardRemove()
    )


# Шаг 5: Получение времени напоминаний
@router.message(BirthdayForm.waiting_for_time, F.text.regexp(r'^\d{1,2}:\d{2}$'))
async def process_time(message: Message, state: FSMContext):
    time_str = message.text.strip()

    try:
        hour, minute = map(int, time_str.split(':'))
        if hour < 0 or hour > 23 or minute < 0 or minute > 59:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ <b>НЕВЕРНОЕ ВРЕМЯ!</b>\n"
            "Пожалуйста, введите время в формате <b>ЧЧ:ММ</b>\n"
            "Часы: 0-23, минуты: 0-59\n"
            "Например: <i>09:00, 10:30, 18:00</i>"
        )
        return

    await state.update_data(reminder_time=time_str)

    user_data = await state.get_data()
    age = calculate_age(user_data['birthdate'])
    next_birthday = get_next_birthday(user_data['birthdate'], time_str)
    days_until = (next_birthday - get_moscow_now()).days

    summary_text = f"""
✅ <b>ШАГ 6 ИЗ 6: ПОДТВЕРЖДЕНИЕ</b>

📋 <b>ВСЕ ДАННЫЕ:</b>
👤 <b>Имя:</b> {user_data['name']}
📅 <b>Дата рождения:</b> {user_data['birthdate']}
🎂 <b>Сейчас:</b> {age} лет
📝 <b>Описание:</b> {user_data['description'] if user_data['description'] else 'не указано'}
🔗 <b>Username:</b> {user_data.get('telegram_username', 'не указан')}
⏰ <b>Время напоминаний:</b> {time_str} (МСК)
📆 <b>Следующий ДР:</b> через {days_until} дней

<b>🎯 ЧТО БУДЕТ ПРОИСХОДИТЬ:</b>
1. <b>За 3 дня до ДР</b> - напоминание о предстоящем событии
2. <b>За 1 день до ДР</b> - напоминание подготовиться
3. <b>В сам день рождения</b> - уведомление и готовое поздравление

<b>Сохранить и настроить напоминания?</b>
    """

    await state.set_state(BirthdayForm.confirm_add)
    await message.answer(summary_text, reply_markup=get_confirm_keyboard())


# Шаг 6: Подтверждение и сохранение
@router.message(BirthdayForm.confirm_add)
async def process_confirm(message: Message, state: FSMContext):
    if message.text == "✅ Да, сохранить":
        user_data = await state.get_data()

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                'SELECT id FROM birthdays WHERE name = ? AND chat_id = ?',
                (user_data['name'], message.chat.id)
            )
            existing = await cursor.fetchone()

            if existing:
                await message.answer(
                    f"⚠️ День рождения для {user_data['name']} уже добавлен!\n"
                    f"Используйте /delete чтобы удалить или /settings чтобы изменить.",
                    reply_markup=ReplyKeyboardRemove()
                )
                await state.clear()
                return

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                '''INSERT INTO birthdays (user_id, chat_id, name, birthdate, description, telegram_username, reminder_time) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (message.from_user.id, message.chat.id, user_data['name'], user_data['birthdate'],
                 user_data['description'], user_data['telegram_username'], user_data['reminder_time'])
            )
            await db.commit()

        await schedule_reminders(
            user_data['name'],
            user_data['birthdate'],
            message.chat.id,
            user_data['reminder_time'],
            user_data.get('telegram_username')
        )

        next_birthday = get_next_birthday(user_data['birthdate'], user_data['reminder_time'])
        days_until = (next_birthday - get_moscow_now()).days

        await message.answer(
            f"🎉 День рождения {user_data['name']} добавлен!\n"
            f"⏰ Напоминания: {user_data['reminder_time']} МСК\n"
            f"📆 Следующий ДР: через {days_until} дней",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.clear()

    elif message.text == "❌ Нет, отменить":
        await message.answer(
            "❌ Добавление отменено.",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.clear()
    else:
        await message.answer(
            "Пожалуйста, выберите вариант:",
            reply_markup=get_confirm_keyboard()
        )


# Команда /list - показываем каждого пользователя отдельным сообщением
@router.message(Command("list"))
async def cmd_list(message: Message):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            '''SELECT name, birthdate, reminder_time, telegram_username, description 
               FROM birthdays 
               WHERE user_id = ? 
               ORDER BY 
                 substr(birthdate, 4, 2) || substr(birthdate, 1, 2)''',
            (message.from_user.id,)
        )
        rows = await cursor.fetchall()

    if not rows:
        await message.answer(
            "📭 У вас пока нет добавленных дней рождения.\n\nДобавьте первый день рождения с помощью /add")
        return

    now_moscow = get_moscow_now()

    await message.answer("📋 <b>Ваши дни рождения:</b>")
    birthdays_with_days = []
    for name, date, time, username, description in rows:
        next_birthday = get_next_birthday(date, time)
        days_until = (next_birthday - now_moscow).days
        age_on_birthday = calculate_age_on_date(date, next_birthday)
        birthdays_with_days.append((name, date, time, username, description, days_until, age_on_birthday))

    birthdays_with_days.sort(key=lambda x: x[5])
    for name, date, time, username, description, days_until, age in birthdays_with_days:
        profile_link = ""
        if username:
            profile_link = f"\n🔗 Профиль: @{username}"

        text = f"👤 <b>{name}</b>\n"
        text += f"📅 Родился: {date}\n"
        text += f"🎂 Будет: {age} лет\n"
        text += f"⏰ Напоминание: {time} МСК\n"

        if days_until == 0:
            text += f"📆 <b>🎉 ДЕНЬ РОЖДЕНИЯ СЕГОДНЯ!</b>\n"
        elif days_until == 1:
            text += f"📆 <b>Завтра!</b>\n"
        else:
            text += f"📆 Через {days_until} дней\n"

        if description:
            text += f"📝 {description}\n"

        text += profile_link

        await message.answer(text)

# Команда /settings - настройки
@router.message(Command("settings"))
async def cmd_settings(message: Message, state: FSMContext):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            '''SELECT name, reminder_time, remind_3_days, remind_1_day, remind_day, telegram_username
               FROM birthdays WHERE user_id = ?''',
            (message.from_user.id,)
        )
        rows = await cursor.fetchall()

    if not rows:
        await message.answer(
            "📭 У вас пока нет добавленных дней рождения.\n\nДобавьте первый день рождения с помощью /add")
        return

    response = "⚙️ <b>Настройки напоминаний</b>\n\n"
    response += "📋 <b>Список:</b> (выберите для настройки)\n\n"

    keyboard_buttons = []
    for name, time, r3d, r1d, rd, username in rows:
        status_3d = "✅" if r3d else "❌"
        status_1d = "✅" if r1d else "❌"
        status_d = "✅" if rd else "❌"

        response += f"👤 <b>{name}</b>\n"
        response += f"   ⏰ Время: {time} МСК\n"
        response += f"   📅 -3 дня: {status_3d} | -1 день: {status_1d} | В день: {status_d}\n\n"

        keyboard_buttons.append([KeyboardButton(text=f"⚙️ {name}")])

    keyboard_buttons.append([KeyboardButton(text="❌ Отмена")])

    keyboard = ReplyKeyboardMarkup(
        keyboard=keyboard_buttons,
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await state.set_state(SettingsForm.waiting_for_name_to_set)
    await message.answer(response, reply_markup=keyboard)

@router.message(SettingsForm.waiting_for_name_to_set)
async def process_settings_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await message.answer("❌ Настройки отменены.", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        return

    if message.text.startswith("⚙️ "):
        name = message.text[3:].strip()
    else:
        name = message.text.strip()

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            '''SELECT reminder_time, remind_3_days, remind_1_day, remind_day, birthdate, telegram_username 
               FROM birthdays WHERE name = ? AND user_id = ?''',
            (name, message.from_user.id)
        )
        row = await cursor.fetchone()

    if not row:
        await message.answer("❌ Не найдено дня рождения для этого имени.", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        return

    time, r3d, r1d, rd, birthdate, username = row

    await state.update_data(
        settings_name=name,
        current_time=time,
        current_3d=r3d,
        current_1d=r1d,
        current_day=rd,
        birthdate=birthdate,
        current_username=username
    )

    response = f"⚙️ <b>Настройки для: {name}</b>\n\n"
    response += f"📅 Дата рождения: {birthdate}\n"
    response += f"⏰ Текущее время: {time} МСК\n"
    response += f"🔗 Username: {username if username else 'не указан'}\n"
    response += f"📅 Напоминания:\n"
    response += f"   • За 3 дня: {'✅ Вкл' if r3d else '❌ Выкл'}\n"
    response += f"   • За 1 день: {'✅ Вкл' if r1d else '❌ Выкл'}\n"
    response += f"   • В день: {'✅ Вкл' if rd else '❌ Выкл'}\n\n"
    response += "Выберите параметр для изменения:"

    await state.set_state(SettingsForm.waiting_for_parameter)
    await message.answer(response, reply_markup=get_settings_keyboard())

@router.message(SettingsForm.waiting_for_parameter)
async def process_settings_parameter(message: Message, state: FSMContext):
    user_data = await state.get_data()

    if message.text == "❌ Отмена":
        await message.answer("❌ Настройки отменены.", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        return

    elif message.text == "⏰ Изменить время":
        await state.set_state(SettingsForm.waiting_for_value)
        await state.update_data(parameter='time')
        await message.answer(
            f"⏰ Введите новое время напоминаний для {user_data['settings_name']}\n\n"
            f"Текущее время: <b>{user_data['current_time']} МСК</b>\n"
            "Формат: <b>ЧЧ:ММ</b>\n"
            "Например: <i>09:00, 10:30, 18:00</i>",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="❌ Отмена")]],
                resize_keyboard=True
            )
        )

    elif message.text == "📅 Настроить напоминания":
        response = f"📅 Настройка напоминаний для {user_data['settings_name']}\n\n"
        response += "Выберите, какие напоминания включить:\n\n"

        keyboard = ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="✅ Включить все")],
                [KeyboardButton(text="❌ Выключить все")],
                [KeyboardButton(text="✏️ Настроить вручную")],
                [KeyboardButton(text="❌ Отмена")]
            ],
            resize_keyboard=True,
            one_time_keyboard=True
        )

        await state.set_state(SettingsForm.waiting_for_value)
        await state.update_data(parameter='reminders')
        await message.answer(response, reply_markup=keyboard)

    elif message.text == "🔗 Изменить username":
        await state.set_state(SettingsForm.waiting_for_value)
        await state.update_data(parameter='username')
        await message.answer(
            f"🔗 Введите новый username для {user_data['settings_name']}\n\n"
            f"Текущий username: <b>{user_data['current_username'] if user_data['current_username'] else 'не указан'}</b>\n"
            "Формат: <b>username</b> (с @ или без)\n"
            "Например: <i>@username</i> или просто <i>username</i>\n\n"
            "Или напишите <b>удалить</b> чтобы убрать username",
            reply_markup=ReplyKeyboardMarkup(
                keyboard=[[KeyboardButton(text="❌ Отмена")]],
                resize_keyboard=True
            )
        )

    else:
        await message.answer("Пожалуйста, выберите параметр из списка.")

@router.message(SettingsForm.waiting_for_value)
async def process_settings_value(message: Message, state: FSMContext):
    user_data = await state.get_data()

    if message.text == "❌ Отмена":
        await message.answer("❌ Настройки отменены.", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        return

    if user_data['parameter'] == 'time':
        if not re.match(r'^\d{1,2}:\d{2}$', message.text):
            await message.answer(
                "❌ Неверный формат времени!\n"
                "Пожалуйста, введите время в формате <b>ЧЧ:ММ</b>\n"
                "Например: <i>09:00, 10:30, 18:00</i>"
            )
            return

        time_str = message.text.strip()
        try:
            hour, minute = map(int, time_str.split(':'))
            if hour < 0 or hour > 23 or minute < 0 or minute > 59:
                raise ValueError
        except ValueError:
            await message.answer(
                "❌ Неверное время!\n"
                "Часы: 0-23, минуты: 0-59"
            )
            return

        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                'UPDATE birthdays SET reminder_time = ? WHERE name = ? AND user_id = ?',
                (time_str, user_data['settings_name'], message.from_user.id)
            )
            await db.commit()

        # Перепланируем напоминания
        remove_scheduled_reminders(message.chat.id, user_data['settings_name'])
        await schedule_reminders(
            user_data['settings_name'],
            user_data['birthdate'],
            message.chat.id,
            time_str,
            user_data.get('current_username')
        )

        await message.answer(
            f"✅ Время напоминаний для {user_data['settings_name']} изменено на {time_str} МСК",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.clear()

    elif user_data['parameter'] == 'reminders':
        if message.text == "✅ Включить все":
            r3d, r1d, rd = 1, 1, 1
        elif message.text == "❌ Выключить все":
            r3d, r1d, rd = 0, 0, 0
        elif message.text == "✏️ Настроить вручную":
            # Создаем клавиатуру для ручной настройки
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="✅ -3 дня"), KeyboardButton(text="❌ -3 дня")],
                    [KeyboardButton(text="✅ -1 день"), KeyboardButton(text="❌ -1 день")],
                    [KeyboardButton(text="✅ В день"), KeyboardButton(text="❌ В день")],
                    [KeyboardButton(text="✅ Сохранить"), KeyboardButton(text="❌ Отмена")]
                ],
                resize_keyboard=True
            )

            await state.update_data(
                manual_3d=user_data['current_3d'],
                manual_1d=user_data['current_1d'],
                manual_day=user_data['current_day']
            )

            response = f"✏️ Ручная настройка для {user_data['settings_name']}\n\n"
            response += "Текущие настройки:\n"
            response += f"• За 3 дня: {'✅ Вкл' if user_data['current_3d'] else '❌ Выкл'}\n"
            response += f"• За 1 день: {'✅ Вкл' if user_data['current_1d'] else '❌ Выкл'}\n"
            response += f"• В день: {'✅ Вкл' if user_data['current_day'] else '❌ Выкл'}\n\n"
            response += "Нажмите на кнопку чтобы изменить состояние, затем 'Сохранить'"

            await message.answer(response, reply_markup=keyboard)
            return

        elif message.text in ["✅ -3 дня", "❌ -3 дня", "✅ -1 день", "❌ -1 день", "✅ В день", "❌ В день"]:
            # Обработка ручной настройки
            manual_data = await state.get_data()
            r3d = manual_data.get('manual_3d', user_data['current_3d'])
            r1d = manual_data.get('manual_1d', user_data['current_1d'])
            rd = manual_data.get('manual_day', user_data['current_day'])

            if message.text in ["✅ -3 дня", "❌ -3 дня"]:
                r3d = 1 if "✅" in message.text else 0
            elif message.text in ["✅ -1 день", "❌ -1 день"]:
                r1d = 1 if "✅" in message.text else 0
            elif message.text in ["✅ В день", "❌ В день"]:
                rd = 1 if "✅" in message.text else 0

            await state.update_data(manual_3d=r3d, manual_1d=r1d, manual_day=rd)

            response = f"✏️ Ручная настройка для {user_data['settings_name']}\n\n"
            response += "Текущие настройки:\n"
            response += f"• За 3 дня: {'✅ Вкл' if r3d else '❌ Выкл'}\n"
            response += f"• За 1 день: {'✅ Вкл' if r1d else '❌ Выкл'}\n"
            response += f"• В день: {'✅ Вкл' if rd else '❌ Выкл'}\n\n"
            response += "Нажмите 'Сохранить' чтобы применить изменения"

            await message.answer(response)
            return

        elif message.text == "✅ Сохранить":
            # Получаем ручные настройки
            manual_data = await state.get_data()
            r3d = manual_data.get('manual_3d', user_data['current_3d'])
            r1d = manual_data.get('manual_1d', user_data['current_1d'])
            rd = manual_data.get('manual_day', user_data['current_day'])

        else:
            await message.answer("Пожалуйста, выберите вариант из списка.")
            return

        # Обновляем в базе данных
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                '''UPDATE birthdays 
                   SET remind_3_days = ?, remind_1_day = ?, remind_day = ? 
                   WHERE name = ? AND user_id = ?''',
                (r3d, r1d, rd, user_data['settings_name'], message.from_user.id)
            )
            await db.commit()

        # Перепланируем напоминания если нужно
        if r3d == 0:
            remove_specific_reminder(message.chat.id, user_data['settings_name'], '3d')
        if r1d == 0:
            remove_specific_reminder(message.chat.id, user_data['settings_name'], '1d')
        if rd == 0:
            remove_specific_reminder(message.chat.id, user_data['settings_name'], 'day_notification')
            remove_specific_reminder(message.chat.id, user_data['settings_name'], 'day_congrats')

        response = f"✅ Настройки напоминаний для {user_data['settings_name']} обновлены:\n\n"
        response += f"• За 3 дня: {'✅ Включено' if r3d else '❌ Выключено'}\n"
        response += f"• За 1 день: {'✅ Включено' if r1d else '❌ Выключено'}\n"
        response += f"• В день: {'✅ Включено' if rd else '❌ Выключено'}"

        await message.answer(response, reply_markup=ReplyKeyboardRemove())
        await state.clear()

    elif user_data['parameter'] == 'username':
        if message.text.lower() == 'удалить':
            new_username = None
        else:
            text = message.text.strip()
            if text.startswith('@'):
                new_username = text[1:]  # Убираем @
            else:
                new_username = text

        # Обновляем в базе данных
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                'UPDATE birthdays SET telegram_username = ? WHERE name = ? AND user_id = ?',
                (new_username, user_data['settings_name'], message.from_user.id)
            )
            await db.commit()

        await state.update_data(current_username=new_username)

        if new_username:
            await message.answer(
                f"✅ Username для {user_data['settings_name']} обновлен: @{new_username}",
                reply_markup=ReplyKeyboardRemove()
            )
        else:
            await message.answer(
                f"✅ Username для {user_data['settings_name']} удален",
                reply_markup=ReplyKeyboardRemove()
            )

        await state.clear()

    else:
        await message.answer("Пожалуйста, выберите вариант из списка.")

# Удаление ДР: /del Имя
@router.message(Command("delete", "del", "remove"))
async def cmd_delete(message: Message, state: FSMContext):
    # Показываем список для выбора
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            'SELECT name FROM birthdays WHERE user_id = ?',
            (message.from_user.id,)
        )
        rows = await cursor.fetchall()

    if not rows:
        await message.answer("📭 У вас пока нет добавленных дней рождения.")
        return

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=row[0])] for row in rows] +
                 [[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    response = "🗑️ Выберите день рождения для удаления:\n\n"
    for name, in rows:
        response += f"• {name}\n"

    await state.set_state(DeleteForm.waiting_for_name_to_delete)
    await message.answer(response, reply_markup=keyboard)


@router.message(DeleteForm.waiting_for_name_to_delete)
async def process_delete_name(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await message.answer("❌ Удаление отменено.", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        return

    name_to_delete = message.text.strip()

    # Проверяем существование
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            'SELECT birthdate FROM birthdays WHERE name = ? AND user_id = ?',
            (name_to_delete, message.from_user.id)
        )
        row = await cursor.fetchone()

    if not row:
        await message.answer(f"❌ Не найдено дня рождения для {name_to_delete}.", reply_markup=ReplyKeyboardRemove())
        await state.clear()
        return

    await state.update_data(name_to_delete=name_to_delete, birthdate=row[0])
    await state.set_state(DeleteForm.confirm_delete)

    await message.answer(
        f"⚠️ Вы уверены, что хотите удалить {name_to_delete}?\n\nЭто действие нельзя отменить!",
        reply_markup=get_confirm_keyboard()
    )


@router.message(DeleteForm.confirm_delete)
async def process_confirm_delete(message: Message, state: FSMContext):
    user_data = await state.get_data()

    if message.text == "✅ Да, сохранить":
        # Удаляем из базы данных
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute(
                'DELETE FROM birthdays WHERE name = ? AND user_id = ?',
                (user_data['name_to_delete'], message.from_user.id)
            )
            await db.commit()

        remove_scheduled_reminders(message.chat.id, user_data['name_to_delete'])

        await message.answer(
            f"✅ День рождения {user_data['name_to_delete']} удален.\nВсе напоминания отменены.",
            reply_markup=ReplyKeyboardRemove()
        )
    else:
        await message.answer("❌ Удаление отменено.", reply_markup=ReplyKeyboardRemove())

    await state.clear()


# Функция для получения следующей даты дня рождения
def get_next_birthday(birthdate_str, reminder_time):
    birthdate = datetime.strptime(birthdate_str, '%d.%m.%Y')
    hour, minute = map(int, reminder_time.split(':'))

    now = get_moscow_now()

    this_year_birth = birthdate.replace(
        year=now.year,
        hour=hour,
        minute=minute,
        second=0,
        tzinfo=MOSCOW_TZ
    )

    if this_year_birth < now:
        this_year_birth = this_year_birth.replace(year=now.year + 1)

    return this_year_birth

scheduler = AsyncIOScheduler()


# Отправка НАПОМИНАНИЯ (за 3 и 1 день)
async def send_reminder(chat_id, text):
    await bot.send_message(chat_id, text)


# Отправка УВЕДОМЛЕНИЯ в день рождения (первое сообщение)
async def send_birthday_notification(chat_id, name, telegram_username=None):
    profile_link = ""
    if telegram_username:
        profile_link = f"\n\n🔗 Можете поздравить здесь: @{telegram_username}"

    message = f"🎉 <b>Сегодня день рождения у {name}!</b>{profile_link}\n\n👇 Вот готовое поздравление:"
    await bot.send_message(chat_id, message)


# Отправка ПОЗДРАВЛЕНИЯ в день рождения (второе сообщение)
async def send_congrats_message(chat_id, name, birthdate_str, description=None):
    congrats = generate_congrats(name, birthdate_str, description)
    message = f"{congrats}\n\n💌 <i>Это сообщение можно отправить {name} для поздравления!</i>"
    await bot.send_message(chat_id, message)


async def schedule_reminders(name, birthdate_str, chat_id, reminder_time="09:00", telegram_username=None):
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            'SELECT remind_3_days, remind_1_day, remind_day FROM birthdays WHERE name = ? AND chat_id = ?',
            (name, chat_id)
        )
        settings_row = await cursor.fetchone()

    if not settings_row:
        return
    remind_3d, remind_1d, remind_day = settings_row
    next_birthday = get_next_birthday(birthdate_str, reminder_time)

    # За 3 дня - НАПОМИНАНИЕ
    if remind_3d:
        reminder_3d = next_birthday - timedelta(days=3)
        job_id = f"{chat_id}_{name}_3d"
        reminder_utc = reminder_3d.astimezone(ZoneInfo("UTC"))

        scheduler.add_job(
            send_reminder,
            DateTrigger(run_date=reminder_utc),
            id=job_id,
            args=[chat_id, f"⏰ Напоминание: Через 3 дня у {name} день рождения!"]
        )

    # За 1 день - НАПОМИНАНИЕ
    if remind_1d:
        reminder_1d = next_birthday - timedelta(days=1)
        job_id = f"{chat_id}_{name}_1d"
        reminder_utc = reminder_1d.astimezone(ZoneInfo("UTC"))

        scheduler.add_job(
            send_reminder,
            DateTrigger(run_date=reminder_utc),
            id=job_id,
            args=[chat_id, f"⏰ Напоминание: Завтра у {name} день рождения!"]
        )

    # В день рождения - сначала уведомление, затем поздравление
    if remind_day:
        job_id = f"{chat_id}_{name}_day_notification"
        birthday_utc = next_birthday.astimezone(ZoneInfo("UTC"))

        scheduler.add_job(
            send_birthday_notification,
            DateTrigger(run_date=birthday_utc),
            id=job_id,
            args=[chat_id, name, telegram_username]
        )
        job_id = f"{chat_id}_{name}_day_congrats"
        congrats_time = birthday_utc + timedelta(seconds=2)
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                'SELECT description FROM birthdays WHERE name = ? AND chat_id = ?',
                (name, chat_id)
            )
            description_row = await cursor.fetchone()

        description = description_row[0] if description_row else None

        scheduler.add_job(
            send_congrats_message,
            DateTrigger(run_date=congrats_time),
            id=job_id,
            args=[chat_id, name, birthdate_str, description]
        )

    # Планируем на следующий год
    next_year_birthday = next_birthday.replace(year=next_birthday.year + 1)
    job_id = f"{chat_id}_{name}_annual"
    next_year_utc = next_year_birthday.astimezone(ZoneInfo("UTC"))

    scheduler.add_job(
        schedule_reminders,
        DateTrigger(run_date=next_year_utc + timedelta(days=1)),
        id=job_id,
        args=[name, birthdate_str, chat_id, reminder_time, telegram_username]
    )


# Функции для удаления напоминаний
def remove_scheduled_reminders(chat_id, name):
    job_ids = [
        f"{chat_id}_{name}_3d",
        f"{chat_id}_{name}_1d",
        f"{chat_id}_{name}_day_notification",
        f"{chat_id}_{name}_day_congrats",
        f"{chat_id}_{name}_annual"
    ]

    for job_id in job_ids:
        try:
            scheduler.remove_job(job_id)
        except:
            pass


def remove_specific_reminder(chat_id, name, reminder_type):
    job_id = f"{chat_id}_{name}_{reminder_type}"
    try:
        scheduler.remove_job(job_id)
    except:
        pass


async def main():
    await init_db()

    dp = Dispatcher()
    dp.include_router(router)

    scheduler.configure(timezone=ZoneInfo("UTC"))
    scheduler.start()

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute('SELECT name, birthdate, chat_id, reminder_time, telegram_username FROM birthdays')
        rows = await cursor.fetchall()

    for name, birthdate, chat_id, reminder_time, telegram_username in rows:
        await schedule_reminders(name, birthdate, chat_id, reminder_time, telegram_username)

    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())