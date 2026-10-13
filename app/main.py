"""Админ-дэшборд расписания (FastAPI) + рабочие эндпойнты приложения."""
from __future__ import annotations

import datetime as dt
import hashlib

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import bells, config, db, push, sync
from . import reminders, timet

app = FastAPI(title='chrt-tt worker', docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory='app/templates')


# ------------------------------------------------------------ фоновые циклы ---


@app.on_event('startup')
def on_startup() -> None:
    db.ensure_schema()
    import asyncio
    asyncio.get_running_loop().create_task(_periodic_sync())
    asyncio.get_running_loop().create_task(_hourly_reminders())


async def _periodic_sync() -> None:
    import asyncio
    while True:
        await asyncio.to_thread(sync.run_sync)
        await asyncio.sleep(sync.SYNC_INTERVAL_SECONDS)


async def _hourly_reminders() -> None:
    import asyncio
    import time as time_module

    while True:
        now = dt.datetime.now(dt.timezone.utc)
        next_run = (now + dt.timedelta(hours=1)).replace(minute=5, second=0, microsecond=0)
        await asyncio.sleep((next_run - now).total_seconds())
        await asyncio.to_thread(reminders.run_reminders)


# --------------------------------------------------------------- авторизация ---


def _session_token() -> str:
    return hashlib.sha256(
        f'pushtt-session:{config.ADMIN_PASSWORD}'.encode()
    ).hexdigest()


def admin_guard(request: Request) -> None:
    expected = _session_token()
    if config.ADMIN_PASSWORD and request.cookies.get('admin_session') == expected:
        return
    raise PermissionsException('/login')


class PermissionsException(Exception):
    def __init__(self, redirect: str) -> None:
        self.redirect = redirect


@app.exception_handler(PermissionsException)
async def permissions_exception_handler(request: Request, exc: PermissionsException):
    return RedirectResponse(exc.redirect, status_code=303)


@app.get('/login', response_class=HTMLResponse)
def login_page(request: Request):
    if config.ADMIN_PASSWORD and request.cookies.get('admin_session') == _session_token():
        return RedirectResponse('/', status_code=303)
    return templates.TemplateResponse(
        request, 'login.html', {'error': False},
    )


@app.post('/login')
def login(request: Request, password: str = Form('')):
    if not config.ADMIN_PASSWORD or password != config.ADMIN_PASSWORD:
        return templates.TemplateResponse(request, 'login.html', {'error': True}, status_code=401)

    response = RedirectResponse('/', status_code=303)
    response.set_cookie('admin_session', _session_token(), httponly=True, samesite='lax')
    return response


@app.post('/logout')
def logout():
    response = RedirectResponse('/login', status_code=303)
    response.delete_cookie('admin_session')
    return response


# ------------------------------------------------------- UTILITY для шаблонов ---


def _common_context(request: Request, **extra) -> dict:
    return {
        'request': request,
        'now_iso': timet.today_iso(),
        'timet': timet,
        **extra,
    }


# ---------------------------------------------------------------- страница / ---


@app.get('/', response_class=HTMLResponse)
def dashboard(request: Request, _: None = Depends(admin_guard)):
    left = db.subscribers_stats()
    last = db.last_sync()
    changes = db.recent_changes(10)

    return templates.TemplateResponse(
        request, 'dashboard.html',
        _common_context(
            request,
            stats=left,
            last_sync=last,
            changes=changes,
            week=timet.format_range(timet.monday_of(timet.today_iso()),
                                    timet.add_days_iso(timet.monday_of(timet.today_iso()), 6)),
        ),
    )

@app.post('/admin/sync')
def run_sync_now(_: None = Depends(admin_guard)):
    sync.run_sync()
    return RedirectResponse('/', status_code=303)


@app.post('/admin/simulate')
def simulate(_: None = Depends(admin_guard)):
    """Дэшборд-кнопка «имитировать изменение»: сбрасывает первый hash-кjuryнап и синк."""
    db.simulate_snapshot_drop()
    sync.run_sync()
    return RedirectResponse('/', status_code=303)


# ------------------------------------------------------- расписание в дэшборде ---


BUILDINGS = [
    ('fulltime', 'Очное расписание'),
    ('parttimefulltime', 'Очно-заочное расписание'),
    ('parttime', 'Заочное расписание'),
]


