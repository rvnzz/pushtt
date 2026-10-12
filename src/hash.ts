import { AllWeekData, Assignment, Pair } from './timet.js';

/**
 * Хэши расписания по цели (группа / преподаватель) в разрезе (корпус, день).
 *
 * Формат ключа: `g:{groupId}` / `t:{teacherId}`.
 * Hash — детерминированная строка по парам/assignments; отличается при любом изменении.
 */

export type TargetKey = string; // "g:38" | "t:33"

export type TargetsSnapshot = Record<TargetKey, string>;

export async function buildSnapshots(
  week: AllWeekData,
): Promise<{ buildingSlug: string; date: string; targets: TargetsSnapshot }[]> {
  const snapshots: { buildingSlug: string; date: string; targets: TargetsSnapshot }[] = [];

  for (const day of week.days) {
    for (const building of day.buildings) {
      const targets: TargetsSnapshot = {};

      for (const schedule of building.group_schedules) {
        targets[`g:${schedule.id}`] = hashPairs(schedule.pairs);
      }

      for (const teacher of building.teachers) {
        targets[`t:${teacher.id}`] = hashAssignments(teacher.assignments);
      }

      snapshots.push({
        buildingSlug: building.building.slug,
        date: day.date,
        targets,
      });
    }
  }

  return snapshots;
}

/** Детерминированная строка по парам группы */
function hashPairs(pairs: Pair[]): string {
  return (
    pairs
      .filter((pair) => pair.has_content)
      .sort((a, b) => a.number - b.number)
      .map((pair) => {
        const lessons = pair.lessons
          .map((lesson) => `${lesson.subgroup ?? '-'}|${lesson.subject}|${lesson.teacher}|${lesson.room}`)
          .sort();
        return `${pair.number}${pair.is_split ? 's' : ''}[${lessons.join(';;')}]`;
      })
      .join('|') || 'empty'
  );
}

/** Детерминированная строка по assignments преподавателя */
function hashAssignments(assignments: Assignment[]): string {
  return (
    assignments
      .sort(
        (a, b) =>
          a.pair_number - b.pair_number ||
          a.group_id - b.group_id ||
          (a.subgroup ?? 0) - (b.subgroup ?? 0),
      )
      .map((a) => `${a.pair_number}|${a.group_id}|${a.subgroup ?? '-'}|${a.subject}|${a.room}`)
      .join('|') || 'empty'
  );
}
