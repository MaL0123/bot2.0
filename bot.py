import telebot
from googleapiclient.discovery import build
from google.oauth2 import service_account
from telebot import types
from api_token import BOT_TOKEN
import time
import configparser
import logging
import json
import threading
import os

config = configparser.ConfigParser()
config.read('config.ini')

SPREADSHEET_ID = config['GoogleSheets']['spreadsheet_id']

ADMIN_ID = 653146205  # Замените на ID администратора
USER_DATA_FILE = 'users.json'
# Настройка бота
bot = telebot.TeleBot(BOT_TOKEN)

lock = threading.Lock()

# Функция для загрузки данных пользователей
def load_user_data():
    try:
        if os.path.exists(USER_DATA_FILE):
            with open(USER_DATA_FILE, 'r') as f:
                return json.load(f)
        else:
            logging.info(f"Файл {USER_DATA_FILE} не найден. Создается новый файл.")
            return {}
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.error(f"Ошибка при загрузке данных пользователей: {str(e)}")
        return {}

# Функция для сохранения данных пользователей
def save_user_data(user_data):
    with lock:
        try:
            with open(USER_DATA_FILE, 'w') as f:
                json.dump(user_data, f, indent=4)
            logging.info(f"Данные пользователей успешно сохранены в {USER_DATA_FILE}.")
        except Exception as e:
            logging.error(f"Ошибка при сохранении данных пользователей: {str(e)}")

# Функция для добавления пользователя в JSON-файл
def add_user(user):
    user_data = load_user_data()
    user_id = str(user.id)

    if user_id not in user_data:
        user_info = {
            "first_seen": time.time(),
            "username": user.username if user.username else None,
            "first_name": user.first_name if user.first_name else None,
            "last_name": user.last_name if user.last_name else None
        }
        user_data[user_id] = user_info
        logging.info(f"Добавление нового пользователя: {user_info}")
        save_user_data(user_data)
    else:
        logging.info(f"Пользователь с ID {user_id} уже существует.")

@bot.message_handler(commands=['otvet'])
def broadcast_message(message):
    """Команда для рассылки сообщений всем пользователям (только для администратора)."""
    if message.from_user.id == ADMIN_ID:
        msg = bot.send_message(message.chat.id, "Введите сообщение для рассылки:")
        bot.register_next_step_handler(msg, send_broadcast_message)
    else:
        bot.send_message(message.chat.id, "У вас нет прав для выполнения этой команды.")

def send_broadcast_message(message):
    """Отправка сообщения всем пользователям из списка."""
    broadcast_text = message.text
    user_data = load_user_data()

    failed_users = []
    for user_id in user_data:
        try:
            bot.send_message(user_id, broadcast_text)
        except Exception as e:
            logging.error(f"Не удалось отправить сообщение пользователю {user_id}: {str(e)}")
            failed_users.append(user_id)

    if failed_users:
        bot.send_message(message.chat.id, f"Сообщение не удалось отправить следующим пользователям: {failed_users}")
    else:
        bot.send_message(message.chat.id, "Сообщение успешно отправлено всем пользователям.")

    logging.info("Рассылка завершена.")

@bot.message_handler(commands=['usercount'])
def user_count(message):
    """Команда для получения количества пользователей бота (только для администратора)."""
    if message.from_user.id == ADMIN_ID:
        user_data = load_user_data()
        user_count = len(user_data)
        bot.send_message(message.chat.id, f"Количество пользователей бота: {user_count}")
    else:
        bot.send_message(message.chat.id, "У вас нет прав для выполнения этой команды.")

@bot.message_handler(commands=['admin'])
def set_spreadsheet_id(message):
    """Команда для изменения Spreadsheet ID (только для администратора)."""
    bot.clear_step_handler_by_chat_id(message.chat.id)  # Очищаем предыдущие шаги
    if message.from_user.id == ADMIN_ID:
        msg = bot.send_message(message.chat.id, "Введите новый Spreadsheet ID:")
        bot.register_next_step_handler(msg, save_spreadsheet_id)
    else:
        bot.send_message(message.chat.id, "У вас нет прав для изменения Spreadsheet ID.")