@app.get('/schedule', response_class=HTMLResponse)
def schedule_page(request: Request, date: str = '', building: str = 'fulltime',
                  _: None = Depends(admin_guard)):
    date = date or today_iso()
    week = timet.fetch_all_week(timet.monday_of(date))
    days = week['days']

    # звонки на выбранный день
    data_day = next((day for day in days if day['date'] == date), None)
    schedule_items: list[dict] = []
    targets: list[dict] = []

    with db.pool().connection() as conn:
        bell = bells.resolve_for_date(conn, date)

    if data_day:
        building_day = next(
            (b for b in data_day['buildings'] if b['building']['slug'] == building), None)

        if building_day:
            pair_times = {item['pair']: item for item in bell['items'] if item['type'] == 'pair'}

            for schedule in building_day.get('group_schedules', []):
                pairs = [
                    {
                        'number': pair['number'],
                        'time_from': (pair_times.get(pair['number']) or {}).get('start', ''),
                        'time_to': (pair_times.get(pair['number']) or {}).get('end', ''),
                        'lessons': pair['lessons'],
                        'is_split': pair.get('is_split'),
                    }
                    for pair in schedule.get('pairs', [])
                    if pair.get('has_content') and pair.get('lessons')
                ]
                if pairs:
                    targets.append({
                        'name': schedule['name'],
                        'id': schedule['id'],
                        'pairs': pairs,
                    })

    return templates.TemplateResponse(
        request, 'schedule_day.html',
        _common_context(
            request,
            date=date,
            week_days=days,
            building=building,
            buildings=BUILDINGS,
            bell=bell,
            targets=targets,
        ),
    )


@app.get('/admin/targets.json')
def targets_json(building: str = 'fulltime', _: None = Depends(admin_guard)):
    week = timet.fetch_all_week(timet.monday_of(today_iso()))
    groups: dict[int, str] = {}
    teachers: dict[int, str] = {}
    for day in week['days']:
        for b in day['buildings']:
            if b['building']['slug'] != building:
                continue
            for schedule in b.get('group_schedules', []):
                groups[schedule['id']] = schedule['name']
            for teacher in b.get('teachers', []):
                teachers[teacher['id']] = teacher['name']

    return JSONResponse({
        'groups': sorted(groups.items()),
        'teachers': sorted(teachers.items()),
    })


# ------------------------------------------------------------- звонки (bells) ---


@app.get('/bells', response_class=HTMLResponse)
def bells_page(request: Request, _: None = Depends(admin_guard)):
    with db.pool().connection() as conn:
        schedules = bells.list_schedules(conn)
        overrides = bells.list_overrides(conn)

    return templates.TemplateResponse(
        request, 'bells.html',
        _common_context(request, schedules=schedules, overrides=overrides),
    )


@app.post('/bells/save')
async def bells_save(
    request: Request,
    _: None = Depends(admin_guard),
):
    form = await request.form()
    schedule_id = int(form.get('id') or 0)
    name = (form.get('name') or '').strip()
    kind = form.get('kind') or 'custom'
    is_default = form.get('is_default') == 'on'
    items = _parse_schedule_items(form)

    if not name:
        return RedirectResponse('/bells', status_code=303)

    with db.pool().connection() as conn:
        existing = conn.execute(
            'SELECT is_default FROM bell_schedules WHERE id = %s', (schedule_id,)).fetchone() \
            if schedule_id else None

        keep_default = is_default or bool(existing and existing['is_default'])
        final_id = bells.save_schedule(conn, schedule_id or None, name, kind, keep_default, items)
        bells.prune_past_overrides(conn)
        conn.commit()

    if not schedule_id:
        return RedirectResponse(f'/bells/{final_id}/edit', status_code=303)
    return RedirectResponse('/bells', status_code=303)


def _parse_schedule_items(form) -> list[dict]:
    """Позиции звонков из формы (строки: type_{i}, pair_{i}, start_{i}, end_{i}, label_{i})."""
    items: list[dict] = []
    for key in sorted(form.keys()):
        if not key.startswith('type_'):
            continue
        index = key[5:]
        entry_type = form.get(f'type_{index}', 'pair')
        pair = form.get(f'pair_{index}') or None
        start = form.get(f'start_{index}', '')
        end = form.get(f'end_{index}', '')
        label = form.get(f'label_{index}', '') or ''
        if not start or not end:
            continue
        items.append({
            'type': entry_type,
            'pair': int(pair) if entry_type == 'pair' and pair else None,
            'start': start,
            'end': end,
            'label': label if entry_type == 'break' else '',
        })
    return items


@app.get('/bells/{schedule_id}/edit', response_class=HTMLResponse)
def bell_edit(request: Request, schedule_id: int, _: None = Depends(admin_guard)):
    with db.pool().connection() as conn:
        schedule = bells.get_schedule(conn, schedule_id)

    if not schedule:
        return RedirectResponse('/bells', status_code=303)

    return templates.TemplateResponse(
        request, 'bell_edit.html',
        _common_context(request, schedule=schedule),
    )


@app.post('/bells/delete')
def bell_delete(id: int = Form(0), _: None = Depends(admin_guard)):
    with db.pool().connection() as conn:
        bells.delete_schedule(conn, id)
        bells.prune_past_overrides(conn)
        conn.commit()
    return RedirectResponse('/bells', status_code=303)


@app.post('/bells/defaults')
def bell_defaults(
    monday_id: int = Form(0),
    common_id: int = Form(0),
    _: None = Depends(admin_guard),
):
    with db.pool().connection() as conn:
        if monday_id:
            bells.set_is_default(conn, monday_id, True)
        if common_id:
            bells.set_is_default(conn, common_id, True)
        bells.prune_past_overrides(conn)
        conn.commit()
    return RedirectResponse('/bells', status_code=303)


