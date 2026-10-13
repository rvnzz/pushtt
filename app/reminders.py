"""Ежечасное напоминание «расписание на завтра» (по локальному времени подписчика)."""
from __future__ import annotations

import datetime as dt

from . import bells, db, push, sync, timet


def run_reminders() -> None:
    subscribers = db.find_reminder_subscribers()
    if not subscribers:
        return

    messages: list[dict] = []

    for subscriber in subscribers:
        wall = _wall_clock(subscriber['tz_offset_minutes'])
        if wall.hour != subscriber['tomorrow_hour']:
            continue

        tomorrow = timet.add_days_iso(wall.date, 1)
        if subscriber['last_tomorrow_date'] == tomorrow:
            continue

        week = sync.cached_weeks.get(timet.monday_of(tomorrow))
        if week is None:
            week = timet.fetch_all_week(timet.monday_of(tomorrow))
            sync.cached_weeks[timet.monday_of(tomorrow)] = week

        pair_numbers = timet.count_target_pairs_for_date(
            week, subscriber['role'], subscriber['building_slug'],
            subscriber['target_id'], tomorrow,
        )

        # Пар нет — не спамим
        if not pair_numbers:
            print(f"[reminders] {subscriber['target_label']}: завтра пар нет")
            db.mark_tomorrow_sent(subscriber['expo_push_token'], tomorrow)
            continue

        first_pair_start = _first_pair_time(tomorrow, pair_numbers[0])

        body = (
            f"у группы {subscriber['target_label']} — {timet.plural_pairs(len(pair_numbers))}"
            if subscriber['role'] == 'student'
            else f"у преподавателя {subscriber['target_label']} — {timet.plural_pairs(len(pair_numbers))}"
        )
        if first_pair_start:
            body += f', первая в {first_pair_start}'

        messages.append({
            'to': subscriber['expo_push_token'],
            'title': f'Завтра, {timet.format_date(tomorrow)}',
            'body': body,
            'data': {'date': tomorrow},
        })

        db.mark_tomorrow_sent(subscriber['expo_push_token'], tomorrow)

    if messages:
        print(f'[reminders] отправляем: {len(messages)}')
        push.send_push(messages)
        db.log_push('reminder', messages)


def _wall_clock(offset_minutes: int) -> dt.datetime:
    """Локальное «стенное» время подписчика (getTimezoneOffset от приложения)."""
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=offset_minutes)


def _first_pair_time(date: str, pair_number: int) -> str | None:
    with db.pool().connection() as conn:
        bell = bells.resolve_for_date(conn, date)
    for item in bell.get('items', []):
        if item['type'] == 'pair' and item['pair'] == pair_number:
            return item['start']
    return None