def save_spreadsheet_id(message):
    global SPREADSHEET_ID
    SPREADSHEET_ID = message.text.strip()

    # Обновление в файле config.ini
    config['GoogleSheets']['spreadsheet_id'] = SPREADSHEET_ID
    with open('config.ini', 'w') as configfile:
        config.write(configfile)

    bot.send_message(message.chat.id, f"Spreadsheet ID успешно обновлен на: {SPREADSHEET_ID}")

# Настройка Google Sheets API
SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
SERVICE_ACCOUNT_FILE = 'BOT.json'
credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
service = build('sheets', 'v4', credentials=credentials)
sheet = service.spreadsheets()

# Кнопки и переменные
role_buttons = ["Студент🧑‍🎓", "Преподаватель👨‍🏫"]
days = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота"]
days_for_first_course = ["понедельник", "вторник", "среда", "четверг", "пятница"]  # Суббота скрыта для первого курса
courses = ["1 курс", "2 курс", "3 курс", "4 курс", "5 курс"]
para_times = ['8:30-10:05', '10:15-11:50', '12:00-13:35', '14:15-15:50', '16:00-17:35', '17:45-19:20']
saturday_para_times = ['8:30-10:05', '10:15-11:50', '12:00-13:35', '14:15-15:50']  # Время пар для субботы
user_variables = {}

# Кэширование данных
cache = {
    "data": None,
    "timestamp": 0,
    "cache_duration": 300  # 5 минут
}

def read_google_sheet(spreadsheet_id, range_name):
    """Чтение данных из Google Sheets с кэшированием."""
    current_time = time.time()
    if cache["data"] is None or (current_time - cache["timestamp"] > cache["cache_duration"]):
        result = sheet.values().get(spreadsheetId=spreadsheet_id, range=range_name).execute()
        cache["data"] = result.get('values', [])
        cache["timestamp"] = current_time
    return cache["data"]

@bot.message_handler(commands=['start'])
def start(message):
    """Начальный экран с выбором роли."""
    add_user(message.from_user)  # Добавляем пользователя в JSON
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*role_buttons)
    msg = bot.send_message(message.chat.id, "Привет! Какое расписание тебе нужно?", reply_markup=markup)
    bot.register_next_step_handler(msg, process_role)

@bot.message_handler(func=lambda message: message.text == "Прочитано")
def handle_read(message):
    start(message)

def process_role(message):
    """Обработка выбора роли."""
    role = message.text
    if role == 'Студент🧑‍🎓':
        select_course(message)
    elif role == 'Преподаватель👨‍🏫':
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("На один день", "На всю неделю", "Назад")
        msg = bot.send_message(message.chat.id, "🧐Вы хотите посмотреть расписание на один день или на всю неделю?", reply_markup=markup)
        bot.register_next_step_handler(msg, handle_schedule_choice_teacher)
    else:
        start(message)

def select_course(message):
    """Выбор курса для студентов."""
    chat_id = message.chat.id
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*courses)
    msg = bot.send_message(chat_id, "Выберите ваш курс:", reply_markup=markup)
    bot.register_next_step_handler(msg, handle_course_selection)

def handle_course_selection(message):
    """Обработка выбора курса для студентов."""
    chat_id = message.chat.id
    course = message.text.lower()
    course_mapping = {
        "1 курс": "I   к у р с",
        "2 курс": "I I  к у р с",
        "3 курс": "I I I   к у р с",
        "4 курс": "I V   к у р с",
        "5 курс": "V   курс",
    }

    if course in course_mapping:
        user_variables[chat_id] = {
            "course": course_mapping[course],
        }
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        markup.add("На один день", "На всю неделю", "Назад")
        msg = bot.send_message(chat_id, "Вы хотите посмотреть расписание на один день или на всю неделю?", reply_markup=markup)
        bot.register_next_step_handler(msg, handle_schedule_choice_student)
    else:
        select_course(message)

