"""PostgreSQL: пул соединений, схема, seed-данные звонков."""
from __future__ import annotations

import datetime as dt

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from psycopg.types.json import Json


_pool: psycopg.Pool | None = None


def pool() -> psycopg.Pool:
    global _pool
    if _pool is None:
        from . import config
        _pool = ConnectionPool(
            config.DATABASE_URL,
            min_size=1,
            max_size=5,
            kwargs={'row_factory': dict_row},
        )
    return _pool


SCHEMA = r"""
CREATE TABLE IF NOT EXISTS subscriptions (
  expo_push_token     text PRIMARY KEY,
  role                text NOT NULL CHECK (role IN ('student', 'teacher')),
  building_slug       text NOT NULL,
  target_id           int NOT NULL,
  target_label        text NOT NULL,
  changes_enabled     boolean NOT NULL DEFAULT true,
  tomorrow_hour       int,
  tz_offset_minutes   int NOT NULL DEFAULT -180,
  last_tomorrow_date  date,
  updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS schedule_hashes (
  building_slug  text NOT NULL,
  date           text NOT NULL,
  targets        jsonb NOT NULL,
  PRIMARY KEY (building_slug, date)
);

CREATE TABLE IF NOT EXISTS bell_schedules (
  id serial PRIMARY KEY,
  name text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('monday', 'common', 'hour', 'custom')),
  is_default boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS bell_schedules_default_kind
  ON bell_schedules (kind) WHERE is_default;

CREATE TABLE IF NOT EXISTS bell_items (
  id serial PRIMARY KEY,
  bell_schedule_id int NOT NULL REFERENCES bell_schedules(id) ON DELETE CASCADE,
  entry_type text NOT NULL CHECK (entry_type IN ('pair', 'break')),
  pair_number int,
  start_time time NOT NULL,
  end_time time NOT NULL,
  label text
);

CREATE TABLE IF NOT EXISTS bell_overrides (
  date date PRIMARY KEY,
  bell_schedule_id int NOT NULL REFERENCES bell_schedules(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS schedule_changes (
  id bigserial PRIMARY KEY,
  building_slug text NOT NULL,
  date date NOT NULL,
  target_key text NOT NULL,
  target_label text NOT NULL,
  recipients int NOT NULL DEFAULT 0,
  detected_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS push_log (
  id bigserial PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now(),
  source text NOT NULL CHECK (source IN ('change', 'reminder', 'manual')),
  title text NOT NULL,
  body text NOT NULL,
  recipients int NOT NULL DEFAULT 0,
  meta jsonb
);

CREATE TABLE IF NOT EXISTS sync_log (
  id bigserial PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now(),
  ok boolean NOT NULL,
  message text,
  duration_ms int
);
"""


def ensure_schema() -> None:
    with pool().connection() as conn:
        conn.execute(SCHEMA)
        conn.commit()
        seed_bells(conn)


# ---------------------------------------------------------------- звонки ---

"""Seed трёх шаблонов звонков (при пустой таблице bell_schedules)."""

_MONDAY = [
    ('break', None, '08:30', '09:10', 'Линейка и классный час'),
    ('pair', 1, '09:20', '10:45', None),
    ('pair', 2, '10:55', '12:20', None),
    ('break', None, '12:20', '13:05', 'Обед'),
    ('pair', 3, '13:05', '14:30', None),
    ('pair', 4, '14:40', '16:05', None),
    ('pair', 5, '16:15', '17:40', None),
    ('pair', 6, '17:50', '19:15', None),
    ('pair', 7, '19:25', '20:55', None),
]
_COMMON = [
    ('pair', 1, '08:30', '10:00', None),
    ('pair', 2, '10:10', '11:40', None),
    ('break', None, '11:40', '12:25', 'Обед'),
    ('pair', 3, '12:25', '13:55', None),
    ('pair', 4, '14:05', '15:35', None),
    ('pair', 5, '15:45', '17:15', None),
    ('pair', 6, '17:25', '18:55', None),
    ('pair', 7, '19:05', '20:35', None),
]
_HOUR_EXPLICIT = [
    ('pair', 1, '08:30', '09:30', None),
    ('pair', 2, '09:40', '10:40', None),
    ('pair', 3, '10:50', '11:50', None),
    ('pair', 4, '12:00', '13:00', None),
    ('pair', 5, '13:10', '14:10', None),
    ('pair', 6, '14:20', '15:20', None),
    ('pair', 7, '15:30', '16:30', None),
]