@app.post('/overrides/save')
def override_save(date: str = Form(''), schedule_id: int = Form(0),
                  _: None = Depends(admin_guard)):
    if date:
        with db.pool().connection() as conn:
            bells.set_override(conn, date, schedule_id)
            conn.commit()
    return RedirectResponse('/bells', status_code=303)


@app.post('/overrides/delete')
def override_delete(date: str = Form(''), _: None = Depends(admin_guard)):
    with db.pool().connection() as conn:
        bells.delete_override(conn, date)
        conn.commit()
    return RedirectResponse('/bells', status_code=303)


# ------------------------------------------------------------- ручные пуши ---


@app.get('/push', response_class=HTMLResponse)
def push_page(request: Request, _: None = Depends(admin_guard)):
    return templates.TemplateResponse(
        request, 'push.html',
        _common_context(request, buildings=BUILDINGS, sent=False),
    )


@app.post('/push/send')
async def push_send(
    request: Request,
    target_type: str = Form('all'),
    building: str = Form('fulltime'),
    group_id: int = Form(0),
    teacher_id: int = Form(0),
    title: str = Form(''),
    body: str = Form(''),
    _: None = Depends(admin_guard),
):
    with db.pool().connection() as conn:
        if target_type == 'group':
            sql = ("SELECT * FROM subscriptions WHERE role = 'student'"
                   ' AND target_id = %s AND building_slug = %s')
            rows = conn.execute(sql, (group_id, building)).fetchall()
        elif target_type == 'teacher':
            rows = conn.execute(
                "SELECT * FROM subscriptions WHERE role = 'teacher' AND target_id = %s",
                (teacher_id,)).fetchall()
        else:
            rows = conn.execute('SELECT * FROM subscriptions').fetchall()

    messages = [
        {
            'to': row['expo_push_token'],
            'title': title or 'Расписание ЧРТ',
            'body': body or 'Обновления в расписании — посмотрите актуальные пары',
            'data': {'type': 'manual'},
        }
        for row in rows
    ]
    push.send_push(messages)
    db.log_push('manual', messages)

    return templates.TemplateResponse(
        request, 'push.html',
        _common_context(request, buildings=BUILDINGS, sent=True, count=len(messages)),
    )


@app.get('/log', response_class=HTMLResponse)
def log_page(request: Request, _: None = Depends(admin_guard)):
    with db.pool().connection() as conn:
        rows = db.recent_pushes(40)
    changes = db.recent_changes(40)
    return templates.TemplateResponse(
        request, 'log.html',
        _common_context(request, pushes=rows, changes=changes),
    )


# ---------------------------------------------------- публичные эндпойнты приложения ---


@app.get('/health')
def health():
    return {'ok': True}


@app.post('/register')
async def register(request: Request):
    body = await request.json()
    token = body.get('expoPushToken')

    if not isinstance(token, str) or not token.startswith('Expo'):
        return JSONResponse({'errors': ['expoPushToken — недействительный']}, status_code=400)
    if body.get('role') not in ('student', 'teacher'):
        return JSONResponse({'errors': ['role — student | teacher']}, status_code=400)
    if not isinstance(body.get('buildingSlug'), str):
        return JSONResponse({'errors': ['buildingSlug обязателен']}, status_code=400)
    if not isinstance(body.get('targetId'), int):
        return JSONResponse({'errors': ['targetId обязателен']}, status_code=400)

    tomorrow_hour = body.get('tomorrowHour')
    if tomorrow_hour is not None and (not isinstance(tomorrow_hour, int)
                                      or not 0 <= tomorrow_hour <= 24):
        return JSONResponse({'errors': ['tomorrowHour — 0..24 или null']}, status_code=400)

    db.upsert_subscription(
        token,
        body['role'],
        body['buildingSlug'],
        body['targetId'],
        body.get('targetLabel') or '',
        body.get('changesEnabled', True) is not False,
        tomorrow_hour,
        body.get('tzOffsetMinutes') or 0,
    )
    return {'ok': True}


@app.post('/unregister')
async def unregister(request: Request):
    token = (await request.json()).get('expoPushToken')
    if not token:
        return JSONResponse({'errors': ['expoPushToken обязателен']}, status_code=400)
    db.delete_subscription(token)
    return {'ok': True}


@app.get('/debug/simulate')
def debug_simulate(key_check: str = ''):
    """Тест push-канала без браузера: GET /debug/simulate?key=крать (DEBUG_KEY)."""
    if not config.DEBUG_KEY or key_check != config.DEBUG_KEY:
        return JSONResponse({'errors': ['debug выключен: задайте DEBUG_KEY']}, status_code=403)

    db.simulate_snapshot_drop()
    sync.run_sync()
    return {'ok': True, 'targetKey': 'g:10'}


@app.get('/api/bells')
def api_bell(date: str = ''):
    """Для приложения: разрешенные звонки на дату (без auth)."""
    date = date or today_iso()
    with db.pool().connection() as conn:
        bell = bells.resolve_for_date(conn, date)
    return JSONResponse({'date': date, 'schedule': bell})


def today_iso() -> str:
    return timet.today_iso()