def handle_schedule_choice_student(message):
    """Обработка выбора расписания для студентов (на один день или на неделю)."""
    choice = message.text.lower()
    chat_id = message.chat.id
    if choice == 'на один день':
        select_day(message)
    elif choice == 'на всю неделю':
        select_group_weekly(message)  # Здесь нужно было исправить имя функции
    elif choice == "Назад":
        select_course(message)
    else:
        select_course(message)

# Выбор дня недели для студентов
def select_day(message):
    """Выбор дня недели для студентов."""
    chat_id = message.chat.id
    course = user_variables[chat_id].get('course', '')
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)

    if course == "I   к у р с":
        markup.add(*days_for_first_course)  # Скрываем субботу для первого курса
    else:
        markup.add(*days) # Для остальных курсов отображаем субботу

    markup.add("Назад")
    msg = bot.send_message(chat_id, "На какой день нужно расписание?", reply_markup=markup)
    bot.register_next_step_handler(msg, handle_day_selection)

def handle_day_selection(message):
    """Обработка выбора дня недели и сохранение строки для этого дня."""
    chat_id = message.chat.id
    selected_day = message.text.lower()

    day_row_mapping = {
        "понедельник": 3,
        "вторник": 9,
        "среда": 15,
        "четверг": 21,
        "пятница": 27,
        "суббота": 33
    }

    if selected_day in day_row_mapping:
        user_variables[chat_id]['day_row'] = day_row_mapping[selected_day]
        choose_group(message)  # Переход к выбору группы после выбора дня
    else:
        bot.send_message(chat_id, "Неверный выбор дня. Пожалуйста, выберите день снова.")
        select_day(message)

def find_groups_for_course(course_label):
    """Поиск диапазона колонок для групп под объединённой ячейкой с названием курса."""
    data = read_google_sheet(SPREADSHEET_ID, '2 Семестр!A1:FS40')

    start_col = None
    end_col = None
    groups = []

    # Поиск строки с названием курса
    for col_num, cell in enumerate(data[1]):  # Проходим по второй строке (индекс 1)
        if cell.strip() == course_label:
            start_col = col_num
            # Теперь найдём, где заканчивается объединённая ячейка
            for next_col in range(col_num + 1, len(data[1])):
                if data[1][next_col].strip() != "":
                    end_col = next_col
                    break
            if end_col is None:  # Если не нашли ненулевую ячейку дальше, конец - последний столбец
                end_col = len(data[1])
            break

    if start_col is not None:
        print(f"Объединённая ячейка '{course_label}' найдена в колонке {start_col}, заканчивается в колонке {end_col - 1}")
        print("Группы под этой ячейкой:")

        for col_num in range(start_col, end_col):
            if data[2][col_num] and data[2][col_num].strip():  # Если ячейка не пуста
                groups.append((col_num, data[2][col_num]))

        return groups
    else:
        print(f"Объединённая ячейка '{course_label}' не найдена.")
        return None

def choose_group(message):
    """Выбор группы после выбора курса."""
    chat_id = message.chat.id
    course = user_variables[chat_id].get('course', '')

    groups = find_groups_for_course(course)

    if groups:
        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons_group = [types.InlineKeyboardButton(group_name, callback_data=str(col_num)) for col_num, group_name in groups if group_name.strip().lower() != "№ пары"]
        markup.add(*buttons_group)
        bot.send_message(chat_id, "Выберите свою группу:", reply_markup=markup)
    else:
        bot.send_message(chat_id, "Группы для выбранного курса не найдены.")
        select_course(message)

