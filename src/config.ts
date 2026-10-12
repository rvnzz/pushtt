/** Конфиг сервера из окружения */
export const config = {
  databaseUrl: process.env.DATABASE_URL ?? '',
  port: Number(process.env.PORT ?? 4000),
  timetBaseUrl: process.env.TIMET_BASE_URL ?? 'https://timet.eremin.tech',
  /** Если задан — открывает POST /debug/simulate (тест push-канала) */
  debugKey: process.env.DEBUG_KEY ?? '',
} as const;

if (!config.databaseUrl) {
  // Не«выходим» здесь — пусть db.ensureSchema сообщит красивее, но и тут напомним
  console.warn('[config] DATABASE_URL не задан — сервер не сможет работать с БД');
}
