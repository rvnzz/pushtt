# pushtt — пуш-воркер + админ-дэшборд расписания ЧРТ

FastAPI-сервис: собирает расписание с timet.eremin.tech, сравнивает со снапшотами,
рассылает push (Expo Push API) и даёт админ-дэшборд:

- **Дэшборд** — подписчики, последний синк, кнопка «Обновить расписание сейчас», тест push-канала;
- **Расписание дня** — по корпусам, с подстановкой времени звонков;
- **Звонки** — шаблоны (понедельник/общий день/сокращённый «пары по часу»), значения по умолчанию и переопределения на конкретную дату (в т.ч. «понедельник по общему расписанию»);
- **Ручной push** — всем / группе / преподавателю;
- **Журнал** — история пушей и изменений расписания.

## Запуск (Docker Compose)

```bash
cp .env.example .env     # поменяйте ADMIN_PASSWORD и (опц.) DEBUG_KEY
docker compose up -d --build
docker compose logs -f server
```

- Веб: `http://localhost:4000` → вход по `ADMIN_PASSWORD` (`/login`).
- БД: PostgreSQL 17 c volume `pgdata`, схема и seed-звонки создаются сами.

## Endpoints

Приложение (без auth):
- `POST /register`, `POST /unregister` — подписки (токен, роль, цель, настройки напоминаний)
- `GET  /api/bells?date=YYYY-MM-DD` — активное расписание звонков на дату (для будущего использования в приложении)
- `GET  /health`

Дэшборд (после `/login`):
- `/`, `/schedule?date=&building=`, `/bells`, `/bells/{id}/edit`, `/push`, `/log`
- `POST /admin/sync` — синк вручную; `POST /admin/simulate` — тест push-канала
- `GET  /debug/simulate?key=<DEBUG_KEY>` — тест push-канала из curl*

## Проверка push-канала

1. В приложении включите «Уведомления» — появится подписка (`/register`).
2. На дэшборде нажмите «Тест push» — сервер уберёт хэш цели подписки из снапшотов
   и синк отправит реальный пуш «Опубликовано расписание …» на устройство.

## Планировщики (внутри контейнера)

- Синк расписания каждые 15 минут (текущая + следующая недели),
  изменения записываются в `schedule_changes`, пуши — подписчикам цели.
- «Расписание на завтра» — ежечасно на 5-й минуте, по локальному часу
  подписчика (`tzOffsetMinutes`), со временем первой пары из актуальных звонков.

## Схема БД (PostgreSQL)

`subscriptions`, `schedule_hashes` — работа контура;
`bell_schedules` / `bell_items` / `bell_overrides` — звонки;
`schedule_changes`, `push_log`, `sync_log` — журнал.

## CI

GitHub Actions (`.github/workflows/docker.yml`) собирает и пушит образ в
`ghcr.io/rvnzz/pushtt:latest` на каждый push в `main`.

## Приложение (chrt-tt)

Адрес сервера задаётся в `src/api/settings.ts` (`EXPO_PUBLIC_PUSH_API_URL`).
Приложение шлёт токен только по HTTPS — перед контейнером нужен Caddy/nginx
с сертификатом (443 → 4000), например `push.schrt.ru`.
