import {
  deleteSnapshotsOlderThan,
  findSubscribersForChange,
  loadSnapshots,
  saveSnapshots,
} from './db.js';
import { buildSnapshots, TargetsSnapshot } from './hash.js';
import { sendPush } from './push.js';
import { addDaysISO, fetchAllWeek, formatDate, mondayOf, todayISO, AllWeekData } from './timet.js';

/**
 * Периодическая сверка расписания:
 * 1) тянем текущую и следующую недели (изменения в конце текущей недели);
 * 2) хэши по целям (группа / преподаватель) на каждый (корпус, день);
 * 3) diff со снапшотами в БД;
 * 4) для каждой изменившейся цели — push её подписчикам;
 * 5) снапшоты сохраняем, старые — чистим.
 */
export async function runSync(): Promise<void> {
  const thisMonday = mondayOf(todayISO());
  const nextMonday = addDaysISO(thisMonday, 7);

  const weeks = await Promise.all([fetchAllWeek(thisMonday), fetchAllWeek(nextMonday)]);
  const fetchedDates = [...new Set(weeks.flatMap((week) => week.days.map((day) => day.date)))];

  const before = await loadSnapshots(fetchedDates);
  const names = collectNames(weeks);
  const after: { buildingSlug: string; date: string; targets: TargetsSnapshot }[] = [];
  const messages: Parameters<typeof sendPush>[0] = [];

  for (const week of weeks) {
    after.push(...(await buildSnapshots(week)));
  }

  for (const week of weeks) {
    for (const snapshot of await buildSnapshots(week)) {
      const previous = (before.get(`${snapshot.buildingSlug}|${snapshot.date}`) ?? {}) as Record<string, string>;

      for (const [targetKey, hash] of Object.entries(snapshot.targets)) {
        const previousHash = previous[targetKey];
        if (previousHash === hash) continue;

        const kind = targetKey.startsWith('g:') ? ('student' as const) : ('teacher' as const);
        const targetId = Number(targetKey.slice(2));
        const label = names(targetKey.startsWith('g:') ? 'g' : 't', targetId);
        if (!label) continue;

        const subscribers = await findSubscribersForChange(kind, snapshot.buildingSlug, targetId);
        if (subscribers.length === 0) continue;

        const title = previousHash === undefined ? 'Опубликовано расписание' : 'Изменение расписания';
        const body = `${label} — ${formatDate(snapshot.date)}`;

        for (const subscriber of subscribers) {
          messages.push({
            to: subscriber.expo_push_token,
            title,
            body,
            data: { role: kind, targetId, date: snapshot.date },
          });
        }
      }
    }
  }

  if (messages.length > 0) {
    console.log(`[sync] изменений: ${messages.length} пушей`);
    await sendPush(messages);
  } else {
    console.log('[sync] изменений нет');
  }

  await saveSnapshots(after);
  await deleteSnapshotsOlderThan(thisMonday);

  cachedWeeks = new Map(weeks.map((week) => [week.week_start, week]));
}

/** Недельные данные последнего синка (reminders смотрят сюда, без повторного fetch) */
let cachedWeeks = new Map<string, AllWeekData>();

export function getCachedWeek(monday: string): AllWeekData | undefined {
  return cachedWeeks.get(monday);
}

/** Локальные занятость цели для напоминаний */
export function countTargetPairsForDate(
  week: AllWeekData,
  role: 'student' | 'teacher',
  buildingSlug: string,
  targetId: number,
  date: string,
): number {
  for (const day of week.days) {
    if (day.date !== date) continue;
    const building = day.buildings.find((b) => b.building.slug === buildingSlug);
    if (!building) continue;

    if (role === 'student') {
      return (
        building.group_schedules
          .find((schedule) => schedule.id === targetId)
          ?.pairs.filter((pair) => pair.has_content && pair.lessons.length > 0).length ?? 0
      );
    }

    return (
      building.teachers
        .find((teacher) => teacher.id === targetId)
        ?.assignments.filter((assignment) => assignment.subject.trim().length > 0).length ?? 0
    );
  }

  return 0;
}

type NameResolver = (kind: 'g' | 't', id: number) => string | undefined;

/** Имя группы/преподавателя из свежих данных — для текста пуша */
function collectNames(weeks: AllWeekData[]): NameResolver {
  const names = new Map<string, string>();

  for (const week of weeks) {
    for (const day of week.days) {
      for (const building of day.buildings) {
        for (const groupSchedule of building.group_schedules) {
          names.set(`g:${groupSchedule.id}`, groupSchedule.name);
        }
        for (const teacher of building.teachers) {
          names.set(`t:${teacher.id}`, teacher.name);
        }
      }
    }
  }

  return (kind, id) => names.get(`${kind}:${id}`);
}
