import { Pool } from 'pg';

import { config } from './config.js';

export const pool = new Pool({
  connectionString: config.databaseUrl,
  max: 5,
});

/** Схема: подписки и снапшоты хэшей расписания */
const SCHEMA = `
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
`;

export async function ensureSchema(): Promise<void> {
  const client = await pool.connect();
  try {
    await client.query(SCHEMA);
  } finally {
    client.release();
  }
}

export type SubscriptionRow = {
  expo_push_token: string;
  role: 'student' | 'teacher';
  building_slug: string;
  target_id: number;
  target_label: string;
  changes_enabled: boolean;
  tomorrow_hour: number | null;
  tz_offset_minutes: number;
  last_tomorrow_date: string | null;
};

export async function upsertSubscription(sub: {
  expoPushToken: string;
  role: string;
  buildingSlug: string;
  targetId: number;
  targetLabel: string;
  changesEnabled: boolean;
  tomorrowHour: number | null;
  tzOffsetMinutes: number;
}): Promise<void> {
  await pool.query(
    `INSERT INTO subscriptions
       (expo_push_token, role, building_slug, target_id, target_label,
        changes_enabled, tomorrow_hour, tz_offset_minutes)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
     ON CONFLICT (expo_push_token) DO UPDATE SET
       role = EXCLUDED.role,
       building_slug = EXCLUDED.building_slug,
       target_id = EXCLUDED.target_id,
       target_label = EXCLUDED.target_label,
       changes_enabled = EXCLUDED.changes_enabled,
       tomorrow_hour = EXCLUDED.tomorrow_hour,
       tz_offset_minutes = EXCLUDED.tz_offset_minutes,
       updated_at = now()`,
    [
      sub.expoPushToken,
      sub.role,
      sub.buildingSlug,
      sub.targetId,
      sub.targetLabel,
      sub.changesEnabled,
      sub.tomorrowHour,
      sub.tzOffsetMinutes,
    ],
  );
}

export async function deleteSubscription(token: string): Promise<void> {
  await pool.query('DELETE FROM subscriptions WHERE expo_push_token = $1', [token]);
}

/** Подписки, которым нужен пуш при изменении конкретной цели.
 * Преподаватели подписываются со building_slug='*' — их ищем по target_id независимо от корпуса. */
export async function findSubscribersForChange(
  role: 'student' | 'teacher',
  buildingSlug: string,
  targetId: number,
): Promise<SubscriptionRow[]> {
  const { rows } = await pool.query<SubscriptionRow>(
    `SELECT * FROM subscriptions
     WHERE role = $1 AND target_id = $3 AND changes_enabled = true
       AND (role = 'teacher' OR building_slug = $2)`,
    [role, buildingSlug, targetId],
  );
  return rows;
}

/** Подписки с включённым напоминанием «на завтра» */
export async function findReminderSubscribers(): Promise<SubscriptionRow[]> {
  const { rows } = await pool.query<SubscriptionRow>(
    'SELECT * FROM subscriptions WHERE tomorrow_hour IS NOT NULL',
  );
  return rows;
}

export async function loadSnapshots(dates: string[]) {
  const { rows } = await pool.query<{ building_slug: string; date: string; targets: unknown }>(
    'SELECT building_slug, date, targets FROM schedule_hashes WHERE date = ANY($1::text[])',
    [dates],
  );
  const map = new Map<string, Record<string, unknown>>();
  for (const row of rows) {
    map.set(`${row.building_slug}|${row.date}`, (row.targets ?? {}) as Record<string, unknown>);
  }
  return map;
}

export async function saveSnapshots(
  snapshots: { buildingSlug: string; date: string; targets: Record<string, string> }[],
) {
  for (const snapshot of snapshots) {
    await pool.query(
      `INSERT INTO schedule_hashes (building_slug, date, targets) VALUES ($1, $2, $3::jsonb)
       ON CONFLICT (building_slug, date) DO UPDATE SET targets = EXCLUDED.targets`,
      [snapshot.buildingSlug, snapshot.date, JSON.stringify(snapshot.targets)],
    );
  }
}

/** Хэши старше недели (ранее fetched weeks) чистим */
export async function deleteSnapshotsOlderThan(date: string) {
  await pool.query('DELETE FROM schedule_hashes WHERE date < $1', [date]);
}

export async function deleteNotificationsTokens(tokens: string[]) {
  await pool.query('DELETE FROM subscriptions WHERE expo_push_token = ANY($1::text[])', [tokens]);
}

/** Тест push-канала: из снапшотов убирается ключ цели — следующий sync вышлет «публикацию» */
export async function simulateSnapshotDrop(targetKey: string) {
  await pool.query('UPDATE schedule_hashes SET targets = targets - $1::text', [targetKey]);
}
