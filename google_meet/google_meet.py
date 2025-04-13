#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
TOKEN_PATH = 'google_meet/token.pickle'
CREDENTIALS_FILE = 'google_meet/credentials.json'

# Область действия для Google Calendar API
SCOPES = ['https://www.googleapis.com/auth/calendar']

def get_credentials():
    creds = None
    
    # Проверяем существует ли токен
    if os.path.exists(TOKEN_PATH):
        try:
            with open(TOKEN_PATH, 'rb') as token:
                creds = pickle.load(token)
        except Exception as e:
            pass
    
    # Если нет действительных учетных данных, получаем новые
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                creds = None
        
        # Если токен не удалось обновить, создаем новый
        if not creds:
            # Проверяем наличие файла с учетными данными
            if not os.path.exists(CREDENTIALS_FILE):
                return None
            
            try:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            except Exception as e:
                return None
            
            # Сохраняем токен
            with open(TOKEN_PATH, 'wb') as token:
                pickle.dump(creds, token)
    
    return creds

def create_fully_accessible_meet():
    # Получаем учетные данные
    creds = get_credentials()
    
    # Создаем сервис
    try:
        service = build('calendar', 'v3', credentials=creds)
    except Exception as e:
        return None
    
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
            return None
        
        # Сохраняем ссылку в файл
        with open('google_meet/last_meet_link.txt', 'w') as file:
            file.write(meet_link)
        
        return meet_link
    
    except HttpError as error:
        return None

def google_meet():
    # Создаем встречу с открытым доступом
    meet_link = create_fully_accessible_meet()
    
    if meet_link:
        return meet_link
    else:
        return None

if __name__ == "__main__":
    meet_link = google_meet()
    
    if not meet_link:
        sys.exit(1)
    
    sys.exit(0) 