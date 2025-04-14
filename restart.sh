#!/bin/bash

# Удаляем файл блокировки если существует
rm -f bot.lock

# Перезапускаем бота
pm2 restart google_meet_bot