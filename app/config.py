"""Конфиг воркера и дэшборда из окружения."""
import os

DATABASE_URL = os.environ.get('DATABASE_URL', '')
PORT = os.environ.get('PORT', '4000')
TIMET_BASE_URL = os.environ.get('TIMET_BASE_URL', 'https://timet.eremin.tech')

# Дэшборд
ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')
# Тест push-канала: POST /debug/simulate c заголовком X-Debug-Key
DEBUG_KEY = os.environ.get('DEBUG_KEY', '')

if not DATABASE_URL:
    print('[config] DATABASE_URL не задан — сервер не сможет работать с БД')
if not ADMIN_PASSWORD:
    print('[config] ADMIN_PASSWORD не задан — вход в дэшборд закрыт')
