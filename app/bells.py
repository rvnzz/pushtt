"""Звонки: шаблоны расписания звонков + переопределения на конкретную дату."""
from __future__ import annotations

import datetime as dt

from . import timet


def resolve_for_date(conn, date: str) -> dict:
    """Шаблон звонков на дату: переопределение > понедельник > общий день."""
    override = conn.execute(
        """SELECT bs.id, bs.name, bs.kind
           FROM bell_overrides o JOIN bell_schedules bs ON bs.id = o.bell_schedule_id
           WHERE o.date = %s""",
            (date,),
    ).fetchone()
    source = 'override'

    if not override:
        kind = 'monday' if timet.weekday_index(date) == 0 else 'common'
        override = conn.execute(
            'SELECT id, name, kind FROM bell_schedules WHERE kind = %s AND is_default = true',
            (kind,),
        ).fetchone()
        source = 'default'

    if not override:
        return {'name': 'Не настроено', 'source': source, 'items': []}

    items = conn.execute(
        """SELECT entry_type, pair_number, start_time, end_time, label
           FROM bell_items WHERE bell_schedule_id = %s
           ORDER BY start_time""",
            (override['id'],),
    ).fetchall()

    return {
        'id': override['id'],
        'name': override['name'],
        'kind': override['kind'],
        'source': source,
        'items': [
            {
                'type': item['entry_type'],
                'pair': item['pair_number'],
                'start': item['start_time'].strftime('%H:%M'),
                'end': item['end_time'].strftime('%H:%M'),
                'label': item['label'],
            }
            for item in items
        ],
    }


def list_schedules(conn) -> list[dict]:
    return conn.execute(
        '''SELECT bs.id, bs.name, bs.kind, bs.is_default,
                  (SELECT count(*) FROM bell_items bi WHERE bi.bell_schedule_id = bs.id) AS items_count
           FROM bell_schedules bs ORDER BY bs.id'''
    ).fetchall()


def get_schedule(conn, schedule_id: int) -> dict | None:
    schedule = conn.execute(
        'SELECT id, name, kind, is_default FROM bell_schedules WHERE id = %s',
        (schedule_id,),
    ).fetchone()
    if not schedule:
        return None

    schedule['items'] = conn.execute(
        '''SELECT id, entry_type, pair_number, start_time, end_time, label
           FROM bell_items WHERE bell_schedule_id = %s ORDER BY start_time''',
        (schedule_id,),
    ).fetchall()
    return schedule


def save_schedule(
    conn,
    schedule_id: int | None,
    name: str,
    kind: str,
    is_default: bool,
    items: list[dict],
) -> int:
    """Сохранение шаблона: апдейт полей + полная замена позиций."""
    if schedule_id:
        schedule = conn.execute(
            'UPDATE bell_schedules SET name = %s, kind = %s, updated_at = now() WHERE id = %s'
            ' RETURNING id',
            (name, kind, schedule_id),
        ).fetchone()
        schedule_id = schedule['id']
    else:
        schedule_id = conn.execute(
            'INSERT INTO bell_schedules (name, kind) VALUES (%s, %s) RETURNING id',
                (name, kind),
        ).fetchone()['id']
        # Свежесозданный шаблон ещё не дефолт — приведём is_default ниже

    set_is_default(conn, schedule_id, is_default)

    conn.execute('DELETE FROM bell_items WHERE bell_schedule_id = %s', (schedule_id,))
    for item in items:
        conn.execute(
            """INSERT INTO bell_items (bell_schedule_id, entry_type, pair_number, start_time, end_time, label)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (schedule_id, item['type'], item['pair'], item['start'], item['end'], item['label'] or None),
        )
    return schedule_id


def set_is_default(conn, schedule_id: int, is_default: bool) -> None:
    schedule = conn.execute('SELECT kind FROM bell_schedules WHERE id = %s', (schedule_id,)).fetchone()
    if not schedule:
        return

    if not is_default:
        conn.execute(
            'UPDATE bell_schedules SET is_default = false WHERE id = %s '
            'AND EXISTS (SELECT 1 FROM bell_schedules other WHERE other.kind = %s'
            ' AND other.is_default AND other.id != %s)',
            (schedule_id, schedule['kind'], schedule_id),
        )
        return

    # Снимаем дефолт с прежнего шаблона этого типа и ставим наш
    conn.execute(
        'UPDATE bell_schedules SET is_default = false WHERE kind = %s AND is_default',
            (schedule['kind'],),
    )
    conn.execute('UPDATE bell_schedules SET is_default = true WHERE id = %s', (schedule_id,))


def delete_schedule(conn, schedule_id: int) -> None:
    conn.execute('DELETE FROM bell_schedules WHERE id = %s', (schedule_id,))


def list_overrides(conn) -> list[dict]:
    return conn.execute(
        """SELECT o.date, o.bell_schedule_id, bs.name
           FROM bell_overrides o JOIN bell_schedules bs ON bs.id = o.bell_schedule_id
           ORDER BY o.date"""
    ).fetchall()


def set_override(conn, date: str, schedule_id: int) -> None:
    conn.execute('DELETE FROM bell_overrides WHERE date = %s', (date,))
    conn.execute(
        'INSERT INTO bell_overrides (date, bell_schedule_id) VALUES (%s, %s)',
        (date, schedule_id),
    )


def delete_override(conn, date: str) -> None:
    conn.execute('DELETE FROM bell_overrides WHERE date = %s', (date,))


def prune_past_overrides(conn) -> None:
    """Настройки прошлых дней не нужны храниться вечно."""
    conn.execute("DELETE FROM bell_overrides WHERE date < %s", (dt.date.today().isoformat(),))
