#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import json
import logging
import datetime
import time
import threading
import schedule
import pytz
import fcntl
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, BotCommand
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, ConversationHandler
from google_meet.google_meet import google_meet

# Load environment variables from .env file
load_dotenv()

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Create lock file to prevent multiple instances
LOCK_FILE = 'bot.lock'
lock_file_handle = None

def check_single_instance():
    """Ensure only one instance of the bot is running."""
    global lock_file_handle
    
    # Skip lock check if running under PM2
    if os.environ.get('PM2_HOME') is not None:
        logger.info("Running under PM2, skipping lock check")
        return True
    
    try:
        # Open the lock file
        lock_file_handle = open(LOCK_FILE, 'w')
        
        # Try to acquire an exclusive lock
        fcntl.flock(lock_file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        
        # If we got here, no other instance is running
        return True
    except IOError:
        # Another instance has the lock
        logger.error("Another instance of the bot is already running!")
        return False

# Conversation states
ADD_SCHEDULE, DELETE_SCHEDULE = range(2)

# Storage for scheduled tasks
SCHEDULE_FILE = 'scheduled_meets.json'
scheduled_meets = {}
schedule_lock = threading.Lock()

# Moscow timezone
MOSCOW_TZ = pytz.timezone('Europe/Moscow')

# Days of the week in Russian
DAYS_RU = {
    'понедельник': 0,
    'вторник': 1,
    'среда': 2,
    'четверг': 3,
    'пятница': 4,
    'суббота': 5,
    'воскресенье': 6
}

# Days of the week in Russian for display
DAYS_DISPLAY = {
    0: 'понедельник',
    1: 'вторник',
    2: 'среда',
    3: 'четверг',
    4: 'пятница',
    5: 'суббота',
    6: 'воскресенье'
}

# Используем dict для отслеживания состояний в разных чатах
user_states = {}

def load_schedules():
    """Load schedules from file."""
    global scheduled_meets
    if os.path.exists(SCHEDULE_FILE):
        with open(SCHEDULE_FILE, 'r') as f:
            data = json.load(f)
            scheduled_meets = {int(k): v for k, v in data.items()}
    else:
        scheduled_meets = {}

def save_schedules():
    """Save schedules to file."""
    with open(SCHEDULE_FILE, 'w') as f:
        json.dump(scheduled_meets, f)

def setup_commands(updater):
    """Set up bot commands in menu"""
    commands = [
        BotCommand("start", "Начать работу с ботом"),
        BotCommand("help", "Показать справку"),
        BotCommand("add", "Добавить еженедельную отправку"),
        BotCommand("addtime", "Добавить отправку в формате: /addtime день ЧЧ:ММ"),
        BotCommand("list", "Посмотреть отправки"),
        BotCommand("delete", "Удалить отправку"),
        BotCommand("deletetime", "Удалить отправку в формате: /deletetime день ЧЧ:ММ"),
        BotCommand("meet", "Мгновенная встреча")
    ]
    updater.bot.set_my_commands(commands)
    logger.info("Bot commands have been set up")

def start(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    chat_id = update.effective_chat.id
    
    keyboard = [
        ['/add', '/list'],
        ['/delete', '/meet'],
        ['/help']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    update.message.reply_text(
        f'Привет, {user.first_name}! Я бот для создания и отправки ссылок на Google Meet.\n\n'
        'Используйте команды ниже для управления автоматическими отправками.',
        reply_markup=reply_markup
    )
    
    # Register chat_id if it's a group
    if update.effective_chat.type in ['group', 'supergroup']:
        with schedule_lock:
            load_schedules()
            group_name = update.effective_chat.title
            logger.info(f"Bot added to group: {group_name} ({chat_id})")

def add_schedule_command(update: Update, context: CallbackContext) -> int:
    """Start the process of adding a new schedule."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Сохраняем состояние пользователя/чата
    user_states[f"{chat_id}_{user_id}"] = ADD_SCHEDULE
    
    # Проверяем, является ли отправитель администратором группы, если это групповой чат
    if update.effective_chat.type in ['group', 'supergroup']:
        try:
            member = context.bot.get_chat_member(chat_id, user_id)
            if member.status not in ['creator', 'administrator']:
                update.message.reply_text('Только администраторы группы могут управлять расписанием.')
                return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
            update.message.reply_text('Произошла ошибка при проверке прав администратора.')
            return ConversationHandler.END
    
    update.message.reply_text(
        'Укажите день недели и время по Москве в формате "день ЧЧ:ММ"\n'
        'Например: среда 12:46'
    )
    return ADD_SCHEDULE

def process_schedule_add(update: Update, context: CallbackContext) -> int:
    """Process a schedule request."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    state_key = f"{chat_id}_{user_id}"
    
    # Проверяем состояние пользователя
    if state_key not in user_states or user_states[state_key] != ADD_SCHEDULE:
        logger.info(f"Received message without valid state: {update.message.text} from {user_id} in chat {chat_id}")
        return ConversationHandler.END
    
    text = update.message.text.strip().lower()
    logger.info(f"Processing add schedule: {text} from user {user_id} in chat {chat_id}")
    
    try:
        day_text, time_text = text.split(' ', 1)
        
        if day_text not in DAYS_RU:
            update.message.reply_text(
                f'Некорректный день недели. Используйте: {", ".join(DAYS_RU.keys())}'
            )
            return ADD_SCHEDULE
        
        day_of_week = DAYS_RU[day_text]
        
        try:
            hours, minutes = map(int, time_text.split(':'))
            if not (0 <= hours < 24 and 0 <= minutes < 60):
                raise ValueError("Invalid time")
        except:
            update.message.reply_text('Некорректный формат времени. Используйте ЧЧ:ММ, например 12:46')
            return ADD_SCHEDULE
        
        with schedule_lock:
            load_schedules()
            
            if chat_id not in scheduled_meets:
                scheduled_meets[chat_id] = []
            
            # Check if this schedule already exists
            for schedule_item in scheduled_meets[chat_id]:
                if schedule_item['day'] == day_of_week and schedule_item['hours'] == hours and schedule_item['minutes'] == minutes:
                    update.message.reply_text('Такое расписание уже существует!')
                    # Очищаем состояние
                    if state_key in user_states:
                        del user_states[state_key]
                    return ConversationHandler.END
            
            # Add new schedule
            scheduled_meets[chat_id].append({
                'day': day_of_week,
                'hours': hours,
                'minutes': minutes
            })
            
            save_schedules()
            
            # Schedule just this new task instead of rescheduling everything
            if hasattr(context, 'job_queue') and context.job_queue:
                create_job_for_schedule(
                    context.bot,
                    context.job_queue,
                    chat_id,
                    day_of_week,
                    hours,
                    minutes
                )
        
        update.message.reply_text(
            f'Еженедельная отправка добавлена: {day_text} {hours:02d}:{minutes:02d}'
        )
    except Exception as e:
        logger.error(f"Error adding schedule: {e}")
        update.message.reply_text(
            'Произошла ошибка. Убедитесь, что формат "день ЧЧ:ММ" правильный.\n'
            'Например: среда 12:46'
        )
    
    # Очищаем состояние
    if state_key in user_states:
        del user_states[state_key]
    
    return ConversationHandler.END

def list_schedules(update: Update, context: CallbackContext) -> None:
    """Show all scheduled tasks for the user."""
    chat_id = update.effective_chat.id
    
    # Получаем thread_id (ID темы), если сообщение из темы в супергруппе
    thread_id = update.message.message_thread_id if hasattr(update.message, 'message_thread_id') else None
    
    with schedule_lock:
        load_schedules()
        
        if chat_id not in scheduled_meets or not scheduled_meets[chat_id]:
            update.message.reply_text('У вас нет запланированных еженедельных отправок.')
            return
        
        schedules_list = []
        for schedule_item in scheduled_meets[chat_id]:
            # Если сообщение из темы, показываем только настройки для этой темы
            if thread_id is not None and schedule_item.get('thread_id') != thread_id:
                continue
                
            day = DAYS_DISPLAY[schedule_item['day']]
            hours = schedule_item['hours']
            minutes = schedule_item['minutes']
            schedules_list.append(f"{day} {hours:02d}:{minutes:02d}")
        
        if not schedules_list and thread_id is not None:
            update.message.reply_text('В этой теме нет запланированных еженедельных отправок.')
            return
            
        message = "Ваши еженедельные отправки:\n" + "\n".join(schedules_list)
        update.message.reply_text(message)

def delete_schedule_command(update: Update, context: CallbackContext) -> int:
    """Start the process of deleting a schedule."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Сохраняем состояние пользователя/чата
    user_states[f"{chat_id}_{user_id}"] = DELETE_SCHEDULE
    
    # Проверяем, является ли отправитель администратором группы, если это групповой чат
    if update.effective_chat.type in ['group', 'supergroup']:
        try:
            member = context.bot.get_chat_member(chat_id, user_id)
            if member.status not in ['creator', 'administrator']:
                update.message.reply_text('Только администраторы группы могут управлять расписанием.')
                return ConversationHandler.END
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
            update.message.reply_text('Произошла ошибка при проверке прав администратора.')
            return ConversationHandler.END
    
    with schedule_lock:
        load_schedules()
        
        if chat_id not in scheduled_meets or not scheduled_meets[chat_id]:
            update.message.reply_text('У вас нет запланированных еженедельных отправок.')
            return ConversationHandler.END
    
    update.message.reply_text(
        'Укажите день и время отправки, которую нужно удалить, в формате "день ЧЧ:ММ"\n'
        'Например: среда 12:46'
    )
    return DELETE_SCHEDULE

def process_schedule_delete(update: Update, context: CallbackContext) -> int:
    """Process a schedule deletion request."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    state_key = f"{chat_id}_{user_id}"
    
    # Проверяем состояние пользователя
    if state_key not in user_states or user_states[state_key] != DELETE_SCHEDULE:
        logger.info(f"Received message without valid delete state: {update.message.text} from {user_id} in chat {chat_id}")
        return ConversationHandler.END
    
    text = update.message.text.strip().lower()
    logger.info(f"Processing delete schedule: {text} from user {user_id} in chat {chat_id}")
    
    try:
        # Раздельный анализ формата "день ЧЧ:ММ"
        parts = text.split()
        
        if len(parts) != 2:
            update.message.reply_text(
                'Некорректный формат. Используйте точно формат "день ЧЧ:ММ", например: среда 12:46'
            )
            return DELETE_SCHEDULE
            
        day_text = parts[0]
        time_text = parts[1]
        
        if day_text not in DAYS_RU:
            update.message.reply_text(
                f'Некорректный день недели. Используйте: {", ".join(DAYS_RU.keys())}'
            )
            return DELETE_SCHEDULE
        
        day_of_week = DAYS_RU[day_text]
        
        try:
            hours, minutes = map(int, time_text.split(':'))
            if not (0 <= hours < 24 and 0 <= minutes < 60):
                raise ValueError("Invalid time")
        except:
            update.message.reply_text('Некорректный формат времени. Используйте ЧЧ:ММ, например 12:46')
            return DELETE_SCHEDULE
        
        deleted = False
        with schedule_lock:
            load_schedules()
            
            # Логируем текущее состояние расписания перед удалением
            logger.info(f"Current schedules before deletion for chat {chat_id}: {scheduled_meets.get(chat_id, [])}")
            
            if chat_id in scheduled_meets:
                new_schedules = []
                for schedule_item in scheduled_meets[chat_id]:
                    if (schedule_item['day'] == day_of_week and 
                        schedule_item['hours'] == hours and 
                        schedule_item['minutes'] == minutes):
                        deleted = True
                        logger.info(f"Deleting schedule: {day_text} {hours:02d}:{minutes:02d} for chat {chat_id}")
                    else:
                        new_schedules.append(schedule_item)
                
                scheduled_meets[chat_id] = new_schedules
                save_schedules()
                
                # Логируем состояние расписания после удаления
                logger.info(f"Schedules after deletion for chat {chat_id}: {scheduled_meets.get(chat_id, [])}")
                
                # Remove the specific job instead of rescheduling everything
                if hasattr(context, 'job_queue') and context.job_queue:
                    for job in context.job_queue.jobs():
                        job_context = job.context
                        if (job_context.get('user_id') == chat_id and
                            job_context.get('day') == day_of_week and
                            job_context.get('hours') == hours and
                            job_context.get('minutes') == minutes):
                            job.schedule_removal()
                            logger.info(f"Removed job for chat {chat_id} on {DAYS_DISPLAY[day_of_week]} at {hours:02d}:{minutes:02d}")
        
        if deleted:
            update.message.reply_text(
                f'Еженедельная отправка удалена: {day_text} {hours:02d}:{minutes:02d}'
            )
        else:
            update.message.reply_text(
                f'Отправка {day_text} {hours:02d}:{minutes:02d} не найдена'
            )
    except Exception as e:
        logger.error(f"Error deleting schedule: {e}", exc_info=True)
        update.message.reply_text(
            'Произошла ошибка. Убедитесь, что формат "день ЧЧ:ММ" правильный.\n'
            'Например: среда 12:46'
        )
    
    # Очищаем состояние
    if state_key in user_states:
        del user_states[state_key]
    
    return ConversationHandler.END

def send_meet_link(context: CallbackContext) -> None:
    """Send a Google Meet link to the user or group."""
    job = context.job
    chat_id = job.context['user_id']  # это может быть ID пользователя или группы
    day = job.context['day']
    hours = job.context['hours']
    minutes = job.context['minutes']
    thread_id = job.context.get('thread_id')  # Получаем thread_id из контекста, если есть
    
    try:
        # Use static Google Meet link
        meet_link = "https://meet.google.com/pep-zuux-ubg"
        
        day_text = DAYS_DISPLAY[day]
        
        # Параметры сообщения
        send_params = {
            'chat_id': chat_id,
            'text': f'Ваша еженедельная Google Meet встреча ({day_text} {hours:02d}:{minutes:02d}):\n{meet_link}'
        }
        
        # Добавляем параметр message_thread_id, если thread_id указан
        if thread_id is not None:
            send_params['message_thread_id'] = thread_id
        
        # Отправляем сообщение
        message = context.bot.send_message(**send_params)
        
        # Параметры удаления сообщения
        delete_params = {
            'chat_id': chat_id,
            'message_id': message.message_id
        }
        
        # Schedule message deletion after 59 minutes
        context.job_queue.run_once(
            lambda context: context.bot.delete_message(**delete_params),
            3540,  # 59 minutes
            context=None
        )
        
        logger.info(f"Sent meet link to chat {chat_id} for {day_text} {hours:02d}:{minutes:02d}, thread_id={thread_id}")
    except Exception as e:
        logger.error(f"Error sending meet link: {e}")
        try:
            # Параметры сообщения об ошибке
            send_params = {
                'chat_id': chat_id,
                'text': 'Произошла ошибка при отправке ссылки на Google Meet.'
            }
            
            # Добавляем параметр message_thread_id, если thread_id указан
            if thread_id is not None:
                send_params['message_thread_id'] = thread_id
            
            context.bot.send_message(**send_params)
        except Exception as inner_e:
            logger.error(f"Failed to send error message: {inner_e}")

def create_job_for_schedule(bot, job_queue, user_id, day, hours, minutes, thread_id=None):
    """Create a job for the scheduler."""
    # We run the job at the specified time on the specified day of the week
    target_day = day
    
    # Calculate days until next occurrence
    now = datetime.datetime.now(MOSCOW_TZ)
    current_day = now.weekday()
    
    # Days until the next scheduled day (0-6)
    days_ahead = (target_day - current_day) % 7
    
    # If it's the same day but the time has passed, schedule for next week
    if days_ahead == 0:
        target_time = now.replace(hour=hours, minute=minutes, second=0, microsecond=0)
        if now > target_time:
            days_ahead = 7
    
    # Calculate the next run time
    target_date = now + datetime.timedelta(days=days_ahead)
    target_time = target_date.replace(hour=hours, minute=minutes, second=0, microsecond=0)
    
    job_context = {
        'user_id': user_id,
        'day': day,
        'hours': hours,
        'minutes': minutes
    }
    
    # Добавляем thread_id в контекст, если он есть
    if thread_id is not None:
        job_context['thread_id'] = thread_id
    
    # Schedule the job with job_queue from telegram.ext
    job_queue.run_repeating(
        send_meet_link,
        interval=datetime.timedelta(days=7),  # Weekly
        first=target_time.astimezone(pytz.UTC),  # Convert to UTC for the job queue
        context=job_context
    )
    
    logger.info(f"Scheduled job for user {user_id} on {DAYS_DISPLAY[day]} at {hours:02d}:{minutes:02d}, thread_id={thread_id}")

def setup_schedules(job_queue, bot) -> None:
    """Setup all schedules for all users."""
    # Clear all existing jobs in job_queue
    for job in job_queue.jobs():
        job.schedule_removal()
    
    with schedule_lock:
        load_schedules()
        
        for user_id, user_schedules in scheduled_meets.items():
            for schedule_item in user_schedules:
                day = schedule_item['day']
                hours = schedule_item['hours']
                minutes = schedule_item['minutes']
                thread_id = schedule_item.get('thread_id')  # Получаем thread_id, если он есть
                
                # Create a job with the telegram job queue
                create_job_for_schedule(
                    bot,
                    job_queue,
                    int(user_id),  # Ensure user_id is an integer
                    day,
                    hours,
                    minutes,
                    thread_id
                )

def help_command(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /help is issued."""
    is_group = update.effective_chat.type in ['group', 'supergroup']
    
    if is_group:
        update.message.reply_text(
            'Команды бота в группах:\n'
            '/start - начать работу с ботом\n'
            '/help - показать эту справку\n'
            '/addtime день ЧЧ:ММ - добавить еженедельную отправку (например: /addtime среда 12:46)\n'
            '/list - просмотреть все отправки\n'
            '/deletetime день ЧЧ:ММ - удалить отправку (например: /deletetime среда 12:46)\n'
            '/meet - получить мгновенную ссылку на встречу\n\n'
            'В группах управлять расписанием могут только администраторы.'
        )
    else:
        update.message.reply_text(
            'Команды бота:\n'
            '/start - начать работу с ботом\n'
            '/help - показать эту справку\n'
            '/add - добавить еженедельную отправку\n'
            '/list - просмотреть все отправки\n'
            '/delete - удалить отправку\n'
            '/meet - получить мгновенную ссылку на встречу'
        )

def send_instant_meet_link(update: Update, context: CallbackContext) -> None:
    """Send an instant Google Meet link to the user."""
    chat_id = update.effective_chat.id
    
    # Получаем thread_id (ID темы), если сообщение из темы в супергруппе
    thread_id = update.message.message_thread_id if hasattr(update.message, 'message_thread_id') else None
    
    try:
        # Use static Google Meet link
        meet_link = "https://meet.google.com/pep-zuux-ubg"
        
        # Параметры сообщения
        send_params = {
            'text': f'Ваша мгновенная Google Meet ссылка:\n{meet_link}'
        }
        
        # Добавляем параметр message_thread_id, если thread_id указан
        if thread_id is not None:
            message = update.message.reply_text(**send_params)
        else:
            message = update.message.reply_text(**send_params)
        
        # Параметры удаления сообщения
        delete_params = {
            'chat_id': chat_id,
            'message_id': message.message_id
        }
        
        # Schedule message deletion after 59 minutes
        context.job_queue.run_once(
            lambda context: context.bot.delete_message(**delete_params),
            3540,  # 59 minutes
            context=None
        )
        
        logger.info(f"Sent instant meet link to chat {chat_id}, thread_id={thread_id}")
    except Exception as e:
        logger.error(f"Error sending instant meet link: {e}")
        update.message.reply_text('Произошла ошибка при отправке ссылки на Google Meet.')

def add_schedule_direct(update: Update, context: CallbackContext) -> None:
    """Directly add a schedule without conversation (for groups)."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Получаем thread_id (ID темы), если сообщение из темы в супергруппе
    thread_id = update.message.message_thread_id if hasattr(update.message, 'message_thread_id') else None
    
    # Проверяем, является ли отправитель администратором группы, если это групповой чат
    if update.effective_chat.type in ['group', 'supergroup']:
        try:
            member = context.bot.get_chat_member(chat_id, user_id)
            if member.status not in ['creator', 'administrator']:
                update.message.reply_text('Только администраторы группы могут управлять расписанием.')
                return
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
            update.message.reply_text('Произошла ошибка при проверке прав администратора.')
            return
    
    # Получаем аргументы
    text = update.message.text.strip()
    
    # Удаляем имя бота, если команда вызвана с @botname
    if '@' in text:
        text = text.split('@', 1)[0].strip()
    
    # Удаляем команду из текста
    parts = text.split(' ', 1)
    if len(parts) < 2:
        update.message.reply_text(
            'Пожалуйста, укажите день и время в формате: /addtime день ЧЧ:ММ\n'
            'Например: /addtime среда 12:46'
        )
        return
    
    # Разбираем аргументы (день и время)
    arguments = parts[1].strip().lower()
    
    # Проверяем, есть ли в тексте день недели
    day_found = False
    for day in DAYS_RU.keys():
        if day in arguments:
            day_text = day
            day_found = True
            # Удаляем день из строки, чтобы проще было найти время
            remaining_text = arguments.replace(day, "").strip()
            break
    
    if not day_found:
        update.message.reply_text(
            f'Некорректный день недели. Используйте: {", ".join(DAYS_RU.keys())}\n'
            'Например: /addtime среда 12:46'
        )
        return
    
    # Ищем время в формате ЧЧ:ММ в оставшемся тексте
    import re
    time_match = re.search(r'(\d{1,2}):(\d{2})', remaining_text)
    if not time_match:
        update.message.reply_text(
            'Некорректный формат времени. Используйте ЧЧ:ММ, например 12:46\n'
            'Например: /addtime среда 12:46'
        )
        return
    
    hours = int(time_match.group(1))
    minutes = int(time_match.group(2))
    
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        update.message.reply_text('Некорректное время. Часы должны быть от 0 до 23, минуты от 0 до 59.')
        return
    
    logger.info(f"Processing direct add: day={day_text}, time={hours}:{minutes:02d} from user {user_id} in chat {chat_id}, thread_id={thread_id}")
    
    try:
        day_of_week = DAYS_RU[day_text]
        
        with schedule_lock:
            load_schedules()
            
            if chat_id not in scheduled_meets:
                scheduled_meets[chat_id] = []
            
            # Check if this schedule already exists
            for schedule_item in scheduled_meets[chat_id]:
                if (schedule_item['day'] == day_of_week and 
                    schedule_item['hours'] == hours and 
                    schedule_item['minutes'] == minutes and
                    schedule_item.get('thread_id') == thread_id):
                    update.message.reply_text('Такое расписание уже существует!')
                    return
            
            # Add new schedule with thread_id
            new_schedule = {
                'day': day_of_week,
                'hours': hours,
                'minutes': minutes
            }
            
            # Добавляем thread_id, если он есть
            if thread_id is not None:
                new_schedule['thread_id'] = thread_id
            
            scheduled_meets[chat_id].append(new_schedule)
            
            save_schedules()
            
            # Schedule just this new task instead of rescheduling everything
            if hasattr(context, 'job_queue') and context.job_queue:
                create_job_for_schedule(
                    context.bot,
                    context.job_queue,
                    chat_id,
                    day_of_week,
                    hours,
                    minutes,
                    thread_id
                )
        
        update.message.reply_text(
            f'Еженедельная отправка добавлена: {day_text} {hours:02d}:{minutes:02d}'
        )
    except Exception as e:
        logger.error(f"Error in direct add schedule: {e}")
        update.message.reply_text(
            'Произошла ошибка. Убедитесь, что формат "/addtime день ЧЧ:ММ" правильный.\n'
            'Например: /addtime среда 12:46'
        )

def delete_schedule_direct(update: Update, context: CallbackContext) -> None:
    """Directly delete a schedule without conversation (for groups)."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Получаем thread_id (ID темы), если сообщение из темы в супергруппе
    thread_id = update.message.message_thread_id if hasattr(update.message, 'message_thread_id') else None
    
    # Проверяем, является ли отправитель администратором группы, если это групповой чат
    if update.effective_chat.type in ['group', 'supergroup']:
        try:
            member = context.bot.get_chat_member(chat_id, user_id)
            if member.status not in ['creator', 'administrator']:
                update.message.reply_text('Только администраторы группы могут управлять расписанием.')
                return
        except Exception as e:
            logger.error(f"Error checking admin status: {e}")
            update.message.reply_text('Произошла ошибка при проверке прав администратора.')
            return
    
    # Получаем аргументы
    text = update.message.text.strip()
    
    # Удаляем имя бота, если команда вызвана с @botname
    if '@' in text:
        text = text.split('@', 1)[0].strip()
    
    # Удаляем команду из текста
    parts = text.split(' ', 1)
    if len(parts) < 2:
        update.message.reply_text(
            'Пожалуйста, укажите день и время в формате: /deletetime день ЧЧ:ММ\n'
            'Например: /deletetime среда 12:46'
        )
        return
    
    # Разбираем аргументы (день и время)
    arguments = parts[1].strip().lower()
    
    # Проверяем, есть ли в тексте день недели
    day_found = False
    for day in DAYS_RU.keys():
        if day in arguments:
            day_text = day
            day_found = True
            # Удаляем день из строки, чтобы проще было найти время
            remaining_text = arguments.replace(day, "").strip()
            break
    
    if not day_found:
        update.message.reply_text(
            f'Некорректный день недели. Используйте: {", ".join(DAYS_RU.keys())}\n'
            'Например: /deletetime среда 12:46'
        )
        return
    
    # Ищем время в формате ЧЧ:ММ в оставшемся тексте
    import re
    time_match = re.search(r'(\d{1,2}):(\d{2})', remaining_text)
    if not time_match:
        update.message.reply_text(
            'Некорректный формат времени. Используйте ЧЧ:ММ, например 12:46\n'
            'Например: /deletetime среда 12:46'
        )
        return
    
    hours = int(time_match.group(1))
    minutes = int(time_match.group(2))
    
    if not (0 <= hours < 24 and 0 <= minutes < 60):
        update.message.reply_text('Некорректное время. Часы должны быть от 0 до 23, минуты от 0 до 59.')
        return
    
    logger.info(f"Processing direct delete: day={day_text}, time={hours}:{minutes:02d} from user {user_id} in chat {chat_id}, thread_id={thread_id}")
    
    try:
        day_of_week = DAYS_RU[day_text]
        
        deleted = False
        with schedule_lock:
            load_schedules()
            
            if chat_id in scheduled_meets:
                new_schedules = []
                for schedule_item in scheduled_meets[chat_id]:
                    if (schedule_item['day'] == day_of_week and 
                        schedule_item['hours'] == hours and 
                        schedule_item['minutes'] == minutes and
                        schedule_item.get('thread_id') == thread_id):
                        deleted = True
                    else:
                        new_schedules.append(schedule_item)
                
                scheduled_meets[chat_id] = new_schedules
                save_schedules()
                
                # Remove the specific job instead of rescheduling everything
                if hasattr(context, 'job_queue') and context.job_queue:
                    for job in context.job_queue.jobs():
                        job_context = job.context
                        if (job_context.get('user_id') == chat_id and
                            job_context.get('day') == day_of_week and
                            job_context.get('hours') == hours and
                            job_context.get('minutes') == minutes and
                            job_context.get('thread_id') == thread_id):
                            job.schedule_removal()
                            logger.info(f"Removed job for chat {chat_id} on {DAYS_DISPLAY[day_of_week]} at {hours:02d}:{minutes:02d}, thread_id={thread_id}")
        
        if deleted:
            update.message.reply_text(
                f'Еженедельная отправка удалена: {day_text} {hours:02d}:{minutes:02d}'
            )
        else:
            update.message.reply_text(
                f'Отправка {day_text} {hours:02d}:{minutes:02d} не найдена'
            )
    except Exception as e:
        logger.error(f"Error in direct delete schedule: {e}")
        update.message.reply_text(
            'Произошла ошибка. Убедитесь, что формат "/deletetime день ЧЧ:ММ" правильный.\n'
            'Например: /deletetime среда 12:46'
        )

def handle_text(update: Update, context: CallbackContext) -> None:
    """Handle text messages."""
    if not update.message:
        return
        
    text = update.message.text.strip()
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    state_key = f"{chat_id}_{user_id}"
    
    logger.info(f"Received text: '{text}' from user {user_id} in chat {chat_id}, state_key: {state_key}")
    logger.info(f"All active states: {user_states}")
    
    # Проверяем, если пользователь находится в состоянии диалога
    if state_key in user_states:
        state = user_states[state_key]
        logger.info(f"User {user_id} in chat {chat_id} has state: {state}")
        if state == ADD_SCHEDULE:
            return process_schedule_add(update, context)
        elif state == DELETE_SCHEDULE:
            return process_schedule_delete(update, context)
    
    # Обработка команд с @username в группах
    if '@' in text:
        cmd_parts = text.split('@', 1)
        command = cmd_parts[0]
        if command == '/add':
            return add_schedule_command(update, context)
        elif command == '/list':
            return list_schedules(update, context)
        elif command == '/delete':
            return delete_schedule_command(update, context)
        elif command == '/meet':
            return send_instant_meet_link(update, context)
    
    # Если это не состояние диалога, обрабатываем команды
    if text.startswith('/add') or text == 'Добавить еженедельную отправку':
        return add_schedule_command(update, context)
    elif text.startswith('/list') or text == 'Посмотреть отправки':
        return list_schedules(update, context)
    elif text.startswith('/delete') or text == 'Удалить отправку':
        return delete_schedule_command(update, context)
    elif text.startswith('/meet') or text == 'Мгновенная встреча':
        return send_instant_meet_link(update, context)
    else:
        # Не отвечаем на случайные сообщения в группах
        if update.effective_chat.type in ['private']:
            update.message.reply_text(
                'Используйте команды меню или /help для справки'
            )

def cleanup():
    """Clean up resources before exiting."""
    global lock_file_handle
    
    # Skip cleanup if running under PM2
    if os.environ.get('PM2_HOME') is not None:
        logger.info("Running under PM2, skipping lock cleanup")
        return
    
    # Release the lock and close the file handle
    if lock_file_handle:
        try:
            fcntl.flock(lock_file_handle, fcntl.LOCK_UN)
            lock_file_handle.close()
            # Optionally remove the lock file
            os.remove(LOCK_FILE)
        except:
            pass

def main() -> None:
    """Start the bot."""
    # Check if another instance is running
    if not check_single_instance():
        logger.error("Exiting due to another instance running")
        sys.exit(1)
    
    try:
        # Get bot token from environment variable
        token = os.getenv("TELEGRAM_TOKEN")
        if not token:
            logger.error("No TELEGRAM_TOKEN found in .env file")
            return
        
        # Create the Updater and pass it your bot's token with increased timeouts
        updater = Updater(token, request_kwargs={'read_timeout': 30, 'connect_timeout': 30})
        
        # Get the dispatcher to register handlers
        dispatcher = updater.dispatcher
        
        # Add handlers
        dispatcher.add_handler(CommandHandler("start", start))
        dispatcher.add_handler(CommandHandler("help", help_command))
        dispatcher.add_handler(CommandHandler("meet", send_instant_meet_link))
        dispatcher.add_handler(CommandHandler("list", list_schedules))
        dispatcher.add_handler(CommandHandler("add", add_schedule_command))
        dispatcher.add_handler(CommandHandler("delete", delete_schedule_command))
        
        # Прямые команды для групп
        dispatcher.add_handler(CommandHandler("addtime", add_schedule_direct))
        dispatcher.add_handler(CommandHandler("deletetime", delete_schedule_direct))
        
        # Обработка текстовых сообщений
        dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
        
        # Setup bot commands in menu
        setup_commands(updater)
        
        # Setup schedules using the job_queue from the updater
        load_schedules()
        setup_schedules(updater.job_queue, updater.bot)
        
        # Start the Bot
        updater.start_polling(allowed_updates=["message", "callback_query", "chat_member"])
        logger.info("Bot started")
        
        # Run the bot until you press Ctrl-C
        updater.idle()
    finally:
        # Clean up when the bot stops
        cleanup()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        cleanup()
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        cleanup() 