def seed_bells(conn: psycopg.Connection) -> None:
    (count,) = conn.execute('SELECT count(*) FROM bell_schedules').fetchone().values()
    if count > 0:
        return

    for kind, name, items, default in (
        ('monday', 'Понедельник (с линейкой)', _MONDAY, True),
        ('common', 'Общее (вторник–суббота)', _COMMON, True),
        ('hour', 'Пары по часу (сокращённое)', _HOUR_EXPLICIT, False),
    ):
        cur = conn.execute(
            'INSERT INTO bell_schedules (name, kind, is_default) VALUES (%s, %s, %s) RETURNING id',
            (name, kind, default),
        )
        schedule_id = cur.fetchone()['id']
        for entry_type, pair, start, end, label in items:
            conn.execute(
                'INSERT INTO bell_items (bell_schedule_id, entry_type, pair_number, start_time, end_time, label)'
                ' VALUES (%s, %s, %s, %s, %s, %s)',
                (schedule_id, entry_type, pair, start, end, label),
            )
    conn.commit()


# -------------------------------------------------------- подписки/снапшоты ---


def upsert_subscription(
    token: str,
    role: str,
    building_slug: str,
    target_id: int,
    target_label: str,
    changes_enabled: bool,
    tomorrow_hour: int | None,
    tz_offset_minutes: int,
) -> None:
    with pool().connection() as conn:
        conn.execute(
            """
            INSERT INTO subscriptions
              (expo_push_token, role, building_slug, target_id, target_label,
               changes_enabled, tomorrow_hour, tz_offset_minutes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (expo_push_token) DO UPDATE SET
              role = EXCLUDED.role,
              building_slug = EXCLUDED.building_slug,
              target_id = EXCLUDED.target_id,
              target_label = EXCLUDED.target_label,
              changes_enabled = EXCLUDED.changes_enabled,
              tomorrow_hour = EXCLUDED.tomorrow_hour,
              tz_offset_minutes = EXCLUDED.tz_offset_minutes,
              updated_at = now()
            """,
            (token, role, building_slug, target_id, target_label,
             changes_enabled, tomorrow_hour, tz_offset_minutes),
        )
        conn.commit()


def delete_subscription(token: str) -> None:
    with pool().connection() as conn:
        conn.execute('DELETE FROM subscriptions WHERE expo_push_token = %s', (token,))
        conn.commit()


