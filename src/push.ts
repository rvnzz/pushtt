import { deleteNotificationsTokens } from './db.js';

const EXPO_PUSH_URL = 'https://exp.host/--/api/v2/push/send';
const CHUNK_SIZE = 100;

export type PushMessage = {
  to: string;
  title: string;
  body: string;
  sound?: 'default';
  data?: Record<string, unknown>;
};

/** Отправка батчами по 100; чистит подписки с отозванными токенами */
export async function sendPush(messages: PushMessage[]): Promise<void> {
  for (let i = 0; i < messages.length; i += CHUNK_SIZE) {
    const chunk = messages.slice(i, i + CHUNK_SIZE);

    const response = await fetch(EXPO_PUSH_URL, {
      method: 'POST',
      headers: {
        host: 'exp.host',
        accept: 'application/json',
        'accept-encoding': 'gzip, deflate',
        'content-type': 'application/json',
      },
      body: JSON.stringify(chunk),
    });

    if (!response.ok) {
      console.error(`[push] HTTP ${response.status}: ${await response.text()}`);
      continue;
    }

    const tickets = ((await response.json()) as {
      data?: { status: string; details?: { error?: string } }[];
    }).data ?? [];

    const deadTokens: string[] = [];
    for (let j = 0; j < tickets.length; j++) {
      if (tickets[j]!.status === 'error' && tickets[j]!.details?.error === 'DeviceNotRegistered') {
        deadTokens.push(chunk[j]!.to);
      }
    }

    if (deadTokens.length > 0 && i === 0) {
      console.log(`[push] чистим отозванные токены: ${deadTokens.length}`);
      await deleteNotificationsTokens(deadTokens);
    }
  }
}
