import logging
import sqlite3
import uuid
import hashlib
import sys
from aiogram import Bot, Dispatcher, types, F
from aiogram.utils.formatting import Text
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters.command import Command
import google.generativeai as genai
from aiogram.utils.keyboard import ReplyKeyboardBuilder, InlineKeyboardBuilder
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
import asyncio
from aiogram.types import CallbackQuery
import os
import warnings
from aiogram.types import Message
from typing import Union
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
    'AIzaSyDDmhZ5byN13zbgC35Hlp4YLQYh-xiLCGc'
]
current_api_key_index = 0
ASSIGNMENTS_PER_PAGE = 1

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
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

model = genai.GenerativeModel('gemini-1.5-flash')

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
    waiting_for_custom_deadline = State()
    waiting_for_deadline = State()
@contextmanager
def get_db_connection():
    conn = sqlite3.connect('education_bot.db')
    try:
        yield conn
    finally:
        conn.close()

def generate_referral_link(class_id):
    # Генерация уникального идентификатора
    unique_id = str(uuid.uuid4())
    
    # Создание базовой ссылки
    base_link = f"https://t.me/edustud_bot?start={class_id}"
    
    # Добавление уникального идентификатора к ссылке
    referral_link = f"{base_link}&ref={unique_id}"
    
    # Хеширование ссылки для повышения безопасности
    hashed_link = hashlib.sha256(referral_link.encode()).hexdigest()
    
    return referral_link, hashed_link

def get_user_type_keyboard():
    # Создаем кнопки
    button_teacher = KeyboardButton(text="Учитель")
    button_student = KeyboardButton(text="Ученик")
    
    # Создаем клавиатуру
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [button_teacher],
            [button_student]
        ],
        resize_keyboard=True
    )
    return keyboard


def init_db():
    with get_db_connection() as conn:
        c = conn.cursor()
        
        # Создание таблицы учителей
        c.execute('''CREATE TABLE IF NOT EXISTS teachers
                     (id INTEGER PRIMARY KEY, 
                      name TEXT NOT NULL)''')
        
        # Создание таблицы классов
        c.execute('''CREATE TABLE IF NOT EXISTS classes
                     (id INTEGER PRIMARY KEY, 
                      teacher_id INTEGER,
                      class_name TEXT NOT NULL,
                      FOREIGN KEY (teacher_id) REFERENCES teachers(id))''')
        
        # Создание таблицы учеников (без привязки к конкретному классу)
        c.execute('''CREATE TABLE IF NOT EXISTS students
                     (id INTEGER PRIMARY KEY, 
                      name TEXT NOT NULL)''')
        
        # Создание таблицы связи учеников и классов
        c.execute('''CREATE TABLE IF NOT EXISTS student_classes
                     (student_id INTEGER,
                      class_id INTEGER,
                      FOREIGN KEY (student_id) REFERENCES students(id),
                      FOREIGN KEY (class_id) REFERENCES classes(id),
                      PRIMARY KEY (student_id, class_id))''')
        
        # Создание таблицы заданий
        c.execute('''CREATE TABLE IF NOT EXISTS assignments
                     (id INTEGER PRIMARY KEY, 
                      class_id INTEGER, 
                      text TEXT NOT NULL, 
                      deadline DATETIME,
                      FOREIGN KEY (class_id) REFERENCES classes(id))''')
        
        # Создание таблицы ответов на задания с оценкой
        c.execute('''CREATE TABLE IF NOT EXISTS submissions
                     (id INTEGER PRIMARY KEY, 
                      assignment_id INTEGER, 
                      student_id INTEGER, 
                      answer TEXT,
                      evaluation REAL,
                      grade REAL,
                      feedback TEXT,
                      FOREIGN KEY (assignment_id) REFERENCES assignments(id),
                      FOREIGN KEY (student_id) REFERENCES students(id))''')
        
        # Создание таблицы ссылок
        c.execute('''CREATE TABLE IF NOT EXISTS links
                     (id INTEGER PRIMARY KEY, 
                      class_id INTEGER, 
                      link TEXT NOT NULL,
                      FOREIGN KEY (class_id) REFERENCES classes(id))''')
        
        # Создание таблицы связи учителей и классов
        c.execute('''CREATE TABLE IF NOT EXISTS teacher_classes
                     (id INTEGER PRIMARY KEY AUTOINCREMENT,
                      teacher_id INTEGER NOT NULL,
                      class_id INTEGER NOT NULL,
                      FOREIGN KEY (teacher_id) REFERENCES teachers(id),
                      FOREIGN KEY (class_id) REFERENCES classes(id),
                      UNIQUE(teacher_id, class_id))''')
        
        conn.commit()


def add_student(student_id, name, class_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO students (id, name) VALUES (?, ?)",
                  (student_id, name))
        c.execute("INSERT OR IGNORE INTO student_classes (student_id, class_id) VALUES (?, ?)",
                  (student_id, class_id))
        conn.commit()

