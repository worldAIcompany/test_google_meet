#!/bin/bash

# Удаляем файл блокировки, если он существует
if [ -f "bot.lock" ]; then
  rm -f bot.lock
  echo "Файл блокировки удален"
fi

# Перезапускаем PM2 процесс
echo "Перезапуск бота..."
pm2 restart google_meet_bot

echo "Бот успешно перезапущен!"
echo "Для проверки статуса: pm2 status"
echo "Для просмотра логов: pm2 logs google_meet_bot" 