import logging

import sqlite3

import uuid

from aiogram import Bot, Dispatcher, types, F

from aiogram.fsm.storage.memory import MemoryStorage

from aiogram.fsm.context import FSMContext

from aiogram.fsm.state import State, StatesGroup

from aiogram.filters.command import Command

import google.generativeai as genai

from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder

from aiogram.types import InlineKeyboardButton

import asyncio

from aiogram.types import CallbackQuery

import os

import warnings

from aiogram.types import Message

from aiogram.enums import ParseMode

from datetime import datetime, timedelta

import calendar

from contextlib import contextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from apscheduler.triggers.date import DateTrigger

from datetime import datetime, timedelta

from pytz import timezone

import re

import docx



TIMEZONE = timezone('Asia/Almaty')

warnings.filterwarnings("ignore", message="Timezone offset does not match system offset")



BOT_TOKEN = '7840665570:AAGQK-0rG6SaZYuNpEE9w2G9WjgmbHcgCrY'

GEMINI_API_KEYS = [

    'AIzaSyCLXytzaJR4hcOMIstA8kzE1luMkkfakZQ'

]

current_api_key_index = 0



# Функция для получения текущего API-ключа

def get_current_api_key():

    global current_api_key_index

    api_key = GEMINI_API_KEYS[current_api_key_index]

    current_api_key_index = (current_api_key_index + 1) % len(GEMINI_API_KEYS)

    return api_key



# Используйте функцию get_current_api_key для получения текущего API-ключа

# при инициализации модели GenerativeModel

GEMINI_API_KEY = get_current_api_key()

genai.configure(api_key=GEMINI_API_KEY)



# Обновите API-ключ перед каждым запросом

def update_api_key():

    global GEMINI_API_KEY

    GEMINI_API_KEY = get_current_api_key()

    genai.configure(api_key=GEMINI_API_KEY)





logging.basicConfig(

    level=logging.INFO,

    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',

    handlers=[

        logging.FileHandler("bot.log"),

        logging.StreamHandler()

    ]

)

logger = logging.getLogger(__name__)



bot = Bot(token=BOT_TOKEN)

storage = MemoryStorage()

dp = Dispatcher(storage=storage)



model = genai.GenerativeModel('gemini-1.5-pro')



generation_config = {

    "temperature": 0.9,

    "top_p": 1,

    "top_k": 1,

    "max_output_tokens": 2048,

}



safety_settings = [

    {

        "category": "HARM_CATEGORY_HARASSMENT",

        "threshold": "BLOCK_MEDIUM_AND_ABOVE"

    },

    {

        "category": "HARM_CATEGORY_HATE_SPEECH",

        "threshold": "BLOCK_MEDIUM_AND_ABOVE"

    },

    {

        "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",

        "threshold": "BLOCK_MEDIUM_AND_ABOVE"

    },

    {

        "category": "HARM_CATEGORY_DANGEROUS_CONTENT",

        "threshold": "BLOCK_MEDIUM_AND_ABOVE"

    },

]





chat = model.start_chat(history=[])



scheduler = AsyncIOScheduler(timezone=TIMEZONE)



class UserStates(StatesGroup):

    waiting_for_user_type = State()

    waiting_for_user_name = State()

    waiting_for_class_name = State()

    waiting_for_class_selection = State()

    waiting_for_assignment = State()

    waiting_for_deadline_year = State()

    waiting_for_deadline_month = State()

    waiting_for_deadline_day = State()

    waiting_for_deadline_time = State()

    waiting_for_submission = State()

    waiting_for_assignment_method = State()

    editing_profile = State()

    waiting_for_user_type = State()

    waiting_for_generation_request = State()

    waiting_for_generation_choice = State()

@contextmanager

def get_db_connection():

    conn = sqlite3.connect('education_bot.db')

    try:

        yield conn

    finally:

        conn.close()



def init_db():

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute('''CREATE TABLE IF NOT EXISTS teachers

                     (id INTEGER PRIMARY KEY, name TEXT)''')

        c.execute('''CREATE TABLE IF NOT EXISTS students

                     (id INTEGER PRIMARY KEY, name TEXT, class_id INTEGER)''')

        c.execute('''CREATE TABLE IF NOT EXISTS classes

                     (id INTEGER PRIMARY KEY, teacher_id INTEGER, class_name TEXT)''')

        c.execute('''CREATE TABLE IF NOT EXISTS assignments

                     (id INTEGER PRIMARY KEY, class_id INTEGER, text TEXT, deadline DATETIME)''')

        c.execute('''CREATE TABLE IF NOT EXISTS submissions

                     (id INTEGER PRIMARY KEY, assignment_id INTEGER, student_id INTEGER, 

                      answer TEXT, evaluation REAL, feedback TEXT)''')

        c.execute('''CREATE TABLE IF NOT EXISTS links

                     (id INTEGER PRIMARY KEY, class_id INTEGER, link TEXT)''')

        conn.commit()