def find_subscribers_for_change(role: str, building_slug: str, target_id: int) -> list[dict]:
    with pool().connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM subscriptions
            WHERE role = %s AND target_id = %s AND changes_enabled = true
              AND (role = 'teacher' OR building_slug = %s)
            """,
            (role, target_id, building_slug),
        ).fetchall()
    return rows


def find_reminder_subscribers() -> list[dict]:
    with pool().connection() as conn:
        rows = conn.execute('SELECT * FROM subscriptions WHERE tomorrow_hour IS NOT NULL').fetchall()
    return rows


def mark_tomorrow_sent(token: str, date: str) -> None:
    with pool().connection() as conn:
        conn.execute(
            'UPDATE subscriptions SET last_tomorrow_date = %s WHERE expo_push_token = %s',
            (date, token),
        )
        conn.commit()


def load_snapshots(dates: list[str]) -> dict[str, dict]:
    if not dates:
        return {}
    with pool().connection() as conn:
        rows = conn.execute(
            'SELECT building_slug, date, targets FROM schedule_hashes WHERE date = ANY(%s)',
            (dates,),
        ).fetchall()
    return {f"{r['building_slug']}|{r['date']}": (r['targets'] or {}) for r in rows}


def save_snapshots(snapshots: list[dict]) -> None:
    with pool().connection() as conn:
        for s in snapshots:
            conn.execute(
                """INSERT INTO schedule_hashes (building_slug, date, targets)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (building_slug, date) DO UPDATE SET targets = EXCLUDED.targets""",
                (s['buildingSlug'], s['date'], Json(s['targets'])),
            )
        conn.commit()


def delete_snapshots_older_than(date: str) -> None:
    with pool().connection() as conn:
        conn.execute('DELETE FROM schedule_hashes WHERE date < %s', (date,))
        conn.commit()


def delete_notifications_tokens(tokens: list[str]) -> None:
    with pool().connection() as conn:
        conn.execute(
            'DELETE FROM subscriptions WHERE expo_push_token = ANY(%s)',
            (tokens,),
        )
        conn.commit()


# ------------------------------------------------------------- журнал/лог ---


def record_changes(rows: list[dict]) -> None:
    if not rows:
        return
    with pool().connection() as conn:
        for row in rows:
            conn.execute(
                """INSERT INTO schedule_changes (building_slug, date, target_key, target_label, recipients)
                   VALUES (%s, %s, %s, %s, %s)""",
                (row['building_slug'], row['date'], row['target_key'],
                 row['target_label'], row['recipients']),
            )
        conn.commit()


def log_push(source: str, messages: list[dict]) -> None:
    if not messages:
        return
    with pool().connection() as conn:
        first_title = messages[0].get('title', '')
        first_body = messages[0].get('body', '')
        meta = {'kinds': sorted({m.get('kind', '') for m in messages})}
        conn.execute(
            """INSERT INTO push_log (source, title, body, recipients, meta)
               VALUES (%s, %s, %s, %s, %s)""",
            (source, first_title, first_body, len(messages),
             Json(meta)),
        )
        conn.commit()


def log_sync(ok: bool, message: str, duration_ms: int) -> None:
    with pool().connection() as conn:
        conn.execute('INSERT INTO sync_log (ok, message, duration_ms) VALUES (%s, %s, %s)',
                     (ok, message, duration_ms))
        conn.commit()


def last_sync() -> dict | None:
    with pool().connection() as conn:
        row = conn.execute(
            'SELECT created_at, ok, message, duration_ms FROM sync_log ORDER BY id DESC LIMIT 1'
        ).fetchone()
    return row


def recent_changes(limit: int = 25) -> list[dict]:
    with pool().connection() as conn:
        return conn.execute(
            'SELECT detected_at, building_slug, date, target_key, target_label, recipients'
            ' FROM schedule_changes ORDER BY id DESC LIMIT %s',
            (limit,),
        ).fetchall()


def recent_pushes(limit: int = 25) -> list[dict]:
    with pool().connection() as conn:
        return conn.execute(
            'SELECT created_at, source, title, body, recipients FROM push_log'
            ' ORDER BY id DESC LIMIT %s',
            (limit,),
        ).fetchall()


def subscribers_stats() -> dict:
    with pool().connection() as conn:
        (total,) = conn.execute('SELECT count(*) FROM subscriptions').fetchone().values()
        (changes,) = conn.execute(
            "SELECT count(*) FROM subscriptions WHERE changes_enabled = true"
        ).fetchone().values()
        (tomorrow,) = conn.execute(
            'SELECT count(*) FROM subscriptions WHERE tomorrow_hour IS NOT NULL'
        ).fetchone().values()
    return {'total': total, 'changes': changes, 'tomorrow': tomorrow}


def simulate_snapshot_drop() -> tuple[str, int]:
    """Отладка push-канала: убирает хэш цели ПЕРВОЙ подписки из её снапшотов,
    чтобы следующий sync работал как «публикация» и ушёл реальный пуш."""
    with pool().connection() as conn:
        subscriber = conn.execute(
            'SELECT role, target_id, building_slug FROM subscriptions LIMIT 1'
        ).fetchone()

        if subscriber:
            key = ('g' if subscriber['role'] == 'student' else 't') + f":{subscriber['target_id']}"
            if subscriber['building_slug'] == '*':
                conn.execute(
                    'UPDATE schedule_hashes SET targets = targets - %s::text',
                    (key,),
                )
            else:
                conn.execute(
                    "UPDATE schedule_hashes SET targets = targets - %s::text"
                    " WHERE building_slug = %s",
                    (key, subscriber['building_slug']),
                )
            return key, 1

        # Подписок нет — гасим первый ключ каждого снапшота (проверка diff-логики)
        rows = conn.execute('SELECT building_slug, date, targets FROM schedule_hashes').fetchall()
        for row in rows:
            targets = row['targets'] or {}
            first_key = next(iter(targets), None)
            if first_key:
                rests = {k: v for k, v in targets.items() if k != first_key}
                conn.execute(
                    'UPDATE schedule_hashes SET targets = %s WHERE building_slug = %s AND date = %s',
                    (Json(rests), row['building_slug'], row['date']),
                )
        return 'first-key-per-snapshot', 0
