#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import json
import logging
import datetime
import time
import threading
import schedule
import pytz
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, ConversationHandler
from google_meet.google_meet import google_meet

# Load environment variables from .env file
load_dotenv()

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

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

def start(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /start is issued."""
    user = update.effective_user
    keyboard = [
        ['Добавить еженедельную отправку'],
        ['Посмотреть отправки'],
        ['Удалить отправку']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    update.message.reply_text(
        f'Привет, {user.first_name}! Я бот для создания и отправки ссылок на Google Meet.\n\n'
        'Используйте кнопки ниже для управления автоматическими отправками.',
        reply_markup=reply_markup
    )

def add_schedule_command(update: Update, context: CallbackContext) -> int:
    """Start the process of adding a new schedule."""
    update.message.reply_text(
        'Укажите день недели и время по Москве в формате "день ЧЧ:ММ"\n'
        'Например: среда 12:46'
    )
    return ADD_SCHEDULE

def process_schedule_add(update: Update, context: CallbackContext) -> int:
    """Process a schedule request."""
    user_id = update.effective_user.id
    text = update.message.text.strip().lower()
    
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
            
            if user_id not in scheduled_meets:
                scheduled_meets[user_id] = []
            
            # Check if this schedule already exists
            for schedule_item in scheduled_meets[user_id]:
                if schedule_item['day'] == day_of_week and schedule_item['hours'] == hours and schedule_item['minutes'] == minutes:
                    update.message.reply_text('Такое расписание уже существует!')
                    return ConversationHandler.END
            
            # Add new schedule
            scheduled_meets[user_id].append({
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
                    user_id,  # Already an integer
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
    
    return ConversationHandler.END

def list_schedules(update: Update, context: CallbackContext) -> None:
    """Show all scheduled tasks for the user."""
    user_id = update.effective_user.id
    
    with schedule_lock:
        load_schedules()
        
        if user_id not in scheduled_meets or not scheduled_meets[user_id]:
            update.message.reply_text('У вас нет запланированных еженедельных отправок.')
            return
        
        schedules_list = []
        for schedule_item in scheduled_meets[user_id]:
            day = DAYS_DISPLAY[schedule_item['day']]
            hours = schedule_item['hours']
            minutes = schedule_item['minutes']
            schedules_list.append(f"{day} {hours:02d}:{minutes:02d}")
        
        message = "Ваши еженедельные отправки:\n" + "\n".join(schedules_list)
        update.message.reply_text(message)

def delete_schedule_command(update: Update, context: CallbackContext) -> int:
    """Start the process of deleting a schedule."""
    user_id = update.effective_user.id
    
    with schedule_lock:
        load_schedules()
        
        if user_id not in scheduled_meets or not scheduled_meets[user_id]:
            update.message.reply_text('У вас нет запланированных еженедельных отправок.')
            return ConversationHandler.END
    
    update.message.reply_text(
        'Укажите день и время отправки, которую нужно удалить, в формате "день ЧЧ:ММ"\n'
        'Например: среда 12:46'
    )
    return DELETE_SCHEDULE

def process_schedule_delete(update: Update, context: CallbackContext) -> int:
    """Process a schedule deletion request."""
    user_id = update.effective_user.id
    text = update.message.text.strip().lower()
    
    try:
        day_text, time_text = text.split(' ', 1)
        
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
            
            if user_id in scheduled_meets:
                new_schedules = []
                for schedule_item in scheduled_meets[user_id]:
                    if (schedule_item['day'] == day_of_week and 
                        schedule_item['hours'] == hours and 
                        schedule_item['minutes'] == minutes):
                        deleted = True
                    else:
                        new_schedules.append(schedule_item)
                
                scheduled_meets[user_id] = new_schedules
                save_schedules()
                
                # Remove the specific job instead of rescheduling everything
                if hasattr(context, 'job_queue') and context.job_queue:
                    for job in context.job_queue.jobs():
                        job_context = job.context
                        if (job_context.get('user_id') == user_id and
                            job_context.get('day') == day_of_week and
                            job_context.get('hours') == hours and
                            job_context.get('minutes') == minutes):
                            job.schedule_removal()
                            logger.info(f"Removed job for user {user_id} on {DAYS_DISPLAY[day_of_week]} at {hours:02d}:{minutes:02d}")
        
        if deleted:
            update.message.reply_text(
                f'Еженедельная отправка удалена: {day_text} {hours:02d}:{minutes:02d}'
            )
        else:
            update.message.reply_text(
                f'Отправка {day_text} {hours:02d}:{minutes:02d} не найдена'
            )
    except Exception as e:
        logger.error(f"Error deleting schedule: {e}")
        update.message.reply_text(
            'Произошла ошибка. Убедитесь, что формат "день ЧЧ:ММ" правильный.\n'
            'Например: среда 12:46'
        )
    
    return ConversationHandler.END

def send_meet_link(context: CallbackContext) -> None:
    """Send a Google Meet link to the user."""
    job = context.job
    user_id = job.context['user_id']
    day = job.context['day']
    hours = job.context['hours']
    minutes = job.context['minutes']
    
    try:
        # Generate a new Google Meet link
        meet_link = google_meet()
        
        if meet_link:
            day_text = DAYS_DISPLAY[day]
            context.bot.send_message(
                chat_id=user_id,
                text=f'Ваша еженедельная Google Meet встреча ({day_text} {hours:02d}:{minutes:02d}):\n{meet_link}'
            )
            logger.info(f"Sent meet link to user {user_id} for {day_text} {hours:02d}:{minutes:02d}")
        else:
            context.bot.send_message(
                chat_id=user_id,
                text='Не удалось создать ссылку на Google Meet. Пожалуйста, проверьте настройки.'
            )
            logger.error(f"Failed to create meet link for user {user_id}")
    except Exception as e:
        logger.error(f"Error sending meet link: {e}")
        try:
            context.bot.send_message(
                chat_id=user_id,
                text='Произошла ошибка при отправке ссылки на Google Meet.'
            )
        except Exception as inner_e:
            logger.error(f"Failed to send error message: {inner_e}")

def create_job_for_schedule(bot, job_queue, user_id, day, hours, minutes):
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
    
    # Schedule the job with job_queue from telegram.ext
    job_queue.run_repeating(
        send_meet_link,
        interval=datetime.timedelta(days=7),  # Weekly
        first=target_time.astimezone(pytz.UTC),  # Convert to UTC for the job queue
        context=job_context
    )
    
    logger.info(f"Scheduled job for user {user_id} on {DAYS_DISPLAY[day]} at {hours:02d}:{minutes:02d}")

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
                
                # Create a job with the telegram job queue
                create_job_for_schedule(
                    bot,
                    job_queue,
                    int(user_id),  # Ensure user_id is an integer
                    day,
                    hours,
                    minutes
                )

def help_command(update: Update, context: CallbackContext) -> None:
    """Send a message when the command /help is issued."""
    update.message.reply_text(
        'Команды бота:\n'
        '/start - начать работу с ботом\n'
        '/help - показать эту справку\n\n'
        'Функции:\n'
        '1. "Добавить еженедельную отправку" - создать новую еженедельную отправку ссылки Google Meet\n'
        '2. "Посмотреть отправки" - просмотреть все ваши еженедельные отправки\n'
        '3. "Удалить отправку" - удалить существующую еженедельную отправку'
    )

def handle_text(update: Update, context: CallbackContext) -> None:
    """Handle text messages."""
    text = update.message.text.strip()
    
    if text == 'Добавить еженедельную отправку':
        return add_schedule_command(update, context)
    elif text == 'Посмотреть отправки':
        return list_schedules(update, context)
    elif text == 'Удалить отправку':
        return delete_schedule_command(update, context)
    else:
        update.message.reply_text(
            'Используйте кнопки меню или команды /start и /help'
        )

def main() -> None:
    """Start the bot."""
    # Get bot token from environment variable
    token = os.getenv("TELEGRAM_TOKEN")
    if not token:
        logger.error("No TELEGRAM_TOKEN found in .env file")
        return
    
    # Create the Updater and pass it your bot's token with increased timeouts
    updater = Updater(token, request_kwargs={'read_timeout': 30, 'connect_timeout': 30})
    
    # Get the dispatcher to register handlers
    dispatcher = updater.dispatcher
    
    # Add conversation handlers
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('add', add_schedule_command),
            MessageHandler(Filters.regex('^Добавить еженедельную отправку$'), add_schedule_command)
        ],
        states={
            ADD_SCHEDULE: [MessageHandler(Filters.text & ~Filters.command, process_schedule_add)],
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    )
    
    del_handler = ConversationHandler(
        entry_points=[
            CommandHandler('delete', delete_schedule_command),
            MessageHandler(Filters.regex('^Удалить отправку$'), delete_schedule_command)
        ],
        states={
            DELETE_SCHEDULE: [MessageHandler(Filters.text & ~Filters.command, process_schedule_delete)],
        },
        fallbacks=[CommandHandler('cancel', lambda u, c: ConversationHandler.END)]
    )
    
    # Add handlers
    dispatcher.add_handler(CommandHandler("start", start))
    dispatcher.add_handler(CommandHandler("help", help_command))
    dispatcher.add_handler(conv_handler)
    dispatcher.add_handler(del_handler)
    dispatcher.add_handler(MessageHandler(Filters.regex('^Посмотреть отправки$'), list_schedules))
    dispatcher.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text))
    
    # Setup schedules using the job_queue from the updater
    load_schedules()
    setup_schedules(updater.job_queue, updater.bot)
    
    # Start the Bot
    updater.start_polling()
    logger.info("Bot started")
    
    # Run the bot until you press Ctrl-C
    updater.idle()

if __name__ == '__main__':
    main() 