def get_student_classes(student_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT c.id, c.class_name
            FROM classes c
            JOIN student_classes sc ON c.id = sc.class_id
            WHERE sc.student_id = ?
        """, (student_id,))
        return c.fetchall()

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
        c.execute("SELECT id, text, deadline FROM assignments WHERE class_id = ? ORDER BY id DESC", (class_id,))
        assignments = c.fetchall()
        logger.info(f"Retrieved assignments for class {class_id}: {assignments}")
        return assignments



def add_assignment(class_id, text, deadline):
    if text is None:
        logger.error("Attempt to add assignment with None text")
        return None
    
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT MAX(id) FROM assignments WHERE class_id = ?", (class_id,))
        max_id = c.fetchone()[0]
        assignment_id = max_id + 1 if max_id is not None else 1
        
        # Убедитесь, что deadline в правильном формате
        if isinstance(deadline, datetime):
            deadline_str = deadline.strftime('%Y-%m-%d %H:%M')
        else:
            deadline_str = deadline
        
        c.execute("INSERT INTO assignments (class_id, id, text, deadline) VALUES (?, ?, ?, ?)",
                  (class_id, assignment_id, text, deadline_str))
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
    builder.button(text="📊 Посмотреть оценки учеников")
    builder.button(text="✏️ Редактировать профиль")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)

def get_student_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="👤 Мой профиль")
    builder.button(text="📚 Мои задания")
    builder.button(text="📝 Отправить работу")
    builder.button(text="✏️ Редактировать профиль")
    builder.button(text="🔄 Сменить класс")
    builder.adjust(2)
    return builder.as_markup(resize_keyboard=True)
async def show_student_menu(message: types.Message, class_id: int):
    keyboard = ReplyKeyboardBuilder()
    keyboard.button(text="👤 Мой профиль")
    keyboard.button(text="📚 Мои задания")
    keyboard.button(text="📝 Отправить работу")
    keyboard.button(text="✏️ Редактировать профиль")
    keyboard.button(text="🔄 Сменить класс")
    keyboard.adjust(2)
    

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

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    args = message.text.split()[1:] if len(message.text.split()) > 1 else None
    user_id = message.from_user.id

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT id, name FROM teachers WHERE id = ?", (user_id,))
        teacher = c.fetchone()
        c.execute("SELECT id, name FROM students WHERE id = ?", (user_id,))
        student = c.fetchone()

    if args:
        class_id = args[0]
        if student:
            try:
                with get_db_connection() as conn:
                    c = conn.cursor()
                    c.execute("INSERT OR IGNORE INTO student_classes (student_id, class_id) VALUES (?, ?)",
                              (user_id, class_id))
                    conn.commit()
                await message.reply("Вы успешно добавлены в новый класс!")
                await show_class_selection(message, state)
            except Exception as e:
                logger.error(f"Ошибка при добавлении в класс: {e}")
                await message.reply("Произошла ошибка при добавлении в класс.")
        else:
            await message.reply("Введите ваше имя:")
            await state.set_state(UserStates.waiting_for_user_name)
            await state.update_data(class_id=class_id)
    else:
        if teacher:
            await message.reply(f"С возвращением, {teacher[1]}!", 
                              reply_markup=get_teacher_keyboard())
        elif student:
            await show_class_selection(message, state)
        else:
            await message.reply("Добро пожаловать! Вы учитель или ученик?", 
                              reply_markup=get_user_type_keyboard())
            await state.set_state(UserStates.waiting_for_user_type)

async def show_class_selection(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    classes = get_student_classes(user_id)
    
    if not classes:
        await message.reply("Вы пока не присоединились ни к одному классу.")
        return

    keyboard = InlineKeyboardBuilder()
    for class_id, class_name in classes:
        keyboard.add(InlineKeyboardButton(
            text=class_name,
            callback_data=f"select_class:{class_id}"
        ))
    keyboard.adjust(1)
    
    # Сохраняем список классов в состоянии
    await state.update_data(available_classes=classes)
    
    await message.reply("Выберите класс:", reply_markup=keyboard.as_markup())


@dp.message(F.text == "🔄 Сменить класс")
async def change_class(message: types.Message, state: FSMContext):
    await show_class_selection(message, state)


@dp.callback_query(lambda c: c.data.startswith("select_class:"))
async def process_class_selection(callback: CallbackQuery, state: FSMContext):
    class_id = int(callback.data.split(":")[1])
    
    # Сохраняем выбранный класс в состоянии пользователя
    await state.update_data(current_class_id=class_id)
    
    # Получаем название класса
    class_name = get_class_name(class_id)
    
    # Отправляем сообщение о выбранном классе и показываем меню студента
    await callback.message.edit_text(f"Вы выбрали класс: {class_name}")
    await show_student_menu(callback.message, class_id)

@dp.message(UserStates.waiting_for_user_type)
async def process_user_type(message: types.Message, state: FSMContext):
    user_type = message.text.lower().strip()
    if user_type in ['учитель', 'ученик']:
        await state.update_data(user_type=user_type)
        await message.reply("Введите ваше имя:")
        await state.set_state(UserStates.waiting_for_user_name)
    else:
        await message.reply("Пожалуйста, выберите 'Учитель' или 'Ученик'.", reply_markup=get_user_type_keyboard())

@dp.message(UserStates.waiting_for_user_name)
async def process_name(message: types.Message, state: FSMContext):
    data = await state.get_data()
    class_id = data.get('class_id')
    user_type = data.get('user_type')
    user_id = message.from_user.id
    
    try:
        if class_id:  # Регистрация ученика через ссылку
            with get_db_connection() as conn:
                c = conn.cursor()
                # Добавляем ученика в таблицу students
                c.execute("INSERT INTO students (id, name) VALUES (?, ?)", 
                          (user_id, message.text))
                # Добавляем связь ученика с классом
                c.execute("INSERT INTO student_classes (student_id, class_id) VALUES (?, ?)",
                          (user_id, class_id))
                conn.commit()
            await message.reply("Вы успешно зарегистрированы!")
            await show_class_selection(message)
        elif user_type == 'учитель':
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("INSERT INTO teachers (id, name) VALUES (?, ?)", 
                          (user_id, message.text))
                conn.commit()
            await message.reply("Регистрация учителя завершена!", 
                              reply_markup=get_teacher_keyboard())
        
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
    data = await state.get_data()
    current_class_id = data.get('current_class_id')
    if not current_class_id:
        await message.reply("Пожалуйста, сначала выберите класс.")
        return

    assignments = get_class_assignments(current_class_id)
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
    try:
        update_api_key()  # Обновляем API-ключ перед запросом
        request = message.text
        logger.info(f"Получен запрос на генерацию задания: {request}")
        await state.update_data(generation_request=request)

        # Получаем class_id из состояния
        data = await state.get_data()
        class_id = data.get('class_id')
        logger.info(f"Class ID: {class_id}")

        # Генерация задания по запросу
        prompt = f"Сгенерируйте задание по запросу: {request}. Пиши только само задание без дополнительных комментариев, критериев или сроков. Используй возможности форматирования Telegram.Создай такое задание которую ты можешь проверить не используй стороенные материалы и ссылки не давай задание где нужно использовать медиа"
        logger.info(f"Отправка промпта в AI: {prompt}")
        
        response = chat.send_message(
            prompt,
            generation_config=generation_config,
            safety_settings=safety_settings
        )
        generated_assignment = response.text
        logger.info(f"Сгенерированный текст задания: {generated_assignment[:100]}...")  # Логируем первые 100 символов

        # Сохраняем сгенерированный текст задания в состоянии
        await state.update_data(generated_assignment_text=generated_assignment)
        logger.info("Сгенерированный текст задания сохранен в состоянии")

        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(
            text="Выбрать это задание",
            callback_data="select_generated_assignment"
        ))
        keyboard.add(InlineKeyboardButton(
            text="Сгенерировать новое",
            callback_data="regenerate_assignment"
        ))
        keyboard.adjust(1)  # Размещаем кнопки в один столбец

        # Отправляем сообщение с заданием
        await message.answer("Сгенерированное задание:", reply_markup=keyboard.as_markup())
        await message.answer(generated_assignment)
        logger.info("Сообщение с сгенерированным заданием отправлено пользователю")

        await state.set_state(UserStates.waiting_for_generation_choice)
        logger.info("Установлено состояние waiting_for_generation_choice")

    except Exception as e:
        logger.error(f"Ошибка при генерации задания: {str(e)}")
        await message.answer("Произошла ошибка при генерации задания. Пожалуйста, попробуйте еще раз.")
        await state.set_state(UserStates.waiting_for_generation_request)



@dp.callback_query(F.data == "select_generated")
async def process_select_generated_assignment(callback: types.CallbackQuery, state: FSMContext):
    logger.info("Функция process_select_generated_assignment вызвана")
    data = await state.get_data()
    assignment_text = data.get('generated_assignment_text')
    class_id = data.get('class_id')
    
    logger.info(f"Assignment text: {assignment_text[:50] if assignment_text else None}")
    logger.info(f"Class ID: {class_id}")
    
    if not assignment_text:
        await callback.answer("Ошибка: текст задания не найден.")
        return

    if not class_id:
        await callback.answer("Ошибка: класс не выбран.")
        return

    # Переходим к выбору дедлайна
    await state.set_state(UserStates.waiting_for_deadline_year)
    
    # Используем существующую функцию для отображения клавиатуры выбора дедлайна
    await callback.answer()
    
    
@dp.callback_query(F.data == "select_generated_assignment")
async def process_select_generated_assignment(callback: types.CallbackQuery, state: FSMContext):
    try:
        logger.info("Начало обработки выбора сгенерированного задания")
        
        data = await state.get_data()
        generated_assignment_text = data.get('generated_assignment_text')
        class_id = data.get('class_id')
        
        logger.info(f"Полученные данные: class_id={class_id}, текст задания={generated_assignment_text[:50] if generated_assignment_text else None}...")

        if not generated_assignment_text or not class_id:
            await callback.answer("Ошибка: текст задания или ID класса не найдены.")
            logger.error(f"Отсутствуют данные: text={bool(generated_assignment_text)}, class_id={bool(class_id)}")
            return

        # Сохраняем текст задания в состоянии под ключом 'assignment_text'
        await state.update_data(
            assignment_text=generated_assignment_text,
            selected_class_id=class_id,
        )
        
        logger.info("Данные успешно сохранены в состоянии")

        # Создаем клавиатуру с кнопкой "Выбрать дедлайн"
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(
            text="Выбрать дедлайн",
            callback_data="select_deadline"
        ))

        # Отправляем сообщение с текстом задания
        new_message = await callback.message.answer(
            text=generated_assignment_text,
            reply_markup=keyboard.as_markup()
        )

        # Сохраняем ID сообщения
        await state.update_data(current_assignment_message_id=new_message.message_id)
        
        logger.info(f"Сообщение с заданием отправлено, ID: {new_message.message_id}")
        
        # Отвечаем на callback
        await callback.answer()

    except Exception as e:
        logger.error(f"Ошибка при обработке выбора задания: {e}")
        await callback.answer("Произошла ошибка при выборе задания.")



@dp.callback_query(F.data == "select_deadline")
async def process_select_deadline(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Выберите дату дедлайна:", 
                                    reply_markup=get_calendar_keyboard(datetime.now().year, datetime.now().month))
    await state.set_state(UserStates.waiting_for_deadline_year)

@dp.callback_query(F.data == "regenerate_assignment")
async def process_regenerate_assignment(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    generation_request = data.get('generation_request')
    
    # Generate new assignment by request
    prompt = f"Сгенерируйте задание по запросу: {generation_request}"
    response = chat.send_message(
        prompt,
        generation_config=generation_config,
        safety_settings=safety_settings
    )
    generated_assignment = response.text
    
    # Сохраняем новое задание в состоянии
    await state.update_data(generated_assignment_text=generated_assignment)
    
    
    keyboard = InlineKeyboardBuilder()
    select_button = InlineKeyboardButton(
        text="Выбрать",
        callback_data="select_generated_assignment"
    )
    generate_button = InlineKeyboardButton(
        text="Сгенерировать новое задание",
        callback_data="regenerate_assignment"
    )
    

    
    keyboard.add(select_button)
    keyboard.add( generate_button)
    keyboard.adjust(2)

    # Delete old messages
    old_assignment_message_id = data.get('old_assignment_message_id')
    old_menu_message_id = data.get('old_menu_message_id')
    if old_assignment_message_id:
        try:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=old_assignment_message_id)
        except aiogram.exceptions.MessageToDeleteNotFound:
            pass
    if old_menu_message_id:
        try:
            await bot.delete_message(chat_id=callback.message.chat.id, message_id=old_menu_message_id)
        except aiogram.exceptions.MessageToDeleteNotFound:
            pass

    # Send new message with generated assignment
    new_message = await bot.send_message(chat_id=callback.message.chat.id, text=generated_assignment)
    
    # Store new message ID
    await state.update_data({'old_assignment_message_id': new_message.message_id})

    # Send new message with menu
    new_menu_message = await bot.send_message(chat_id=callback.message.chat.id, text="Сгенерированное задание:", reply_markup=keyboard.as_markup())
    await state.update_data({'old_menu_message_id': new_menu_message.message_id})

    # Handle "Выбрать" button click
    @dp.callback_query()
    async def show_deadline_button(callback_query: CallbackQuery):
        if callback_query.data == 'select_generated_assignment':
            deadline_button = InlineKeyboardButton(
                text="Выбрать дедлайн",
                callback_data="select_deadline"
            )
            keyboard.add(deadline_button)
            await callback_query.message.edit_reply_markup(reply_markup=keyboard.as_markup())

    await state.set_state(UserStates.waiting_for_deadline_year)


@dp.message(UserStates.waiting_for_generation_choice)
async def process_generation_choice(message: types.Message, state: FSMContext):
    await message.reply("Выберите дату дедлайна:", 
                        reply_markup=get_calendar_keyboard(datetime.now().year, datetime.now().month))
    await state.set_state(UserStates.waiting_for_deadline_year)

@dp.callback_query(F.data.in_({"add_own_assignment", "generate_assignment"}))
async def process_assignment_method(callback: types.CallbackQuery, state: FSMContext):
    method = callback.data
    await state.update_data(assignment_method=method)

    if method == "add_own_assignment":
        await callback.message.edit_text("Введите текст задания:")
        await state.set_state(UserStates.waiting_for_assignment)
    elif method == "generate_assignment":
        await callback.message.edit_text("Введите запрос для генерации задания:")
        await state.set_state(UserStates.waiting_for_generation_request)


@dp.callback_query(F.data.startswith("class:"))
async def process_class_selection(callback: types.CallbackQuery, state: FSMContext):
    class_id = callback.data.split(":")[1]
    await state.update_data(class_id=class_id)
    
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(
        text="Добавить свое задание",
        callback_data="add_own_assignment"
    ))
    keyboard.add(InlineKeyboardButton(
        text="Сгенерировать задание",
        callback_data="generate_assignment"
    ))
    keyboard.adjust(2)
    
    await callback.message.edit_text("Выберите способ добавления задания:", reply_markup=keyboard.as_markup())
    await state.set_state(UserStates.waiting_for_assignment_method)

@dp.message(UserStates.waiting_for_assignment)
async def process_assignment(message: types.Message, state: FSMContext):
    assignment_text = message.text.strip()  # Удаляем лишние пробелы
    await state.update_data(assignment_text=assignment_text)

    logger.info(f"Текст задания сохранен: {assignment_text}")  # Логируем текст задания
    
    current_year = datetime.now().year
    await message.reply("Выберите дату дедлайна:", 
                        reply_markup=get_calendar_keyboard(current_year, datetime.now().month))
    await state.set_state(UserStates.waiting_for_deadline_year)


@dp.callback_query(F.data.startswith("month:"))
async def process_month_selection(callback: types.CallbackQuery):
    _, year, month = callback.data.split(":")
    await callback.message.edit_reply_markup(
        reply_markup=get_calendar_keyboard(int(year), int(month))
    )


@dp.callback_query(F.data.startswith("date:"))
async def process_date_selection(callback: types.CallbackQuery, state: FSMContext):
    _, year, month, day = callback.data.split(":")
    await state.update_data(deadline_date=f"{year}-{month}-{day}")
    
    time_keyboard = InlineKeyboardBuilder()
    hours = ["09", "10", "11", "12", "13", "14", "15", "16", "17", "18", "19", "20"]
    for hour in hours:
        time_keyboard.add(InlineKeyboardButton(
            text=f"{hour}:00",
            callback_data=f"hour:{hour}"
        ))
    time_keyboard.adjust(3)
    
    await callback.message.edit_text("Выберите час дедлайна:", 
                                    reply_markup=time_keyboard.as_markup())
    await state.set_state(UserStates.waiting_for_deadline_time)

@dp.callback_query(F.data.startswith("hour:"))
async def process_hour_selection(callback: types.CallbackQuery, state: FSMContext):
    hour = callback.data.split(":")[1]
    await state.update_data(deadline_hour=hour)
    
    minute_keyboard = InlineKeyboardBuilder()
    minutes = ["00", "15", "30", "45"]
    for minute in minutes:
        minute_keyboard.add(InlineKeyboardButton(
            text=minute,
            callback_data=f"minute:{minute}"
        ))
    minute_keyboard.adjust(4)
    
    await callback.message.edit_text("Выберите минуты дедлайна:", 
                                    reply_markup=minute_keyboard.as_markup())

@dp.callback_query(F.data.startswith("minute:"))
async def process_time_selection(callback: types.CallbackQuery, state: FSMContext):
    try:
        logger.info(f"Начало обработки выбора времени. Callback data: {callback.data}")
        
        minute = callback.data.split(":")[1]
        data = await state.get_data()
        
        logger.info(f"Полученные данные из состояния: {data}")
        
        deadline_date = data.get('deadline_date')
        deadline_hour = data.get('deadline_hour')
        selected_class_id = data.get('class_id')  # Изменено с 'selected_class_id' на 'class_id'
        selected_assignment_text = data.get('assignment_text')  
        
        logger.info(f"Извлеченные данные: date={deadline_date}, hour={deadline_hour}, class_id={selected_class_id}, text={selected_assignment_text[:50] if selected_assignment_text else None}...")
        
  
        
        # Подробная проверка наличия всех необходимых данных
        if not deadline_date:
            await callback.answer("Ошибка: отсутствует дата дедлайна.")
            logger.error("Отсутствует дата дедлайна")
            return
        if not deadline_hour:
            await callback.answer("Ошибка: отсутствует час дедлайна.")
            logger.error("Отсутствует час дедлайна")
            return
        if not selected_class_id:
            await callback.answer("Ошибка: не выбран класс.")
            logger.error("Не выбран класс")
            return
        if not selected_assignment_text:
            await callback.answer("Ошибка: текст задания отсутствует.")
            logger.error("Отсутствует текст задания")
            return
        
        deadline_str = f"{deadline_date} {deadline_hour}:{minute}"
        logger.info(f"Сформированная строка дедлайна: {deadline_str}")
        
        try:
            deadline = datetime.strptime(deadline_str, '%Y-%m-%d %H:%M')
            deadline = TIMEZONE.localize(deadline)
            logger.info(f"Преобразованный дедлайн: {deadline}")
        except ValueError as e:
            await callback.answer("Ошибка: неверный формат даты или времени.")
            logger.error(f"Ошибка при преобразовании даты: {e}")
            return
        
        # Добавление задания в базу данных
        try:
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("INSERT INTO assignments (class_id, text, deadline) VALUES (?, ?, ?)", 
                          (selected_class_id, selected_assignment_text, deadline.strftime('%Y-%m-%d %H:%M')))
                conn.commit()
                new_assignment_id = c.lastrowid
            logger.info(f"Задание успешно добавлено!")
        except Exception as e:
            await callback.answer("Ошибка при сохранении задания в базу данных.")
            logger.error(f"Ошибка при добавлении задания в БД: {e}")
            return
        
        # Удаление старых сообщений
        old_assignment_message_id = data.get('current_assignment_message_id')
        old_menu_message_id = data.get('current_menu_message_id')
        
        if old_assignment_message_id:
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=old_assignment_message_i )
                logger.info(f"Старое сообщение задания удалено!")
            except Exception as e:
                logger.error(f"Ошибка при удалении старого сообщения задания: {e}")
        
        if old_menu_message_id:
            try:
                await bot.delete_message(chat_id=callback.message.chat.id, message_id=old_menu_message_id)
                logger.info(f"Старое меню удалено. ID: {old_menu_message_id}")
            except Exception as e:
                logger.error(f"Ошибка при удалении старого меню: {e}")
        
        # Создание нового сообщения задания
        try:
            new_assignment_message = await callback.message.answer(f"Задание создано успешно!")
            logger.info(f"Новое сообщение задания создано. ID: {new_assignment_message.message_id}")
        except Exception as e:
            logger.error(f"Ошибка при создании нового сообщения задания: {e}")
        
        # Обновление состояния
        await state.update_data(current_assignment_message_id=new_assignment_message.message_id)
        logger.info(f"Состояние обновлено. current_assignment_message_id: {new_assignment_message.message_id}")
        
    except Exception as e:
        logger.error(f"Ошибка при обработке выбора времени: {e}")
        await callback.answer("Произошла ошибка при создании задания.")

@dp.callback_query(F.data.startswith("submit:"))
async def process_submission_selection(callback: types.CallbackQuery, state: FSMContext):
    try:
        assignment_id = callback.data.split(":")[1]
        await state.update_data(assignment_id=assignment_id)
        await callback.message.reply("Введите ваш ответ на задание:")
        await callback.answer()
    except Exception as e:
        logger.error(f"Ошибка при обработке выбора задания для ответа: {e}")
        await callback.answer("Произошла ошибка. Пожалуйста, попробуйте еще раз.")

@dp.message(F.text == "🔗 Мои ссылки")
async def show_links(message: types.Message):
    try:
        teacher_id = message.from_user.id
        
        with get_db_connection() as conn:
            c = conn.cursor()
            
            # Получаем все классы, созданные учителем
            c.execute("SELECT id, class_name FROM classes WHERE teacher_id = ?", (teacher_id,))
            classes = c.fetchall()
            
            if classes:
                response = "Мои ссылки:\n\n"
                for class_id, class_name in classes:
                    # Получаем реферальную ссылку из таблицы links по class_id
                    c.execute("SELECT link FROM links WHERE class_id = ?", (class_id,))
                    link_results = c.fetchall()
                    
                    if link_results:
                        response += f"{class_name}:\n"
                        for link in link_results:
                            response += f"Присоединиться к классу: {link[0]}\n"
                            
                    else:
                        response += f"{class_name}: У вас пока нет ссылок.\n\n"
                        
                await message.reply(response)
            else:
                await message.reply("Вы не создали ни одного класса.")
    except Exception as e:
        logger.error(f"Ошибка при отображении ссылок: {e}")
        await message.reply("Произошла ошибка при получении ссылок. Попробуйте позже.")

@dp.message(F.text == "📚 Мои задания")
async def show_assignments(message: types.Message, state: FSMContext):
    data = await state.get_data()
    current_class_id = data.get('current_class_id')
    if not current_class_id:
        await message.reply("Пожалуйста, сначала выберите класс.")
        return

    assignments = get_class_assignments(current_class_id)
    total_assignments = len(assignments)

    if total_assignments == 0:
        await message.reply("У вас пока нет заданий.")
        return

    # Сохраняем задания и текущую страницу в состоянии
    await state.update_data(assignments=assignments, current_page=0)
    await send_assignments_page(chat_id=message.chat.id, message_id=message.message_id, assignments=assignments, page=0)

async def send_assignments_page(callback=None, chat_id=None, message_id=None, assignments=None, page=None):
    if callback:
        chat_id = callback.message.chat.id
        message_id = callback.message.message_id
    elif chat_id and message_id and assignments and page is not None:
        pass
    else:
        raise ValueError("Недостаточно аргументов")

    # Проверка, что page не None
    if page is None:
        raise ValueError("page не может быть None")

    start_index = page * ASSIGNMENTS_PER_PAGE
    end_index = start_index + ASSIGNMENTS_PER_PAGE
    assignments_to_send = assignments[start_index:end_index]

    if not assignments_to_send:
        await bot.send_message(chat_id, "Это последняя страница.")
        return

    response = "📝 Ваши задания:\n\n"
    for assignment in assignments_to_send:
        response += f"📚 Задание: {assignment[1]}\n📅 Дедлайн: {assignment[2]}\n\n"

    keyboard = InlineKeyboardBuilder()
    
    # Добавляем кнопку "Назад", если это не первая страница
    if page > 0:
        keyboard.add(InlineKeyboardButton(text="◀️ Назад", callback_data=f"assignments_page:{page - 1}"))
    
    # Добавляем кнопку "Вперед", если есть еще страницы
    if end_index < len(assignments):
        keyboard.add(InlineKeyboardButton(text="▶️ Вперед", callback_data=f"assignments_page:{page + 1}"))

    if callback:
        await bot.edit_message_text(
            text=response,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=keyboard.as_markup()
        )
    else:
        await bot.send_message(
            chat_id=chat_id,
            text=response,
            reply_markup=keyboard.as_markup()
        )
@dp.callback_query(F.data.startswith("assignments_page:"))
async def process_assignments_page(callback: types.CallbackQuery, state: FSMContext):
    # Извлекаем номер страницы из callback.data
    page = int(callback.data.split(":")[1])

    # Получаем данные из состояния
    data = await state.get_data()
    assignments = data.get("assignments")

    # Проверка наличия заданий
    if assignments is None:
        await callback.answer("Задания не найдены.")
        return

    # Проверка границ страницы
    if page < 0 or page >= (len(assignments) + ASSIGNMENTS_PER_PAGE - 1) // ASSIGNMENTS_PER_PAGE:
        await callback.answer("Некорректный номер страницы.")
        return

    await send_assignments_page(callback=callback, assignments=assignments, page=page)
    await callback.answer()  # Убедитесь, что вы отвечаете на callback

@dp.message(UserStates.waiting_for_submission)
async def process_submission(message: types.Message, state: FSMContext):
    data = await state.get_data()
    assignment_id = data.get('assignment_id')
    if not assignment_id:
        await message.reply("Произошла ошибка. Пожалуйста, начните процесс отправки заново.")
        await state.clear()
        return

    if message.document:
        file_info = await bot.get_file(message.document.file_id)
        file_path = file_info.file_path
        downloaded_file = await bot.download_file(file_path)

        # Проверка, является ли файл .docx
        if message.document.mime_type == 'application/vnd.openxmlformats-officedocument.wordprocessingml.document':
            # Извлечение текста из .docx файла
            doc = docx.Document(downloaded_file)
            answer = ''.join(p.text for p in doc.paragraphs)
        elif message.document.mime_type.startswith('text/'):
            answer = downloaded_file.read().decode('utf-8', errors='replace')
        else:
            await message.reply("Пожалуйста, отправьте файл в текстовом формате.")
            return
    elif message.text:
        answer = message.text
    else:
        await message.reply("Пожалуйста, отправьте файл с ответом или введите текст ответа.")
        return

    # Отправка сообщения о загрузке
    loading_message = await message.reply("Оцениваю ваш ответ... (0/5)")

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT text, deadline FROM assignments WHERE id = ?", (assignment_id,))
        assignment = c.fetchone()
    
    if not assignment:
        await message.reply("Задание не найдено.")
        await state.clear()
        return
    
    assignment_text, deadline_str = assignment
    
    prompt = f"""Оцени ответ ученика на задание.
    Текст задания: {assignment_text}
    Ответ ученика: {answer}
    
    Оцени ответ по следующим критериям:
    1. Полнота ответа
    2. Правильность
    3. Оригинальность мышления от 2 баллов    

    Дай оценку от 1 до 10 и подробно объясни её.
    Формат ответа:
    Оценка: X/10
    Обоснование: Подробное объяснение оценки...
    """
    
    try:
        response = chat.send_message(
            prompt,
            generation_config=generation_config,
            safety_settings=safety_settings
        )
        
        # Update loading message
        await loading_message.edit_text("Оцениваю ваш ответ... (1/5)")
        
        evaluation, feedback = parse_evaluation(response.text)
        
        if evaluation is None:
            logger.warning("Не удалось получить оценку от AI")
            await message.reply("Не удалось получить оценку от AI. Пожалуйста, попробуйте ещё раз.")
            await state.clear()
            return
        
        # Update loading message
        await loading_message.edit_text("Оцениваю ваш ответ... (2/5)")
        
        add_submission(assignment_id, message.from_user.id, answer, evaluation, feedback)
        
        # Update loading message
        await loading_message.edit_text("Оцениваю ваш ответ... (3/5)")
        
        # Отправка ответа ИИ после загрузки файла
        messages = [
            f"✅ Ваш ответ был оценён!\n\nЗадание: {assignment_text}\n",
            f"Оценка: {evaluation}/10\n",
            f"Обоснование: {feedback}\n",
            "Спасибо за участие в оценке!"
        ]
        
        for message_text in messages:
            await message.reply(message_text)
        
        # Update loading message
        await loading_message.edit_text("Оцениваю ваш ответ... (5/5) ✅")
    except Exception as e:
        logger.error(f"Error processing submission: {e}")
        await message.reply("Ошибка при обработке ответа. Пожалуйста, попробуйте ещё раз.")
        await state.clear()
        return
# Class creation
@dp.message(F.text == "➕ Создать класс")
async def create_class(message: types.Message, state: FSMContext):
    if not is_teacher(message.from_user.id):
        await message.reply("Эта функция доступна только для учителей.")
        return
    
    await message.reply("Введите название класса:")
    await state.set_state(UserStates.waiting_for_class_name)

@dp.message(UserStates.waiting_for_class_name)
async def process_class_name(message: types.Message, state: FSMContext):
    class_name = message.text.strip()
    with get_db_connection() as conn:
        c = conn.cursor()
        # Сначала создаем класс и получаем его ID
        c.execute("INSERT INTO classes (teacher_id, class_name) VALUES (?, ?)", 
                  (message.from_user.id, class_name))
        class_id = c.lastrowid  # Получаем ID только что созданного класса
        
        # Теперь генерируем реферальную ссылку с полученным class_id
        ref_link, hashed_link = generate_referral_link(class_id)
        
        # Добавляем ссылку в таблицу links
        c.execute("INSERT INTO links (class_id, link) VALUES (?, ?)",
                  (class_id, ref_link))
        
        conn.commit()
    
    await message.reply(f"Класс '{class_name}' создан! Ваша реферальная ссылка: {ref_link}")
    await state.clear()

@dp.message(F.text == "📊 Статистика класса")
async def show_class_statistics(message: types.Message):
    if not is_teacher(message.from_user.id):
        await message.reply("Эта функция доступна только для учителей.")
        return
    
    classes = get_teacher_classes(message.from_user.id)
    if not classes:
        await message.reply("У вас пока нет классов.")
        return
    
    for class_id, class_name in classes:
        try:
            stats = get_assignment_statistics(class_id)
            if stats:
                response = f"📊 <b>Статистика класса {class_name}:</b>\n\n"
                for assignment_id, text, deadline, submissions, avg_score in stats:
                    # Обрезаем текст задания, если он слишком длинный
                    short_text = text[:50] + "..." if len(text) > 50 else text
                    response += f"📝 <b>Задание:</b> {short_text}\n"
                    response += f"📅 <b>Дедлайн:</b> {deadline}\n"
                    response += f"📤 <b>Отправлено работ:</b> {submissions}\n"
                    if avg_score is not None:
                        response += f"📈 <b>Средний балл:</b> {avg_score:.1f}/10\n\n"
                    else:
                        response += "📈 <b>Средний балл:</b> Нет данных\n\n"
            else:
                response = f"В классе {class_name} пока нет заданий."

            # Разбиваем длинные сообщения на части
            max_length = 4000
            for i in range(0, len(response), max_length):
                part = response[i:i+max_length]
                await message.answer(part, parse_mode="HTML")
                
        except Exception as e:
            logger.error(f"Ошибка при получении статистики для класса {class_name}: {e}")
            await message.answer(f"Произошла ошибка при получении статистики для класса {class_name}")
# Teacher assignments
@dp.message(F.text == "📝 Посмотреть мои задания")
async def show_assignments(message: types.Message):
    try:
        teacher_id = message.from_user.id
        
        if not is_teacher(teacher_id):
            await message.answer("Эта функция доступна только для учителей.")
            return
        
        # Получаем список классов учителя
        classes = get_teacher_classes(teacher_id)
        
        if not classes:
            await message.answer("У вас пока нет классов.")
            return
        
        # Создаем клавиатуру с классами
        keyboard = InlineKeyboardBuilder()
        for class_id, class_name in classes:
            keyboard.add(InlineKeyboardButton(
                text=class_name,
                callback_data=f"view_assignments_{class_id}_0"  # Добавляем индекс страницы
            ))
        keyboard.adjust(1)
        
        await message.answer(
            "Выберите класс для просмотра заданий:",
            reply_markup=keyboard.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при показе классов: {e}")
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@dp.callback_query(lambda c: c.data.startswith('view_assignments_'))
async def show_class_assignments(callback: CallbackQuery):
    try:
        parts = callback.data.split('_')
        if len(parts) < 3:
            await callback.answer("Неверный формат данных")
            return
        
        class_id = parts[2]
        page = int(parts[3]) if len(parts) > 3 else 0
        
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT a.id, a.text, strftime('%Y-%m-%d %H:%M', a.deadline) as deadline
                FROM assignments a
                WHERE a.class_id = ?
                ORDER BY a.deadline DESC
            """, (class_id,))
            
            assignments = c.fetchall()
            
            if not assignments:
                await callback.message.edit_text("В этом классе пока нет заданий.")
                return

            # Показываем только одно задание на странице
            total_assignments = len(assignments)
            if page >= total_assignments:
                page = total_assignments - 1
            elif page < 0:
                page = 0

            assignment = assignments[page]
            assignment_id, text, deadline = assignment

            response = f"📚 Задание {page + 1} из {total_assignments}:\n\n"
            response += f"📌 <b>Задание {assignment_id}:</b>\n{text}\n"
            
            if deadline:
                deadline_dt = datetime.strptime(deadline, '%Y-%m-%d %H:%M')
                deadline_str = deadline_dt.strftime('%d.%m.%Y %H:%M')
                response += f"⏰ <b>Дедлайн:</b> {deadline_str}\n"
            else:
                response += "⏰ <b>Дедлайн:</b> Не указан\n"

            # Создаем клавиатуру с кнопками навигации
            keyboard = InlineKeyboardBuilder()
            
            # Кнопка "Назад" если не первая страница
            if page > 0:
                keyboard.add(InlineKeyboardButton(
                    text="◀️ Предыдущее",
                    callback_data=f"view_assignments_{class_id}_{page-1}"
                ))

            # Кнопка "Вперед" если не последняя страница
            if page < total_assignments - 1:
                keyboard.add(InlineKeyboardButton(
                    text="Следующее ▶️",
                    callback_data=f"view_assignments_{class_id}_{page+1}"
                ))

            # Кнопка удаления задания
            keyboard.add(InlineKeyboardButton(
                text="🗑 Удалить задание",
                callback_data=f"delete_assignment_{class_id}_{assignment_id}"
            ))

            # Кнопка возврата к классам
            keyboard.add(InlineKeyboardButton(
                text="◀️ К списку классов",
                callback_data="back_to_classes"
            ))

            keyboard.adjust(2)  # Размещаем кнопки по 2 в ряд
            
            await callback.message.edit_text(
                response,
                reply_markup=keyboard.as_markup(),
                parse_mode="HTML"
            )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при показе заданий класса: {e}")
        await callback.message.edit_text("Произошла ошибка при получении заданий. Пожалуйста, попробуйте позже.")

