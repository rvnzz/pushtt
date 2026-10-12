import express from 'express';

import { config } from './config.js';
import { ensureSchema } from './db.js';
import { runSync } from './sync.js';
import { runReminders } from './reminders.js';
import { registerHandler, simulateHandler, unregisterHandler } from './routes.js';

const app = express();
app.use(express.json());

app.get('/health', (_req, res) => {
  res.json({ ok: true });
});

app.post('/register', registerHandler);
app.post('/unregister', unregisterHandler);
app.post('/debug/simulate', simulateHandler);

const SYNC_INTERVAL_MS = 15 * 60 * 1000;

async function main() {
  await ensureSchema();

  // Первый синк не блокирует старт сервера
  runSync().catch((error) => console.error('[sync] ошибка:', error));
  setInterval(() => {
    runSync().catch((error) => console.error('[sync] ошибка:', error));
  }, SYNC_INTERVAL_MS);

  scheduleHourlyReminders();

  app.listen(config.port, () => {
    console.log(`[server] слушает :${config.port}`);
  });
}

/** Каждую минуту часа №5 (05, 1:05, 2:05 … по времени сервера) */
function scheduleHourlyReminders() {
  const run = () => {
    runReminders().catch((error) => console.error('[reminders] ошибка:', error));
    setTimeout(run, 60 * 60 * 1000);
  };

  const now = new Date();
  const next = new Date(now.getTime());
  next.setMinutes(5, 0, 0);
  if (next <= now) {
    next.setHours(next.getHours() + 1);
  }

  setTimeout(run, next.getTime() - now.getTime());
  console.log(`[server] напоминания начнутся в ${next.toISOString()}`);
}

main().catch((error) => {
  console.error('[server] фатальная ошибка старта:', error);
  process.exit(1);
});
