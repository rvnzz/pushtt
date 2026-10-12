import { deleteSubscription, simulateSnapshotDrop, upsertSubscription } from './db.js';
import { config } from './config.js';
import { runSync } from './sync.js';
import { Request, Response } from 'express';

type RegisterBody = {
  expoPushToken?: string;
  role?: string;
  buildingSlug?: string;
  targetId?: number;
  targetLabel?: string;
  changesEnabled?: boolean;
  tomorrowHour?: number | null;
  tzOffsetMinutes?: number;
};

/**
 * POST /register
 * body: { expoPushToken, role, buildingSlug, targetId, targetLabel,
 *         changesEnabled, tomorrowHour, tzOffsetMinutes }
 */
export async function registerHandler(req: Request, res: Response) {
  const body = (req.body ?? {}) as RegisterBody;

  const errors = validate(body);
  if (errors.length > 0) {
    res.status(400).json({ errors });
    return;
  }

  await upsertSubscription({
    expoPushToken: body.expoPushToken!,
    role: body.role as 'student' | 'teacher',
    buildingSlug: body.buildingSlug!,
    targetId: body.targetId!,
    targetLabel: body.targetLabel ?? '',
    changesEnabled: body.changesEnabled !== false,
    tomorrowHour: body.tomorrowHour ?? null,
    tzOffsetMinutes: body.tzOffsetMinutes ?? 0,
  });

  res.json({ ok: true });
}

/** POST /unregister — body: { expoPushToken } */
export async function unregisterHandler(req: Request, res: Response) {
  const token = (req.body ?? {} as RegisterBody).expoPushToken;
  if (!token) {
    res.status(400).json({ errors: ['expoPushToken обязателен'] });
    return;
  }

  await deleteSubscription(token);
  res.json({ ok: true });
}

/**
 * POST /debug/simulate — тест push-канала (только при заданном DEBUG_KEY в .env).
 * body: { targetKey?: string }   — по умолчанию 'g:10' (первая группа очного корпуса).
 * Убирает хэш цели из снапшотов и сразу запускает sync.
 */
export async function simulateHandler(req: Request, res: Response) {
  if (!config.debugKey || req.header('x-debug-key') !== config.debugKey) {
    res.status(403).json({ errors: ['эндпой mankind выключен: задайте DEBUG_KEY'] });
    return;
  }

  const targetKey = ((req.body ?? {}) as { targetKey?: string }).targetKey ?? 'g:10';
  await simulateSnapshotDrop(targetKey);
  await runSync();

  res.json({ ok: true, targetKey });
}

function validate(body: RegisterBody): string[] {
  const errors: string[] = [];

  if (typeof body.expoPushToken !== 'string' || !body.expoPushToken.startsWith('Expo')) {
    errors.push('expoPushToken — недействительный');
  }
  if (body.role !== 'student' && body.role !== 'teacher') {
    errors.push('role — student | teacher');
  }
  if (typeof body.buildingSlug !== 'string' || body.buildingSlug.length === 0) {
    errors.push('buildingSlug обязателен');
  }
  if (typeof body.targetId !== 'number') {
    errors.push('targetId обязателен');
  }

  if (
    body.tomorrowHour != null &&
    (typeof body.tomorrowHour !== 'number' || body.tomorrowHour < 0 || body.tomorrowHour > 24)
  ) {
    errors.push('tomorrowHour — 0..24 или null');
  }

  return errors;
}