@bot.callback_query_handler(func=lambda call: True)
def on_group_selected(call):
    """Обработка выбранной группы и вывод расписания на один день или на неделю."""
    chat_id = call.message.chat.id
    column_number = int(call.data)  # Получаем номер колонки
    user_variables[chat_id]['selected_group_col'] = column_number  # Сохраняем выбранную группу
    print(user_variables[chat_id])

    # Проверка, что пользователь выбрал опцию на один день или на всю неделю
    if 'day_row' in user_variables[chat_id]:
        # Если выбрана опция на один день
        send_daily_schedule_student(call.message)
    else:
        # Если выбрана опция на всю неделю
        send_weekly_schedule_student(call.message)

def send_daily_schedule_student(message):
    """Отправка расписания на один день для студентов."""
    chat_id = message.chat.id
    data = read_google_sheet(SPREADSHEET_ID, '2 Семестр!A1:FS40')
    column_number = user_variables[chat_id]['selected_group_col']
    start_row = user_variables[chat_id].get("day_row", 0)
    group_name = data[2][column_number]

    if column_number is None or start_row == 0:
        bot.send_message(chat_id, "Группа или день не найдены.")
        return

    para_times_used = para_times if start_row != 33 else saturday_para_times  # Проверка, если суббота

    response = f"Ваше расписание для группы *{group_name}*:\n\n"
    for i in range(len(para_times_used)):  # Проверяем количество пар
        if start_row + i < len(data):  # Проверка длины данных
            row = data[start_row + i + 2]  # Смещение на 2 строки для корректного доступа
            pair_info_raw = row[column_number] if len(row) > column_number else "Окно"
            if not pair_info_raw or pair_info_raw.lower() == "окно":
                response += f"*{i + 1} пара*\n🎓 Пара: *Окно😋*\n\n"
            else:
                pair_info_lines = pair_info_raw.split('\n')
                pair_info = pair_info_lines[0].strip()
                teacher_info = pair_info_lines[1].strip() if len(pair_info_lines) > 1 else "Преподаватель не указан"
                cabinet_info = row[column_number + 1] if len(row) > column_number + 1 else "Кабинет не указан"
                response += f"*{i + 1} пара*\n"
                response += f"⏰ {para_times_used[i]}\n"
                response += f"🎓 Пара: *{pair_info}*\n"
                response += f"👨‍🏫 Преподаватель: *{teacher_info}*\n"
                response += f"🏛 Кабинет: *{cabinet_info}*\n\n"

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("Прочитано")
    bot.send_message(chat_id, response, parse_mode="Markdown", reply_markup=markup)

def select_group_weekly(message):
    """Выбор группы для просмотра расписания на всю неделю."""
    chat_id = message.chat.id
    course = user_variables[chat_id].get('course', '')

    groups = find_groups_for_course(course)

    if groups:
        markup = types.InlineKeyboardMarkup(row_width=2)
        buttons_group = [types.InlineKeyboardButton(group_name, callback_data=str(col_num)) for col_num, group_name in groups if group_name.strip().lower() != "№ пары"]
        markup.add(*buttons_group)
        bot.send_message(chat_id, "Выберите свою группу:", reply_markup=markup)
    else:
        bot.send_message(chat_id, "Группы для выбранного курса не найдены.")
        select_course(message)

@bot.callback_query_handler(func=lambda call: True)
def on_group_selected_weekly(call):
    """Обработка выбранной группы и вывод расписания на всю неделю."""
    chat_id = call.message.chat.id
    column_number = int(call.data)  # Получаем номер колонки
    user_variables[chat_id]['selected_group_col'] = column_number  # Сохраняем выбранную группу

    send_weekly_schedule_student(call.message)