@dp.callback_query(lambda c: c.data.startswith('delete_assignment_'))
async def delete_assignment(callback: CallbackQuery):
    try:
        # Получаем все части callback data
        parts = callback.data.split('_')
        class_id = parts[2]
        assignment_id = parts[3]
        
        # Удаляем задание из базы данных
        with get_db_connection() as conn:
            c = conn.cursor()
            # Сначала удаляем все связанные submissions
            c.execute("DELETE FROM submissions WHERE assignment_id = ?", (assignment_id,))
            # Затем удаляем само задание
            c.execute("DELETE FROM assignments WHERE id = ? AND class_id = ?", 
                     (assignment_id, class_id))
            conn.commit()
        
        await callback.answer("Задание успешно удалено!")
        
        # Получаем список оставшихся заданий
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT a.id, a.text, strftime('%Y-%m-%d %H:%M', a.deadline) as deadline
                FROM assignments a
                WHERE a.class_id = ?
                ORDER BY a.deadline DESC
            """, (class_id,))
            
            assignments = c.fetchall()
            
            if not assignments:
                await callback.message.edit_text("В этом классе больше нет заданий.")
                return

            # Показываем первое задание
            assignment = assignments[0]
            assignment_id, text, deadline = assignment

            response = f"📚 Задание 1 из {len(assignments)}:\n\n"
            response += f"📌 <b>Задание {assignment_id}:</b>\n{text}\n"
            
            if deadline:
                deadline_dt = datetime.strptime(deadline, '%Y-%m-%d %H:%M')
                deadline_str = deadline_dt.strftime('%d.%m.%Y %H:%M')
                response += f"⏰ <b>Дедлайн:</b> {deadline_str}\n"
            else:
                response += "⏰ <b>Дедлайн:</b> Не указан\n"

            # Создаем клавиатуру
            keyboard = InlineKeyboardBuilder()
            
            # Кнопка "Вперед" если есть следующее задание
            if len(assignments) > 1:
                keyboard.add(InlineKeyboardButton(
                    text="Следующее ▶️",
                    callback_data=f"view_assignments_{class_id}_1"
                ))

            # Кнопка удаления задания
            keyboard.add(InlineKeyboardButton(
                text="🗑 Удалить задание",
                callback_data=f"delete_assignment_{class_id}_{assignment_id}"
            ))

            # Кнопка возврата к классам
            keyboard.add(InlineKeyboardButton(
                text="◀️ К списку классов",
                callback_data="back_to_classes"
            ))

            keyboard.adjust(2)

            await callback.message.edit_text(
                response,
                reply_markup=keyboard.as_markup(),
                parse_mode="HTML"
            )
        
    except Exception as e:
        logger.error(f"Ошибка при удалении задания: {e}")
        await callback.answer("Произошла ошибка при удалении задания.")

# Обработчик для кнопки "Назад к списку классов"
@dp.callback_query(lambda c: c.data == 'back_to_classes')
async def back_to_classes(callback: CallbackQuery):
    try:
        teacher_id = callback.from_user.id
        classes = get_teacher_classes(teacher_id)
        
        keyboard = InlineKeyboardBuilder()
        for class_id, class_name in classes:
            keyboard.add(InlineKeyboardButton(
                text=class_name,
                callback_data=f"view_assignments_{class_id}"
            ))
        keyboard.adjust(1)
        
        await callback.message.edit_text(
            "Выберите класс для просмотра заданий:",
            reply_markup=keyboard.as_markup()
        )
        
        await callback.answer()
        
    except Exception as e:
        logger.error(f"Ошибка при возврате к списку классов: {e}")
        await callback.message.edit_text("Произошла ошибка. Пожалуйста, попробуйте позже.")

# Student grades
@dp.message(F.text == "📊 Посмотреть оценки учеников")
async def show_classes_for_grades(message: Union[Message, CallbackQuery]):
    try:
        if isinstance(message, CallbackQuery):
            message = message.message
        
        teacher_id = message.from_user.id
        
        # Получаем список классов
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT id, class_name 
                FROM classes 
                WHERE teacher_id = ?
                ORDER BY class_name
            """, (teacher_id,))
            classes = c.fetchall()
        
        if not classes:
            await message.answer("У вас пока нет назначенных классов.")
            return
        
        # Создаем клавиатуру с классами
        keyboard = InlineKeyboardBuilder()
        for class_id, class_name in classes:
            keyboard.add(InlineKeyboardButton(
                text=class_name,
                callback_data=f"grades_class_{class_id}"
            ))
        keyboard.adjust(1)
        
        await message.answer(
            "Выберите класс для просмотра оценок:",
            reply_markup=keyboard.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при показе классов для оценок: {e}")
        await message.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@dp.callback_query(lambda c: c.data == "view_grades")
async def show_classes_for_grades(callback: CallbackQuery):
    await show_classes_for_grades(callback.message)


@dp.callback_query(lambda c: c.data.startswith('grades_class_'))
async def show_assignments_for_grades(callback_query: CallbackQuery):
    try:
        # Изменим эту строку
        class_id = callback_query.data.split('_')[-1]
        
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT id, text, strftime('%d.%m.%Y', deadline) as formatted_deadline
                FROM assignments
                WHERE class_id = ?
                ORDER BY deadline DESC
            """, (class_id,))
            assignments = c.fetchall()
        
        if not assignments:
            await callback_query.answer("В этом классе пока нет заданий.")
            return
        
        keyboard = InlineKeyboardBuilder()
        for assignment_id, text, deadline in assignments:
            keyboard.add(InlineKeyboardButton(
                text=f"{text[:20]}... ({deadline})" if len(text) > 20 else f"{text} ({deadline})",
                callback_data=f"grades_assignment_{class_id}_{assignment_id}"
            ))
        keyboard.adjust(1)
        
        await callback_query.message.edit_text(
            "Выберите задание для просмотра оценок:",
            reply_markup=keyboard.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при показе заданий для оценок: {e}")
        await callback_query.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@dp.callback_query(lambda c: c.data.startswith('show_students_'))
async def show_students(callback_query: types.CallbackQuery):
    try:
        class_id = int(callback_query.data.split('_')[-1])
        
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT id, name 
                FROM students 
                WHERE class_id = ?
                ORDER BY name
            """, (class_id,))
            students = c.fetchall()
        
        if not students:
            await callback_query.answer("В этом классе пока нет учеников.")
            return
        
        student_list = "\n".join([f"{i+1}. {student[1]}" for i, student in enumerate(students)])
        
        # Создаем клавиатуру с кнопкой "Назад"
        keyboard = InlineKeyboardBuilder()
        keyboard.add(InlineKeyboardButton(text="◀️ Назад", callback_data=f"back_to_class_{class_id}"))
        
        await callback_query.message.edit_text(
            f"Список учеников:\n\n{student_list}",
            reply_markup=keyboard.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при показе списка учеников: {e}")
        await callback_query.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")
async def show_class_menu(message: types.Message, class_id: int):
    keyboard = InlineKeyboardBuilder()
    keyboard.add(InlineKeyboardButton(text="📚 Задания", callback_data=f"assignments_{class_id}"))
    keyboard.add(InlineKeyboardButton(text="👥 Список учеников", callback_data=f"show_students_{class_id}"))
    keyboard.add(InlineKeyboardButton(text="🔗 Ссылки", callback_data=f"links_{class_id}"))
    keyboard.adjust(1)

    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT class_name FROM classes WHERE id = ?", (class_id,))
        class_name = c.fetchone()[0]

    await message.edit_text(f"Меню класса {class_name}:", reply_markup=keyboard.as_markup())
@dp.callback_query(lambda c: c.data.startswith('grades_assignment_class_'))
async def back_to_assignments_list(callback: CallbackQuery):
    try:
        # Получаем assignment_id из callback данных
        assignment_id = callback.data.split('_')[3]
        
        # Получаем class_id из базы данных по assignment_id
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT class_id FROM assignments WHERE id = ?", (assignment_id,))
            result = c.fetchone()
            if not result:
                await callback.answer("Задание не найдено")
                return
            class_id = result[0]

        # Получаем список заданий для этого класса
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT id, text, strftime('%d.%m.%Y', deadline) as formatted_deadline
                FROM assignments
                WHERE class_id = ?
                ORDER BY deadline DESC
            """, (class_id,))
            assignments = c.fetchall()

        if assignments:
            keyboard = InlineKeyboardBuilder()
            for assignment_id, text, deadline in assignments:
                keyboard.add(InlineKeyboardButton(
                    text=f"{text[:20]}... ({deadline})" if len(text) > 20 else f"{text} ({deadline})",
                    callback_data=f"grades_assignment_{class_id}_{assignment_id}"
                ))
            
            # Добавляем кнопку возврата к списку классов
            keyboard.add(InlineKeyboardButton(
                text="◀️ К списку классов",
                callback_data="back_to_classes_grades"
            ))
            
            keyboard.adjust(1)
            
            await callback.message.edit_text(
                "Выберите задание для просмотра оценок:",
                reply_markup=keyboard.as_markup()
            )
        else:
            keyboard = InlineKeyboardBuilder()
            keyboard.add(InlineKeyboardButton(
                text="◀️ К списку классов",
                callback_data="back_to_classes_grades"
            ))
            await callback.message.edit_text(
                "В этом классе пока нет заданий.",
                reply_markup=keyboard.as_markup()
            )

    except Exception as e:
        logger.error(f"Ошибка при возврате к списку заданий: {e}")
        await callback.answer("Произошла ошибка. Пожалуйста, попробуйте позже.")

@dp.callback_query(lambda c: c.data == "back_to_classes_grades")
async def back_to_classes_grades(callback: CallbackQuery):
    try:
        teacher_id = callback.from_user.id
        
        # Получаем список классов учителя
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT id, class_name 
                FROM classes 
                WHERE teacher_id = ?
                ORDER BY class_name
            """, (teacher_id,))
            classes = c.fetchall()

        keyboard = InlineKeyboardBuilder()
        
        if classes:
            for class_id, class_name in classes:
                keyboard.add(InlineKeyboardButton(
                    text=class_name,
                    callback_data=f"grades_class_{class_id}"
                ))
            keyboard.adjust(1)
            
            await callback.message.edit_text(
                "Выберите класс для просмотра оценок:",
                reply_markup=keyboard.as_markup()
            )
        else:
            await callback.message.edit_text(
                "У вас пока нет классов.",
                reply_markup=None
            )
        
    except Exception as e:
        logger.error(f"Ошибка при возврате к списку классов: {e}")
        await callback.message.edit_text("Произошла ошибка. Пожалуйста, попробуйте позже.")

