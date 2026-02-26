import { NextResponse } from 'next/server';
import { loadStoredData } from '@/lib/storage';

export const dynamic = 'force-dynamic';

export async function GET() {
  try {
    const data = await loadStoredData();
    return NextResponse.json({ ok: true, ...data });
  } catch (e) {
    return NextResponse.json({ ok: false, error: String(e), latest: null, history: [] }, { status: 500 });
  }
}
