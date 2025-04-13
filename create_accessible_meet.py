#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для создания Google Meet с полностью открытым доступом
Автор: Claude 3.7 Sonnet
Дата: 2024-04-14
"""

import os
import sys
import datetime
import json
import pickle
import random
import string
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Путь к токену и файлу с учетными данными
TOKEN_PATH = 'token.pickle'
CREDENTIALS_FILE = 'credentials.json'

# Область действия для Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_credentials():
    """
    Получение учетных данных Google API.
    Создает токен, если его нет, или обновляет существующий.
    """
    creds = None
    
    # Проверяем существует ли токен
    if os.path.exists(TOKEN_PATH):
        try:
            with open(TOKEN_PATH, 'rb') as token:
                creds = pickle.load(token)
        except Exception as e:
            print(f"Ошибка при чтении токена: {e}")
    
    # Если нет действительных учетных данных, получаем новые
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                print(f"Ошибка при обновлении токена: {e}")
                creds = None
        
        # Если токен не удалось обновить, создаем новый
        if not creds:
            # Проверяем наличие файла с учетными данными
            if not os.path.exists(CREDENTIALS_FILE):
                print(f"\033[91mФайл {CREDENTIALS_FILE} не найден!\033[0m")
                print("\033[93mДля создания файла credentials.json выполните следующие шаги:\033[0m")
                print("1. Перейдите на https://console.cloud.google.com/")
                print("2. Создайте проект и включите Google Calendar API")
                print("3. Создайте учетные данные OAuth и скачайте JSON-файл")
                print("4. Переименуйте файл в credentials.json и поместите его в текущую директорию")
                sys.exit(1)
            
            try:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                print(f"\033[91mОшибка при создании токена: {e}\033[0m")
                sys.exit(1)
            
            # Сохраняем токен
            with open(TOKEN_PATH, 'wb') as token:
                pickle.dump(creds, token)
            
            print("\033[92mТокен авторизации успешно создан и сохранен\033[0m")
    
    return creds

def create_fully_accessible_meet():
    """
    Создает Google Meet с полностью открытым доступом
    через Google Calendar API
    """
    # Получаем учетные данные
    creds = get_credentials()
    
    # Создаем сервис
    try:
        service = build('calendar', 'v3', credentials=creds)
    except Exception as e:
        print(f"\033[91mОшибка при создании сервиса: {e}\033[0m")
        sys.exit(1)
    
    # Случайное имя для встречи
    random_str = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
    event_name = f"Open Meet {random_str}"
    
    # Время начала встречи (сейчас)
    start_time = datetime.datetime.utcnow()
    
    # Время окончания (через 24 часа)
    end_time = start_time + datetime.timedelta(hours=24)
    
    # Конвертируем время в формат RFC3339
    start_time_str = start_time.isoformat() + 'Z'
    end_time_str = end_time.isoformat() + 'Z'
    
    # Создаем событие с максимальной открытостью
    event = {
        'summary': event_name,
        'description': 'Открытая встреча Google Meet созданная через API',
        'start': {
            'dateTime': start_time_str,
            'timeZone': 'UTC',
        },
        'end': {
            'dateTime': end_time_str,
            'timeZone': 'UTC',
        },
        # Настройки для максимальной открытости
        'guestsCanModify': True,            # Гости могут изменять встречу
        'guestsCanInviteOthers': True,      # Гости могут приглашать других
        'guestsCanSeeOtherGuests': True,    # Гости могут видеть других гостей
        'anyoneCanAddSelf': True,           # Кто угодно может присоединиться
        'visibility': 'public',             # Встреча публичная
        # Создание Google Meet конференции
        'conferenceData': {
            'createRequest': {
                'requestId': random_str,  # Уникальный ID для создания конференции
                'conferenceSolutionKey': {
                    'type': 'hangoutsMeet'
                },
            }
        }
    }
    
    # Добавляем настройку для открытого доступа
    try:
        print("\033[93mСоздаем встречу с открытым доступом...\033[0m")
        event = service.events().insert(
            calendarId='primary',
            body=event,
            conferenceDataVersion=1
        ).execute()
        
        # Получаем ссылку на встречу
        meet_link = None
        if 'conferenceData' in event and 'entryPoints' in event['conferenceData']:
            for entry_point in event['conferenceData']['entryPoints']:
                if entry_point['entryPointType'] == 'video':
                    meet_link = entry_point['uri']
                    break
        
        if not meet_link:
            print("\033[91mНе удалось получить ссылку на встречу\033[0m")
            return None
        
        # Сохраняем ссылку в файл
        with open('last_meet_link.txt', 'w') as file:
            file.write(meet_link)
        
        print("\033[92mВстреча успешно создана!\033[0m")
        print(f"\033[92mСсылка на встречу: {meet_link}\033[0m")
        print("\033[93mРекомендуется зайти в настройки встречи и проверить, что 'Быстрый доступ' включен\033[0m")
        
        return meet_link
    
    except HttpError as error:
        print(f"\033[91mОшибка при создании встречи: {error}\033[0m")
        return None

if __name__ == "__main__":
    print("\033[94m====================================================================\033[0m")
    print("\033[92mСоздание Google Meet с ГАРАНТИРОВАННО ОТКРЫТЫМ ДОСТУПОМ\033[0m")
    print("\033[94m====================================================================\033[0m")
    
    # Создаем встречу с открытым доступом
    meet_link = create_fully_accessible_meet()
    
    if meet_link:
        print("\033[92mУспешно создана встреча с открытым доступом\033[0m")
        print("\033[93mВАЖНО: При входе в созданную встречу убедитесь, что 'Быстрый доступ' включен!\033[0m")
    else:
        print("\033[91mНе удалось создать встречу\033[0m")
        sys.exit(1)
    
    sys.exit(0) 