def send_weekly_schedule_student(message):
    """Отправка расписания на всю неделю для студентов."""
    chat_id = message.chat.id
    data = read_google_sheet(SPREADSHEET_ID, '2 Семестр!A1:FS40')
    column_number = user_variables[chat_id]['selected_group_col']
    group_name = data[2][column_number]
    course = user_variables[chat_id].get('course', '')

    if column_number is None:
        bot.send_message(chat_id, "Группа не найдена.")
        return

    days_to_process = days_for_first_course if course == "I   к у р с" else days  # Для 1 курса скрываем субботу

    day_row_mapping = {
        "понедельник": (3, para_times),
        "вторник": (9, para_times),
        "среда": (15, para_times),
        "четверг": (21, para_times),
        "пятница": (27, para_times),
        "суббота": (33, saturday_para_times)
    }

    for day in days_to_process:
        start_row, para_times_used = day_row_mapping[day]
        response = f"Расписание на {day} для группы *{group_name}*:\n\n"

        for i in range(len(para_times_used)):  # Проверяем количество пар для каждого дня
            if start_row + i < len(data):  # Проверка длины данных
                row = data[start_row + i + 2]  # Смещение на 2 строки для корректного доступа
                pair_info_raw = row[column_number] if len(row) > column_number else "Окно"
                if not pair_info_raw or pair_info_raw.lower() == "окно":
                    response += f"*{i + 1} пара*\n🎓 Пара: *Окно😋*\n\n"
                else:
                    pair_info_lines = pair_info_raw.split('\n')
                    pair_info = pair_info_lines[0].strip()
                    teacher_info = pair_info_lines[1].strip() if len(pair_info_lines) > 1 else "Преподаватель не указан"
                    cabinet_info = row[column_number + 1] if len(row) > column_number + 1 else "Кабинет не указан"
                    response += f"*{i + 1} пара*\n"
                    response += f"⏰ {para_times_used[i]}\n"
                    response += f"🎓 Пара: *{pair_info}*\n"
                    response += f"👨‍🏫 Преподаватель: *{teacher_info}*\n"
                    response += f"🏛 Кабинет: *{cabinet_info}*\n\n"

        # Отправляем расписание на каждый день отдельным сообщением
        if response.strip():  # Отправляем только если есть данные для отправки
            markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
            markup.add("Прочитано")
            bot.send_message(chat_id, response, parse_mode="Markdown", reply_markup=markup)


def handle_schedule_choice_teacher(message):
    """Обработка выбора расписания для преподавателей (на один день или на неделю)."""
    choice = message.text.lower()
    if choice == 'на один день':
        select_day_for_teacher(message)
    elif choice == 'на всю неделю':
        select_teacher_weekly(message)
    else:
        process_role(message)