@dp.callback_query(lambda c: c.data.startswith('grades_assignment_'))
async def show_students_for_grades(callback: CallbackQuery):
    try:
        _, _, class_id, assignment_id = callback.data.split('_')
        
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT s.id, s.name, sb.evaluation, sb.feedback
                FROM students s
                LEFT JOIN submissions sb ON s.id = sb.student_id 
                    AND sb.assignment_id = ?
                WHERE s.class_id = ?
                ORDER BY s.name
            """, (assignment_id, class_id))
            students = c.fetchall()

        keyboard = InlineKeyboardBuilder()
        
        if students:
            message_text = "Список учеников и их оценки:\n\n"
            for student_id, name, evaluation, feedback in students:
                status = f" (Оценка: {evaluation}/10)" if evaluation is not None else " (Не оценено)"
                keyboard.add(InlineKeyboardButton(
                    text=f"👤 {name}{status}",
                    callback_data=f"grade_student_{student_id}_{assignment_id}"
                ))
        else:
            message_text = "В этом классе пока нет учеников."
            
        # Добавляем кнопку "Назад"
        keyboard.add(InlineKeyboardButton(
            text="◀️ Назад к заданиям",
            callback_data=f"grades_class_{class_id}"
        ))
        
        keyboard.adjust(1)
        
        await callback.message.edit_text(
            message_text,
            reply_markup=keyboard.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при показе учеников и оценок: {e}")
        await callback.message.edit_text("Произошла ошибка. Пожалуйста, попробуйте позже.")

# Обработчик выбора ученика для выставления оценки
@dp.callback_query(lambda c: c.data.startswith('grade_student_'))
async def grade_student(callback: CallbackQuery, state: FSMContext):
    try:
        parts = callback.data.split('_')
        if len(parts) < 4:
            await callback.message.edit_text("Неверный формат данных.")
            return
        
        student_id = parts[2]
        assignment_id = parts[3]
        
        # Получаем информацию о студенте и его ответе
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT s.name, sb.evaluation, sb.answer, sb.feedback
                FROM students s
                LEFT JOIN submissions sb ON s.id = sb.student_id 
                    AND sb.assignment_id = ?
                WHERE s.id = ?
            """, (assignment_id, student_id))
            student_info = c.fetchone()
            
        if not student_info:
            await callback.message.edit_text("Ученик не найден.")
            return
            
        name, current_grade, answer, feedback = student_info  # Добавлен feedback
        
        message_text = f"Ученик: {name}\n\n"
        if answer:
            message_text += f"Ответ ученика: {answer}\n\n"
        if feedback:  # Используем feedback вместо ai_feedback
            message_text += f"Обратная связь от ИИ: {feedback}\n\n"
        if current_grade is not None:
            message_text += f"Текущая оценка: {current_grade}/10\n\n"
        
        keyboard = InlineKeyboardBuilder()
        keyboard.button(
            text="◀️ Назад к списку учеников",
            callback_data=f"grades_assignment_class_{assignment_id}"
        )
        
        await callback.message.edit_text(
            message_text,
            reply_markup=keyboard.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при выборе ученика: {e}")
        await callback.message.edit_text("Произошла ошибка. Пожалуйста, попробуйте позже.")

@dp.callback_query(lambda c: c.data == 'back_to_classes_grades')
async def back_to_classes_grades(callback: CallbackQuery):
    try:
        teacher_id = callback.from_user.id
        
        # Получаем список классов учителя
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT DISTINCT c.id, c.name 
                FROM classes c
                JOIN teacher_classes tc ON c.id = tc.class_id
                WHERE tc.teacher_id = ?
                ORDER BY c.name
            """, (teacher_id,))
            classes = c.fetchall()
        
        keyboard = InlineKeyboardBuilder()
        for class_id, class_name in classes:
            keyboard.add(InlineKeyboardButton(
                text=class_name,
                callback_data=f"grades_class_{class_id}"
            ))
        keyboard.adjust(1)
        
        await callback.message.edit_text(
            "Выберите класс для просмотра оценок:",
            reply_markup=keyboard.as_markup()
        )
        
    except Exception as e:
        logger.error(f"Ошибка при возврате к списку классов: {e}")
        await callback.message.edit_text("Произошла ошибка. Пожалуйста, попробуйте позже.")


def get_user_profile(user_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT name FROM teachers WHERE id = ?", (user_id,))
        teacher = c.fetchone()
        if teacher:
            classes = get_teacher_classes(user_id)
            return {
                'type': 'teacher',
                'name': teacher[0],
                'classes': classes
            }
        else:
            c.execute("SELECT name, class_id FROM students WHERE id = ?", (user_id,))
            student = c.fetchone()
            if student:
                class_name = get_class_name(student[1])
                return {
                    'type': 'student',
                    'name': student[0],
                    'class': class_name
                }
    return None

def get_class_name(class_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT class_name FROM classes WHERE id = ?", (class_id,))
        result = c.fetchone()
        return result[0] if result else "Неизвестный класс"

def update_user_profile(user_id, new_name):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("UPDATE teachers SET name = ? WHERE id = ?", (new_name, user_id))
        if c.rowcount == 0:
            c.execute("UPDATE students SET name = ? WHERE id = ?", (new_name, user_id))
        conn.commit()

def get_assignment_statistics(class_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT a.id, a.text, a.deadline,
                   COUNT(DISTINCT s.id) as submissions,
                   AVG(s.evaluation) as avg_score
            FROM assignments a
 LEFT JOIN submissions s ON a.id = s.assignment_id
            WHERE a.class_id = ?
            GROUP BY a.id
        """, (class_id,))
        return c.fetchall()

