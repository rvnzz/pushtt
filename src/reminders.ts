import { findReminderSubscribers, SubscriptionRow } from './db.js';
import { sendPush } from './push.js';
import { addDaysISO } from './timet.js';
import { countTargetPairsForDate, getCachedWeek, runSync } from './sync.js';

/**
 * Ежечасное напоминание «расписание на завтра»:
 * каждому подписчику отправляем, когда UTC-время совпадает
 * с его локальным выбором (tz_offset_minutes из подписки).
 */
export async function runReminders(): Promise<void> {
  const subscribers = await findReminderSubscribers();
  if (subscribers.length === 0) return;

  const nowUtc = Date.now();
  const messages: Parameters<typeof sendPush>[0] = [];

  for (const subscriber of subscribers) {
    const local = wallClock(subscriber);
    if (local.hour !== subscriber.tomorrow_hour) continue;

    const tomorrow = addDaysISO(local.date, 1);
    if (subscriber.last_tomorrow_date === tomorrow) continue;

    const week = await weekFor(tomorrow);

    const pairCount = countTargetPairsForDate(
      week,
      subscriber.role,
      subscriber.building_slug,
      subscriber.target_id,
      tomorrow,
    );

    // Пар нет — не спамим (пустой день в напоминании не интересен)
    if (pairCount === 0) {
      console.log(`[reminders] ${subscriber.target_label}: завтра пар нет — пропускаем`);
      await markSent(subscriber, tomorrow);
      continue;
    }

    messages.push({
      to: subscriber.expo_push_token,
      title: 'Расписание на завтра',
      body: `${targetPhrase(subscriber)} — ${pairCount} ${plural(pairCount)}`,
      data: { date: tomorrow },
    });

    await markSent(subscriber, tomorrow);
  }

  if (messages.length > 0) {
    console.log(`[reminders] отправляем: ${messages.length}`);
    await sendPush(messages);
  }
}

/** Локальные календалинг-рендеринг подписчика */
function wallClock(subscriber: { tz_offset_minutes: number }) {
  // getTimezoneOffset: минуты ПОСЛЕ UTC (напр., Москва = -180),
  // значит локальное равнение wall = Date.now() - offset*60000, читаем как UTC
  const shifted = new Date(Date.now() - subscriber.tz_offset_minutes * 60_000);
  return {
    hour: shifted.getUTCHours(),
    date: shifted.toISOString().slice(0, 10),
  };
}

/** Неделя для даты: кэш синка или догрузка */
async function weekFor(date: string) {
  const { mondayOf, fetchAllWeek } = await import('./timet.js');
  const monday = mondayOf(date);
  return getCachedWeek(monday) ?? fetchAllWeek(date);
}

function targetPhrase(subscriber: SubscriptionRow) {
  return subscriber.role === 'student'
    ? `у группы ${subscriber.target_label}`
    : `у преподавателя ${subscriber.target_label}`;
}

export function plural(count: number) {
  const abs10 = count % 10;
  const abs100 = count % 100;
  if (abs10 === 1 && abs100 !== 11) return 'пара';
  if (abs10 >= 2 && abs10 <= 4 && (abs100 < 12 || abs100 > 14)) return 'пары';
  return 'пар';
}

async function markSent(subscriber: SubscriptionRow, date: string) {
  const { pool } = await import('./db.js');
  await pool.query('UPDATE subscriptions SET last_tomorrow_date = $2 WHERE expo_push_token = $1', [
    subscriber.expo_push_token,
    date,
  ]);
}
