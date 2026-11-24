"""Кеш недель расписания timet.eremin.tech (в памяти процесса, с TTL).

- TTL = интервал синка (15 мин): между синками запросы не дёргают timet.
- Single-flight: параллельные запросы одной и той же недели ждут первый
  фетч, а не ходят в timet каждый сам по себе (per-key лок).
- Свежие данные кладёт и синк после каждой сверки — виджет/напоминания
  видят их сразу, без ожидания собственного TTL.
"""
from __future__ import annotations

import os
import threading
import time

from . import timet

TTL_SECONDS = int(os.environ.get('WEEK_CACHE_TTL_SECONDS', str(15 * 60)))


class _Entry:
    __slots__ = ('week', 'fetched_at')

    def __init__(self, week: dict, fetched_at: float) -> None:
        self.week = week
        self.fetched_at = fetched_at


_cache: dict[str, _Entry] = {}
_guard = threading.Lock()          # защищает _cache и _locks
_locks: dict[str, threading.Lock] = {}  # per-key: один фетч на понедельник


def _key_lock(monday: str) -> threading.Lock:
    with _guard:
        lock = _locks.get(monday)
        if lock is None:
            lock = _locks[monday] = threading.Lock()
        return lock


def _fresh(entry: _Entry | None) -> _Entry | None:
    if entry and time.monotonic() - entry.fetched_at < TTL_SECONDS:
        return entry
    return None


def get_week(monday: str) -> dict:
    """Неделя из кеша; устарела — один фетч в timet на всех ожидавших."""
    entry = _fresh(_cache.get(monday))
    if entry:
        return entry.week

    with _key_lock(monday):
        entry = _fresh(_cache.get(monday))  # double-check: пока ждали, кто-то фетчнул
        if entry:
            return entry.week

        week = timet.fetch_all_week(monday)
        put_week(monday, week)
        return week


def put_week(monday: str, week: dict) -> None:
    """Положить свежую неделю (синк делает это после каждой сверки)."""
    now = time.monotonic()
    with _guard:
        _cache[monday] = _Entry(week, now)
        # подчистка: протухшие записи и их локи (рост ключей = прошедшие недели)
        for key in [k for k, e in _cache.items() if now - e.fetched_at >= TTL_SECONDS]:
            del _cache[key]
            _locks.pop(key, None)


def drop_week(monday: str) -> None:
    with _guard:
        _cache.pop(monday, None)
        _locks.pop(monday, None)