def parse_evaluation(text):
    score_match = re.search(r'Оценка:\s(\d+)/10', text)
    if score_match:
        score = int(score_match.group(1))
    else:
        logger.warning("Не удалось найти оценку в ответе от AI")
        return None, None

    feedback_match = re.search(r'Обоснование:(.*)', text, re.DOTALL)
    if feedback_match:
        feedback = feedback_match.group(1).strip()
    else:
        logger.warning("Не удалось найти обоснование в ответе от AI")
        return None, None

    return score, feedback
async def schedule_results_sending(assignment_id: int, deadline: datetime):
    await asyncio.sleep((deadline - datetime.now(TIMEZONE)).total_seconds() + 5)
    await send_results_to_teacher(assignment_id)

async def send_results_to_teacher(assignment_id: int):
    results = get_assignment_results(assignment_id)
    
    # Получаем класс, который был выбран для задания
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT c.teacher_id, c.class_name
            FROM assignments a
            JOIN classes c ON a.class_id = c.id
            WHERE a.id = ?
        """, (assignment_id,))
        result = c.fetchone()
    
    if result:
        teacher_id = result[0]
        class_name = result[1]
        
        message = f"Результаты задания #{assignment_id} в классе {class_name}:\n\n"
        for student, result in results.items():
            message += f"Студент: {student}\n"
            message += f"Оценка: {result['evaluation']}/10\n"
            message += f"Обратная связь: {result['feedback']}\n\n"
        
        try:
            await bot.send_message(teacher_id, message)
        except Exception as e:
            logger.error(f"Ошибка отправки результатов учителю {teacher_id}: {e}")
    else:
        logger.error(f"Ошибка: класс не найден для задания {assignment_id}")

def get_assignment_results(assignment_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT s.student_id, st.name, s.answer, s.evaluation, s.feedback
            FROM submissions s
            JOIN students st ON s.student_id = st.id
            WHERE s.assignment_id = ?
        """, (assignment_id,))
        results = c.fetchall()
        
    formatted_results = {}
    for student_id, student_name, answer, evaluation, feedback in results:
        formatted_results[student_name] = {
            'answer': answer,
            'evaluation': evaluation,
            'feedback': feedback
        }
    
    return formatted_results

async def main():
    init_db()
    scheduler.start()
    logger.info("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    init_db()
    asyncio.run(main())
