# chrt-tt worker — пуш-уведомления расписания (pushtt)

Самостоятельный сервис: собирает расписание с timet.eremin.tech, сравнивает со
снапшотами (хэши по группе/преподавателю) и рассылает push через Expo Push API.
Подписки хранятся в PostgreSQL. Всё работает в Docker.

## Прод: из GHCR

```bash
echo 'POSTGRES_PASSWORD=<пароль>' > .env
docker compose pull   # image ghcr.io/rvnzz/pushtt:latest
docker compose up -d
```

## Запуск из исходников

```bash
docker compose up -d --build
docker compose logs -f server
```

Сервисы:
- `db` — PostgreSQL 17 (volume `pgdata`, схема создается автоматически);
- `server` — worker + HTTP (порт `4000`, `SERVER_PORT` переопределяет).

## HTTP

- `GET  /health`
- `POST /register`   — `{expoPushToken, role, buildingSlug, targetId, targetLabel, changesEnabled, tomorrowHour, tzOffsetMinutes}`
- `POST /unregister` — `{expoPushToken}`
- `POST /debug/simulate` — тест push-канала (заголовок `X-Debug-Key: <DEBUG_KEY>`); body `{ "targetKey": "g:10" | "t:33" }` (по умолчанию `g:10`).

Планировщики: синк каждые 15 мин, напоминания «на завтра» ежечасно на 5-й минуте.

## Проверка

```bash
curl -s localhost:4000/health

curl -s -X POST localhost:4000/register -H 'Content-Type: application/json' -d '{
  "expoPushToken":"ExponentPushToken[...]", "role":"student",
  "buildingSlug":"fulltime", "targetId":10, "targetLabel":"Ис-103",
  "changesEnabled":true, "tomorrowHour":null, "tzOffsetMinutes":-180 }'

curl -s -X POST localhost:4000/debug/simulate \
  -H 'Content-Type: application/json' -H 'X-Debug-Key: ваш-секрет' -d '{}'
```

## Приложение (chrt-tt)

Адрес сервера — `EXPO_PUBLIC_PUSH_API_URL` (или константа в `src/api/settings.ts`).
Приложение шлет токен только по HTTPS: перед контейнером используйте Caddy/nginx
с сертификатом (443 → 4000).
