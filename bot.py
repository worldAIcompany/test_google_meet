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
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext, ConversationHandler
from google_meet.google_meet import google_meet

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
            
            # Update active schedules
            setup_schedules(context)
        
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
                
                # Update active schedules
                setup_schedules(context)
        
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
        else:
            context.bot.send_message(
                chat_id=user_id,
                text='Не удалось создать ссылку на Google Meet. Пожалуйста, проверьте настройки.'
            )
    except Exception as e:
        logger.error(f"Error sending meet link: {e}")
        try:
            context.bot.send_message(
                chat_id=user_id,
                text='Произошла ошибка при отправке ссылки на Google Meet.'
            )
        except:
            pass

def setup_schedules(context: CallbackContext) -> None:
    """Setup all schedules for all users."""
    # Clear all existing schedule jobs
    schedule.clear()
    
    with schedule_lock:
        load_schedules()
        
        for user_id, user_schedules in scheduled_meets.items():
            for schedule_item in user_schedules:
                day = schedule_item['day']
                hours = schedule_item['hours']
                minutes = schedule_item['minutes']
                
                # Get day of week name
                day_name = list(DAYS_RU.keys())[list(DAYS_RU.values()).index(day)]
                
                # Schedule the job
                job_context = {
                    'user_id': user_id,
                    'day': day,
                    'hours': hours,
                    'minutes': minutes
                }
                
                # Set up the schedule
                if day == 0:  # Monday
                    schedule.every().monday.at(f"{hours:02d}:{minutes:02d}").do(
                        lambda ctx=context, jctx=job_context: send_meet_link_wrapper(ctx, jctx)
                    )
                elif day == 1:  # Tuesday
                    schedule.every().tuesday.at(f"{hours:02d}:{minutes:02d}").do(
                        lambda ctx=context, jctx=job_context: send_meet_link_wrapper(ctx, jctx)
                    )
                elif day == 2:  # Wednesday
                    schedule.every().wednesday.at(f"{hours:02d}:{minutes:02d}").do(
                        lambda ctx=context, jctx=job_context: send_meet_link_wrapper(ctx, jctx)
                    )
                elif day == 3:  # Thursday
                    schedule.every().thursday.at(f"{hours:02d}:{minutes:02d}").do(
                        lambda ctx=context, jctx=job_context: send_meet_link_wrapper(ctx, jctx)
                    )
                elif day == 4:  # Friday
                    schedule.every().friday.at(f"{hours:02d}:{minutes:02d}").do(
                        lambda ctx=context, jctx=job_context: send_meet_link_wrapper(ctx, jctx)
                    )
                elif day == 5:  # Saturday
                    schedule.every().saturday.at(f"{hours:02d}:{minutes:02d}").do(
                        lambda ctx=context, jctx=job_context: send_meet_link_wrapper(ctx, jctx)
                    )
                elif day == 6:  # Sunday
                    schedule.every().sunday.at(f"{hours:02d}:{minutes:02d}").do(
                        lambda ctx=context, jctx=job_context: send_meet_link_wrapper(ctx, jctx)
                    )

def send_meet_link_wrapper(context, job_context):
    """Wrapper for send_meet_link to be used with schedule."""
    context.job_queue.run_once(send_meet_link, 0, context=job_context)

def run_scheduler():
    """Run the scheduler in a separate thread."""
    while True:
        schedule.run_pending()
        time.sleep(1)

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
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        logger.error("No TELEGRAM_TOKEN found in environment variables")
        return
    
    # Create the Updater and pass it your bot's token
    updater = Updater(token)
    
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
    
    # Setup schedules
    load_schedules()
    setup_schedules(updater.dispatcher.bot_data)
    
    # Start the scheduler thread
    scheduler_thread = threading.Thread(target=run_scheduler)
    scheduler_thread.daemon = True
    scheduler_thread.start()
    
    # Start the Bot
    updater.start_polling()
    logger.info("Bot started")
    
    # Run the bot until you press Ctrl-C
    updater.idle()

if __name__ == '__main__':
    main() 