def show_links(user_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        # Сначала получаем class_id пользователя из таблицы students

        c.execute("SELECT class_id FROM students WHERE id = ?", (user_id,))

        class_id = c.fetchone()[0]

        

        # Затем получаем ссылку из таблицы links по class_id

        c.execute("SELECT link FROM links WHERE class_id = ?", (class_id,))

        link = c.fetchone()[0]

        

        # Возвращаем ссылку

        return link



# Database operations

def add_student(student_id, name, class_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("INSERT INTO students (id, name, class_id) VALUES (?, ?, ?)",

                  (student_id, name, class_id))

        conn.commit()



def is_teacher(user_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("SELECT id FROM teachers WHERE id = ?", (user_id,))

        return c.fetchone() is not None



def get_teacher_classes(teacher_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("SELECT id, class_name FROM classes WHERE teacher_id = ?", (teacher_id,))

        return c.fetchall()



def get_student_class(student_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("SELECT class_id FROM students WHERE id = ?", (student_id,))

        result = c.fetchone()

        return result[0] if result else None



def get_class_assignments(class_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("SELECT id, text, deadline FROM assignments WHERE class_id = ?", (class_id,))

        return c.fetchall()



def add_assignment(class_id, text, deadline):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("SELECT MAX(id) FROM assignments WHERE class_id = ?", (class_id,))

        max_id = c.fetchone()[0]

        if max_id is None:

            assignment_id = 1

        else:

            assignment_id = max_id + 1

        c.execute("INSERT INTO assignments (class_id, id, text, deadline) VALUES (?, ?, ?, ?)",

                  (class_id, assignment_id, text, deadline))

        conn.commit()

        return assignment_id



def add_submission(assignment_id, student_id, answer, evaluation, feedback):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("""INSERT INTO submissions 

                     (assignment_id, student_id, answer, evaluation, feedback) 

                     VALUES (?, ?, ?, ?, ?)""",

                  (assignment_id, student_id, answer, evaluation, feedback))

        conn.commit()



def get_class_students(class_id):

    with get_db_connection() as conn:

        c = conn.cursor()

        c.execute("SELECT id, name FROM students WHERE class_id = ?", (class_id,))

        return c.fetchall()



def get_teacher_keyboard():

    builder = ReplyKeyboardBuilder()

    builder.button(text="👤 Мой профиль")

    builder.button(text="➕ Создать класс")

    builder.button(text="📝 Добавить задание")

    builder.button(text="📚 Мои классы")

    builder.button(text="🔗 Мои ссылки")

    builder.button(text="📊 Статистика класса")

    builder.button(text="📝 Посмотреть мои задания")

    builder.button(text="📊 Посмотреть оценки учеников")  # Новая кнопка

    builder.adjust(2)

    return builder.as_markup(resize_keyboard=True)



def get_student_keyboard():

    builder = ReplyKeyboardBuilder()

    builder.button(text="👤 Мой профиль")

    builder.button(text="📚 Мои задания")

    builder.button(text="📝 Отправить работу")

    builder.button(text="✏️ Редактировать профиль")

    builder.adjust(2)

    return builder.as_markup(resize_keyboard=True)



def get_calendar_keyboard(year, month):

    builder = InlineKeyboardBuilder()

    month_calendar = calendar.monthcalendar(year, month)

    

    builder.row(InlineKeyboardButton(

        text=f"{calendar.month_name[month]} {year}",

        callback_data="ignore"

    ))

    

    days = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    for day in days:

        builder.add(InlineKeyboardButton(text=day, callback_data="ignore"))

    builder.adjust(7)

    

    for week in month_calendar:

        for day in week:

            if day == 0:

                builder.add(InlineKeyboardButton(text=" ", callback_data="ignore"))

            else:

                builder.add(InlineKeyboardButton(

                    text=str(day),

                    callback_data=f"date:{year}:{month}:{day}"

                ))

    builder.adjust(7)

    

    prev_month = month - 1 if month > 1 else 12

    prev_year = year if month > 1 else year - 1

    next_month = month + 1 if month < 12 else 1

    next_year = year if month < 12 else year + 1

    

    builder.row(

        InlineKeyboardButton(text="◀️", callback_data=f"month:{prev_year}:{prev_month}"),

        InlineKeyboardButton(text="▶️", callback_data=f"month:{next_year}:{next_month}")

    )

    

    return builder.as_markup()



# Command handlers

@dp.message(Command("start"))

async def cmd_start(message: types.Message, state: FSMContext):

    args = message.text.split()[1:] if len(message.text.split()) > 1 else None

    

    if args:  

        class_id = args[0]

        await message.reply("Добро пожаловать! Вы присоединяетесь к классу. Введите ваше имя.")

        await state.set_state(UserStates.waiting_for_user_name)

        await state.update_data(class_id=class_id)

    else:  

        profile = get_user_profile(message.from_user.id)

        if profile:

            keyboard = get_teacher_keyboard() if profile['type'] == 'teacher' else get_student_keyboard()

            await message.reply(f"С возвращением, {profile['name']}!", reply_markup=keyboard)

        else:

            await message.reply("Добро пожаловать! Вы учитель или ученик? (Введите 'учитель' или 'ученик')")

            await state.set_state(UserStates.waiting_for_user_type)



@dp.message(UserStates.waiting_for_user_type)

async def process_user_type(message: types.Message, state: FSMContext):

    user_type = message.text.lower().strip()

    if user_type in ['учитель', 'ученик']:

        await state.update_data(user_type=user_type)

        await message.reply("Введите ваше имя:")

        await state.set_state(UserStates.waiting_for_user_name)

    else:

        await message.reply("Пожалуйста, введите 'учитель' или 'ученик'.")



@dp.message(UserStates.waiting_for_user_name)

async def process_name(message: types.Message, state: FSMContext):

    data = await state.get_data()

    class_id = data.get('class_id')

    user_type = data.get('user_type')

    

    try:

        if class_id:  

            add_student(message.from_user.id, message.text, class_id)

            await message.reply("Вы успешно зарегистрированы в классе!", reply_markup=get_student_keyboard())

        elif user_type == 'учитель':

            with get_db_connection() as conn:

                c = conn.cursor()

                c.execute("INSERT INTO teachers (id, name) VALUES (?, ?)", 

                          (message.from_user.id, message.text))

                conn.commit()

            await message.reply("Регистрация учителя завершена!", reply_markup=get_teacher_keyboard())

        elif user_type == 'ученик':

            await message.reply("Для регистрации ученика необходима ссылка-приглашение от учителя.")

        

    except sqlite3.IntegrityError:

        await message.reply("Ошибка: этот пользователь уже зарегистрирован.")

    except Exception as e:

        logger.error(f"Ошибка при регистрации: {e}")

        await message.reply("Произошла ошибка при регистрации. Пожалуйста, попробуйте ещё раз.")

    

    await state.clear()



# Keyboard handlers

@dp.message(F.text == "👤 Мой профиль")

async def show_profile(message: types.Message):

    profile = get_user_profile(message.from_user.id)

    if profile:

        if profile['type'] == 'teacher':

            classes_text = "\n".join([f"📚 {name}" for _, name in profile['classes']])

            response = f"👤 Ваш профиль\n\nИмя: {profile['name']}\nСтатус: Учитель\n\nВаши классы:\n{classes_text}"

        else:

            response = f"👤 Ваш профиль\n\nИмя: {profile['name']}\nСтатус: Ученик\nКласс: {profile['class']}"

        await message.reply(response, parse_mode=ParseMode.MARKDOWN)

    else:

        await message.reply("Профиль не найден.")



@dp.message(F.text == "✏️ Редактировать профиль")

async def edit_profile(message: types.Message, state: FSMContext):

    await message.reply("Введите новое имя:")

    await state.set_state(UserStates.editing_profile)



@dp.message(UserStates.editing_profile)

async def process_profile_edit(message: types.Message, state: FSMContext):

    new_name = message.text.strip()

    update_user_profile(message.from_user.id, new_name)

    await message.reply("Профиль успешно обновлен!")

    await state.clear()



# Class management

@dp.message(F.text == "📚 Мои классы")

async def show_classes(message: types.Message):

    if is_teacher(message.from_user.id):

        classes = get_teacher_classes(message.from_user.id)

        if classes:

            response = "📚 Ваши классы:\n\n"

            for class_id, class_name in classes:

                students = get_class_students(class_id)

                students_text = "\n".join([f"👤 {name}" for _, name in students])

                response += f"{class_name}\nУченики:\n{students_text}\n\n"

            await message.reply(response, parse_mode=ParseMode.MARKDOWN)

        else:

            await message.reply("У вас пока нет классов.")

    else:

        student_class = get_student_class(message.from_user.id)

        if student_class:

            class_name = get_class_name(student_class)

            students = get_class_students(student_class)

            response = f"📚 Ваш класс: {class_name}\n\nОдноклассники:\n"

            response += "\n".join([f"👤 {name}" for _, name in students])

            await message.reply(response, parse_mode=ParseMode.MARKDOWN)

        else:

            await message.reply("Вы не состоите в классе.")

@dp.message(F.text == "📝 Отправить работу")

async def start_submission(message: types.Message, state: FSMContext):

    student_class_id = get_student_class(message.from_user.id)

    if not student_class_id:

        await message.reply("Вы не зарегистрированы в классе.")

        return

    

    assignments = get_class_assignments(student_class_id)

    if not assignments:

        await message.reply("В вашем классе пока нет заданий.")

        return

    

    keyboard = InlineKeyboardBuilder()

    for assignment_id, text, deadline in assignments:

        if deadline is not None:

            deadline_naive = datetime.strptime(deadline, '%Y-%m-%d %H:%M')

            deadline = TIMEZONE.localize(deadline_naive)

            if datetime.now(TIMEZONE) <= deadline:

                keyboard.add(InlineKeyboardButton(

                    text=f"Задание {assignment_id}",

                    callback_data=f"submit:{assignment_id}"

                ))

        else:

            keyboard.add(InlineKeyboardButton(

                text=f"Задание {assignment_id}",

                callback_data=f"submit:{assignment_id}"

            ))

    keyboard.adjust(1)

    

    await message.reply("Выберите задание для отправки ответа:", 

                        reply_markup=keyboard.as_markup())

    await state.set_state(UserStates.waiting_for_submission)



# Assignment management

@dp.message(F.text == "📝 Добавить задание")

async def add_assignment_start(message: types.Message, state: FSMContext):

    if not is_teacher(message.from_user.id):

        await message.reply("Эта функция доступна только для учителей.")

        return

    

    classes = get_teacher_classes(message.from_user.id)

    if not classes:

        await message.reply("У вас пока нет классов.")

        return

    

    keyboard = InlineKeyboardBuilder()

    for class_id, class_name in classes:

        keyboard.add(InlineKeyboardButton(

            text=class_name,

            callback_data=f"class:{class_id}"

        ))

    keyboard.adjust(2)

    

    await message.reply("Выберите класс, в котором хотите добавить задание:", reply_markup=keyboard.as_markup())

    await state.set_state(UserStates.waiting_for_class_selection)



@dp.message(UserStates.waiting_for_generation_request)

async def process_generation_request(message: types.Message, state: FSMContext):

    update_api_key()  # Обновите API-ключ перед запросом

    request = message.text

    await state.update_data(generation_request=request)



    # Генерация задания по запросу

    prompt = f"Сгенерируйте задание по запросу: {request}"

    response = chat.send_message(

        prompt,

        generation_config=generation_config,

        safety_settings=safety_settings

    )

    generated_assignment = response.text

    # ...

    

    await state.update_data(generated_assignment_text=generated_assignment)

    

    keyboard = InlineKeyboardBuilder()

    keyboard.add(InlineKeyboardButton(

        text="Выбрать",

        callback_data="select_generated_assignment"

    ))

    keyboard.add(InlineKeyboardButton(

        text="Сгенерировать новое задание",

        callback_data="regenerate_assignment"

    ))

    keyboard.adjust(2)



    await message.reply("Сгенерированное задание:", reply_markup=keyboard.as_markup())

    await message.reply(generated_assignment)

    await state.set_state(UserStates.waiting_for_generation_choice)





@dp.callback_query(F.data == "select_generated_assignment")

async def process_select_generated_assignment(callback: types.CallbackQuery, state: FSMContext):

    data = await state.get_data()

    assignment_text = data.get('generated_assignment_text')

    class_id = data.get('class_id')

    old_assignment_message_id = data.get('old_assignment_message_id')

    

    # Сохранить задание в базу данных

    assignment_id = add_assignment(class_id, assignment_text, None)

    

    if assignment_id:

        # Отправить новое сообщение с заданием

        new_message = await bot.send_message(chat_id=callback.message.chat.id, text=assignment_text)

        

        # Хранить идентификатор нового сообщения с заданием

        await state.update_data({'old_assignment_message_id': new_message.message_id})

        

        # Создать клавиатуру с кнопкой "Выбрать дедлайн"

        keyboard = InlineKeyboardBuilder()

        deadline_button = InlineKeyboardButton(

            text="Выбрать дедлайн",

            callback_data="select_deadline"

        )

        generate_button = InlineKeyboardButton(

            text="Сгенерировать новое задание",

            callback_data="regenerate_assignment"

        )



        keyboard.add(deadline_button)

        keyboard.add(generate_button)

        keyboard.adjust(2)

        

        # Отправить новое сообщение с меню

        menu_message = await bot.send_message(

            chat_id=callback.message.chat.id,

            text="Выбери
