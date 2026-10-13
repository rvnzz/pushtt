"""Отправка push через Expo Push API."""
from __future__ import annotations

import httpx

from . import db

EXPO_PUSH_URL = 'https://exp.host/--/api/v2/push/send'
CHUNK_SIZE = 100


def send_push(messages: list[dict]) -> None:
    """Батчами по 100; чистит подписки с отозванными токенами."""
    for i in range(0, len(messages), CHUNK_SIZE):
        chunk = messages[i:i + CHUNK_SIZE]

        response = httpx.post(
            EXPO_PUSH_URL,
            headers={
                'accept': 'application/json',
                'content-type': 'application/json',
            },
            json=chunk,
            timeout=30,
        )
        if response.status_code != 200:
            print(f'[push] HTTP {response.status_code}: {response.text[:300]}')
            continue

        tickets = response.json().get('data') or []
        dead: list[str] = []
        for j, ticket in enumerate(tickets):
            if ticket.get('status') == 'error' \
                    and ticket.get('details', {}).get('error') == 'DeviceNotRegistered':
                if j < len(chunk):
                    dead.append(chunk[j]['to'])

        if dead:
            print(f'[push] чистим отозванные токены: {len(dead)}')
            db.delete_notifications_tokens(dead)
