"""Синк расписания: diff со снапшотами + мгновенные пуши подписчикам."""
from __future__ import annotations

import time

from . import db, push, timet
from .hash import build_snapshots

SYNC_INTERVAL_SECONDS = 15 * 60

"""Недели последнего синка — reminders смотрят сюда без повторного fetch."""
cached_weeks: dict[str, dict] = {}


def run_sync(**kwargs) -> None:
    """Полный цикл сверки. Текущая + следующая неделя."""
    started = time.monotonic()
    ok, message = True, ''

    try:
        sent, changes = _run_sync()
        message = f'{changes} изменений, {sent} пушей'
        print(f'[sync] {message}')
    except Exception as error:  # noqa: BLE001 — пилотский лог в sync_log
        ok = False
        message = f'{type(error).__name__}: {error}'
        print(f'[sync] ошибка: {message}')

    db.log_sync(ok, message, int((time.monotonic() - started) * 1000))


def _run_sync() -> tuple[int, int]:
    this_monday = timet.monday_of(timet.today_iso())
    next_monday = timet.add_days_iso(this_monday, 7)

    weeks = [timet.fetch_all_week(this_monday), timet.fetch_all_week(next_monday)]
    fetched_dates = sorted({day['date'] for week in weeks for day in week['days']})

    before = db.load_snapshots(fetched_dates)
    names = _collect_names(weeks)

    after: list[dict] = []
    messages: list[dict] = []
    change_rows: list[dict] = []

    for week in weeks:
        for snapshot in build_snapshots(week):
            after.append(snapshot)
            previous = before.get(f"{snapshot['buildingSlug']}|{snapshot['date']}", {})

            for target_key, current_hash in snapshot['targets'].items():
                previous_hash = previous.get(target_key)

                if previous_hash == current_hash:
                    continue

                kind = 'student' if target_key.startswith('g:') else 'teacher'
                target_id = int(target_key.split(':')[1])
                label = names(target_key[:1], target_id)
                if not label:
                    continue

                subscribers = db.find_subscribers_for_change(
                    kind, snapshot['buildingSlug'], target_id)

                change_rows.append({
                    'building_slug': snapshot['buildingSlug'],
                    'date': snapshot['date'],
                    'target_key': target_key,
                    'target_label': label,
                    'recipients': len(subscribers),
                })

                if not subscribers:
                    continue

                title = (
                    'Опубликовано расписание'
                    if previous_hash is None else 'Изменение расписания'
                )
                body = f'{label} — {timet.format_date(snapshot["date"])}'

                for subscriber in subscribers:
                    messages.append({
                        'to': subscriber['expo_push_token'],
                        'title': title,
                        'body': body,
                        'data': {
                            'kind': kind,
                            'targetId': target_id,
                            'date': snapshot['date'],
                            'buildingSlug': snapshot['buildingSlug'],
                        },
                    })

    if messages:
        print(f'[sync] изменений: {len(messages)} пушей')
        push.send_push(messages)
    else:
        print('[sync] изменений нет')

    db.save_snapshots(after)
    db.record_changes(change_rows)
    db.log_push('change', messages)
    db.delete_snapshots_older_than(this_monday)

    return len(messages), len(change_rows)


def _collect_names(weeks: list[dict]):
    """Имя группы/преподавателя из свежих данных — для текста пушей."""
    names: dict[str, str] = {}
    for week in weeks:
        for day in week['days']:
            for building in day['buildings']:
                for schedule in building.get('group_schedules', []):
                    names[f'g:{schedule["id"]}'] = schedule['name']
                for teacher in building.get('teachers', []):
                    names[f't:{teacher["id"]}'] = teacher['name']

    return lambda key, target_id: names.get(f'{key}:{target_id}')
