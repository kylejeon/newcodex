import { del, list, put } from '@vercel/blob';
import { DashboardPayload, Snapshot, StoredData } from './types';

const LATEST_KEY = 'kosdaqpi/latest.json';
const HISTORY_KEY = 'kosdaqpi/history.json';
const MAX_HISTORY = 5000;

function getPreferredAccess(): 'public' | 'private' {
  const raw = (process.env.BLOB_ACCESS || '').toLowerCase().trim();
  if (raw === 'private') return 'private';
  return 'public';
}

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

function pickBlobByPathname(blobs: Array<{ pathname: string; url: string; uploadedAt?: Date }>, key: string) {
  const exact = blobs.find((b) => b.pathname === key);
  if (exact) return exact;
  const prefixed = blobs
    .filter((b) => b.pathname.startsWith(key))
    .sort((a, b) => {
      const at = a.uploadedAt instanceof Date ? a.uploadedAt.getTime() : 0;
      const bt = b.uploadedAt instanceof Date ? b.uploadedAt.getTime() : 0;
      return bt - at;
    });
  return prefixed[0];
}

export async function loadStoredData(): Promise<StoredData> {
  const blobs = await list({ prefix: 'kosdaqpi/' });
  const latestBlob = pickBlobByPathname(blobs.blobs, LATEST_KEY);
  const historyBlob = pickBlobByPathname(blobs.blobs, HISTORY_KEY);

  const latest = await readJson<DashboardPayload>(latestBlob?.url);
  const history = (await readJson<Snapshot[]>(historyBlob?.url)) ?? [];
  return { latest, history };
}

async function putJson(pathname: string, data: unknown): Promise<void> {
  const body = JSON.stringify(data);
  const baseOpts = {
    contentType: 'application/json; charset=utf-8',
    addRandomSuffix: false,
  };

  const preferred = getPreferredAccess();
  const firstOpts: any = { ...baseOpts, access: preferred };

  try {
    await put(pathname, body, firstOpts);
    return;
  } catch (e) {
    const msg = String(e);
    if (preferred === 'private' && msg.includes('access must be "public"')) {
      await put(pathname, body, { ...baseOpts, access: 'public' });
      return;
    }
    if (preferred === 'public' && msg.includes('Cannot use public access on a private store')) {
      await put(pathname, body, { ...baseOpts, access: 'private' as any });
      return;
    }
    throw e;
  }
}

export async function savePayload(payload: DashboardPayload): Promise<void> {
  const cur = await loadStoredData();
  const nextHistory = [...cur.history, payload.snapshot].slice(-MAX_HISTORY);

  await putJson(LATEST_KEY, payload);
  await putJson(HISTORY_KEY, nextHistory);
}

export async function resetData() {
  const blobs = await list({ prefix: 'kosdaqpi/' });
  for (const b of blobs.blobs) {
    await del(b.url);
  }
}
