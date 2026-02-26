import { del, list, put } from '@vercel/blob';
import { DashboardPayload, Snapshot, StoredData } from './types';

const LATEST_KEY = 'kosdaqpi/latest.json';
const HISTORY_KEY = 'kosdaqpi/history.json';
const MAX_HISTORY = 5000;

async function readJson<T>(url?: string): Promise<T | null> {
  if (!url) return null;
  const headers: Record<string, string> = {};
  if (process.env.BLOB_READ_WRITE_TOKEN) {
    headers['Authorization'] = `Bearer ${process.env.BLOB_READ_WRITE_TOKEN}`;
  }
  const r = await fetch(url, { cache: 'no-store', headers });
  if (!r.ok) return null;
  return (await r.json()) as T;
}

export async function loadStoredData(): Promise<StoredData> {
  const blobs = await list({ prefix: 'kosdaqpi/' });
  const latestBlob = blobs.blobs.find((b) => b.pathname === LATEST_KEY);
  const historyBlob = blobs.blobs.find((b) => b.pathname === HISTORY_KEY);

  const latest = await readJson<DashboardPayload>(latestBlob?.url);
  const history = (await readJson<Snapshot[]>(historyBlob?.url)) ?? [];
  return { latest, history };
}

export async function savePayload(payload: DashboardPayload): Promise<void> {
  const cur = await loadStoredData();
  const nextHistory = [...cur.history, payload.snapshot].slice(-MAX_HISTORY);

  await put(LATEST_KEY, JSON.stringify(payload), {
    access: 'private' as any,
    contentType: 'application/json; charset=utf-8',
    addRandomSuffix: false,
  });

  await put(HISTORY_KEY, JSON.stringify(nextHistory), {
    access: 'private' as any,
    contentType: 'application/json; charset=utf-8',
    addRandomSuffix: false,
  });
}

export async function resetData() {
  const blobs = await list({ prefix: 'kosdaqpi/' });
  for (const b of blobs.blobs) {
    await del(b.url);
  }
}
