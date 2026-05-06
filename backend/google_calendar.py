

import os
import json
from datetime import datetime, timezone
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Путь к credentials.json
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), 'credentials.json')

# Scopes - права доступа
SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/calendar.events',
]

# Redirect URI - должен совпадать с настройками в Google Cloud Console
REDIRECT_URI = 'http://localhost:80/api/calendar/callback'


def create_flow():
    """Создает OAuth flow для авторизации Google."""
    flow = Flow.from_client_secrets_file(
        CREDENTIALS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
    )
    return flow


def credentials_from_db(token_record) -> Credentials:
    """Восстанавливает объект Credentials из записи БД."""
    creds = Credentials(
        token=token_record.token,
        refresh_token=token_record.refresh_token,
        token_uri=token_record.token_uri,
        client_id=token_record.client_id,
        client_secret=token_record.client_secret,
        scopes=json.loads(token_record.scopes) if token_record.scopes else SCOPES,
    )
    if token_record.expiry:
        creds.expiry = token_record.expiry.replace(tzinfo=timezone.utc)
    return creds


def refresh_if_expired(creds: Credentials) -> Credentials:
    """Обновляет токен если истёк."""
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
    return creds


def get_calendar_service(creds: Credentials):
    """Создает сервис Google Calendar API."""
    return build('calendar', 'v3', credentials=creds)


def get_upcoming_events(service, max_results: int = 50) -> list[dict]:
    """Получает предстоящие события из Google Calendar."""
    now = datetime.now(timezone.utc).isoformat()

    events_result = service.events().list(
        calendarId='primary',
        timeMin=now,
        maxResults=max_results,
        singleEvents=True,
        orderBy='startTime',
    ).execute()

    events = events_result.get('items', [])

    result = []
    for event in events:
        start = event.get('start', {})
        end = event.get('end', {})

        result.append({
            'id': event.get('id'),
            'title': event.get('summary', 'Без названия'),
            'description': event.get('description', ''),
            'location': event.get('location', ''),
            'start': start.get('dateTime') or start.get('date'),
            'end': end.get('dateTime') or end.get('date'),
            'all_day': 'dateTime' not in start,
            'color': event.get('colorId', ''),
            'html_link': event.get('htmlLink', ''),
        })

    return result


def get_events_for_month(service, year: int, month: int) -> list[dict]:
    """Получает события за конкретный месяц."""
    from calendar import monthrange

    # Начало месяца
    time_min = datetime(year, month, 1, tzinfo=timezone.utc).isoformat()

    # Конец месяца
    last_day = monthrange(year, month)[1]
    time_max = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc).isoformat()

    events_result = service.events().list(
        calendarId='primary',
        timeMin=time_min,
        timeMax=time_max,
        singleEvents=True,
        orderBy='startTime',
    ).execute()

    events = events_result.get('items', [])

    result = []
    for event in events:
        start = event.get('start', {})
        end = event.get('end', {})

        result.append({
            'id': event.get('id'),
            'title': event.get('summary', 'Без названия'),
            'description': event.get('description', ''),
            'location': event.get('location', ''),
            'start': start.get('dateTime') or start.get('date'),
            'end': end.get('dateTime') or end.get('date'),
            'all_day': 'dateTime' not in start,
            'color_id': event.get('colorId', ''),
            'html_link': event.get('htmlLink', ''),
        })

    return result


def add_workout_event(service, title: str, date: str,
                      duration_minutes: int = 60,
                      description: str = '') -> dict:
    """Добавляет тренировку в Google Calendar."""
    from datetime import timedelta

    # Парсим дату
    start_dt = datetime.fromisoformat(date)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    event = {
        'summary': f'🏋️ {title}',
        'description': description,
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': 'Europe/Moscow',
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': 'Europe/Moscow',
        },
        'colorId': '10',  # зеленый цвет для тренировок
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'popup', 'minutes': 30},
            ],
        },
    }

    created_event = service.events().insert(
        calendarId='primary',
        body=event,
    ).execute()

    return {
        'id': created_event.get('id'),
        'html_link': created_event.get('htmlLink'),
        'title': created_event.get('summary'),
    }