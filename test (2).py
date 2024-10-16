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
            text="Выберите дедлайн для задания:",
            parse_mode=ParseMode.MARKDOWN
        )
        await menu_message.edit_reply_markup(reply_markup=keyboard.as_markup())
        
        # Установить состояние ожидания выбора дедлайна
        await state.set_state(UserStates.waiting_for_deadline_year)
    else:
        await bot.send_message(callback.message.chat.id, "Ошибка добавления задания. Пожалуйста, повторите попытку.")
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
    await state.update_data(assignment_text=message.text)
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
    minute = callback.data.split(":")[1]
    data = await state.get_data()
    deadline_date = data['deadline_date']
    deadline_hour = data['deadline_hour']
    deadline_str = f"{deadline_date} {deadline_hour}:{minute}"
    
    class_id = data.get('class_id')
    assignment_text = data.get('generated_assignment_text')
    assignment_id = add_assignment(class_id, assignment_text, deadline_str)
    
    if assignment_id:
        # Get deadline from database
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("SELECT deadline FROM assignments WHERE id = ?", (assignment_id,))
            deadline = c.fetchone()[0]
            deadline = datetime.strptime(deadline, '%Y-%m-%d %H:%M')
            deadline = TIMEZONE.localize(deadline)
        
        new_text = f"Задание успешно добавлено!\nТекст: {assignment_text}\nДедлайн: {deadline_str}"
        
        await bot.send_message(callback.message.chat.id, new_text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        
        asyncio.create_task(schedule_results_sending(assignment_id, deadline))
        
        students = get_class_students(class_id)
        for student_id, student_name in students:
            try:
                await bot.send_message(
                    student_id,
                    f"📚 Новое задание:\n{assignment_text}\n📅 Дедлайн: {deadline_str}",
                    parse_mode=ParseMode.MARKDOWN,
                    disable_notification=True
                )
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения ученику {student_id}: {e}")
    else:
        await bot.send_message(callback.message.chat.id, "Ошибка добавления задания. Пожалуйста, повторите попытку.")
@dp.callback_query(F.data.startswith("submit:"))
async def process_submission_selection(callback: types.CallbackQuery, state: FSMContext):
    assignment_id = callback.data.split(":")[1]
    await state.update_data(assignment_id=assignment_id)
    await callback.message.reply("Введите ваш ответ на задание:")
    await callback.answer()

@dp.message(F.text == "🔗 Мои ссылки")
async def show_links(message: types.Message):
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

@dp.message(F.text.startswith("/copy_"))
async def copy_link(message: types.Message):
    command, class_id = message.text.split("_", 1)
    class_id = int(class_id)
    
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT link FROM links WHERE class_id = ?", (class_id,))
        link_result = c.fetchone()
        
        if link_result:
            link = link_result[0]
            await message.reply(f"Ссылка скопирована: {link}")
            # Добавьте код здесь, чтобы фактически скопировать ссылку в буфер обмена пользователя
        else:
            await message.reply("Ссылка не найдена.")
@dp.message(F.text == "📚 Мои задания")
async def show_assignments(message: types.Message):
    user_id = message.from_user.id
    student_class_id = get_student_class(user_id)
    if not student_class_id:
        await message.reply("Вы не зарегистрированы в классе.")
        return
    
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT text, deadline FROM assignments WHERE class_id = ?", (student_class_id,))
        assignments = c.fetchall()
        if assignments:
            response = "📚 Мои задания:\n\n"
            for assignment in assignments:
                response += f"📝 {assignment[0]}\n📅 {assignment[1]}\n\n"
            await message.reply(response)
        else:
            await message.reply("У вас пока нет заданий.")

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
        c.execute("INSERT INTO classes (teacher_id, class_name) VALUES (?, ?)", 
                  (message.from_user.id, class_name))
        class_id = c.lastrowid
        conn.commit()
        
        # Генерация уникальной реферальной ссылки
        ref_link = f"https://t.me/edustud_bot?start={class_id}"
        
        # Хранение реферальной ссылки в таблице links
        c.execute("INSERT INTO links (class_id, link) VALUES (?, ?)", 
                  (class_id, ref_link))
        conn.commit()
    
    await message.reply("Класс создан!")
    await state.clear()

# Statistics
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
        stats = get_assignment_statistics(class_id)
        if stats:
            response = f"📊 Статистика класса {class_name}:\n\n"
            for assignment_id, text, deadline, submissions, avg_score in stats:
                response += f"📝 Задание: {text}\n"
                response += f"📅 Дедлайн: {deadline}\n"
                response += f"📤 Отправлено работ: {submissions}\n"
                if avg_score is not None:
                    response += f"📈 Средний балл: {avg_score:.1f}/10\n\n"
                else:
                    response += "📈 Средний балл: Нет данных\n\n"
        else:
            response = f"В классе {class_name} пока нет заданий."
        
        await message.reply(response, parse_mode=ParseMode.MARKDOWN)

# Teacher assignments
@dp.message(F.text == "📝 Посмотреть мои задания")
async def show_teacher_assignments(message: types.Message):
    if not is_teacher(message.from_user.id):
        await message.reply("Эта функция доступна только для учителей.")
        return
    
    assignments = get_teacher_assignments(message.from_user.id)
    if not assignments:
        await message.reply("У вас пока нет созданных заданий.")
        return
    
    response = "📝 Ваши задания:\n\n"
    for class_name, assignment_text, deadline in assignments:
        response += f"📚 Класс: {class_name}\n"
        response += f"📝 Задание: {assignment_text}\n"
        response += f"📅 Дедлайн: {deadline}\n\n"
    
    await message.reply(response, parse_mode=ParseMode.MARKDOWN)

# Student grades
@dp.message(F.text == "📊 Посмотреть оценки учеников")
async def show_student_grades(message: types.Message):
    if not is_teacher(message.from_user.id):
        await message.reply("Эта функция доступна только для учителей.")
        return
    
    classes = get_teacher_classes(message.from_user.id)
    if not classes:
        await message.reply("У вас пока нет классов.")
        return
    
    response = "📊 Оценки учеников по классам:\n\n"
    
    for class_id, class_name in classes:
        grades = get_student_grades(class_id)
        if grades:
            response += f"Класс: {class_name}\n"
            for student_name, assignment_text, evaluation in grades:
                response += f"👤 Студент: {student_name}\n"
                response += f"📝 Задание: {assignment_text}\n"
                response += f"📈 Оценка: {evaluation}/10\n\n"
        else:
            response += f"Класс: {class_name}\nНет оценок для этого класса.\n\n"
    
    await message.reply(response or "Нет оценок для всех классов.", parse_mode=ParseMode.MARKDOWN)

# Helper functions
def get_student_grades(class_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT st.name, a.text, s.evaluation
            FROM submissions s
            JOIN students st ON s.student_id = st.id
            JOIN assignments a ON s.assignment_id = a.id
            WHERE a.class_id = ?
        """, (class_id,))
        return c.fetchall()

def get_teacher_assignments(teacher_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT c.class_name, a.text, a.deadline
            FROM assignments a
            JOIN classes c ON a.class_id = c.id
            WHERE c.teacher_id = ?
            ORDER BY a.deadline
        """, (teacher_id,))
        return c.fetchall()

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

def get_teacher_id_for_assignment(assignment_id):
    with get_db_connection() as conn:
        c = conn.cursor()
        c.execute("""
            SELECT c.teacher_id
            FROM assignments a
            JOIN classes c ON a.class_id = c.id
            WHERE a.id = ?
        """, (assignment_id,))
        result = c.fetchone()
    return result[0] if result else None

async def main():
    init_db()
    scheduler.start()
    logger.info("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    init_db()
    asyncio.run(main())