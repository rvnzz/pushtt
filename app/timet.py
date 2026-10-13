"""Клиент timet.eremin.tech + работа с датами (всё в UTC-строках YYYY-MM-DD)."""
from __future__ import annotations

import datetime as dt

import httpx

from . import config

MONTHS_GENITIVE = [
    'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
    'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]

WEEKDAYS_FULL = [
    'Понедельник', 'Вторник', 'Среда', 'Четверг',
    'Пятница', 'Суббота', 'Воскресенье',
]

WEEKDAYS_SHORT = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']


def today_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d')


def monday_of(iso: str) -> str:
    date = dt.date.fromisoformat(iso)
    diff = (date.weekday() - 0) % 7
    return (date - dt.timedelta(days=diff)).isoformat()


def add_days_iso(iso: str, days: int) -> str:
    date = dt.date.fromisoformat(iso)
    return (date + dt.timedelta(days=days)).isoformat()


def weekday_index(iso: str) -> int:
    return dt.date.fromisoformat(iso).weekday()  # 0=Пн … 6=Вс


def weekday_full(iso: str) -> str:
    return WEEKDAYS_FULL[weekday_index(iso)]


def weekday_short(iso: str) -> str:
    return WEEKDAYS_SHORT[weekday_index(iso)]


def day_number(iso: str) -> str:
    return str(dt.date.fromisoformat(iso).day)


def format_date(iso: str) -> str:
    date = dt.date.fromisoformat(iso)
    return f"{date.day} {MONTHS_GENITIVE[date.month - 1]}"


def format_range(start_iso: str, end_iso: str) -> str:
    start = dt.date.fromisoformat(start_iso)
    end = dt.date.fromisoformat(end_iso)
    year = start.year
    if start.month == end.month:
        return f'{start.day} – {end.day} {MONTHS_GENITIVE[end.month - 1]} {year}'
    return (
        f'{start.day} {MONTHS_GENITIVE[start.month - 1]} – '
        f'{end.day} {MONTHS_GENITIVE[end.month - 1]} {year}'
    )


def plural_pairs(count: int) -> str:
    abs10, abs100 = count % 10, count % 100
    if abs10 == 1 and abs100 != 11:
        return f'{count} пара'
    if abs10 in (2, 3, 4) and abs100 not in (12, 13, 14):
        return f'{count} пары'
    return f'{count} пар'


def fetch_all_week(date: str) -> dict:
    response = httpx.get(
        f'{config.TIMET_BASE_URL}/embed/all/week/data',
        params={'date': date},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def count_target_pairs_for_date(
    week: dict,
    role: str,
    building_slug: str,
    target_id: int,
    date: str,
) -> list[int]:
    """Номера пар цели в конкретный день (для напоминаний)."""
    for day in week['days']:
        if day['date'] != date:
            continue
        building = next(
            (b for b in day['buildings'] if b['building']['slug'] == building_slug), None)
        if building is None:
            return []

        if role == 'student':
            schedule = next(
                (g for g in building.get('group_schedules', []) if g['id'] == target_id), None)
            if not schedule:
                return []
            return sorted(
                p['number'] for p in schedule['pairs']
                if p['has_content'] and p['lessons']
            )

        teacher = next((t for t in building.get('teachers', []) if t['id'] == target_id), None)
        if not teacher:
            return []
        return sorted({
            a['pair_number'] for a in teacher['assignments']
            if a.get('subject', '').strip()
        })

    return []
