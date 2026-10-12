import { config } from './config.js';

/**
 * Дни недели/даты — всё в UTC (сервер сравнивает «даты» как строки YYYY-MM-DD).
 * Локальное время подписчика управляется через эеждмы tz_offset_minutes из БД.
 */

export function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

export function mondayOf(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  const day = date.getUTCDay();
  const diff = day === 0 ? -6 : 1 - day;
  date.setUTCDate(date.getUTCDate() + diff);
  return date.toISOString().slice(0, 10);
}

export function addDaysISO(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

/** «12 октября» — человеческое Дата на русском */
const MONTHS_GENITIVE = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
];

export function formatDate(iso: string): string {
  const date = new Date(`${iso}T00:00:00Z`);
  return `${date.getUTCDate()} ${MONTHS_GENITIVE[date.getUTCMonth()]}`;
}

/** «4 пары», «1 пара», «2 пары» */
export function pluralPairs(count: number): string {
  const abs10 = count % 10;
  const abs100 = count % 100;
  if (abs10 === 1 && abs100 !== 11) return '1 пара';
  if (abs10 >= 2 && abs10 <= 4 && (abs100 < 12 || abs100 > 14)) return `${count} пары`;
  return `${count} пар`;
}

/** Логотип */
export type AllWeekData = {
  mode: string;
  scope: string;
  week_start: string;
  week_end: string;
  anchor_date: string;
  days: Day[];
};

export type Day = {
  date: string;
  has_schedule: boolean;
  buildings: BuildingDay[];
};

export type BuildingDay = {
  building: { name: string; slug: string; max_pairs: number };
  date: string;
  is_published: boolean;
  has_schedule: boolean;
  group_schedules: GroupSchedule[];
  teachers: TeacherDay[];
};

export type GroupSchedule = {
  id: number;
  name: string;
  course_number: number;
  pairs: Pair[];
};

export type TeacherDay = {
  id: number;
  name: string;
  assignments: Assignment[];
};

export type Pair = {
  number: number;
  is_split: boolean;
  has_content: boolean;
  lessons: Lesson[];
};

export type Lesson = {
  subgroup: number | null;
  subject: string;
  teacher: string;
  room: string;
};

export type Assignment = {
  group_id: number;
  group_name: string;
  course_number: number;
  pair_number: number;
  subgroup: number | null;
  subject: string;
  room: string;
  teacher: string;
};

export async function fetchAllWeek(date: string): Promise<AllWeekData> {
  const response = await fetch(
    `${config.timetBaseUrl}/embed/all/week/data?date=${date}`,
    { signal: AbortSignal.timeout(30_000) },
  );

  if (!response.ok) {
    throw new Error(`timet API ${response.status}`);
  }

  return (await response.json()) as AllWeekData;
}