def select_day_for_teacher(message):
    """Выбор дня недели для преподавателя."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(*days)
    msg = bot.send_message(message.chat.id, 'Выберите день недели:', reply_markup=markup)
    bot.register_next_step_handler(msg, handle_day_choice)

def handle_day_choice(message):
    """Обработка выбора дня и запрос фамилии преподавателя."""
    day = message.text.lower()
    if day in days:
        start_row, end_row = get_row_range(day)
        msg = bot.send_message(message.chat.id, 'Введите фамилию преподавателя👨‍🏫:')
        bot.register_next_step_handler(msg, lambda msg: search_teacher_schedule(msg, start_row, end_row))
    else:
        select_day_for_teacher(message)

def get_row_range(day):
    """Получение диапазона строк для указанного дня недели."""
    days_range = {
        'понедельник': (6, 11),
        'вторник': (12, 17),
        'среда': (18, 23),
        'четверг': (24, 29),
        'пятница': (30, 35),
        'суббота': (36, 40)  # Для субботы диапазон заканчивается на 40-й строке, так как максимум 4 пары
    }
    return days_range.get(day, (None, None))

def search_teacher_schedule(message, start_row=None, end_row=None):
    """Поиск расписания преподавателя."""
    query = message.text.strip().lower()
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add('Назад')

    data = read_google_sheet(SPREADSHEET_ID, '2 Семестр!A1:FS40')

    result = []

    # Вычисляем соответствие времени парам
    for i in range(start_row, end_row):
        if i < len(data):
            row = data[i]
            for j, cell in enumerate(row):
                if query in str(cell).lower():
                    group = data[2][j]
                    pair_info_lines = cell.split('\n')
                    pair_info = pair_info_lines[0].strip()
                    teacher_info = pair_info_lines[1].strip() if len(pair_info_lines) > 1 else "Преподаватель не указан"
                    cabinet_info = row[j + 1] if len(row) > j + 1 else "Кабинет не указан"
                    time_info = para_times[i - start_row]  # Используем индекс, чтобы подобрать время пары
                    result.append((pair_info, group, teacher_info, cabinet_info, time_info, f'{i - start_row + 1}'))

                    break

    if result:
        response = f"Расписание на выбранный день:\n\n"
        for entry in result:
            response += (
                f'*❗️---{entry[5]} пара---❗️*\n'
                f'⏰ Время: *{entry[4]}*\n'
                f'👥 Группа: *{entry[1]}*\n'
                f'🎓 Название пары: *{entry[0]}*\n'
                f'👨‍🏫 Преподаватель: *{entry[2]}*\n'
                f'🏛 Кабинет: *{entry[3]}*\n\n'
            )
        bot.send_message(message.chat.id, response, parse_mode='Markdown')
        start(message)
    else:
        bot.send_message(message.chat.id, 'Преподаватель не найден или не имеет расписания на этот день.', reply_markup=markup)
        handle_day_choice(message)

# Новый функционал для преподавателей
def select_teacher_weekly(message):
    """Запрос фамилии преподавателя для просмотра расписания на всю неделю."""
    msg = bot.send_message(message.chat.id, 'Введите фамилию преподавателя👨‍🏫:')
    bot.register_next_step_handler(msg, send_weekly_schedule_teacher)

def send_weekly_schedule_teacher(message):
    """Отправка расписания на всю неделю для преподавателей."""
    chat_id = message.chat.id
    query = message.text.strip().lower()
    data = read_google_sheet(SPREADSHEET_ID, '2 Семестр!A1:FS40')

    day_row_mapping = {
        "понедельник": (6, 11, para_times),
        "вторник": (12, 17, para_times),
        "среда": (18, 23, para_times),
        "четверг": (24, 29, para_times),
        "пятница": (30, 35, para_times),
        "суббота": (36, 40, saturday_para_times)
    }

    for day, (start_row, end_row, para_times_used) in day_row_mapping.items():
        result = []
        for i in range(start_row, end_row):
            if i < len(data):  # Проверка длины данных
                row = data[i]
                for j, cell in enumerate(row):
                    if query in str(cell).lower():
                        group = data[2][j]
                        pair_info_lines = cell.split('\n')
                        pair_info = pair_info_lines[0].strip()
                        teacher_info = pair_info_lines[1].strip() if len(pair_info_lines) > 1 else "Преподаватель не указан"
                        cabinet_info = row[j + 1] if len(row) > j + 1 else "Кабинет не указан"
                        time_info = para_times_used[i - start_row]  # Используем индекс для подбора времени пары
                        result.append((pair_info, group, teacher_info, cabinet_info, time_info, f'{i - start_row + 1}'))

                        break

        if result:
            response = f"Расписание на {day}:\n\n"
            for entry in result:
                response += (
                    f'*❗️---{entry[5]} пара---❗️*\n'
                    f'⏰ Время: *{entry[4]}*\n'
                    f'👥Группа: *{entry[1]}*\n'
                    f'🎓 Название пары: *{entry[0]}*\n'
                    f'👨‍🏫 Преподаватель: *{entry[2]}*\n'
                    f'🏛 Кабинет: *{entry[3]}*\n\n'
                )
            bot.send_message(chat_id, response, parse_mode='Markdown')

    start(message)

while True:
    try:
        logging.info("Запуск бота...")
        bot.polling(none_stop=True, interval=0, timeout=20)
    except Exception as e:
        logging.error(f"Произошла ошибка: {str(e)}")
        time.sleep(5)  # Задержка перед перезапуском